import os
import sys
import imp
from io import BytesIO
import datetime
import mimetypes
from http import HTTPStatus

from PIL import Image, ImageOps, ImageColor

sys.path.append(os.path.join(os.path.dirname(__file__)))
install_path = os.path.realpath(os.path.join(os.path.dirname(__file__), '../'))

config_path = "twms/twms.conf"
if os.path.exists(config_path):
    config_path = os.path.join(install_path, config_path)
    config = imp.load_source("config", os.path.realpath(config_path))
else:
    print("No config in '{}'".format(config_path))
    quit()


from twms import correctify
from twms import capabilities
from twms import fetchers
from twms import bbox as bbox_utils
from twms import projections
from twms import overview


class TWMSMain(object):
    def __init__(self):
        super(TWMSMain, self).__init__()
        self.cached_objs = {}  # a dict. (layer, z, x, y): PIL image
        self.cached_hist_list = list()
        self.fetchers_pool = dict()  # self.fetchers_pool[layer['prefix']]

    def handler(self, data):
        """Do main TWMS work. Some WMS implementation.

        data - dictionary of params.
        returns (HTTP_code, content_type, resp)

        http://cite.opengeospatial.org/OGCTestData/wms/1.1.1/spec/wms1.1.1.html

        http://127.0.0.1:8080/?request=GetCapabilities&
        http://127.0.0.1:8080/?request=GetCapabilities&version=1.0.0
        """
        # WMS request keys must be case insensitive, values must not
        data = {k.lower(): v for k, v in data.items()}

        start_time = datetime.datetime.now()
        srs = data.get("srs", "EPSG:4326")
        wkt = data.get("wkt", "")
        # color = data.get("color", data.get("colour", "")).split(",")

        req_type = data.get("request", "GetMap")
        version = data.get("version", "1.1.1")
        ref = data.get("ref", config.service_url)

        if req_type == "GetCapabilities":
            content_type, resp = capabilities.get(version, ref)
            return HTTPStatus.OK, content_type, resp

        layer = data.get("layers", config.default_layers).split(",")
        if "layers" in data and not layer[0]:
            layer = ["transparent"]

        if req_type == "GetCorrections":
            points = data.get('points', '').split('=')
            points = [a.split(",") for a in points]
            points = [(float(a[0]), float(a[1])) for a in points]

            resp = ""
            for lay in layer:
                for point in points:
                    resp += "%s,%s;" % tuple(correctify.rectify(config.layers[lay], point))
                resp += "\n"
            return HTTPStatus.OK, 'text/plain', resp

        force = data.get("force", "")
        if force != "":
            force = force.split(",")
        force = tuple(force)

        filt = data.get("filt", "")
        if filt != "":
            filt = filt.split(",")
        filt = tuple(filt)

        if layer == [""]:
            resp = overview.html()
            return HTTPStatus.OK, 'text/html', resp

        # Serving imagery
        content_type = 'image/jpeg'  # Default content type of image to serve
        try:
            # Get requested content type from standard WMS 'format' parameter,
            # https://docs.geoserver.org/stable/en/user/services/wms/outputformats.html
            content_type = data['format']
            if content_type not in mimetypes.types_map.values():
                return HTTPStatus.INTERNAL_SERVER_ERROR, 'text/plain', f"Invalid image format '{content_type}' requested"
        except KeyError:
            pass

        width = 0
        height = 0
        z = int(data.get("z", 1)) + 1  # FIXME: why +1?
        x = int(data.get("x", 0))
        y = int(data.get("y", 0))
        if req_type == "GetTile":
            # Both TMS and WMS
            width = 256
            height = 256
            height = int(data.get("height", height))
            width = int(data.get("width", width))
            srs = data.get("srs", "EPSG:3857")
            if len(layer) == 1:
                # Try to return tile as is, if possible
                if layer[0] in config.layers:
                    if (config.layers[layer[0]]["proj"] == srs
                        and width == 256
                        and height == 256
                        and not filt
                        and not force
                        and not correctify.has_corrections(config.layers[layer[0]])):
                        tile_path = config.tiles_cache + config.layers[layer[0]]['prefix'] + "/z{:.0f}/{:.0f}/{:.0f}.{}".format(
                            z - 1, y, x, config.layers[layer[0]]['ext'])
                        if os.path.exists(tile_path):
                            # Not returning HTTP 404
                            with open(tile_path, 'rb') as f:
                                tile_file = f.read()
                            print(f"handler: load '{tile_path}'")
                            return HTTPStatus.OK, content_type, tile_file

        req_bbox = projections.from4326(projections.bbox_by_tile(z, x, y, srs), srs)

        # Indent?
        if data.get("bbox", None):
            req_bbox = tuple(map(float, data.get("bbox", req_bbox).split(",")))

        req_bbox = projections.to4326(req_bbox, srs)
        req_bbox, flip_h = bbox_utils.normalize(req_bbox)
        box = req_bbox

        width = int(data.get("width", width))
        height = int(data.get("height", height))
        width = min(width, config.max_width)
        height = min(height, config.max_height)
        if width == 0 and height == 0:
            width = 350

        imgs = 1.0
        ll = layer.pop(0)
        if ll[-2:] == "!c":
            ll = ll[:-2]
            if wkt:
                wkt = "," + wkt
            wkt = correctify.corr_wkt(config.layers[ll]) + wkt
            srs = config.layers[ll]["proj"]

        try:
            # WMS image
            result_img = self.getimg(box, srs, (height, width), config.layers[ll], start_time, force)
        except KeyError:
            result_img = Image.new("RGBA", (width, height))

        for ll in layer:
            if ll[-2:] == "!c":
                ll = ll[:-2]
                if wkt:
                    wkt = "," + wkt
                wkt = correctify.corr_wkt(config.layers[ll]) + wkt
                srs = config.layers[ll]["proj"]

            im2 = self.getimg(box, srs, (height, width), config.layers[ll], start_time, force)
            if "empty_color" in config.layers[ll]:
                ec = ImageColor.getcolor(config.layers[ll]["empty_color"], "RGBA")
                sec = set(ec)
                if "empty_color_delta" in config.layers[ll]:
                    delta = config.layers[ll]["empty_color_delta"]
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

        # Applying filters
        # result_img = filter.raster(result_img, filt, req_bbox, srs)
        if flip_h:
            result_img = ImageOps.flip(result_img)

        img_buf = BytesIO()
        if content_type == "image/jpeg":
            result_img = result_img.convert("RGB")
            try:
                result_img.save(img_buf, 'JPEG', quality=config.output_quality, progressive=config.output_progressive)
            except OSError:
                result_img.save(img_buf, 'JPEG', quality=config.output_quality)
        elif content_type == "image/png":
            result_img.save(img_buf, 'PNG', progressive=config.output_progressive, optimize=config.output_optimize)
        elif content_type == "image/gif":
            result_img.save(img_buf, 'GIF', quality=config.output_quality, progressive=config.output_progressive)
        else:  # E.g. GIF
            result_img = result_img.convert("RGB")
            result_img.save(img_buf, content_type.split('/')[1], quality=config.output_quality, progressive=config.output_progressive)
        return HTTPStatus.OK, content_type, img_buf.getvalue()

    def getimg(self, bbox, request_proj, size, layer, start_time, force):
        """Get tile for a given bbox."""
        orig_bbox = bbox
        ## Making 4-corner maximal bbox
        bbox_p = projections.from4326(bbox, request_proj)
        bbox_p = projections.to4326(
            (bbox_p[2], bbox_p[1], bbox_p[0], bbox_p[3]), request_proj)

        bbox_4 = (
            (bbox_p[2], bbox_p[3]),
            (bbox[0], bbox[1]),
            (bbox_p[0], bbox_p[1]),
            (bbox[2], bbox[3]))
        if "nocorrect" not in force:
            bb4 = []
            for point in bbox_4:
                bb4.append(correctify.rectify(layer, point))
            bbox_4 = bb4
        bbox = bbox_utils.expand_to_point(bbox, bbox_4)
        H, W = size

        max_zoom = layer.get("max_zoom", config.default_max_zoom)
        min_zoom = layer.get("min_zoom", config.default_min_zoom)

        zoom = bbox_utils.zoom_for_bbox(
            bbox, size, layer, min_zoom, max_zoom, (config.max_height, config.max_width)
        )
        from_tile_x, from_tile_y, to_tile_x, to_tile_y = projections.tile_by_bbox(
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
        # print(x, y, file=sys.stderr)
        # sys.stderr.flush()
        out = Image.new("RGBA", (x, y))
        for x in range(from_tile_x, to_tile_x + 1):
            for y in range(to_tile_y, from_tile_y + 1):
                im1 = self.tile_image(layer, zoom, x, y, start_time, real=True)
                if im1:
                    if (layer["prefix"], zoom, x, y) not in self.cached_objs:
                        self.cached_objs[(layer["prefix"], zoom, x, y)] = im1
                        self.cached_hist_list.append((layer["prefix"], zoom, x, y))
                        # print((layer["prefix"], zoom, x, y), self.cached_objs[(layer["prefix"], zoom, x, y)], file=sys.stderr)
                        # sys.stderr.flush()
                    if len(self.cached_objs) >= config.max_ram_cached_tiles:
                        del self.cached_objs[self.cached_hist_list.pop(0)]
                        # print("Removed tile from cache", file=sys.stderr)
                        # sys.stderr.flush()
                else:
                    ec = ImageColor.getcolor(
                        layer.get("empty_color", config.default_background), "RGBA")
                    im1 = Image.new("RGBA", (256, 256), ec)
                out.paste(im1, ((x - from_tile_x) * 256, (-to_tile_y + y) * 256))

        ## TODO: Here's a room for improvement. we could drop this crop in case user doesn't need it.
        out = out.crop(bbox_im)
        if "noresize" not in force:
            if (H == W) and (H == 0):
                W, H = out.size
            if H == 0:
                H = out.size[1] * W // out.size[0]
            if W == 0:
                W = out.size[0] * H // out.size[1]
        # bbox = orig_bbox
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

    def tile_image(self, layer, z, x, y, start_time, again=False, trybetter=True, real=False):
        """Returns asked tile (from cache, fetcher, or recursively rescaled).

        again - is this a second pass on this tile?
        trybetter - should we try to combine this tile from better ones?
        real - should we return the tile even in not good quality?

        dsc.downscale?
        ups.upscale?
        """
        # Dedicated fetcher for each imagery layer - if one fetcher hangs,
        # others should be responsive
        if layer['prefix'] not in self.fetchers_pool:
            self.fetchers_pool[layer['prefix']] = fetchers.TileFetcher(layer)

        x = x % (2 ** (z - 1))
        if y < 0 or y >= (2 ** (z - 1)):
            return None
        if not bbox_utils.bbox_is_in(
            projections.bbox_by_tile(z, x, y, layer["proj"]),
            layer.get("data_bounding_box", config.default_bbox),
            fully=False,
        ):
            return None
        if "prefix" in layer:
            if (layer["prefix"], z, x, y) in self.cached_objs:
                return self.cached_objs[(layer["prefix"], z, x, y)]

        # Working with cache
        if layer.get("cached", True):
            # Second, try to glue image of better ones
            if layer["scalable"] and (z < layer.get("max_zoom", config.default_max_zoom)) and trybetter:
                print("tile_image: scaling tile")
                # # Load upscaled images
                # if os.path.exists(local + "ups." + ext):
                #     try:
                #         im = Image.open(local + "ups." + ext)
                #         return im
                #     except OSError:
                #         pass
                ec = ImageColor.getcolor(layer.get("empty_color", config.default_background), "RGBA")
                ec = (ec[0], ec[1], ec[2], 0)
                im = Image.new("RGBA", (512, 512), ec)
                im1 = self.tile_image(layer, z + 1, x * 2, y * 2, start_time)
                if im1:
                    im2 = self.tile_image(layer, z + 1, x * 2 + 1, y * 2, start_time)
                    if im2:
                        im3 = self.tile_image(layer, z + 1, x * 2, y * 2 + 1, start_time)
                        if im3:
                            im4 = self.tile_image(layer, z + 1, x * 2 + 1, y * 2 + 1, start_time)
                            if im4:
                                im.paste(im1, (0, 0))
                                im.paste(im2, (256, 0))
                                im.paste(im3, (0, 256))
                                im.paste(im4, (256, 256))
                                im = im.resize((256, 256), Image.ANTIALIAS)
                                # if layer.get("cached", True):
                                #     try:
                                #         im.save(local + "ups." + ext)
                                #     except OSError:
                                #         pass
                                return im
            if not again:
                if 'fetch' in layer:
                    seconds_spent = (datetime.datetime.now() - start_time).total_seconds()
                    if (config.deadline > seconds_spent) or (z < 4):
                        print(f"tile_image: invoke fetcher for z{z}/x{x}/y{y}")
                        im = self.fetchers_pool[layer['prefix']].fetch(z, x, y)  # Try fetching from outside
                        if im:
                            return im
            if real and (z > 1):
                im = self.tile_image(layer, z - 1, int(x // 2), int(y // 2), start_time, again=False, trybetter=False, real=True)
                if im:
                    im = im.crop(
                        (
                            128 * (x % 2),
                            128 * (y % 2),
                            128 * (x % 2) + 128,
                            128 * (y % 2) + 128,
                        )
                    )
                    im = im.resize((256, 256), Image.BILINEAR)
                    return im
        else:
            if 'fetch' in layer:
                print("tile_image: fetching an uncached layer")
                seconds_spent = (datetime.datetime.now() - start_time).total_seconds()
                if (config.deadline > seconds_spent) or (z < 4):
                    im = self.fetchers_pool[layer['prefix']].fetch(z, x, y)  # Try fetching from outside
                    if im:
                        return im
