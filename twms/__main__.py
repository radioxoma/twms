#!/usr/bin/env python

"""
debug - tile file operations
info - tile fetching or constructing
warning - HTTP errors
"""

import sys
import re
import urllib
import mimetypes
from http.server import ThreadingHTTPServer
from http.server import BaseHTTPRequestHandler
import logging
logging.basicConfig(level=logging.INFO)
# logging.basicConfig(level=logging.DEBUG)

from twms import twms
import config

tile_hyperlink = re.compile(r"/(.*)/([0-9]+)/([0-9]+)/([0-9]+)(\.[a-zA-Z]+)?(.*)")
# main_hyperlink = re.compile(r"/(.*)")


class GetHandler(BaseHTTPRequestHandler):
    TWMS = twms.TWMSMain()  # Will be same for all instances

    def do_GET(self):
        """Parse GET tile request.
        """
        tileh = re.fullmatch(tile_hyperlink, self.path)
        if tileh:
            try:
                # Guess image format by link extension
                content_type = mimetypes.types_map[tileh.group(5)]
            except KeyError:
                content_type = 'image/jpeg'
            data = {  # Construct WMS-like request
                'request': 'GetTile',
                'layers': tileh.group(1),
                'z': tileh.group(2),
                'x': tileh.group(3),
                'y': tileh.group(4),
                'format': content_type}
            # rest = m.group(6)
        else:
            data = dict(urllib.parse.parse_qsl(self.path[2:]))  # Strip /?

        resp, content_type, content = self.TWMS.wms_handler(data)
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.end_headers()
        if 'text/' in content_type or 'xml' in content_type:
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
