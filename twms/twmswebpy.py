#!/usr/bin/env python

"""
Deprecated webpy-based server.
"""

import sys
from twms import twms
import urllib
import web


OK = 200
ERROR = 500

urls = (
    "/(.*)/([0-9]+)/([0-9]+)/([0-9]+)(\.[a-zA-Z]+)?(.*)", "tilehandler",
    "/(.*)", "mainhandler",
)


def handler(data):
    """
    A handler for web.py.
    """
    resp, ctype, content = twms.twms_main(data)
    web.header("Content-Type", ctype)
    return content


class tilehandler:
    def GET(self, layers, z, x, y, format, rest):
        if format is None:
            format = "jpeg"
        else:
            format = format.lower()
        data = {
            "request": "GetTile",
            "layers": layers,
            "format": format.strip("."),
            "z": z,
            "x": x,
            "y": y,
        }
        return handler(data)


class mainhandler:
    def GET(self, crap):
        data = web.input()
        data = dict((k.lower(), data[k]) for k in iter(data))
        if "ref" not in data:
            if web.ctx.env["HTTP_HOST"]:
                data["ref"] = (
                    web.ctx.env["wsgi.url_scheme"]
                    + "://"
                    + web.ctx.env["HTTP_HOST"]
                    + "/"
                )
        return handler(data)


def main():
    try:
        if sys.argv[1] == 'josm':  # josm mode
            url, params = sys.argv[2].split("/?", 1)
            data = urllib.parse.parse_qsl(params)
            for t in data.keys():
                data[t] = data[t][0]
            resp, ctype, content = twms.twms_main(data)
            print(content)
            exit()
    except IndexError:
        pass

    try:
        app = web.application(urls, globals())
        app.run()  # standalone run
    except socket.error:
        print("Can't open socket. Abort.", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
