import os
import sys
import imp
from io import BytesIO
import time
import datetime
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


import correctify
import capabilities
import fetchers
import bbox as bbox_utils
import projections
import overview
import mimetypes


class ImageryHandler(object):
    def __init__(self):
        super(ImageryHandler, self).__init__()
        self.cached_objs = {}  # a dict. (layer, z, x, y): PIL image
        self.cached_hist_list = list()
        self.fetchers_pool = dict()

    def handler(self, data):
        """
        Do main TWMS work.
        data - dictionary of params.
        returns (error_code, content_type, resp)

        http://cite.opengeospatial.org/OGCTestData/wms/1.1.1/spec/wms1.1.1.html

        http://127.0.0.1:8080/?request=GetCapabilities&
        http://127.0.0.1:8080/?request=GetCapabilities&version=1.0.0
        """
        # WMS keys must be case insensitive, values must not
        data = {k.lower(): v for k, v in data.items()}
        start_time = datetime.datetime.now()
        content_type = "text/html"
        resp = ""
        srs = data.get("srs", "EPSG:4326")
        gpx = data.get("gpx", "").split(",")
        if gpx == [""]:
            gpx = []
        wkt = data.get("wkt", "")
        trackblend = float(data.get("trackblend", "0.5"))
        color = data.get("color", data.get("colour", "")).split(",")
        track = False

        req_type = data.get("request", "GetMap")
        version = data.get("version", "1.1.1")
        ref = data.get("ref", config.service_url)

        if req_type == "GetCapabilities":
            content_type, resp = capabilities.get(version, ref)
            return (HTTPStatus.OK, content_type, resp)

        layer = data.get("layers", config.default_layers).split(",")
        if "layers" in data and not layer[0]:
            layer = ["transparent"]

        if req_type == "GetCorrections":
            points = data.get("points", data.get("POINTS", "")).split("=")
            resp = ""
            points = [a.split(",") for a in points]
            points = [(float(a[0]), float(a[1])) for a in points]

            req.content_type = "text/plain"
            for lay in layer:
                for point in points:
                    resp += "%s,%s;" % tuple(correctify.rectify(config.layers[lay], point))
                resp += "\n"
            return (HTTPStatus.OK, content_type, resp)

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

        content_type = 'image/jpeg'  # Default content type of image to serve
        try:
            # Get requested content type from standard WMS 'format' parameter,
            # https://docs.geoserver.org/stable/en/user/services/wms/outputformats.html
            content_type = data['format']
            if content_type not in mimetypes.types_map.values():
                return HTTPStatus.INTERNAL_SERVER_ERROR, 'text/plain', f"Invalid image format '{content_type}' requested"
        except KeyError:
            pass
        try:
            # Get content type by link extension
            content_type = mimetypes.types_map[data['ext']]
        except KeyError:
            pass

        width = 0
        height = 0
        resp_cache_path, resp_ext = "", ""
        z = int(data.get("z", 1)) + 1
        x = int(data.get("x", 0))
        y = int(data.get("y", 0))
        if req_type == "GetTile":
            width = 256
            height = 256
            height = int(data.get("height", height))
            width = int(data.get("width", width))
            srs = data.get("srs", "EPSG:3857")
            if "cache_tile_responses" in dir(config) and not wkt and (len(gpx) == 0):
                if (
                        srs,
                        tuple(layer),
                        filt,
                        width,
                        height,
                        force,
                        content_type,
                ) in config.cache_tile_responses:

                    resp_cache_path, resp_ext = config.cache_tile_responses[
                        (srs, tuple(layer), filt, width, height, force, content_type)
                    ]
                    resp_cache_path = resp_cache_path + "/%s/%s/%s.%s" % (
                        z - 1,
                        x,
                        y,
                        resp_ext,
                    )
                    if os.path.exists(resp_cache_path):
                        return (HTTPStatus.OK, content_type, open(resp_cache_path, "r").read())
            if len(layer) == 1:
                if layer[0] in config.layers:
                    if (
                            config.layers[layer[0]]["proj"] == srs
                            and width == 256
                            and height == 256
                            and not filt
                            and not force
                            and not correctify.has_corrections(config.layers[layer[0]])):
                        local = (
                                config.tiles_cache + config.layers[layer[0]]["prefix"]
                                # + "/z%s/%s/x%s/%s/y%s." % (z, x // 1024, x, y // 1024, y)
                                + "/z{:.0f}/{:.0f}/{:.0f}.".format(z - 1, y, x)
                        )
                        ext = config.layers[layer[0]]["ext"]
                        adds = ["", "ups."]
                        for add in adds:
                            if os.path.exists(local + add + ext):
                                tile_file = open(local + add + ext, 'rb').read()
                                return (HTTPStatus.OK, content_type, tile_file)

        req_bbox = projections.from4326(projections.bbox_by_tile(z, x, y, srs), srs)

        # Indent?
        if data.get("bbox", None):
            req_bbox = tuple(map(float, data.get("bbox", req_bbox).split(",")))

        req_bbox = projections.to4326(req_bbox, srs)

        req_bbox, flip_h = bbox_utils.normalize(req_bbox)
        box = req_bbox

        height = int(data.get("height", height))
        width = int(data.get("width", width))
        width = min(width, config.max_width)
        height = min(height, config.max_height)
        if (width == 0) and (height == 0):
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
            result_img = self.getimg(
                box, srs, (height, width), config.layers[ll], start_time, force
            )
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

        ##Applying filters
        # result_img = filter.raster(result_img, filt, req_bbox, srs)

        if flip_h:
            result_img = ImageOps.flip(result_img)
        image_content = BytesIO()
        if content_type == "image/jpeg":
            result_img = result_img.convert("RGB")
            try:
                result_img.save(
                    image_content,
                    'JPEG',
                    quality=config.output_quality,
                    progressive=config.output_progressive,
                )
            except IOError:
                result_img.save(image_content, 'JPEG', quality=config.output_quality)
        elif content_type == "image/png":
            result_img.save(
                image_content,
                'PNG',
                progressive=config.output_progressive,
                optimize=config.output_optimize,
            )
        elif content_type == "image/gif":
            result_img.save(
                image_content,
                'GIF',
                quality=config.output_quality,
                progressive=config.output_progressive,
            )
        else:  # E.g. GIF
            result_img = result_img.convert("RGB")
            result_img.save(
                image_content,
                content_type.split('/')[1],
                quality=config.output_quality,
                progressive=config.output_progressive,
            )
        resp = image_content.getvalue()
        if resp_cache_path:
            try:
                "trying to create local cache directory, if it doesn't exist"
                os.makedirs("/".join(resp_cache_path.split("/")[:-1]))
            except OSError:
                pass
            try:
                a = open(resp_cache_path, "w")
                a.write(resp)
                a.close()
            except (OSError, IOError):
                print(
                    "error saving response answer to file %s." % (resp_cache_path),
                    file=sys.stderr,
                )
                sys.stderr.flush()

        return (HTTPStatus.OK, content_type, resp)

    def getimg(self, bbox, request_proj, size, layer, start_time, force):
        orig_bbox = bbox
        ## Making 4-corner maximal bbox
        bbox_p = projections.from4326(bbox, request_proj)
        bbox_p = projections.to4326(
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
                bb4.append(correctify.rectify(layer, point))
            bbox_4 = bb4
        bbox = bbox_utils.expand_to_point(bbox, bbox_4)
        # print(bbox)
        # print(orig_bbox)

        H, W = size

        max_zoom = layer.get("max_zoom", config.default_max_zoom)
        min_zoom = layer.get("min_zoom", config.default_min_zoom)

        zoom = bbox_utils.zoom_for_bbox(
            bbox, size, layer, min_zoom, max_zoom, (config.max_height, config.max_width)
        )
        lo1, la1, lo2, la2 = bbox
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
                got_image = False
                im1 = self.tile_image(layer, zoom, x, y, start_time, real=True)
                if im1:
                    if (layer["prefix"], zoom, x, y) not in self.cached_objs:
                        if im1.is_ok:
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
                    # ec = (ec[0],ec[1],ec[2],0)
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
        """
        Returns asked image.
        again - is this a second pass on this tile?
        trybetter - should we try to combine this tile from better ones?
        real - should we return the tile even in not good quality?
        """
        # Dedicated fetcher for each imagery layer - if one layer hangs,
        # others should be responsive
        if layer['prefix'] not in self.fetchers_pool:
            self.fetchers_pool['prefix'] = fetchers.TileFetcher(layer)

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
        if layer.get("cached", True):
            local = (
                config.tiles_cache + layer["prefix"]
                # + "/z%s/%s/x%s/%s/y%s." % (z, x // 1024, x, y // 1024, y)
                + "/z{:.0f}/{:.0f}/{:.0f}.".format(z - 1, y, x)  # Changed Z!
            )
            ext = layer["ext"]
            if "cache_ttl" in layer:
                for ex in [ext, "dsc." + ext, "ups." + ext, "tne"]:
                    f = local + ex
                    if os.path.exists(f):
                        if os.stat(f).st_mtime < (time.time() - layer["cache_ttl"]):
                            os.remove(f)

            gpt_image = False
            os.makedirs("/".join(local.split("/")[:-1]), exist_ok=True)

            if not os.path.exists(local + "tne") and not os.path.exists(local + "lock"):
                if os.path.exists(local + ext):  # First, look for tile in cache
                    try:
                        im1 = Image.open(local + ext)
                        im1.is_ok = True
                        return im1
                    except IOError:
                        if os.path.exists(local + "lock"):
                            return None
                        else:
                            os.remove(local + ext)  # # Cached tile is broken - remove it

                if (
                    layer["scalable"]
                    and (z < layer.get("max_zoom", config.default_max_zoom))
                    and trybetter
                ):  # Second, try to glue image of better ones
                    if os.path.exists(local + "ups." + ext):
                        try:
                            im = Image.open(local + "ups." + ext)
                            im.is_ok = True
                            return im
                        except IOError:
                            pass
                    ec = ImageColor.getcolor(
                        layer.get("empty_color", config.default_background), "RGBA"
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
                                    im = im.resize((256, 256), Image.ANTIALIAS)
                                    if layer.get("cached", True):
                                        try:
                                            im.save(local + "ups." + ext)
                                        except IOError:
                                            pass
                                    im.is_ok = True
                                    return im
                if not again:
                    if "fetch" in layer:
                        delta = datetime.datetime.now() - start_time
                        delta = delta.seconds + delta.microseconds / 1000000
                        if (config.deadline > delta) or (z < 4):
                            im = self.fetchers_pool['prefix'].fetch(z, x, y)  # Try fetching from outside
                            if im:
                                im.is_ok = True
                                return im
            if real and (z > 1):
                im = self.tile_image(
                    layer,
                    z - 1,
                    int(x / 2),
                    int(y / 2),
                    start_time,
                    again=False,
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
                    im = im.resize((256, 256), Image.BILINEAR)
                    im.is_ok = False
                    return im
        else:
            if "fetch" in layer:
                delta = datetime.datetime.now() - start_time
                delta = delta.seconds + delta.microseconds / 1000000.0
                if (config.deadline > delta) or (z < 4):
                    im = self.fetchers_pool['prefix'].fetch(z, x, y)  # Try fetching from outside
                    if im:
                        im.is_ok = True
                        return im
