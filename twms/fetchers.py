import os
from pathlib import Path
from io import BytesIO
import time
import re
import hashlib
import threading
from functools import wraps
import logging
import urllib.request as request
import http.cookiejar as http_cookiejar
from http import HTTPStatus
# import ssl
# ssl._create_default_https_context = ssl._create_unverified_context  # Disable context for gismap.by

from PIL import Image

from twms import projections
from twms import config


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:84.0) Gecko/20100101 Firefox/84.0",
    "Connection": "Keep-Alive"}


def prepare_opener(tries=4, delay=3, backoff=2, headers=dict()):
    """Build HTTP opener with custom headers (User-Agent) and cookie support.

    Retry HTTP request using an exponential backoff:
        * Retry only on network issues
        * Raise HTTPError immediatly, to handle it with complex code

    https://wiki.python.org/moin/PythonDecoratorLibrary#Retry
    http://www.katasonov.com/ru/2014/10/python-urllib2-decorators-and-exceptions-fun/

    :param int tries: number of times to try (not retry) before giving up
    :param int delay: initial delay between retries in seconds
    :param int backoff: backoff multiplier e.g. value of 2 will double the
        delay each retry
    :param dict headers: Update opener headers (add new and spoof existing).

    :rtype: http.client.HTTPResponse
    """
    cj = http_cookiejar.CookieJar()

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
    hdrs = {**DEFAULT_HEADERS, **headers}
    opener.addheaders = list(hdrs.items())

    @wraps(opener.open)
    def retry(*args, **kwargs):
        mtries, mdelay = tries, delay
        while mtries > 1:
            try:
                return opener.open(*args, **kwargs)
            except request.HTTPError as err:
                # Prevent catching HTTPError as subclass of URLError
                # logging.error(err)
                raise
            except request.URLError as err:
                logging.debug(f"{err}, retrying '{args[0]}' in {mdelay} seconds...")
                time.sleep(mdelay)
                mtries -= 1
                mdelay *= backoff
        return opener.open(*args, **kwargs)

    return retry


