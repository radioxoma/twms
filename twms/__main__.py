#!/usr/bin/env python

import re
import urllib
from http.server import HTTPServer
from http.server import BaseHTTPRequestHandler

from twms import twms


tileh = re.compile(r"/(.*)/([0-9]+)/([0-9]+)/([0-9]+)(\.[a-zA-Z]+)?(.*)")
# mainh = re.compile(r"/(.*)")


class GetHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        """Parse GET tile request.
        """
        th = re.fullmatch(tileh, self.path)
        if th:
            if th.group(5):
                fmt = th.group(5).strip('.').lower()
            else:
                fmt = 'jpeg'
            data = {
                'request': 'GetTile',
                'layers': th.group(1),
                'z': th.group(2),
                'x': th.group(3),
                'y': th.group(4),
                'format': fmt,
            }
            # rest = m.group(6)
        else:
            data = dict(urllib.parse.parse_qsl(self.path[2:]))  # Strip /?

        resp, ctype, content = twms.twms_main(data)
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.end_headers()
        if ctype == 'text/html':
            content = content.encode('utf-8')
        self.wfile.write(content)


def main():
    """Simple TWMS server.
    """
    server = HTTPServer(('localhost', 8080), GetHandler)
    print("Starting TWMS server at http://{}:{} use <Ctrl-C> to stop".format(
        server.server_address[0], server.server_address[1]))
    server.serve_forever()


if __name__ == "__main__":
    main()
