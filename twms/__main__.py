#!/usr/bin/env python

import sys
import re
import urllib
from http.server import ThreadingHTTPServer
from http.server import BaseHTTPRequestHandler

from twms import twms
import config


tile_hyperlink = re.compile(r"/(.*)/([0-9]+)/([0-9]+)/([0-9]+)(\.[a-zA-Z]+)?(.*)")
# main_hyperlink = re.compile(r"/(.*)")


class GetHandler(BaseHTTPRequestHandler):
    IHandler = twms.ImageryHandler()  # Will be same for all instances

    def do_GET(self):
        """Parse GET tile request.
        """
        tileh = re.fullmatch(tile_hyperlink, self.path)
        if tileh:
            data = {
                'request': 'GetTile',
                'layers': tileh.group(1),
                'z': tileh.group(2),
                'x': tileh.group(3),
                'y': tileh.group(4),
                'ext': tileh.group(5)}  # File extension
            # rest = m.group(6)
        else:
            data = dict(urllib.parse.parse_qsl(self.path[2:]))  # Strip /?

        resp, content_type, content = self.IHandler.handler(data)
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        if content_type in ('text/html', 'text/plain'):
            content = content.encode('utf-8')
        self.wfile.write(content)

    def log_message(self, format, *args):
        """Disable logger."""
        pass

    def log_error(self, format, *args):
        """Declare, because we had disabled 'log_message'."""
        sys.stderr.write(format % args)


def main():
    """Simple TWMS server.
    """
    # if len(sys.argv) > 1:
    #     if sys.argv[1].isdigit():
    #         port = int(sys.argv[1])
    server = ThreadingHTTPServer((config.host, config.port), GetHandler)
    print("Starting TWMS server at http://{}:{} use <Ctrl-C> to stop".format(
        server.server_address[0], server.server_address[1]))
    server.serve_forever()


if __name__ == "__main__":
    main()
