import logging
import mimetypes
import os
import time
from http import HTTPStatus

from PIL import Image, ImageColor, ImageOps

import twms.bbox
import twms.correctify
import twms.fetchers
import twms.projections

# from PIL import ImageFile
# ImageFile.LOAD_TRUNCATED_IMAGES = True

logger = logging.getLogger(__name__)


class TWMSMain:
    """Inside tWMS, only EPSG:4326 latlon should be used for transmitting coordinates.

    WMS http://cite.opengeospatial.org/OGCTestData/wms/1.1.1/spec/wms1.1.1.html
    TMS
        https://wiki.osgeo.org/wiki/Tile_Map_Service_Specification
        https://gis-lab.info/docs/tms-specification-ru.html
    WMTS
        Web Map Tile Service Implementation Standard 2010-04-06 1.0.0
        http://www.opengeospatial.org/standards/wmts
        https://sampleserver6.arcgisonline.com/arcgis/rest/services/WorldTimeZones/MapServer/WMTS
        Usually link to WMTSCapabilities.xml
    """

    def __init__(self):
        super().__init__()
        self.cached_objs = dict()  # a dict. (layer, z, x, y): PIL image
        self.cached_hist_list = list()
        self.fetchers_pool = dict()  # self.fetchers_pool[layer['prefix']]

    def wms_handler(self, data):
        """Do main TWMS work. Some WMS implementation.

        data - dictionary of params.
        returns (HTTP_code, content_type, resp)

        http://127.0.0.1:8080/?request=GetCapabilities&
        http://127.0.0.1:8080/?request=GetCapabilities&version=1.0.0
        """
        # WMS request keys must be case insensitive, values must not
        data = {k.lower(): v for k, v in data.items()}

        start_time = time.time()
        srs = data.get("srs", "EPSG:4326")
        wkt = data.get("wkt", "")
        # color = data.get("color", data.get("colour", "")).split(",")

        req_type = data.get("request", "GetMap")
        version = data.get("version", "1.1.1")
        ref = data.get("ref", twms.config.service_url)

        if req_type == "GetCapabilities":
            content_type, resp = twms.api.maps_wms(version, ref)
            return HTTPStatus.OK, content_type, resp

        layer = data.get("layers", twms.config.default_layers).split(",")
        if "layers" in data and not layer[0]:
            layer = ["transparent"]

        if req_type == "GetCorrections":
            points = data.get("points", "").split("=")
            points = [a.split(",") for a in points]
            points = [(float(a[0]), float(a[1])) for a in points]

            resp = ""
            for lay in layer:
                for point in points:
                    resp += "%s,%s;" % (
                        twms.correctify.rectify(twms.config.layers[lay], point)
                    )
                resp += "\n"
            return HTTPStatus.OK, "text/plain", resp

        force = data.get("force", "")
        if force != "":
            force = force.split(",")
        force = tuple(force)

        if layer == [""]:
            return HTTPStatus.OK, "text/html", twms.api.maps_html()

        # Serving imagery
        content_type = "image/jpeg"  # Default content type of image to serve
        try:
            # Get requested content type from standard WMS 'format' parameter,
            # https://docs.geoserver.org/stable/en/user/services/wms/outputformats.html
            content_type = data["format"]
            if content_type not in mimetypes.types_map.values():
                return (
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "text/plain",
                    f"Invalid image format '{content_type}' requested",
                )
        except KeyError:
            pass

        width = 0
        height = 0
        z = int(data.get("z", 0))
        x = int(data.get("x", 0))
        y = int(data.get("y", 0))
        if req_type == "GetTile":
            # Both TMS and WMS
            width = 256
            height = 256
            height = int(data.get("height", height))
            width = int(data.get("width", width))
            srs = data.get("srs", "EPSG:3857")
            # Try to return tile as is, if possible
            if all(
                (
                    len(layer) == 1,
                    layer[0] in twms.config.layers,
                    "cache_ttl"
                    not in twms.config.layers[
                        layer[0]
                    ],  # Need to check time in fetcher
                    srs == twms.config.layers[layer[0]]["proj"],
                    width == height == 256,
                    not force,
                )
            ):
                tile_path = (
                    twms.config.tiles_cache
                    + twms.config.layers[layer[0]]["prefix"]
                    + "/{:.0f}/{:.0f}/{:.0f}{}".format(
                        z, x, y, twms.config.layers[layer[0]]["ext"]
                    )
                )
                logger.debug(f"{layer[0]} z{z}/x{x}/y{y} query cache {tile_path}")
                if os.path.exists(tile_path):
                    # Not returning HTTP 404
                    logger.info(
                        f"{layer[0]} z{z}/x{x}/y{y} wms_handler cache hit {tile_path}"
                    )
                    with open(tile_path, "rb") as f:
                        # Note: image file validation performed only in TileFetcher
                        return HTTPStatus.OK, content_type, f.read()

        req_bbox = twms.projections.from4326(
            twms.projections.bbox_by_tile(z, x, y, srs), srs
        )

        if data.get("bbox", None):
            req_bbox = tuple(map(float, data.get("bbox", req_bbox).split(",")))

        req_bbox = twms.projections.to4326(req_bbox, srs)
        req_bbox, flip_h = twms.bbox.normalize(req_bbox)
        box = req_bbox

        width = int(data.get("width", width))
        height = int(data.get("height", height))
        width = min(width, twms.config.max_width)
        height = min(height, twms.config.max_height)
        if width == height == 0:
            width = 350

        imgs = 1.0
        ll = layer.pop(0)
        if ll[-2:] == "!c":
            ll = ll[:-2]
            if wkt:
                wkt = "," + wkt
            srs = twms.config.layers[ll]["proj"]

        try:
            # WMS image
            result_img = self.getimg(
                box, srs, (height, width), twms.config.layers[ll], start_time, force
            )
        except KeyError:
            result_img = Image.new("RGBA", (width, height))

        for ll in layer:
            if ll[-2:] == "!c":
                ll = ll[:-2]
                if wkt:
                    wkt = "," + wkt
                srs = twms.config.layers[ll]["proj"]

            im2 = self.getimg(
                box, srs, (height, width), twms.config.layers[ll], start_time, force
            )
            if "empty_color" in twms.config.layers[ll]:
                ec = ImageColor.getcolor(twms.config.layers[ll]["empty_color"], "RGBA")
                sec = set(ec)
                if "empty_color_delta" in twms.config.layers[ll]:
                    delta = twms.config.layers[ll]["empty_color_delta"]
                    for tr in range(-delta, delta):
                        for tg in range(-delta, delta):
                            for tb in range(-delta, delta):
                                if (
                                    (ec[0] + tr) >= 0
                                    and (ec[0] + tr) < 256
                                    and (ec[1] + tr) >= 0
                                    and (ec[1] + tr) < 256
                                    and (ec[2] + tr) >= 0
                                    and (ec[2] + tr) < 256
                                ):
                                    sec.add((ec[0] + tr, ec[1] + tg, ec[2] + tb, ec[3]))
                i2l = im2.load()
                for x in range(0, im2.size[0]):
                    for y in range(0, im2.size[1]):
                        t = i2l[x, y]
                        if t in sec:
                            i2l[x, y] = (t[0], t[1], t[2], 0)
            if not im2.size == result_img.size:
                im2 = im2.resize(result_img.size, Image.ANTIALIAS)
            im2 = Image.composite(im2, result_img, im2.split()[3])  # imgs/(imgs+1.))

            if "noblend" in force:
                result_img = im2
            else:
                result_img = Image.blend(im2, result_img, 0.5)
            imgs += 1.0

        if flip_h:
            result_img = ImageOps.flip(result_img)

        return (
            HTTPStatus.OK,
            content_type,
            twms.fetchers.im_convert(result_img, content_type),
        )

    def tiles_handler(self, layer_id, z, x, y, content_type):
        """Partial slippy map implementation. Serve tiles by index, reproject, if required.

        Experimental handler.

        http://localhost:8080/tiles/vesat/0/0/0.jpg

        Return 404 instead of blank tile.
        """
        logger.debug(f"{layer_id} z{z}/x{x}/y{y} tiles_handler")
        if twms.config.layers[layer_id]["proj"] != "EPSG:3857":
            raise NotImplementedError(
                "Reprojection is not supported, use wms for this tile set"
            )
        z, x, y = int(z), int(x), int(y)
        im = self.tile_image(
            twms.config.layers[layer_id], z, x, y, time.time(), real=True
        )

        if im:
            return (
                HTTPStatus.OK,
                content_type,
                twms.fetchers.im_convert(im, content_type),
            )
        else:
            return HTTPStatus.NOT_FOUND, "text/plain", "404 Not Found"

    def getimg(self, bbox, request_proj, size, layer, start_time, force):
        """Get tile by a given bbox."""
        # Making 4-corner maximal bbox
        bbox_p = twms.projections.from4326(bbox, request_proj)
        bbox_p = twms.projections.to4326(
            (bbox_p[2], bbox_p[1], bbox_p[0], bbox_p[3]), request_proj
        )

        bbox_4 = (
            (bbox_p[2], bbox_p[3]),
            (bbox[0], bbox[1]),
            (bbox_p[0], bbox_p[1]),
            (bbox[2], bbox[3]),
        )
        if "nocorrect" not in force:
            bb4 = []
            for point in bbox_4:
                bb4.append(twms.correctify.rectify(layer, point))
            bbox_4 = bb4
        bbox = twms.bbox.expand_to_point(bbox, bbox_4)
        H, W = size

        max_zoom = layer.get("max_zoom", twms.config.default_max_zoom)
        min_zoom = layer.get("min_zoom", twms.config.default_min_zoom)

        zoom = twms.bbox.zoom_for_bbox(
            bbox,
            size,
            layer,
            min_zoom,
            max_zoom,
            (twms.config.max_height, twms.config.max_width),
        )
        from_tile_x, from_tile_y, to_tile_x, to_tile_y = twms.projections.tile_by_bbox(
            bbox, zoom, layer["proj"]
        )
        cut_from_x = int(256 * (from_tile_x - int(from_tile_x)))
        cut_from_y = int(256 * (from_tile_y - int(from_tile_y)))
        cut_to_x = int(256 * (to_tile_x - int(to_tile_x)))
        cut_to_y = int(256 * (to_tile_y - int(to_tile_y)))

        from_tile_x, from_tile_y = int(from_tile_x), int(from_tile_y)
        to_tile_x, to_tile_y = int(to_tile_x), int(to_tile_y)
        bbox_im = (
            cut_from_x,
            cut_to_y,
            256 * (to_tile_x - from_tile_x) + cut_to_x,
            256 * (from_tile_y - to_tile_y) + cut_from_y,
        )
        x = 256 * (to_tile_x - from_tile_x + 1)
        y = 256 * (from_tile_y - to_tile_y + 1)

        out = Image.new("RGBA", (x, y))
        for x in range(from_tile_x, to_tile_x + 1):
            for y in range(to_tile_y, from_tile_y + 1):
                im1 = self.tile_image(layer, zoom, x, y, start_time, real=True)
                if not im1:
                    ec = ImageColor.getcolor(
                        layer.get("empty_color", twms.config.default_background), "RGBA"
                    )
                    im1 = Image.new("RGBA", (256, 256), ec)
                out.paste(im1, ((x - from_tile_x) * 256, (-to_tile_y + y) * 256))

        # TODO: We could drop this crop in case user doesn't need it.
        out = out.crop(bbox_im)
        if "noresize" not in force:
            if (H == W) and (H == 0):
                W, H = out.size
            if H == 0:
                H = out.size[1] * W // out.size[0]
            if W == 0:
                W = out.size[0] * H // out.size[1]

        quad = list()
        trans_needed = False
        for point in bbox_4:
            x = (point[0] - bbox[0]) / (bbox[2] - bbox[0]) * (out.size[0])
            y = (1 - (point[1] - bbox[1]) / (bbox[3] - bbox[1])) * (out.size[1])
            x = int(round(x))
            y = int(round(y))
            if (x != 0 and x != out.size[0]) or (y != 0 and y != out.size[1]):
                trans_needed = True
            quad.append(x)
            quad.append(y)

        if trans_needed:
            quad = tuple(quad)
            out = out.transform((W, H), Image.QUAD, quad, Image.BICUBIC)
        elif (W != out.size[0]) or (H != out.size[1]):
            "just resize"
            out = out.resize((W, H), Image.ANTIALIAS)
        return out

    def tile_image(self, layer, z, x, y, start_time, trybetter=True, real=False):
        """Get tile by given coordinates.

        Returns asked tile (from cache, fetcher, or recursively rescaled).

        again - is this a second pass on this tile?
        trybetter - should we try to combine this tile from better ones?
        real - should we return the tile even in not good quality?

        dsc.downscale?
        ups.upscale?

        Function must return None if image is invalid  or unavailable
        """
        tile = None
        # Dedicated fetcher for each imagery layer - if one fetcher hangs,
        # others should be responsive
        if layer["prefix"] not in self.fetchers_pool:
            self.fetchers_pool[layer["prefix"]] = twms.fetchers.TileFetcher(layer)

        x = x % (2**z)
        if y < 0 or y >= (2**z) or z < 0:
            logger.warning(
                f"{layer['prefix']}/z{z}/x{x}/y{y} impossible tile coordinates"
            )
            return None

        if not twms.bbox.bbox_is_in(
            twms.projections.bbox_by_tile(z, x, y, layer["proj"]),
            layer.get("bounds", twms.config.default_bbox),
            fully=False,
        ):
            logger.info(
                f"{layer['prefix']}/z{z}/x{x}/y{y} ignoring request for a tile outside configured bounds"
            )
            return None

        if "prefix" in layer:
            if (layer["prefix"], z, x, y) in self.cached_objs:
                logger.debug(f"{layer['prefix']}/z{z}/x{x}/y{y} RAM cache hit")
                return self.cached_objs[(layer["prefix"], z, x, y)]

        # Working with cache
        if (
            layer["scalable"]
            and (z < layer.get("max_zoom", twms.config.default_max_zoom))
            and trybetter
        ):
            # Second, try to glue image of better ones
            logger.info(f"{layer['prefix']}/z{z}/x{x}/y{y} downscaling from 4 subtiles")
            # # Load upscaled images
            # if os.path.exists(local + "ups" + ext):
            #     try:
            #         im = Image.open(local + "ups" + ext)
            #         return im
            #     except OSError:
            #         pass
            ec = ImageColor.getcolor(
                layer.get("empty_color", twms.config.default_background), "RGBA"
            )
            ec = (ec[0], ec[1], ec[2], 0)
            im = Image.new("RGBA", (512, 512), ec)
            im1 = self.tile_image(layer, z + 1, x * 2, y * 2, start_time)
            if im1:
                im2 = self.tile_image(layer, z + 1, x * 2 + 1, y * 2, start_time)
                if im2:
                    im3 = self.tile_image(layer, z + 1, x * 2, y * 2 + 1, start_time)
                    if im3:
                        im4 = self.tile_image(
                            layer, z + 1, x * 2 + 1, y * 2 + 1, start_time
                        )
                        if im4:
                            im.paste(im1, (0, 0))
                            im.paste(im2, (256, 0))
                            im.paste(im3, (0, 256))
                            im.paste(im4, (256, 256))
                            tile = im.resize((256, 256), Image.ANTIALIAS)
                            # if layer.get("cached", True):
                            #     try:
                            #         im.save(local + "ups" + ext)
                            #     except OSError:
                            #         pass

        if tile is None and "fetch" in layer:
            seconds_spent = time.time() - start_time
            if (twms.config.deadline > seconds_spent) or (z < 4):
                # Try fetching img from outside
                logger.debug(f"{layer['prefix']}/z{z}/x{x}/y{y} creating dl thread")
                tile = self.fetchers_pool[layer["prefix"]].fetch(z, x, y)

        if tile is None and real and z > 0:
            # Downscale?
            logger.info(f"{layer['prefix']}/z{z}/x{x}/y{y} upscaling from top tile")
            im = self.tile_image(
                layer,
                z - 1,
                int(x // 2),
                int(y // 2),
                start_time,
                trybetter=False,
                real=True,
            )
            if im:
                im = im.crop(
                    (
                        128 * (x % 2),
                        128 * (y % 2),
                        128 * (x % 2) + 128,
                        128 * (y % 2) + 128,
                    )
                )
                tile = im.resize((256, 256), Image.BILINEAR)

        # RAM cache. Better use decorator?
        if (layer["prefix"], z, x, y) not in self.cached_objs:
            self.cached_objs[(layer["prefix"], z, x, y)] = tile
            self.cached_hist_list.append((layer["prefix"], z, x, y))
        if len(self.cached_objs) >= twms.config.max_ram_cached_tiles:
            del self.cached_objs[self.cached_hist_list.pop(0)]

        return tile
