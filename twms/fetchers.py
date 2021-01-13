import os
from io import BytesIO
import time
import hashlib
import threading
from functools import wraps
import urllib.request as request
import http.cookiejar as http_cookiejar
import ssl
ssl._create_default_https_context = ssl._create_unverified_context  # Disable for gismap.by

from PIL import Image

from twms import projections
import config


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:84.0) Gecko/20100101 Firefox/84.0",
    "Connection": "Keep-Alive"}


def prepare_opener(tries=4, delay=3, backoff=2, headers=dict()):
    """Build HTTP opener with custom headers (User-Agent) and cookie support.

    Retry HTTP request using an exponential backoff.
    https://wiki.python.org/moin/PythonDecoratorLibrary#Retry
    http://www.katasonov.com/ru/2014/10/python-urllib2-decorators-and-exceptions-fun/

    :param int tries: number of times to try (not retry) before giving up
    :param int delay: initial delay between retries in seconds
    :param int backoff: backoff multiplier e.g. value of 2 will double the
        delay each retry
    :param dict headers: Update opener headers (add new and spoof existing).
    """
    cj = http_cookiejar.CookieJar()

#     if use_proxy:
#         proxy_info = {
#             'user': 'login',
#             'pass': 'passwd',
#             'host': "proxyaddress",
#             'port': 8080}
#
#         proxy_support = urllib.request.ProxyHandler({
#             "http": "http://%(user)s:%(pass)s@%(host)s:%(port)d" % proxy_info})
#         opener = urllib.request.build_opener(
#             urllib.request.HTTPCookieProcessor(cj),
#             # urllib2.HTTPHandler(debuglevel=1),  # Debug outpur
#             proxy_support)

    opener = request.build_opener(request.HTTPCookieProcessor(cj))
    hdrs = {**DEFAULT_HEADERS, **headers}
    opener.addheaders = list(hdrs.items())

    @wraps(opener.open)
    def retry(*args, **kwargs):
        mtries, mdelay = tries, delay
        while mtries > 1:
            try:
                return opener.open(*args, **kwargs)
            except request.HTTPError as e:
                print(f"e.code is '{e.code}'")
                # if e.code == 404:
                #     mtries = 0
                raise
            except request.URLError as e:
                print(f"{e}, Retrying '{args[0]}' in {mdelay} seconds...")
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
        zhash = repr((z, x, y, self.layer))
        try:
            self.zhash_lock[zhash] += 1
        except KeyError:
            self.zhash_lock[zhash] = 1
        if zhash not in self.fetching_now:
            atomthread = threading.Thread(
                None, self.threadworker, None, (z, x, y, zhash))
            atomthread.start()
            self.fetching_now[zhash] = atomthread
        if self.fetching_now[zhash].is_alive():
            self.fetching_now[zhash].join()
        image = self.thread_responses[zhash]
        self.zhash_lock[zhash] -= 1
        if not self.zhash_lock[zhash]:
            del self.thread_responses[zhash]
            del self.fetching_now[zhash]
            del self.zhash_lock[zhash]

        # Catching invalid pictures
        try:
            image.load()  # Validate image
            return image
        except (OSError, AttributeError):
            print("TileFetcher: Corrupted tile")
            return None

    def threadworker(self, z, x, y, zhash):
        if self.layer['fetch'] not in ('tms', 'wms'):
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
            # "Global Mapper Tiles" cache path style
            tile_path = config.tiles_cache + self.layer["prefix"] + "/{:.0f}/{:.0f}/{:.0f}.{}".format(z, x, y, self.layer['ext'])
            partial_path, ext = os.path.splitext(tile_path)  # 'ext' with leading dot
            lock_path = partial_path + '.lock'
            tne_path = partial_path + '.tne'

            os.makedirs(os.path.dirname(tile_path), exist_ok=True)

            if 'cache_ttl' in self.layer:
                for ex in (ext, '.dsc.' + ext, '.ups.' + ext, '.tne'):
                    fp = partial_path + ex
                    if os.path.exists(fp):
                        if os.stat(fp).st_mtime < (time.time() - self.layer["cache_ttl"]):
                            os.remove(fp)

        print(f"\twms: fetching z{z}/x{x}/y{y} {self.layer['name']} {wms}")
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

        Cache is structured according to tile coordinates.
        Actual tile image projection specified in config file.
        https://wiki.openstreetmap.org/wiki/MBTiles

        :rtype: :py:class:`~PIL.Image.Image`. Otherwise None, if
            no image can be served from cache or from remote.
        """
        d_tuple = z, x, y

        # TODO: Conform JOSM tms links zoom restrictions
        if "max_zoom" in self.layer:
            if z > self.layer["max_zoom"]:
                print("Zoom limit")
                return None

        # Option one: trying cache
        if self.layer.get("cached", True):
            # "Global Mapper Tiles" cache path style
            tile_path = config.tiles_cache + self.layer['prefix'] + "/{:.0f}/{:.0f}/{:.0f}.{}".format(z, x, y, self.layer['ext'])
            partial_path, ext = os.path.splitext(tile_path)  # 'ext' with leading dot
            # lock_path = partial_path + '.lock'
            tne_path = partial_path + '.tne'

            os.makedirs(os.path.dirname(tile_path), exist_ok=True)

            if 'cache_ttl' in self.layer:
                for ex in (ext, '.dsc.' + ext, '.ups.' + ext, '.tne'):
                    fp = partial_path + ex
                    if os.path.exists(fp):
                        if os.stat(fp).st_mtime < (time.time() - self.layer["cache_ttl"]):
                            os.remove(fp)

            if not os.path.exists(tne_path):
                if os.path.exists(tile_path):  # First, look for the tile in cache
                    try:
                        im1 = Image.open(tile_path)
                        im1.load()
                        print(f"\ttms: load {tile_path}")
                        return im1
                    except OSError:
                        print(f"\ttms: remove broken tile from cache '{tile_path}'")
                        os.remove(tile_path)  # Cached tile is broken - remove it

        # Option two: tile not in cache, fetching
        if 'transform_tile_number' in self.layer:
            d_tuple = self.layer["transform_tile_number"](z, x, y)
        remote = self.layer['remote_url'] % d_tuple

        try:
            print(f"\ttms: FETCHING z{z}/x{x}/y{y} {self.layer['name']} {remote}")
            im_bytes = self.opener(remote).read()
            if im_bytes:
                im = Image.open(BytesIO(im_bytes))
            else:
                print(f"tms: zero response tile z{z}/x{x}/y{y}")
                return None
        except OSError:
            return None

        # Save something in cache
        if self.layer.get("cached", True):
            # Sometimes server returns file instead of empty HTTP response
            if 'dead_tile' in self.layer:
                # Compare bytestring with dead tile hash
                if len(im_bytes) == self.layer['dead_tile']['size']:
                    hasher = hashlib.md5()
                    hasher.update(im_bytes)
                    if hasher.hexdigest() == self.layer['dead_tile']['md5']:
                        # Tile is recognized as empty
                        # An example http://ecn.t0.tiles.virtualearth.net/tiles/a120210103101222.jpeg?g=0
                        # SASPlanet writes empty files with '.tne' ext
                        print(f"tms: dead tile z{z}/x{x}/y{y} '{tne_path}'")
                        with open(tne_path, "w") as f:
                            when = time.localtime()
                            timestamp = "%02d.%02d.%04d %02d:%02d:%02d" % (when[2], when[1], when[0], when[3], when[4], when[5])
                            # "08.01.2021 17:58:17"
                            f.write(timestamp)
                        return None
            else:
                # os.rmdir(lock_path)
                # All well, save tile to cache
                print(f"\ttms: saving {tile_path}")
                with open(tile_path, "wb") as f:
                    f.write(im_bytes)

        return im


def tile_to_quadkey(z, x, y):
    """Transform tile coordinates to a Bing quadkey.

    GlobalMapper Tiles cache numeration starts from 0 level with one tile. On 1 level four tiles etc
    Bing uses quadkey tile coordinates, so minimal cache level is 1 (four tiles). Single tile at zero level not addressed.

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
