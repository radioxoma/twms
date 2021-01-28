#!/usr/bin/env python

"""
debug - tile file operations
info - tile fetching or constructing
warning - HTTP errors
"""

import os
import sys
import re
import urllib
import mimetypes
from http.server import ThreadingHTTPServer
from http.server import BaseHTTPRequestHandler
from http import HTTPStatus
import logging
logging.basicConfig(level=logging.INFO)
# logging.basicConfig(level=logging.DEBUG)

import twms
import twms.twms
import twms.viewjosm
import twms.viewhtml

tile_hyperlink = re.compile(r"/wms/(.*)/([0-9]+)/([0-9]+)/([0-9]+)(\.[a-zA-Z]+)?(.*)")
# main_hyperlink = re.compile(r"/(.*)")


class GetHandler(BaseHTTPRequestHandler):
    TWMS = twms.twms.TWMSMain()  # Will be same for all instances

    def do_GET(self):
        """Parse GET tile request.

          wms/layer_id/{z}/{x}/{y}{ext}
        tiles/layer_id/{z}/{x}/{y}
        josm/maps.xml
        any overview
        """
        if self.path.startswith('/tiles'):
            # TMS handler
            root, ext = os.path.splitext(self.path)
            r_parts = root.split('/')
            layer_id, z, x, y = r_parts[2], r_parts[3], r_parts[4], r_parts[5]
            resp, content_type, content = self.TWMS.tiles_handler(
                layer_id, z, x, y, mimetypes.types_map[ext])

        elif self.path.startswith('/wms'):
            # WMS and somewhat like WMS-C emulation for getting tiles directly.
            wms_c = re.fullmatch(tile_hyperlink, self.path)
            if wms_c:
                try:
                    # Guess image format by link extension
                    content_type = mimetypes.types_map[wms_c.group(5)]
                except KeyError:
                    content_type = 'image/jpeg'
                data = {  # Construct WMS-like request
                    'request': 'GetTile',
                    'layers': wms_c.group(1),
                    'z': wms_c.group(2),
                    'x': wms_c.group(3),
                    'y': wms_c.group(4),
                    'format': content_type}
                # rest = m.group(6)
            else:
                data = dict(urllib.parse.parse_qsl(self.path.split('?')[1]))
            resp, content_type, content = self.TWMS.wms_handler(data)

        elif self.path == "/josm/maps.xml":
            resp = HTTPStatus.OK
            content_type = 'text/xml'
            content = twms.viewjosm.maps_xml()
            # Cache-Control: no-cache?
        elif self.path == '/':
            # Web page view
            resp = HTTPStatus.OK
            content_type = 'text/html'
            content = twms.viewhtml.html()
        else:
            resp = HTTPStatus.NOT_FOUND
            content_type = 'text/plain'
            content = "404 Not Found"

        self.send_response(resp)
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
    server = ThreadingHTTPServer((twms.config.host, twms.config.port), GetHandler)
    print(f"Starting TWMS server at {twms.config.service_url} use <Ctrl-C> to stop".format(
        server.server_address[0], server.server_address[1]))
    print(f"Add {twms.config.service_url}josm/maps.xml to JOSM 'imagery.layers.sites' property and check imagery setting")
    server.serve_forever()


if __name__ == "__main__":
    main()
