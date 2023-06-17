import hashlib
import http.client
import http.cookiejar
import logging
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request as request
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from http import HTTPStatus
from io import BytesIO
from pathlib import Path

from PIL import Image

import twms.config
import twms.projections

# import ssl
# ssl._create_default_https_context = ssl._create_unverified_context  # Disable context for gismap.by

logger = logging.getLogger(__name__)


def prepare_opener(
    tries: int = 4, delay: int = 3, backoff: int = 2, headers: dict = dict()
):
    """Build HTTP opener with custom headers (User-Agent) and cookie support.

    Retry HTTP request using an exponential backoff:
        * Retry only on network issues
        * Raise HTTPError immediatly, to handle it with complex code

    https://wiki.python.org/moin/PythonDecoratorLibrary#Retry
    http://www.katasonov.com/ru/2014/10/python-urllib2-decorators-and-exceptions-fun/

    Args:
        tries: number of times to try (not retry) before giving up
        delay: initial delay between retries in seconds
        backoff: backoff multiplier e.g. value of 2 will double the
        delay each retry
        headers: Update opener headers (add new and spoof existing)
    """
    cj = http.cookiejar.CookieJar()

    # if use_proxy:
    #     proxy_info = {
    #         'user': 'login',
    #         'pass': 'passwd',
    #         'host': "proxyaddress",
    #         'port': 8080}

    #     proxy_support = urllib.request.ProxyHandler({
    #         "http": "http://%(user)s:%(pass)s@%(host)s:%(port)d" % proxy_info})
    #     opener = urllib.request.build_opener(
    #         urllib.request.HTTPCookieProcessor(cj),
    #         # urllib2.HTTPHandler(debuglevel=1),  # Debug output
    #         proxy_support)

    opener = request.build_opener(request.HTTPCookieProcessor(cj))
    hdrs = twms.config.default_headers | headers
    opener.addheaders = list(hdrs.items())

    @wraps(opener.open)
    def retry(*args, **kwargs) -> http.client.HTTPResponse:
        mtries, mdelay = tries, delay
        while mtries > 1:
            try:
                return opener.open(*args, **kwargs)
            except urllib.error.HTTPError:
                # Prevent catching HTTPError as subclass of URLError
                # logger.error(err)
                raise
            except urllib.error.URLError as err:
                logger.debug(f"{err}, retrying '{args[0]}' in {mdelay} seconds...")
                time.sleep(mdelay)
                mtries -= 1
                mdelay *= backoff
        return opener.open(*args, **kwargs)

    return retry


