#!/usr/bin/env python

import logging
import mimetypes
import os
import re
import sys
import textwrap
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import twms
import twms.api
import twms.config
import twms.twms

logging.basicConfig(level=logging.INFO)
# logging.basicConfig(level=logging.DEBUG)


class GetHandler(BaseHTTPRequestHandler):
    TWMS = twms.twms.TWMSMain()
    server_version = f"twms/{twms.__version__}"
    wms_route = re.compile(r"/wms/(.*)/(\d+)/(\d+)/(\d+)(\.[a-zA-Z]+)?(.*)")

    def do_GET(self):
        """Handle GET request.

        wms/layer_id/{z}/{x}/{y}{ext}
        tiles/layer_id/{z}/{x}/{y}
        josm/maps.xml
        any overview
        """
        if self.path.startswith("/tiles"):
            # TMS handler
            root, ext = os.path.splitext(self.path)
            r_parts = root.split("/")
            layer_id, z, x, y = r_parts[2], r_parts[3], r_parts[4], r_parts[5]
            status, content_type, content = self.TWMS.tiles_handler(
                layer_id, z, x, y, mimetypes.types_map[ext]
            )

        elif self.path.startswith("/wms"):
            # WMS and somewhat like WMS-C emulation for getting tiles directly
            wms_c = self.wms_route.fullmatch(self.path)
            if wms_c:
                # Construct WMS-like request
                # Guess image format by link extension
                data = {
                    "request": "GetTile",
                    "layers": wms_c.group(1),
                    "z": wms_c.group(2),
                    "x": wms_c.group(3),
                    "y": wms_c.group(4),
                    "format": mimetypes.types_map.get(wms_c.group(5), "image/jpeg"),
                }
                # rest = m.group(6)
            else:
                data = dict(urllib.parse.parse_qsl(self.path.split("?")[1]))
            status, content_type, content = self.TWMS.wms_handler(data)

        elif self.path == "/josm/maps.xml":
            status = HTTPStatus.OK
            content_type = "text/xml"
            content = twms.api.maps_xml_josm()
            # Cache-Control: no-cache?
        elif self.path == "/":
            status = HTTPStatus.OK
            content_type = "text/html"
            content = twms.api.maps_html()
        else:
            status = HTTPStatus.NOT_FOUND
            content_type = "text/plain"
            content = repr(status)

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        if "text/" in content_type or "xml" in content_type:
            content = content.encode("utf-8")
        self.wfile.write(content)

    def log_message(self, format, *args):
        """Disable logger."""
        pass

    def log_error(self, format, *args):
        """Declare, because we had disabled 'log_message'."""
        sys.stderr.write(format % args)


def main():
    """Run simple TWMS server."""
    server = ThreadingHTTPServer((twms.config.host, twms.config.port), GetHandler)
    print(
        textwrap.dedent(
            f"""\
        TWMS server {twms.__version__}
        {twms.config.service_url} imagery overview web page
        {twms.config.service_url}wms WMS endpoint
        {twms.config.service_url}tiles TMS endpoint (no reprojection support)
        {twms.config.service_url}josm/maps.xml Add this to JOSM 'imagery.layers.sites' property and check imagery setting"
        Change `twms/config.py` for new layers and custom settings.
        Press <Ctrl-C> to stop"""
        )
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
