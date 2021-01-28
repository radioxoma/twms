#!/usr/bin/env python

import os
from twms import fetchers

# SAS Planet "Mobile Atlas Creator (MOBAC)" cache `cache_ma/{z}/{x}/{y}{ext}` 0,0 from the top left
# See
# https://en.wikipedia.org/wiki/Tiled_web_map
# https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames
tiles_cache = os.path.expanduser("~/dev/gis/sasplanet/SAS.Planet/cache_ma/")
# tiles_cache = os.path.expanduser("~/dev/gis/sasplanet/SAS.Planet/cache_test/")
install_path = os.path.realpath(os.path.join(os.path.dirname(__file__), '../'))

# timeout for outer downloads.
# When time is out, tile will be composited from cached tiles
deadline = 45

# If server returns no tile (HTTP 404) or dead tile (empty tile),
# TWMS saves in cache empty "*.tne" file.
# This is a timeout for a next attempt to fetch missing tile
cache_tne_ttl = 60 * 60 * 24 * 30
default_max_zoom = 19             # Load tiles with equal or less zoom. Can be set with 'max_zoom' per layer
default_min_zoom = 0              # Load tiles with equal or greater zoom. Can be set with 'min_zoom' per layer
default_layers = ""               # layer(s) to show when no layers given explicitly. if False, overview page is returned
default_ext = '.jpg'
max_ram_cached_tiles = 1024
max_height = 4095                 # maximal allowed requested height
max_width = 4095                  # maximal allowed requested width
output_quality = 75               # JPEG output image quality
output_progressive = True         # JPEG progressive codec
output_optimize = False           # Optimize PNG images
default_background = "#ffffff"    # Default background for empty space (Pillow color string)


## WMS GetCapabilities
host = "localhost"
port = 8080
service_url = "http://{}:{}/".format(host, port)                       # URL service installed at

wms_name = "twms based web map service"
contact_person = {
    "mail": "",
    "real_name": "",
    "organization": ""
}
default_bbox = (-180.0, -85.0511287798, 180.0, 85.0511287798)   # spherical mercator maximum. 


# Layers
"""
name                 str - visible layer name
prefix               str - cache tile subdirectory name
ext                  string - tile image files extension '.ext'
overlay              bool - default False - transparent hybrid map
scalable             bool - default False - construct tile of better ones if they are available (better for home use and satellite images, or scanned maps). If False, tWMS will use nearest zoom level (better for rasterized vector maps and production servers)
proj                 str - default 'EPSG:3857' - EPSG code of layer tiles projection.

min_zoom             int - the worst zoom level number service provides
max_zoom             int - the best zoom level number service provides
empty_color          str PIL color string - if this layer is overlayed over another, this color will be considered transparent. Also used for dead tile detection in fetchers.WMS
cache_ttl            int - time that cache will be considered valid
data_bounding_box    4326-bbox tuple - no fetching will be performed outside this bbox. Good when caching just one country or a single satellite image.
fetch                function (z, x, y, layer_dict) - function that fetches given tile. should return None if tile wasn't fetched.

* **fetchers.tms** - TMS fetcher
    * **remote_url** _string_ - Base tiles URL. May contain "%s" placeholders
    * **transform_tile_number** _function (x, y, z)_ - function that returns tuple that will be substituted into **remote_url**. If omitted, (z, x, y) tuple is used.
    * **dead_tile** dict, if given, loaded tiles matching pattern won't be saved.
        size - tile size in bytes
        md5 - md5sum hash of that tile
* **fetchers.wns**
    * **remote_url** _str_ - Base WMS URL. A GetMap request with omitted srs, height, width and bbox. Should probably end in "?" or "&".
    * **wms_proj** _str_ - projec for WMS request. Note that images probably won't be properly reprojected if it differs from **proj**. Helps to cope with broken WMS services.

See other WMTS configs https://github.com/bertt/wmts
"""