class TileFetcher:
    def __init__(self, layer_id: str):
        self.layer = twms.config.layers[layer_id]
        fetcher_names = ("tms", "wms", "tms_google_sat")
        if self.layer["fetch"] not in fetcher_names:
            raise ValueError(f"'fetch' must be one of {fetcher_names}")
        self.__worker = getattr(self, self.layer["fetch"])  # Choose fetcher
        self.opener = prepare_opener(headers=self.layer.get("headers", dict()))
        self.thread_pool = ThreadPoolExecutor(
            max_workers=twms.config.dl_threads_per_layer
        )

    def fetch(self, z: int, x: int, y: int) -> Image.Image | None:
        """Fetch tile asynchronously.

        Returns:
            Image or None if no image can be served.
        """
        return self.thread_pool.submit(self.__worker, z, x, y).result()

    def wms(self, z: int, x: int, y: int) -> Image.Image | None:
        """Use tms instead.

        Possible features to implement:
            * TNE based on histogram
            * Big tile request (e.g. 512x512)

        Leave possibility to request arbitrary (other than cache 'proj')
        projection from WMS by 'wms_proj' parameter, as server may be broken.
        """
        tile_id = f"{self.layer['prefix']} z{z}/x{x}/y{y}"
        if "max_zoom" in self.layer and z > self.layer["max_zoom"]:
            logger.debug(f"{tile_id}: zoom limit")
            return None
        req_proj = self.layer.get("wms_proj", self.layer["proj"])

        width = 256  # Using larger source size to rescale better in python
        height = 256
        tile_bbox = "{},{},{},{}".format(
            *twms.projections.from4326(
                twms.projections.bbox_by_tile(z, x, y, req_proj), req_proj
            )
        )

        remote = self.layer["remote_url"].replace("{bbox}", tile_bbox)
        remote = remote.replace("{width}", str(width))
        remote = remote.replace("{height}", str(height))
        remote = remote.replace("{proj}", req_proj)

        # MOBAC cache path style
        tile_path = (
            twms.config.tiles_cache
            + self.layer["prefix"]
            + "/{:.0f}/{:.0f}/{:.0f}{}".format(
                z,
                x,
                y,
                mimetypes.guess_extension(self.layer["mimetype"]),
            )
        )
        partial_path, ext = os.path.splitext(tile_path)  # '.ext' with leading dot
        tne_path = partial_path + ".tne"

        os.makedirs(os.path.dirname(tile_path), exist_ok=True)

        if "cache_ttl" in self.layer:
            for ex in (ext, ".dsc" + ext, ".ups" + ext, ".tne"):
                fp = partial_path + ex
                if os.path.exists(fp):
                    if os.stat(fp).st_mtime < (time.time() - self.layer["cache_ttl"]):
                        os.remove(fp)

        logger.info(f"wms: fetching z{z}/x{x}/y{y} {self.layer['name']} {remote}")
        im_bytes = self.opener(remote).read()
        if im_bytes:
            im = Image.open(BytesIO(im_bytes))
        else:
            return None
        if width != 256 and height != 256:
            im = im.resize((256, 256), Image.ANTIALIAS)
        im = im.convert("RGBA")

        ic = Image.new(
            "RGBA",
            (256, 256),
            self.layer["empty_color"],
        )
        if im.histogram() == ic.histogram():
            logger.debug(f"{tile_id}: TNE - empty histogram '{tne_path}'")
            Path(tne_path, exist_ok=True).touch()
            return None
        im.save(tile_path)
        return im

    def tms(self, z: int, x: int, y: int) -> Image.Image | None:
        """Fetch tile by coordinates, r/w cache.

        Function fetches image, checks it validity and detects actual
        image format (ignores server Content-Type). All tiles with
        Content-Type not matching default for this layer will be
        converted before saving to cache.

        TNE - tile not exist (got HTTP 404 or default tile for empty zones aka "dead tile")

        Cache is structured according to tile coordinates.
        Actual tile image projection specified in config file.

        :rtype: :py:class:`~PIL.Image.Image`. Otherwise None, if
            no image can be served from cache or from remote.
        """
        need_fetch = False
        tile_parsed = False
        tile_dead = False
        tile_id = f"{self.layer['prefix']} z{z}/x{x}/y{y}"
        target_mimetype = self.layer["mimetype"]
        remote = ""

        if "max_zoom" in self.layer and z > self.layer["max_zoom"]:
            logger.debug(f"{tile_id}: zoom limit")
            return None

        # MOBAC cache path style
        tile_path = (
            twms.config.tiles_cache
            + self.layer["prefix"]
            + "/{:.0f}/{:.0f}/{:.0f}{}".format(
                z,
                x,
                y,
                mimetypes.guess_extension(self.layer["mimetype"]),
            )
        )
        partial_path, ext = os.path.splitext(tile_path)  # '.ext' with leading dot
        tne_path = partial_path + ".tne"
        os.makedirs(os.path.dirname(tile_path), exist_ok=True)

        # Do not delete, only replace if tile exists!
        if os.path.exists(tne_path):
            tne_lifespan = time.time() - os.stat(tne_path).st_mtime
            if tne_lifespan > twms.config.cache_tne_ttl:
                logger.info(f"{tile_id}: TTL tne reached {tne_path}")
                need_fetch = True
            else:
                logger.info(f"{tile_id}: tile cached as TNE {tne_path}")
        if "cache_ttl" in self.layer:
            # for ex in (ext, '.dsc.' + ext, '.ups.' + ext, '.tne'):
            if os.path.exists(tile_path):
                tile_lifespan = time.time() - os.stat(tile_path).st_mtime
                # tile_lifespan_h = tile_lifespan / 60 / 60
                # logger.debug(f"{tile_id}: lifespan {tile_lifespan_h:.0f} h {fp}")
                if tile_lifespan > self.layer["cache_ttl"]:
                    logger.debug(f"{tile_id}: TTL tile reached for {tile_path}")
                    need_fetch = True

        if not os.path.exists(tile_path) and not os.path.exists(tne_path):
            need_fetch = True

        # Fetching image
        if need_fetch and "remote_url" in self.layer:
            if "transform_tile_number" in self.layer:
                trans_z, trans_x, trans_y = self.layer["transform_tile_number"](z, x, y)
            else:
                trans_z, trans_x, trans_y = z, x, y

            # Placeholder substitution
            # TMS
            remote = self.layer["remote_url"].replace("{z}", str(trans_z))
            remote = remote.replace("{x}", str(trans_x))
            remote = remote.replace("{y}", str(trans_y))
            remote = remote.replace(
                "{-y}", str(tile_slippy_to_tms(trans_z, trans_x, trans_y)[2])
            )
            # Bing
            remote = remote.replace("{q}", tile_to_quadkey(trans_z, trans_x, trans_y))

            # WMS, no real difference with TMS except missing *.tne feature
            width = 256
            height = 256
            proj = self.layer["proj"]
            tile_bbox = "{},{},{},{}".format(
                *twms.projections.from4326(
                    twms.projections.bbox_by_tile(z, x, y, proj),
                    proj,
                )
            )
            remote = remote.replace("{bbox}", tile_bbox)
            remote = remote.replace("{width}", str(width))
            remote = remote.replace("{height}", str(height))
            remote = remote.replace("{proj}", proj)

            try:
                # Got response, need to verify content
                logger.info(f"{tile_id}: FETCHING {remote}")
                remote_resp = self.opener(remote)
                remote_bytes = remote_resp.read()
                if remote_bytes:
                    try:
                        im = Image.open(BytesIO(remote_bytes))
                        im.load()  # Validate image
                        tile_parsed = True
                    except (OSError, AttributeError):
                        # Catching invalid pictures
                        logger.error(
                            f"{tile_id}: failed to parse response as image {tne_path}"
                        )
                        logger.debug(
                            f"{tile_id}: invalid image {remote_resp.status}: {remote_resp.msg} - {remote_resp.reason} {remote_resp.url}\n{remote_resp.headers}"
                        )
                        # try:
                        #     logger.debug(remote_bytes.decode('utf-8'))
                        # except UnicodeDecodeError:
                        #     logger.debug(remote_bytes)
                        # if logger.getLogger().getEffectiveLevel() == logger.DEBUG:
                        #     with open('err.htm', mode='wb') as f:
                        #         f.write(remote_bytes)
                else:
                    logger.warning(f"{tile_id}: empty response")
            except urllib.error.HTTPError as err:
                # Heuristic: TNE or server is defending tiles
                # HTTP 403 must be inspected manually
                logger.error(
                    "\n".join(
                        [str(k) for k in (err, err.headers, err.read().decode("utf-8"))]
                    )
                )
                if err.status == HTTPStatus.NOT_FOUND:
                    logger.warning(f"{tile_id}: TNE - {err} '{tne_path}'")
                    Path(tne_path, exist_ok=True).touch()
            except urllib.error.URLError as err:
                # Nothing we can do: no connection, cannot guess TNE or not
                logger.error(f"{tile_id} URLError '{err}'")

            # Save something in cache
            # Sometimes server returns file instead of empty HTTP response
            if "dead_tile" in self.layer:
                # Compare bytestring with dead tile hash
                if len(remote_bytes) == self.layer["dead_tile"]["size"]:
                    hasher = hashlib.md5()
                    hasher.update(remote_bytes)
                    if hasher.hexdigest() == self.layer["dead_tile"]["md5"]:
                        # Tile is recognized as empty
                        # An example http://ecn.t0.tiles.virtualearth.net/tiles/a120210103101222.jpeg?g=0
                        # SASPlanet writes empty files with '.tne' ext
                        logger.warning(f"{tile_id}: TNE - dead tile '{tne_path}'")
                        tile_dead = True
                        Path(tne_path, exist_ok=True).touch()

            logger.debug(f"tile parsed {tile_parsed}, dead {tile_dead}")
            if tile_parsed and not tile_dead:
                # All well, save tile to cache
                logger.debug(f"{tile_id}: saving {tile_path}")

                # Preserving original image if possible, as encoding is lossy
                # Storing all images into one format, just like SAS.Planet does
                if im.get_format_mimetype() != target_mimetype:
                    logger.warning(
                        f"{tile_id} unexpected image Content-Type {im.get_format_mimetype()}, converting to '{target_mimetype}'"
                    )
                    image_bytes = im_convert(im, target_mimetype)
                else:
                    image_bytes = remote_bytes

                with open(tile_path, "wb") as f:
                    f.write(image_bytes)
                if os.path.exists(tne_path):
                    os.remove(tne_path)
                return im

        # If TTL is ok or fetching failed
        if os.path.exists(tile_path):
            try:
                im = Image.open(tile_path)
                im.load()
                logger.info(f"{tile_id}: cache tms {tile_path}")
                return im
            except OSError:
                logger.warning(
                    f"{tile_id}: failed to parse image from cache '{tile_path}'"
                )
                # os.remove(tile_path)  # Cached tile is broken - remove it

        logger.warning(f"{tile_id}: unreachable tile {remote}")
        return None

    def tms_google_sat(self, z: int, x: int, y: int) -> Image.Image:
        """Construct template URI with version from JS API.

        May be use different servers in future:
        https://khms0.google.com/kh/v=889?x=39595&y=20473&z=16
        https://khms3.google.com/kh/v=889?x=39595&y=20472&z=16

        # No 'v=?' required?
        https://mt0.google.com/vt/lyrs=s@0&hl=en&z={z}&x={x}&y={y}
        """
        if "remote_url" not in self.layer:
            try:
                resp = self.opener("https://maps.googleapis.com/maps/api/js").read()
                if resp:
                    match = re.search(
                        r"https://khms\d+.googleapis\.com/kh\?v=(\d+)",
                        resp.decode("utf-8"),
                    )
                    if match and match.group(1):
                        self.layer[
                            "remote_url"
                        ] = f"https://kh.google.com/kh/v={match.group(1)}?x={{x}}&y={{y}}&z={{z}}"
                        logger.info(
                            f"Setting new {self.layer['name']} URI {self.layer['remote_url']}"
                        )
                    else:
                        raise ValueError("Cannot parse 'v=' from maps_googleapis_js")
            except urllib.error.URLError:
                pass

        # URL version can expiry, reset if no image
        # Though it is not only possible cause of None response
        im = self.tms(z, x, y)
        if "remote_url" in self.layer and not im:
            del self.layer["remote_url"]
        return im


