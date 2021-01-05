import os
from io import BytesIO
import time
import threading
from functools import wraps
import urllib.request as request
import http.cookiejar as http_cookiejar
import ssl
ssl._create_default_https_context = ssl._create_unverified_context  # Disable for gismap.by

from PIL import Image

import config
import projections


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:84.0) Gecko/20100101 Firefox/84.0",
    "Connection": "Keep-Alive"}


def prepare_opener(tries=4, delay=3, backoff=2, headers=dict()):
    """Build opener with browser User-Agent and cookie support.

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
        self.thread_responses = {}
        self.zhash_lock = {}

    def fetch(self, z, x, y):
        zhash = repr((z, x, y, self.layer))
        try:
            self.zhash_lock[zhash] += 1
        except KeyError:
            self.zhash_lock[zhash] = 1
        if zhash not in self.fetching_now:
            atomthread = threading.Thread(
                None, self.threadwrapper, None, (z, x, y, zhash)
            )
            atomthread.start()
            self.fetching_now[zhash] = atomthread
        if self.fetching_now[zhash].is_alive():
            self.fetching_now[zhash].join()
        resp = self.thread_responses[zhash]
        self.zhash_lock[zhash] -= 1
        if not self.zhash_lock[zhash]:
            del self.thread_responses[zhash]
            del self.fetching_now[zhash]
            del self.zhash_lock[zhash]

        return resp

    def threadwrapper(self, z, x, y, zhash):
        try:
            if self.layer['fetch'] == 'tms':
                self.thread_responses[zhash] = self.tms(z, x, y)
            elif self.layer['fetch'] == 'wms':
                self.thread_responses[zhash] = self.wms(z, x, y)
            else:
                raise ValueError("fetch must be 'tms' or 'wms'")
        except OSError:
            self.thread_responses[zhash] = None

    def wms(self, z, x, y):
        if "max_zoom" in self.layer:
            if z >= self.layer["max_zoom"]:
                return None
        req_proj = self.layer.get("wms_proj", self.layer["proj"])
        width = 384  # using larger source size to rescale better in python
        height = 384
        local = (
            config.tiles_cache + self.layer["prefix"]
            + "/z{:.0f}/{:.0f}/{:.0f}.".format(z - 1, y, x)
        )
        tile_bbox = "bbox=%s,%s,%s,%s" % tuple(
            projections.from4326(projections.bbox_by_tile(z, x, y, req_proj), req_proj)
        )

        wms = self.layer["remote_url"] + tile_bbox + "&width=%s&height=%s&srs=%s" % (width, height, req_proj)
        if self.layer.get("cached", True):
            if not os.path.exists("/".join(local.split("/")[:-1])):
                os.makedirs("/".join(local.split("/")[:-1]))
            try:
                os.mkdir(local + "lock")
            except OSError:
                for i in range(20):
                    time.sleep(0.1)
                    try:
                        if not os.path.exists(local + "lock"):
                            im = Image.open(local + self.layer["ext"])
                            return im
                    except (OSError, OSError):
                        return None

        print(f"Fetching z{z}/x{x}/y{y} {self.layer['name']} {wms}")
        im = Image.open(BytesIO(self.opener(wms).read()))
        if width != 256 and height != 256:
            im = im.resize((256, 256), Image.ANTIALIAS)
        im = im.convert("RGBA")

        if self.layer.get("cached", True):
            ic = Image.new(
                "RGBA", (256, 256), self.layer.get("empty_color", config.default_background)
            )
            if im.histogram() == ic.histogram():
                tne = open(local + "tne", "wb")
                when = time.localtime()
                tne.write(
                    "%02d.%02d.%04d %02d:%02d:%02d"
                    % (when[2], when[1], when[0], when[3], when[4], when[5]))
                tne.close()
                return False
            im.save(local + self.layer["ext"])
            os.rmdir(local + "lock")
        return im

    def tms(self, z, x, y):
        """
        FIXME: duplicated functional in twms.py

        Normally returns Pillimage
        Returns None, if no image can be served from cache or from remote.
        """
        d_tuple = z, x, y

        # TODO: Conform JOSM tms links
        if "max_zoom" in self.layer:
            if z >= self.layer["max_zoom"]:
                return None

        if self.layer.get("cached", True):
            # "Global Mapper Tiles" cache path style
            tile_path = config.tiles_cache + self.layer["prefix"] + "/z{:.0f}/{:.0f}/{:.0f}.jpg".format(z - 1, y, x)#, self.layer["ext"])
            lockdir_path = tile_path + '.lock'
            tne_path = tile_path + '.tne'
            os.makedirs(os.path.dirname(tile_path), exist_ok=True)

            # try:
            #     os.mkdir(lockdir_path)
            # except OSError:
            #     for i in range(20):
            #         time.sleep(0.1)

            # Don't read tile if lockfile exists
            # if os.path.exists(tile_path):
            #     if not os.path.exists(lockdir_path):
            #         print(f"Loading {tile_path}")
            #         return Image.open(tile_path)

        # Tile not in cache, fetching
        if "transform_tile_number" in self.layer:
            d_tuple = self.layer["transform_tile_number"](z, x, y)
        remote = self.layer["remote_url"] % d_tuple

        try:
            print(f"Fetching z{z}/x{x}/y{y} {self.layer['name']} {remote}")
            contents = self.opener(remote).read()
            im = Image.open(BytesIO(contents))
        except OSError:
            # if self.layer.get("cached", True):
            #     os.rmdir(local + '.lock')
            return None

        # Save something in cache
        if self.layer.get("cached", True):
            # Sometimes server returns file instead of empty HTTP response
            if 'dead_tile' in self.layer:
                try:
                    with open(self.layer["dead_tile"], "rb") as f:
                        dt = f.read()
                    if contents == dt:
                        with open(tne_path, "wb") as f:
                            when = time.localtime()
                            tne.write("%02d.%02d.%04d %02d:%02d:%02d" % (when[2], when[1], when[0], when[3], when[4], when[5]))
                    return False
                except OSError:
                    pass
            else:
                # os.rmdir(lockdir_path)
                # All well, save tile to cache
                print(f"Saving {tile_path}")
                with open(tile_path, "wb") as f:
                    f.write(contents)
        return im


def tile_to_quadkey(z, x, y):
    """Transform tile coordinates to a quadkey.

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