class TileFetcher(object):
    def __init__(self, layer):
        self.layer = layer
        self.opener = prepare_opener(headers=self.layer.get('headers', dict()))
        self.fetching_now = {}
        self.thread_responses = {}  # Dicts are thread safe
        self.zhash_lock = {}

    def fetch(self, z, x, y):
        """Return None if no image can be served."""
        zhash = repr((z, x, y, self.layer))
        try:
            self.zhash_lock[zhash] += 1
        except KeyError:
            self.zhash_lock[zhash] = 1
        if zhash not in self.fetching_now:
            thread = threading.Thread(
                None, self.threadworker, None, (z, x, y, zhash))
            thread.start()
            self.fetching_now[zhash] = thread
        if self.fetching_now[zhash].is_alive():
            self.fetching_now[zhash].join()
        resp = self.thread_responses[zhash]
        self.zhash_lock[zhash] -= 1
        if not self.zhash_lock[zhash]:
            del self.thread_responses[zhash]
            del self.fetching_now[zhash]
            del self.zhash_lock[zhash]
        return resp

    def threadworker(self, z, x, y, zhash):
        if self.layer['fetch'] not in ('tms', 'wms', 'tms_google_sat'):
            raise ValueError("fetch must be 'tms' or 'wms'")

        # Call fetcher by it's name
        self.thread_responses[zhash] = getattr(self, self.layer['fetch'])(z, x, y)

    def wms(self, z, x, y):
        # Untested, probably broken
        if "max_zoom" in self.layer:
            if z > self.layer["max_zoom"]:
                return None
        req_proj = self.layer.get("wms_proj", self.layer["proj"])
        width = 384  # using larger source size to rescale better in python
        height = 384
        tile_bbox = "bbox=%s,%s,%s,%s" % (
            projections.from4326(projections.bbox_by_tile(z, x, y, req_proj), req_proj))

        wms = self.layer["remote_url"] + tile_bbox + "&width=%s&height=%s&srs=%s" % (width, height, req_proj)
        if self.layer.get("cached", True):
            # MOBAC cache path style
            tile_path = config.tiles_cache + self.layer["prefix"] + "/{:.0f}/{:.0f}/{:.0f}{}".format(z, x, y, self.layer['ext'])
            partial_path, ext = os.path.splitext(tile_path)  # '.ext' with leading dot
            lock_path = partial_path + '.lock'
            tne_path = partial_path + '.tne'

            os.makedirs(os.path.dirname(tile_path), exist_ok=True)

            if 'cache_ttl' in self.layer:
                for ex in (ext, '.dsc' + ext, '.ups' + ext, '.tne'):
                    fp = partial_path + ex
                    if os.path.exists(fp):
                        if os.stat(fp).st_mtime < (time.time() - self.layer["cache_ttl"]):
                            os.remove(fp)

        logging.info(f"wms: fetching z{z}/x{x}/y{y} {self.layer['name']} {wms}")
        im_bytes = self.opener(wms).read()
        if im_bytes:
            im = Image.open(BytesIO(im_bytes))
        else:
            return None
        if width != 256 and height != 256:
            im = im.resize((256, 256), Image.ANTIALIAS)
        im = im.convert("RGBA")

        if self.layer.get("cached", True):
            ic = Image.new("RGBA", (256, 256), self.layer.get("empty_color", config.default_background))
            if im.histogram() == ic.histogram():
                with open(tne_path, 'w') as f:
                    when = time.localtime()
                    timestamp = "%02d.%02d.%04d %02d:%02d:%02d" % (
                    when[2], when[1], when[0], when[3], when[4], when[5])
                    f.write(timestamp)
                return False
            im.save(tile_path)
        return im

    def tms(self, z, x, y):
        """Fetch tile by coordinates, r/w cache.

        TNE - tile not exist (got HTTP 404 or default tile for empty zones aka "dead tile")

        Cache is structured according to tile coordinates.
        Actual tile image projection specified in config file.
        
        MBTiles
            https://wiki.openstreetmap.org/wiki/MBTiles
            https://github.com/mapbox/mbtiles-spec
            https://docs.mapbox.com/help/glossary/mbtiles/

        :rtype: :py:class:`~PIL.Image.Image`. Otherwise None, if
            no image can be served from cache or from remote.
        """
        need_fetch = False
        tile_parsed = False
        tile_dead = False
        tile_id = f"{self.layer['prefix']} z{z}/x{x}/y{y}"
        remote = ''

        # TODO: Conform JOSM tms links zoom restrictions
        if 'max_zoom' in self.layer:
            if z > self.layer['max_zoom']:
                logging.debug(f"{tile_id}: zoom limit")
                return None

        # MOBAC cache path style
        tile_path = config.tiles_cache + self.layer['prefix'] + "/{:.0f}/{:.0f}/{:.0f}{}".format(z, x, y, self.layer['ext'])
        partial_path, ext = os.path.splitext(tile_path)  # '.ext' with leading dot
        tne_path = partial_path + '.tne'
        os.makedirs(os.path.dirname(tile_path), exist_ok=True)

        # Do not delete, only replace if tile exists!
        if os.path.exists(tne_path):
            tne_lifespan = time.time() - os.stat(tne_path).st_mtime
            if tne_lifespan > config.cache_tne_ttl:
                logging.info(f"{tile_id}: TTL tne reached {tne_path}")
                need_fetch = True
            else:
                logging.info(f"{tile_id}: tile cached as TNE {tne_path}")
        if 'cache_ttl' in self.layer:
            # for ex in (ext, '.dsc.' + ext, '.ups.' + ext, '.tne'):
            if os.path.exists(tile_path):
                tile_lifespan = time.time() - os.stat(tile_path).st_mtime
                # tile_lifespan_h = tile_lifespan / 60 / 60
                # logging.debug(f"{tile_id}: lifespan {tile_lifespan_h:.0f} h {fp}")
                if tile_lifespan > self.layer["cache_ttl"]:
                    logging.info(f"{tile_id}: TTL tile reached for {tile_path}")
                    need_fetch = True

        if not os.path.exists(tile_path) and not os.path.exists(tne_path):
            need_fetch = True

        # Fetching image
        if need_fetch and 'remote_url' in self.layer:
            if 'transform_tile_number' in self.layer:
                remote = self.layer['remote_url'] % self.layer["transform_tile_number"](z, x, y)
            else:
                remote = self.layer['remote_url'] % (z, x, y)
            try:
                # Got response, need to verify content
                logging.info(f"{tile_id}: FETCHING {remote}")
                remote_resp = self.opener(remote)
                remote_bytes = remote_resp.read()
                if remote_bytes:
                    try:
                        im = Image.open(BytesIO(remote_bytes))
                        im.load()  # Validate image
                        tile_parsed = True
                    except (OSError, AttributeError):
                        # Catching invalid pictures
                        logging.error(f"{tile_id}: failed to parse response as image {tne_path}")
                        logging.debug(f"{tile_id}: invalid image {remote_resp.status}: {remote_resp.msg} - {remote_resp.reason} {remote_resp.url}\n{remote_resp.headers}")
                        # try:
                        #     logging.debug(remote_bytes.decode('utf-8'))
                        # except UnicodeDecodeError:
                        #     logging.debug(remote_bytes)
                        # if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
                        #     with open('err.htm', mode='wb') as f:
                        #         f.write(remote_bytes)
                else:
                    logging.warning(f"{tile_id}: empty response")
            except request.HTTPError as err:
                # Heuristic: TNE or server is defending tiles
                # HTTP 403 must be inspected manually
                logging.error('\n'.join([str(k) for k in (err, err.headers, err.read().decode('utf-8'))]))
                if err.status == HTTPStatus.NOT_FOUND:
                    logging.warning(f"{tile_id}: TNE - {err} '{tne_path}'")
                    Path(tne_path, exist_ok=True).touch()
            except request.URLError as err:
                # Nothing we can do: no connection, cannot guess TNE or not
                logging.error(f"{tile_id} URLError '{err}'")

            # Save something in cache
            # Sometimes server returns file instead of empty HTTP response
            if 'dead_tile' in self.layer:
                # Compare bytestring with dead tile hash
                if len(remote_bytes) == self.layer['dead_tile']['size']:
                    hasher = hashlib.md5()
                    hasher.update(remote_bytes)
                    if hasher.hexdigest() == self.layer['dead_tile']['md5']:
                        # Tile is recognized as empty
                        # An example http://ecn.t0.tiles.virtualearth.net/tiles/a120210103101222.jpeg?g=0
                        # SASPlanet writes empty files with '.tne' ext
                        logging.warning(f"{tile_id}: TNE - dead tile '{tne_path}'")
                        tile_dead = True
                        Path(tne_path, exist_ok=True).touch()

            logging.debug(f"tile parsed {tile_parsed}, dead {tile_dead}")
            if tile_parsed and not tile_dead:
                # All well, save tile to cache
                logging.info(f"{tile_id}: saving {tile_path}")
                with open(tile_path, "wb") as f:
                    f.write(remote_bytes)
                if os.path.exists(tne_path):
                    os.remove(tne_path)
                return im

        # If TTL is ok or fetching failed
        if os.path.exists(tile_path):
            try:
                im = Image.open(tile_path)
                im.load()
                logging.info(f"{tile_id}: cache tms {tile_path}")
                return im
            except OSError:
                logging.warning(f"{tile_id}: failed to parse image from cache '{tile_path}'")
                # os.remove(tile_path)  # Cached tile is broken - remove it

        logging.warning(f"{tile_id}: unreachable tile {remote}")

    def tms_google_sat(self, z, x, y):
        """Construct template URI with version from JS API.

        May be use different servers in future:
        https://khms0.google.com/kh/v=889?x=39595&y=20473&z=16
        https://khms3.google.com/kh/v=889?x=39595&y=20472&z=16
        """
        if 'remote_url' not in self.layer:
            try:
                resp = self.opener("https://maps.googleapis.com/maps/api/js").read().decode('utf-8')
                if resp:
                    match = re.search(r"https://khms\d+.googleapis\.com/kh\?v=(\d+)", resp)
                    if not match.group(1):
                        logging.error(f"Cannot parse 'v=' from {maps_googleapis_js}")
                        raise ValueError(f"Cannot parse 'v=' from {maps_googleapis_js}")
                    self.layer['remote_url'] = "https://khms0.google.com/kh/v=" + match.group(1) + "?x=%s&y=%s&z=%s"
                    logging.info(f"Setting new {self.layer['name']} URI {self.layer['remote_url']}")
            except request.URLError:
                pass

        # URI version can expiry, reset if no image
        # Though it is not only possible cause of None response
        im = self.tms(z, x, y)
        if 'remote_url' in self.layer and not im:
            del self.layer['remote_url']
        return  im


