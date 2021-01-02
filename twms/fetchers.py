import os
import sys
from io import BytesIO
import time
import threading
from functools import wraps
import urllib.request as request
import http.cookiejar as http_cookiejar

from PIL import Image

import config
import projections


USERAGENT = [(
    "User-Agent",
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:45.0) Gecko/20100101 Firefox/45.0")]


def prepare_opener(tries=4, delay=3, backoff=2):
    """Build opener with browser User-Agent and cookie support.

    Retry HTTP request using an exponential backoff.
    https://wiki.python.org/moin/PythonDecoratorLibrary#Retry
    http://www.katasonov.com/ru/2014/10/python-urllib2-decorators-and-exceptions-fun/

    :param int tries: number of times to try (not retry) before giving up
    :param int delay: initial delay between retries in seconds
    :param int backoff: backoff multiplier e.g. value of 2 will double the
        delay each retry
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

    opener = request.build_opener(
        request.HTTPCookieProcessor(cj))
    opener.addheaders = USERAGENT

    @wraps(opener.open)
    def retry(*args, **kwargs):
        mtries, mdelay = tries, delay
        while mtries > 1:
            try:
                return opener.open(*args, **kwargs)
            except request.URLError as e:
                msg = "{}, Retrying in {} seconds...".format(e, mdelay)
                print(msg)
                time.sleep(mdelay)
                mtries -= 1
                mdelay *= backoff
        return opener.open(*args, **kwargs)

    return retry


class TileFetcher(object):
    def __init__(self):
        self.fetching_now = {}
        self.thread_responses = {}
        self.zhash_lock = {}
        self.opener = prepare_opener()

    def fetch(self, z, x, y, this_layer):
        zhash = repr((z, x, y, this_layer))
        try:
            self.zhash_lock[zhash] += 1
        except KeyError:
            self.zhash_lock[zhash] = 1
        if zhash not in self.fetching_now:
            atomthread = threading.Thread(
                None, self.threadwrapper, None, (z, x, y, this_layer, zhash)
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

    def threadwrapper(self, z, x, y, this_layer, zhash):
        try:
            self.thread_responses[zhash] = this_layer["fetch"](z, x, y, this_layer, self.opener)
        except OSError:
            self.thread_responses[zhash] = None


def WMS(z, x, y, this_layer, opener):
    if "max_zoom" in this_layer:
        if z >= this_layer["max_zoom"]:
            return None
    wms = this_layer["remote_url"]
    req_proj = this_layer.get("wms_proj", this_layer["proj"])
    width = 384  # using larger source size to rescale better in python
    height = 384
    local = (
        config.tiles_cache + this_layer["prefix"]
        # + "/z%s/%s/x%s/%s/y%s." % (z, x // 1024, x, y // 1024, y)
        + "/z{:.0f}/{:.0f}/{:.0f}.".format(z - 1, y, x)
    )
    tile_bbox = "bbox=%s,%s,%s,%s" % tuple(
        projections.from4326(projections.bbox_by_tile(z, x, y, req_proj), req_proj)
    )

    wms += tile_bbox + "&width=%s&height=%s&srs=%s" % (width, height, req_proj)
    if this_layer.get("cached", True):
        if not os.path.exists("/".join(local.split("/")[:-1])):
            os.makedirs("/".join(local.split("/")[:-1]))
        try:
            os.mkdir(local + "lock")
        except OSError:
            for i in range(20):
                time.sleep(0.1)
                try:
                    if not os.path.exists(local + "lock"):
                        im = Image.open(local + this_layer["ext"])
                        return im
                except (IOError, OSError):
                    return None
    im = Image.open(BytesIO(opener(wms).read()))
    if width != 256 and height != 256:
        im = im.resize((256, 256), Image.ANTIALIAS)
    im = im.convert("RGBA")

    if this_layer.get("cached", True):
        ic = Image.new(
            "RGBA", (256, 256), this_layer.get("empty_color", config.default_background)
        )
        if im.histogram() == ic.histogram():
            tne = open(local + "tne", "wb")
            when = time.localtime()
            tne.write(
                "%02d.%02d.%04d %02d:%02d:%02d"
                % (when[2], when[1], when[0], when[3], when[4], when[5])
            )
            tne.close()
            return False
        im.save(local + this_layer["ext"])
        os.rmdir(local + "lock")
    return im


def Tile(z, x, y, this_layer, opener):
    global OSError, IOError
    d_tuple = z, x, y
    if "max_zoom" in this_layer:
        if z >= this_layer["max_zoom"]:
            return None
    if "transform_tile_number" in this_layer:
        d_tuple = this_layer["transform_tile_number"](z, x, y)

    remote = this_layer["remote_url"] % d_tuple
    if this_layer.get("cached", True):
        local = (
            config.tiles_cache + this_layer["prefix"]
            # + "/z%s/%s/x%s/%s/y%s." % (z, x // 1024, x, y // 1024, y)
            + "/z{:.0f}/{:.0f}/{:.0f}.".format(z - 1, y, x)
        )
        if not os.path.exists("/".join(local.split("/")[:-1])):
            os.makedirs("/".join(local.split("/")[:-1]))
        try:
            os.mkdir(local + "lock")
        except OSError:
            for i in range(20):
                time.sleep(0.1)
                try:
                    if not os.path.exists(local + "lock"):
                        im = Image.open(local + this_layer["ext"])
                        return im
                except (IOError, OSError):
                    return None
    try:
        contents = opener(remote).read()
        im = Image.open(BytesIO(contents))
    except IOError:
        if this_layer.get("cached", True):
            os.rmdir(local + "lock")
        return False
    if this_layer.get("cached", True):
        os.rmdir(local + "lock")
        open(local + this_layer["ext"], "wb").write(contents)
    if "dead_tile" in this_layer:
        try:
            dt = open(this_layer["dead_tile"], "rb").read()
            if contents == dt:
                if this_layer.get("cached", True):
                    tne = open(local + "tne", "wb")
                    when = time.localtime()
                    tne.write(
                        "%02d.%02d.%04d %02d:%02d:%02d"
                        % (when[2], when[1], when[0], when[3], when[4], when[5])
                    )
                    tne.close()
                    os.remove(local + this_layer["ext"])
            return False
        except IOError:
            pass
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
