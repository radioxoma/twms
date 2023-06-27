import hashlib
import http.client
import http.cookiejar
import logging
import mimetypes
import pathlib
import re
import textwrap
import time
import urllib.error
import urllib.request as request
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from http import HTTPStatus
from io import BytesIO

from PIL import Image

import twms.config
import twms.projections

# import ssl
# ssl._create_default_https_context = ssl._create_unverified_context  # Disable context for gismap.by

logger = logging.getLogger(__name__)


class TileFile:
    """Filesystem cache.

      * TWMS stores tiles of 256x256 pixels
      * TWMS stores whole cache in single user-defined mimetype. If server returns tile with needed mimetype, original image is preserved, otherwise it will be recompressed
      * TWMS internally uses 'GLOBAL_WEBMERCATOR' grid, 'EPSG:3857' (formely known as 'EPSG:900913') projection, origin north-west (compatible with OpenStreetMap, mapproxy.org)
      * Same as SAS.Planet "Mobile Atlas Creator (MOBAC)" cache `cache_ma/{z}/{x}/{y}{ext}` 0,0 from the top left (nw)

    See:
      [1] https://en.wikipedia.org/wiki/Tiled_web_map
      [2] https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames
      [3] https://josm.openstreetmap.de/wiki/SharedTileCache
    """

    def __init__(
        self,
        cache_dir: str,
        layer_id: str,
        mimetype: str,
        z: int,
        x: int,
        y: int,
        ttl: int | None = None,
    ):
        """Filesystem tile storage "cache_dir/layer_id/z/x/y.ext".

        Conforms SAS.Planet (with TNE), MOBAC, MapProxy 'tms' directory layout.

        TNE - tile not exist (got HTTP 404 or default tile for empty zones aka "dead tile")

        Args:
            cache_dir: relative path to tile cache
            layer_id: subdir for a single cache
            mimetype: One mimetype for whole layer
            z: tile coordinate (starts with zero)
            x: tile coordinate
            y: tile coordinate (positive)
            ttl: time-to-live, seconds or None
        """
        self.mimetype = mimetype
        self.ttl = ttl

        z, x, y = int(z), int(x), int(y)  # Prevent floats from messing up path
        prefix = pathlib.Path(cache_dir) / layer_id
        ext = mimetypes.guess_extension(self.mimetype)
        self.path = prefix / f"{z}/{x}/{y}{ext}"
        self.path_tne = prefix / f"{z}/{x}/{y}.tne"  # Tile not exists

    def __str__(self):
        return f"'{self.mimetype}' TTL: {self.ttl}, '{self.path}'"

    def get(self) -> pathlib.Path:
        """Get tile.

        Must check `needs_fetch()` or `exists()` before.
        """
        logger.debug(f"File cache hit {self.path}")
        return self.path

    def set(self, blob: bytes | None = None) -> None:
        """Set image to cache and remove TNE.

        Args:
            blob: Image data or Mone. None means create TNE file (tile not exists).
        """
        logger.debug(f"Saving {self.path}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if blob:
            self.path.write_bytes(blob)  # Overwrite if exists, newer delete
            self.path_tne.unlink(missing_ok=True)  # Remove TNE-files only there
        else:
            # Empty file, no timestamp inside to save disk space
            logger.info(f"TNE {self.path}")
            self.path_tne.touch()

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path_tne.unlink(missing_ok=True)

    def exists(self) -> bool:
        """For filling map."""
        # Return (1, timestamp) in SQL
        return self.path.exists()

    def needs_fetch(self) -> bool:
        """Not exists in cache or TTL has been reached.

        Returns:
            True if not exists or st_mtime > TTL.
        """
        if self.path_tne.exists():
            if self.ttl and self.ttl < (time.time() - self.path_tne.stat().st_mtime):
                logger.info(f"TTL TNE reached: '{self.path}'")
                return True
            else:
                return False
        # No else for TNE, try to check tile image

        if self.path.exists():
            if self.ttl and self.ttl < (time.time() - self.path.stat().st_mtime):
                logger.info(f"TTL tile reached: '{self.path}'")
                return True
            else:
                return False
        else:
            return True


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
        fetcher_names = ("tms", "tms_google_sat")
        if self.layer["fetch"] not in fetcher_names:
            raise ValueError(f"'fetch' must be one of {fetcher_names}")
        self.__worker = getattr(self, self.layer["fetch"])  # Choose fetcher
        self.opener = prepare_opener(headers=self.layer["headers"])
        self.thread_pool = ThreadPoolExecutor(
            max_workers=twms.config.dl_threads_per_layer
        )
        # self._ic = Image.new("RGBA", (256, 256), self.layer["empty_color"])

    def fetch(self, z: int, x: int, y: int) -> Image.Image | None:
        """Fetch tile asynchronously.

        Returns:
            Image or None if no image can be served.
        """
        return self.thread_pool.submit(self.__worker, z, x, y).result()

    def tms(self, z: int, x: int, y: int) -> Image.Image | None:
        """Fetch tile by coordinates, r/w cache.

        Function fetches image, checks it validity and detects actual
        image format (ignores server Content-Type). All tiles with
        Content-Type not matching default for this layer will be
        converted before saving to cache.
        """
        tile_parsed = False
        tile_dead = False
        tile_id = f"{self.layer['prefix']} z{z}/x{x}/y{y}"

        if z < self.layer["min_zoom"] or z > self.layer["max_zoom"]:
            logger.info(f"Zoom limit {tile_id}")
            return None

        tile = TileFile(
            cache_dir=twms.config.tiles_cache,
            layer_id=self.layer["prefix"],
            z=z,
            x=x,
            y=y,
            mimetype=self.layer["mimetype"],
            ttl=self.layer["cache_ttl"],
        )

        # Fetching image
        if "remote_url" in self.layer and tile.needs_fetch():
            if "transform_tile_number" in self.layer:
                trans_z, trans_x, trans_y = self.layer["transform_tile_number"](z, x, y)
            else:
                trans_z, trans_x, trans_y = z, x, y

            # Placeholder substitution
            # TMS
            remote = self.layer["remote_url"].replace("{z}", str(trans_z))
            remote = remote.replace("{x}", str(trans_x))
            remote = remote.replace("{y}", str(trans_y))
            # Avoid negative zoom errors i.e. when`"transform_tile_number": lambda z, x, y: (z - 8, x, y)`
            if "{-y}" in remote:
                remote = remote.replace(
                    "{-y}", str(tile_slippy_to_tms(trans_z, trans_x, trans_y)[2])
                )
            # Bing quadkey
            remote = remote.replace("{q}", tile_to_quadkey(trans_z, trans_x, trans_y))

            # WMS support, no difference with TMS except missing TNE feature
            # Some considerations:
            #   * Biger tile request (e.g. 512x512)?
            #   * Using different 'wms_proj' parameter, as server may be broken
            if "{bbox}" in remote:
                proj = self.layer["proj"]
                tile_bbox = "{},{},{},{}".format(
                    *twms.projections.from4326(
                        twms.projections.bbox_by_tile(z, x, y, proj),
                        proj,
                    )
                )
                remote = remote.replace("{bbox}", tile_bbox)
                remote = remote.replace("{width}", "256")
                remote = remote.replace("{height}", "256")
                remote = remote.replace("{proj}", proj)
            try:
                # Got response, need to verify content
                logger.info(f"{tile_id}: FETCHING {remote}")
                remote_resp = self.opener(remote)
                remote_bytes = remote_resp.read()
                # Catching invalid pictures
                if remote_bytes:
                    try:
                        im = Image.open(BytesIO(remote_bytes))
                        im.load()  # Validate image
                        tile_parsed = True
                    except (OSError, AttributeError):
                        logger.error(f"{tile_id}: failed to parse response as image")
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
                resp = err.read()
                if err.status == HTTPStatus.NOT_FOUND:
                    logger.warning(f"{tile_id}: TNE - {err}")
                    tile.set()
                    return None
                if (
                    "dead_tile" in self.layer
                    and "http_status" in self.layer["dead_tile"]
                    and err.status == self.layer["dead_tile"]["http_status"]
                ):
                    logger.warning(f"{tile_id}: TNE - {err}")
                    tile.set()
                    return None

                logger.error(
                    textwrap.dedent(
                        f"""
                    {resp.decode("utf-8")}
                    {err}
                    {err.headers}
                    """
                    )
                    + f"md5sum: '{hashlib.md5(resp).hexdigest()}'"
                )

            except urllib.error.URLError as err:
                # Nothing we can do: no connection, cannot guess TNE or not
                logger.error(f"{tile_id} URLError '{err}'")

            # Save something in cache
            # Sometimes server returns file instead of empty HTTP response
            if "dead_tile" in self.layer:
                # Compare bytestring with dead tile hash
                if (
                    "size" in self.layer["dead_tile"]
                    and "md5" in self.layer["dead_tile"]
                ):
                    if len(remote_bytes) == self.layer["dead_tile"]["size"]:
                        hasher = hashlib.md5(remote_bytes)
                        if hasher.hexdigest() == self.layer["dead_tile"]["md5"]:
                            # Tile is recognized as empty
                            # An example http://ecn.t0.tiles.virtualearth.net/tiles/a120210103101222.jpeg?g=0
                            # SASPlanet writes empty files with '.tne' ext
                            logger.warning(f"{tile_id}: TNE - dead tile")
                            tile_dead = True
                            tile.set()
                # TNE based on histogram (from WMS)
                # if im.histogram() == self._ic.histogram():
                #     logger.debug(f"{tile_id}: TNE - empty histogram")
                #     tile.set()
                #     return None

            logger.debug(f"tile parsed {tile_parsed}, dead {tile_dead}")
            if tile_parsed and not tile_dead:
                # All well, save tile to cache
                # Preserving original image if possible, as encoding is lossy
                # Storing all images into one format, just like SAS.Planet does
                if im.get_format_mimetype() != self.layer["mimetype"]:
                    logger.warning(
                        f"{tile_id} unexpected image Content-Type {im.get_format_mimetype()}, converting to '{self.layer['mimetype']}'"
                    )
                    image_bytes = im_convert(im, self.layer["mimetype"])
                else:
                    image_bytes = remote_bytes

                tile.set(image_bytes)
                return im
            logger.warning(f"{tile_id}: unreachable tile {remote}")

        # If fetching failed
        if tile.exists():
            try:
                im = Image.open(tile.get())
                im.load()
                return im
            except OSError:
                logger.warning(f"{tile_id}: failed to parse image from cache")
                # tile.delete()  # Cached tile is broken - remove it

        logger.warning(f"{tile_id}: tile load failed")
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