def tile_to_quadkey(z, x, y):
    """Transform tile coordinates to a Bing quadkey.

    GlobalMapper Tiles cache numeration starts from 0 level with one tile. On 1 level four tiles etc
    Bing uses quadkey tile coordinates, so minimal cache level is 1 (four tiles). Single tile at zero level not addressed.

    https://docs.microsoft.com/en-us/bingmaps/articles/bing-maps-tile-system
    https://github.com/buckhx/QuadKey/blob/master/quadkey/tile_system.py

    Examples
    --------
    >>> tile_to_quadkey(1,0,0)
    '0'
    >>> tile_to_quadkey(4, 9, 5)
    '1203'
    >>> tile_to_quadkey(16, 38354, 20861)
    '1203010313232212'

    Paramaters
    ----------
    :param int z: starts from zero
    :return: Quadkey string
    :rtype: str
    """
    quadkey = ""
    for i in range(z):
        bit = z - i
        digit = ord('0')
        mask = 1 << (bit - 1)
        if (x & mask) != 0:
            digit += 1
        if (y & mask) != 0:
            digit += 2
        quadkey += chr(digit)
    return quadkey


def tile_slippy_to_tms(z, x, y):
    """OSGeo Tile Map Service Specification style Y coordinate.

    Same meaning as '{-y}'.

    https://josm.openstreetmap.de/wiki/Maps
    """
    return z, x, 2 ** z - 1 - y
