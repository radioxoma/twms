import functools
import logging
import mimetypes
import os
from http import HTTPStatus

from PIL import Image, ImageColor, ImageOps

import twms.api
import twms.bbox
import twms.config
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
        # dict[layer_id]: twms.fetchers.TileFetcher(layer)]
        self.fetchers_pool = dict()

    def wms_handler(self, data: dict) -> tuple[HTTPStatus, str, bytes | str]:
        """Do main TWMS work.

        Implied support for WMS 1.1.1 and 1.3.0 as most widespread.

        http://127.0.0.1:8080/wms?request=GetCapabilities&

        Args:
            data: url params

        Returns:
            (http.HTTPStatus, content_type, resp)
        """
        # logger.info(data)
        # WMS request keys must be case-insensitive, values must not
        data = {k.casefold(): v for k, v in data.items()}

        # Support both 1.1.1, 1.3.0 spec projection names
        srs = data.get("crs", data.get("srs", "EPSG:4326"))

        wkt = data.get("wkt", "")
        # color = data.get("color", data.get("colour", "")).split(",")

        req_type = data.get("request", "GetMap")

        if req_type == "GetCapabilities":
            # version = data.get("version", "1.1.1")
            # ref = data.get("ref", twms.config.service_url)
            # resp = twms.api.maps_xml_wms(version, ref + "wms")[1]
            resp = twms.api.maps_xml_wms111()
            return HTTPStatus.OK, "text/xml", resp

        layers_list = data.get("layers", twms.config.default_layers).split(",")
        if "layers" in data and not layers_list[0]:
            layers_list = ["transparent"]

        force = data.get("force", "")
        if force:
            force = force.split(",")
        force = tuple(force)

        # Serving imagery
        content_type = twms.config.default_mimetype
        try:
            # Get requested content type from standard WMS 'format' parameter,
            # https://docs.geoserver.org/stable/en/user/services/wms/outputformats.html
            content_type = data["format"]  # Shell be no default format
            if content_type not in mimetypes.types_map.values():
                return (
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "text/plain",
                    f"Invalid image format '{content_type}' requested",
                )
        except KeyError:
            pass

        z = int(data.get("z", 0))
        x = int(data.get("x", 0))
        y = int(data.get("y", 0))
        if req_type == "GetTile":
            # Both TMS and WMS
            height = int(data.get("height", 256))
            width = int(data.get("width", 256))
            srs = data.get("srs", twms.config.default_src)
            # Try to return tile as is, if possible
            if all(
                (
                    len(layers_list) == 1,
                    layers_list[0] in twms.config.layers,
                    "cache_ttl"
                    not in twms.config.layers[
                        layers_list[0]
                    ],  # Need to check time in fetcher
                    srs
                    == twms.config.layers[layers_list[0]].get(
                        "proj", twms.config.default_src
                    ),
                    width == height == 256,
                    not force,
                )
            ):
                tile_path = (
                    twms.config.tiles_cache
                    + twms.config.layers[layers_list[0]]["prefix"]
                    + "/{:.0f}/{:.0f}/{:.0f}{}".format(
                        z,
                        x,
                        y,
                        mimetypes.guess_extension(
                            twms.config.layers[layers_list[0]].get(
                                "mimetype", twms.config.default_mimetype
                            )
                        ),
                    )
                )
                logger.debug(f"{layers_list[0]} z{z}/x{x}/y{y} query cache {tile_path}")
                if os.path.exists(tile_path):
                    # Not returning HTTP 404
                    logger.info(
                        f"{layers_list[0]} z{z}/x{x}/y{y} wms_handler cache hit {tile_path}"
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

        width = int(data.get("width", 0))
        height = int(data.get("height", 0))
        width = min(width, twms.config.max_width)
        height = min(height, twms.config.max_height)
        if width == height == 0:
            width = 350

        imgs = 1.0
        ll = layers_list.pop(0)
        if ll[-2:] == "!c":  # Remove this
            ll = ll[:-2]
            if wkt:
                wkt = "," + wkt
            srs = twms.config.layers[ll].get("proj", twms.config.default_src)

        try:
            result_img = self.bbox_image(box, srs, (height, width), ll, force)
        except KeyError:
            result_img = Image.new("RGBA", (width, height))

        for ll in layers_list:
            if ll[-2:] == "!c":
                ll = ll[:-2]
                if wkt:
                    wkt = "," + wkt
                srs = twms.config.layers[ll].get("proj", twms.config.default_src)

            im2 = self.bbox_image(box, srs, (height, width), ll, force)
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

    def tiles_handler(
        self, layer_id: str, z: int, x: int, y: int, mimetype: str
    ) -> tuple[HTTPStatus, str, bytes | str]:
        """Serve slippy map tiles as is.

        http://localhost:8080/tiles/vesat/1/0/0.jpg OK
        http://localhost:8080/tiles/yasat/1/0/0.jpg not OK

        Returns:
            Return 404 instead of blank tile.
        """
        logger.debug(f"{layer_id} z{z}/x{x}/y{y} tiles_handler")
        proj = twms.config.layers[layer_id].get("proj", twms.config.default_src)
        if proj != "EPSG:3857":
            raise NotImplementedError(
                "Reprojection is not implemented, use WMS for this tile set"
            )
        z, x, y = int(z), int(x), int(y)
        im = self.tile_image(layer_id, z, x, y, real=True)
        if im:
            return (
                HTTPStatus.OK,
                mimetype,
                twms.fetchers.im_convert(im, mimetype),
            )
        else:
            return HTTPStatus.NOT_FOUND, "text/plain", "404 Not Found"

    def bbox_image(
        self,
        bbox: twms.bbox.Bbox,
        request_proj: twms.projections.EPSG,
        size: tuple[int, int],
        layer_id: str,
        force,
    ) -> Image.Image:
        """Get tile by a given bbox."""
        # Making 4-corner maximal bbox
        bbox_p = twms.projections.from4326(bbox, request_proj)
        bbox_p = twms.projections.to4326(
            (bbox_p[2], bbox_p[1], bbox_p[0], bbox_p[3]), request_proj
        )

        bbox_4: twms.bbox.Bbox4 = (
            (bbox_p[2], bbox_p[3]),
            (bbox[0], bbox[1]),
            (bbox_p[0], bbox_p[1]),
            (bbox[2], bbox[3]),
        )
        bbox = twms.bbox.expand_to_point(bbox, bbox_4)
        H, W = size

        max_zoom = twms.config.layers[layer_id].get(
            "max_zoom", twms.config.default_max_zoom
        )
        min_zoom = twms.config.layers[layer_id].get(
            "min_zoom", twms.config.default_min_zoom
        )

        zoom = twms.projections.zoom_for_bbox(
            bbox,
            size,
            layer_id,
            min_zoom,
            max_zoom,
            (twms.config.max_height, twms.config.max_width),
        )
        from_tile_x, from_tile_y, to_tile_x, to_tile_y = twms.projections.tile_by_bbox(
            bbox,
            zoom,
            twms.config.layers[layer_id].get("proj", twms.config.default_src),
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
                im1 = self.tile_image(layer_id, zoom, x, y, real=True)
                if not im1:
                    ec = ImageColor.getcolor(
                        twms.config.layers[layer_id].get(
                            "empty_color", twms.config.default_background
                        ),
                        "RGBA",
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
            out = out.transform((W, H), Image.QUAD, tuple(quad), Image.BICUBIC)
        elif (W != out.size[0]) or (H != out.size[1]):
            out = out.resize((W, H), Image.ANTIALIAS)
        return out

    @functools.lru_cache(maxsize=twms.config.ram_cache_tiles)
    def tile_image(
        self,
        layer_id: str,
        z: int,
        x: int,
        y: int,
        trybetter=True,
        real=False,
    ) -> Image.Image | None:
        """Get tile by Slippy map coordinates.

        Args:
            trybetter: combine this tile from better ones
            real: return the tile even in not good quality

        Returns:
            Tile (from cache, fetcher, or recursively rescaled) or
            None if image is invalid or unavailable.
        """
        x = x % (2**z)
        if y < 0 or y >= (2**z) or z < 0:
            logger.warning(f"{layer_id}/z{z}/x{x}/y{y} impossible tile coordinates")
            return None

        if not twms.bbox.bbox_is_in(
            twms.projections.bbox_by_tile(
                z,
                x,
                y,
                twms.config.layers[layer_id].get("proj", twms.config.default_src),
            ),
            twms.config.layers[layer_id].get("bounds", twms.config.default_bbox),
            fully=False,
        ):
            logger.info(
                f"{layer_id}/z{z}/x{x}/y{y} ignoring request for a tile outside configured bounds"
            )
            return None

        tile = None
        # Reconstructiong from cache
        if (
            twms.config.layers[layer_id]["scalable"]
            and (
                z
                < twms.config.layers[layer_id].get(
                    "max_zoom", twms.config.default_max_zoom
                )
            )
            and trybetter
        ):
            # Second, try to glue image of better ones
            logger.info(f"{layer_id}/z{z}/x{x}/y{y} downscaling from 4 subtiles")
            # Load upscaled images
            # if os.path.exists(local + "ups" + ext):
            #     try:
            #         im = Image.open(local + "ups" + ext)
            #         return im
            #     except OSError:
            #         pass
            ec = ImageColor.getcolor(
                twms.config.layers[layer_id].get(
                    "empty_color", twms.config.default_background
                ),
                "RGBA",
            )
            empty_color = (ec[0], ec[1], ec[2], 0)
            logger.info(f"{layer_id}/z{z}/x{x}/y{y} downscaling from bottom tiles")
            im = Image.new("RGBA", (512, 512), empty_color)
            im1 = self.tile_image(layer_id, z + 1, x * 2, y * 2)
            if im1:
                im2 = self.tile_image(layer_id, z + 1, x * 2 + 1, y * 2)
                if im2:
                    im3 = self.tile_image(layer_id, z + 1, x * 2, y * 2 + 1)
                    if im3:
                        im4 = self.tile_image(layer_id, z + 1, x * 2 + 1, y * 2 + 1)
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

        if tile is None and "fetch" in twms.config.layers[layer_id]:
            # Dedicated fetcher for each imagery layer
            if layer_id not in self.fetchers_pool:
                self.fetchers_pool[layer_id] = twms.fetchers.TileFetcher(layer_id)
            tile = self.fetchers_pool[layer_id].fetch(z, x, y)

        if tile is None and real:
            logger.info(f"{layer_id}/z{z}/x{x}/y{y} upscaling from top tile")
            im = self.tile_image(
                layer_id,
                z - 1,
                int(x // 2),
                int(y // 2),
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
        return tile