layers = {
    "yasat": {
        "name": "Yandex Satellite",
        "provider_url": "https://yandex.ru/maps/",
        "prefix": "yasat",
        "proj": "EPSG:3395",
        "ext": ".jpg",
        "scalable": False,
        "fetch": 'tms',
            "remote_url": "https://sat01.maps.yandex.net/tiles?l=sat&x=%s&y=%s&z=%s",
            "transform_tile_number": lambda z, x, y: (x, y, z),
    },

    "yamapng": {
        "name": "Yandex Map",
        "provider_url": "https://yandex.ru/maps/",
        "prefix": "yamapng",
        "proj": "EPSG:3395",
        "ext": ".png",
        "scalable": False,
        "fetch": 'tms',
            "remote_url": "https://vec01.maps.yandex.net/tiles?l=map&x=%s&y=%s&z=%s",
            "transform_tile_number": lambda z, x, y: (x, y, z),
            "cache_ttl": 60 * 60 * 24 * 30,  # Month
    },

    "yahyb": {
        "name": "Yandex Hybrid RU",
        "provider_url": "https://yandex.ru/maps/",
        "prefix": "yahyb",  # "maps.yandex.com.Hybrid" for english tiles
        "proj": "EPSG:3395",
        "ext": ".png",
        'overlay': True,
        "scalable": False,
        "min_zoom": 1,
        "fetch": 'tms',
            "remote_url": "https://vec01.maps.yandex.net/tiles?l=skl&lang=ru_RU&x=%s&y=%s&z=%s",
            "transform_tile_number": lambda z, x, y: (x, y, z),
            "cache_ttl": 60 * 60 * 24 * 30,  # Month
    },

    "sat":  {
        "name": "Google Satellite",
        "provider_url": "https://www.google.com/maps/",
        "prefix": "sat",
        "proj": "EPSG:3857",
        "ext": ".jpg",
        "scalable": False,                  # could zN tile be constructed of four z(N+1) tiles
        "fetch": 'tms_google_sat',
            "transform_tile_number": lambda z, x, y: (x, y, z),
    },

    # First available top left tile https://ecn.t0.tiles.virtualearth.net/tiles/a0.jpeg?g=0
    # Dead tile https://ecn.t0.tiles.virtualearth.net/tiles/a120210103100213.jpeg?g=0
    "vesat": {
        "name": "Bing Satellite",
        "provider_url": "https://www.bing.com/maps?style=h",
        "prefix": "vesat",
        "proj": "EPSG:3857",
        "ext": ".jpg",
        "scalable": False,
        "min_zoom": 1,  # doesn't serve z0/x0/y0 (400 Bad Request for "https://ecn.t0.tiles.virtualearth.net/tiles/a.jpeg?g=0")
        "fetch": 'tms',
            "remote_url": "https://ecn.t0.tiles.virtualearth.net/tiles/a%s.jpeg?g=0",
            "transform_tile_number": fetchers.tile_to_quadkey,
            # "max_zoom": 19,
            # Check against known size in bytes and md5 hash
            "dead_tile": {"size": 1033, "md5": "c13269481c73de6e18589f9fbc3bdf7e", "sha256": "45d35034a62d30443e492851752f67f439b95a908fce54de601f7373fcb7ab05"},
    },

    "osmmapMapnik": {                      # Prefix for TMS links
        "name": "OSM Mapnik",
        "provider_url": "https://www.openstreetmap.org/",
        "prefix": "osmmapMapnik",          # tile directory prefix
        "proj": "EPSG:3857",               # Projection
        "ext": ".png",                      # tile images extension
        "scalable": False,                 # could zN tile be constructed of four z(N+1) tiles
        "max_zoom": 19,  # Allowed if <=
        "fetch": 'tms',        # 'tms' or 'wms' imagery source
            "remote_url": "https://tile.openstreetmap.org/%s/%s/%s.png",  # URL template with placeholders
            "headers": {"Referer": "https://www.openstreetmap.org/"},
            # "transform_tile_number": lambda z, x, y: (z, x, y),  # Function to fill URL placeholders
            "empty_color": "#F1EEE8",
            "cache_ttl": 60 * 60 * 24 * 30,  # 1 month
    },

    "osm_gps_tile": {
        "name": "OSM GPS Traces",
        "provider_url": "https://www.openstreetmap.org/",
        "prefix": "osm_gps_tile",
        "proj": "EPSG:3857",
        "ext": ".png",
        'overlay': True,
        "scalable": False,
        "fetch": 'tms',
            "remote_url": "https://gps-tile.openstreetmap.org/lines/%s/%s/%s.png",
            "headers": {"Referer": "https://www.openstreetmap.org/"},
            "cache_ttl": 60 * 60 * 24 * 30,  # 1 month
    },

    # "osm-be": {
    #      "name": "OpenStreetMap mapnik - Belarus",
    #      "cached": False,
    #      "scalable": False,                 # could zN tile be constructed of four z(N+1) tiles
    #      "fetch": 'tms',    # function that fetches given tile. should return None if tile wasn't fetched
    #      "remote_url": "https://tile.latlon.org/tiles/%s/%s/%s.png",
    #      "transform_tile_number": lambda z,x,y: (z-1,x,y),
    #      "proj": "EPSG:3857",
    #      "empty_color": "#f2efe9",
    #      "data_bounding_box": (23.16722,51.25930,32.82244,56.18162),
    # },

    # "kothic": {
    #    "name": "Kothic - Belarus",
    #    "prefix": "kothic",
    #    "cached": False,
    #    "scalable": False,                 # could zN tile be constructed of four z(N+1) tiles
    #    "fetch": fetchers.kothic_fetcher,    # function that fetches given tile. should return None if tile wasn't fetched
    #    "transform_tile_number": lambda z,x,y: (z-1,x,y),
    #    "proj": "EPSG:3857",
    #    "empty_color": "#f2efe9",
    #    "data_bounding_box": (23.16722,51.25930,32.82244,56.18162),
    # },

    # "landsat":  {
    #      "name": "Landsat from onearth.jpl.nasa.gov",
    #      "prefix": "landsat",
    #      "ext": ".jpg",
    #      "scalable": False,
    #      "fetch": 'wms',
    #      string without srs, height, width and bbox
    #      "remote_url": "https://onearth.jpl.nasa.gov/wms.cgi?request=GetMap&layers=global_mosaic&styles=&format=image/jpeg&",
    #      "max_zoom": 14,
    #      "proj": "EPSG:4326",
    #      "wms_proj": "EPSG:4326",  # what projection to ask from wms
    # },

    # "navitel":  {
    #     "name": "Navitel Navigator Maps",
    #     "prefix": "Navitel",
    #     "ext": ".png",
    #     "scalable": False,
    #     "fetch": 'tms',
    #     "remote_url": "https://map.navitel.su/navitms.fcgi?t=%08i,%08i,%02i";,
    #     "transform_tile_number": lambda z,x,y: (x, 2**(z-1)-y-1, z-1),
    #     "min_zoom": 5,
    #     "proj": "EPSG:3857",
    #     "data_bounding_box": (17.999999997494381, 39.999999995338634, 172.99999997592218, 77.999999996263981),
    # },

    # "latlonsat":  {
    #      "name": "Imagery from latlon.org",
    #      "prefix": "latlonsat",
    #      "ext": ".jpg",
    #      "scalable": False,
    #      "fetch": 'tms',
    #      string without srs, height, width and bbox
    #      "remote_url": "https://dev.latlon.org/cgi-bin/ms?FORMAT=image/jpeg&VERSION=1.1.1&SERVICE=WMS&REQUEST=GetMap&Layers=sat,plane&",
    #      "max_zoom": 19,
    #      "proj": "EPSG:3857",
    #      "wms_proj": "EPSG:3857",  # what projection to ask from wms
    # }

    # "DGsat": {
    #      "name": "Digital Globe Satellite",
    #      "prefix": "DGsat",
    #      "ext": ".jpg",
    #      "scalable": False,
    #      "proj": "EPSG:3857",
    #      # Could add "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/16/20867/38349"
    # },

    "maxar_prem": {
         "name": "Maxar Premuim",
         "provider_url": "https://www.maxar.com/",
         "prefix": "maxar_prem",
         "ext": ".jpg",
         "proj": "EPSG:3857",
         "scalable": False,
            "fetch": 'tms',
            "transform_tile_number": fetchers.tile_slippy_to_tms,
            # API key from JOSM
            "remote_url": "https://services.digitalglobe.com/earthservice/tmsaccess/tms/1.0.0/DigitalGlobe:ImageryTileService@EPSG:3857@jpg/%s/%s/%s.jpg?connectId=fa014fbc-6cbe-4b6f-b0ca-fbfb8d1e5b7d&foo=premium",
    },

    # "irs":  {
    #     "name": "Kosmosnimki.ru IRS Satellite",
    #     "prefix": "irs",
    #     "ext": ".jpg",
    #     "scalable": False,
    #     "fetch": 'tms',
    #     "remote_url": "https://maps.kosmosnimki.ru/TileSender.ashx?ModeKey=tile&MapName=F7B8CF651682420FA1749D894C8AD0F6&LayerName=950FA578D6DB40ADBDFC6EEBBA469F4A&z=%s&x=%s&y=%s";,
    #     "transform_tile_number": lambda z,x,y: (z-1,int(-((int(2**(z-1)))/ 2)+x),int(-((int(2**(z-1)))/ 2)+ int(2**(z-1)-(y+1)))),
    #     "dead_tile": {"size": 0, "md5": "d41d8cd98f00b204e9800998ecf8427e", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
    #     "min_zoom": 2,
    #     "max_zoom": 16,
    #     "empty_color": "#000000",
    #     "proj": "EPSG:3395",
    #     "data_bounding_box": (26.0156238531320340,40.7707274153093520,69.257808718487752,67.610652011923932),
    # },

    # "yhsat": {
    #      "name": "Yahoo Satellite",
    #      "prefix": "yhsat",
    #      "ext": ".jpg",
    #      "scalable": False,
    #      "fetch": 'tms',
    #      "remote_url": "https://aerial.maps.yimg.com/ximg?v=1.8&t=a&s=256&r=1&x=%s&y=%s&z=%s",
    #      "transform_tile_number": lambda z,x,y: (x,((2**(z-1)/2)-1)-y,z),
    #      "min_zoom": 2,
    #      "max_zoom": 18,
    #      "proj": "EPSG:3857",
    # },

    "georesursDDZ":  {
        "name": "dzz.by Aerophotography (Belarus)",
        "provider_url": "https://www.dzz.by/izuchdzz/",
        "prefix": "georesursDDZ",
        "proj": "EPSG:3857",
        "ext": ".jpg",
        "scalable": False,
        "data_bounding_box": (23.16722,51.25930,32.82244,56.18162),
            "fetch": 'tms',

            # nca.by has sane proxy (valid 404, SSL certificate)
            "remote_url": "https://api.nca.by/gis/dzz/tile/%s/%s/%s",

            # https://gismap.by invalid certificate, weird 404 handling
            # "headers": {"Referer": "https://gismap.by/next/"},  # 403 without SSL
            # "remote_url": "https://gismap.by/next/proxy/proxy.ashx?https://www.dzz.by/arcgis/rest/services/georesursDDZ/Belarus_Web_Mercator_new/ImageServer/tile/%s/%s/%s",
            # ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1123)

            "transform_tile_number": lambda z, x, y: (z - 6, y, x),
            "min_zoom": 6,
            "max_zoom": 19,
    },
}