def tile_to_quadkey(z: int, x: int, y: int) -> str:
    """Transform tile coordinates to a Bing quadkey.

    Slippy map tiles cache numeration starts from 0 level with one tile. On 1 level four tiles etc
    Bing uses quadkey tile coordinates, so minimal cache level is 1 (four tiles). Single tile at zero level not addressed.

    https://docs.microsoft.com/en-us/bingmaps/articles/bing-maps-tile-system
    https://github.com/buckhx/QuadKey/blob/master/quadkey/tile_system.py

    Args:
        z: zoom, starts from zero

    Returns:
        Quadkey string

    Examples
    --------
    >>> tile_to_quadkey(1,0,0)
    '0'
    >>> tile_to_quadkey(4, 9, 5)
    '1203'
    >>> tile_to_quadkey(16, 38354, 20861)
    '1203010313232212'
    """
    quadkey = list()
    for i in range(z):
        bit = z - i
        digit = ord("0")
        mask = 1 << (bit - 1)
        if (x & mask) != 0:
            digit += 1
        if (y & mask) != 0:
            digit += 2
        quadkey.append(chr(digit))
    return "".join(quadkey)


def tile_slippy_to_tms(z: int, x: int, y: int) -> tuple[int, int, int]:
    """Convert Slippy map coordinate system to OSGeo TMS `{-y}`.

    https://josm.openstreetmap.de/wiki/Maps

    >>> tile_slippy_to_tms(4, 3, 2)
    (4, 3, 13)
    >>> tile_slippy_to_tms(10, 10, 10)
    (10, 10, 1013)
    """
    return z, x, (1 << z) - y - 1


def im_convert(im: Image.Image, mimetype: str) -> bytes:
    """Convert Pillow image to requested mimetype."""
    # Exif-related code not documented, Pillow can change behavior
    exif = Image.Exif()
    exif[0x0131] = twms.config.wms_name  # ExifTags.TAGS['Software']

    img_buf = BytesIO()

    if mimetype == "image/jpeg":
        im = im.convert("RGB")
        im.save(
            img_buf,
            "JPEG",
            quality=twms.config.output_quality,
            progressive=twms.config.output_progressive,
            exif=exif,
        )
    elif mimetype == "image/png":
        im.save(
            img_buf,
            "PNG",
            progressive=twms.config.output_progressive,
            optimize=twms.config.output_optimize,
            exif=exif,
        )
    elif mimetype == "image/gif":
        im.save(
            img_buf,
            "GIF",
            quality=twms.config.output_quality,
            progressive=twms.config.output_progressive,
            exif=exif,
        )
    else:
        im = im.convert("RGB")
        im.save(
            img_buf,
            mimetype.split("/")[1],
            exif=exif,
        )
    return img_buf.getvalue()
