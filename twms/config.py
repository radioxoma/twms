"""TWMS config file.

debug - tile file operations
info - tile fetching or constructing
warning - HTTP errors
"""

import os

import twms
import twms.bbox

"""
Cache layout
------------

There are multiple descriptions for the same thing:

  * TWMS stores tiles of 256x256 pixels
  * TWMS stores whole cache in single user-defined mimetype. If server returns tile with needed mimetype, original image is preserved, otherwise it will be recompressed
  * TWMS internally uses 'GLOBAL_WEBMERCATOR' grid, 'EPSG:3857' (formely known as 'EPSG:900913') projection, origin north-west (compatible with OpenStreetMap, mapproxy.org)
  * Same as SAS.Planet "Mobile Atlas Creator (MOBAC)" cache `cache_ma/{z}/{x}/{y}{ext}` 0,0 from the top left (nw)

See:
  [1] https://en.wikipedia.org/wiki/Tiled_web_map
  [2] https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames
  [3] https://josm.openstreetmap.de/wiki/SharedTileCache
"""

# There may be more appropriate place for a cache, like `~/.cache/osm/tiles/`
tiles_cache = os.path.expanduser("~/dev/gis/sasplanet/SAS.Planet/cache_ma/")
# tiles_cache = os.path.expanduser("~/dev/gis/sasplanet/SAS.Planet/cache_test/")

# timeout for outer downloads.
# When time is out, tile will be composited from cached tiles
deadline = 45

# If server returns no tile (HTTP 404) or dead tile,
# TWMS saves in cache empty "*.tne" file.
# This is a timeout for a next attempt to fetch missing tile
cache_tne_ttl = 60 * 60 * 24 * 30  # Month

# Load tiles with equal or less zoom. Can be set with 'max_zoom' per layer
# [19] 30 cm resolution - best Maxar satellite resolution at 2021
default_max_zoom = 19  # <=

# Load tiles with equal or greater zoom. Can be set with 'min_zoom' per layer
default_min_zoom = 0
default_layers = ""  # layer(s) to show when no layers given explicitly. if False, overview page is returned
default_mimetype = "image/jpeg"
max_ram_cached_tiles = 1024
max_height = 4095  # maximal allowed requested height
max_width = 4095  # maximal allowed requested width
output_quality = 75  # JPEG output image quality
output_progressive = True  # JPEG progressive codec
output_optimize = False  # Optimize PNG images
default_background = "#ffffff"  # Default background for empty space

# WMS GetCapabilities
host = "localhost"
port = 8080
service_url = f"http://{host}:{port}/"  # URL service installed at
wms_name = f"twms {twms.__version__}"
contact_person = {"mail": "", "real_name": "", "organization": ""}
# Spherical mercator maximum
default_bbox: twms.bbox.Bbox = (-180.0, -85.0511287798, 180.0, 85.0511287798)


"""
Layers

name           str - visible layer name
prefix         str - unique cache tile subdirectory name
mimetype       str - tiles will be stored and served in this mimetype, converted if necessary
overlay        bool - default False - transparent hybrid map
scalable       bool - default False - construct tile of better ones if they are available (better for home use and satellite images, or scanned maps). If False, tWMS will use nearest zoom level (better for rasterized vector maps and production servers)
proj           str - default 'EPSG:3857' - EPSG code of layer tiles projection.

min_zoom       int - the worst zoom level number service provides
max_zoom       int - the best zoom level number service provides (<=)
empty_color    str PIL color string - if this layer is overlayed over another, this color will be considered transparent. Also used for dead tile detection in fetchers.WMS
cache_ttl      int - time that cache will be considered valid
bounds         tuple - 4326-bbox - (min-lon, min-lat, max-lon, max-lat) no wms fetching will be performed outside this bbox. Good when caching just one country or a single satellite image.
fetch          function (z, x, y, layer_dict) - function that fetches given tile. should return None if tile wasn't fetched.

* **fetchers.tms** - TMS fetcher
    * **remote_url** _string_ - Base tiles URL. May contain "%s" placeholders
    * **transform_tile_number** _function (x, y, z)_ - function that returns tuple that will be substituted into **remote_url**. If omitted, (z, x, y) tuple is used.
    * **dead_tile** dict, if given, loaded tiles matching pattern won't be saved.
        size - tile size in bytes
        md5 - md5sum hash of that tile
* **fetchers.wms**
    * **remote_url** _str_ - Base WMS URL. A GetMap request with omitted srs, height, width and bbox. Should probably end in "?" or "&".
    * **wms_proj** _str_ - projection for WMS request. Note that images probably won't be properly reprojected if it differs from **proj**. Helps to cope with WMS services unable to serve properly reprojected imagery.

Other WMTS configs https://github.com/bertt/wmts
"""


layers = {
    "yasat": {
        "name": "Yandex Satellite",
        "provider_url": "https://yandex.ru/maps/",
        "prefix": "yasat",
        "proj": "EPSG:3395",
        "scalable": False,
        "fetch": "tms",
        "remote_url": "https://core-sat.maps.yandex.net/tiles?l=sat&x={x}&y={y}&z={z}&scale=1&lang=ru_RU",
    },
    "yamapng": {
        "name": "Yandex Map",
        "provider_url": "https://yandex.ru/maps/",
        "prefix": "yamapng",
        "proj": "EPSG:3395",
        "mimetype": "image/png",
        "scalable": False,
        "fetch": "tms",
        "remote_url": "https://core-renderer-tiles.maps.yandex.net/tiles?l=map&x={x}&y={y}&z={z}&scale=1&lang=ru_RU",
        "cache_ttl": 60 * 60 * 24 * 30,  # Month
    },
    "yahyb": {
        "name": "Yandex Hybrid RU",
        "provider_url": "https://yandex.ru/maps/",
        "prefix": "yahyb",  # "maps.yandex.com.Hybrid" for english tiles
        "proj": "EPSG:3395",
        "mimetype": "image/png",
        "overlay": True,
        "scalable": False,
        "min_zoom": 1,
        "fetch": "tms",
        "remote_url": "https://core-renderer-tiles.maps.yandex.net/tiles?l=skl&x={x}&y={y}&z={z}&scale=1&lang=ru_RU",
        "cache_ttl": 60 * 60 * 24 * 30,  # Month
    },
    # https://core-gpstiles.maps.yandex.net/tiles?style=red_combined&x={x}&y={y}&z={z}
    "yandextracks": {
        "name": "Yandex Tracks",
        "provider_url": "https://n.maps.yandex.ru",
        "prefix": "yandextracks",
        "proj": "EPSG:3395",
        "mimetype": "image/png",
        "scalable": False,
        "fetch": "tms",
        "remote_url": "https://core-gpstiles.maps.yandex.net/tiles?style=point&x={x}&y={y}&z={z}",
        "min_zoom": 10,
        "max_zoom": 17,
        "cache_ttl": 60 * 60 * 24 * 30,  # Month
    },
    "sat": {
        "name": "Google Satellite",
        "provider_url": "https://www.google.com/maps/",
        "prefix": "sat",
        "proj": "EPSG:3857",
        "scalable": False,  # could zN tile be constructed of four z(N+1) tiles
        "fetch": "tms_google_sat",
    },
    # First available top left tile https://ecn.t0.tiles.virtualearth.net/tiles/a0.jpeg?g=0
    # Dead tile https://ecn.t0.tiles.virtualearth.net/tiles/a120210103100213.jpeg?g=0
    "vesat": {
        "name": "Bing Satellite",
        "provider_url": "https://www.bing.com/maps?style=h",
        "prefix": "vesat",
        "proj": "EPSG:3857",
        "scalable": False,
        "min_zoom": 1,  # doesn't serve z0/x0/y0 (400 Bad Request for "https://ecn.t0.tiles.virtualearth.net/tiles/a.jpeg?g=0")
        "fetch": "tms",
        "remote_url": "https://ecn.t0.tiles.virtualearth.net/tiles/a{q}.jpeg?g=0",
        # "max_zoom": 19,
        # Check against known size in bytes and md5 hash
        "dead_tile": {
            "size": 1033,
            "md5": "c13269481c73de6e18589f9fbc3bdf7e",
            "sha256": "45d35034a62d30443e492851752f67f439b95a908fce54de601f7373fcb7ab05",
        },
    },
    "osmmapMapnik": {  # Prefix for TMS links
        "name": "OSM Mapnik",
        "provider_url": "https://www.openstreetmap.org/",
        "prefix": "osmmapMapnik",  # tile directory prefix
        "proj": "EPSG:3857",  # Projection
        "mimetype": "image/png",
        "scalable": False,  # could zN tile be constructed of four z(N+1) tiles
        "max_zoom": 19,  # Allowed if <=
        "fetch": "tms",  # 'tms' or 'wms' imagery source
        "remote_url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",  # URL template with placeholders
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
        "mimetype": "image/png",
        "overlay": True,
        "scalable": False,
        "fetch": "tms",
        "remote_url": "https://gps-tile.openstreetmap.org/lines/{z}/{x}/{y}.png",
        "headers": {"Referer": "https://www.openstreetmap.org/"},
        "cache_ttl": 60 * 60 * 24 * 30,  # 1 month
    },
    # 'addr_ks' - red dot - капитальное строение (КС)
    # yellow dot - Незавершенное законсервированное капитальное строение (НЗКС)
    # green dot - земельный участок (ЗУ)
    "ncaby_radr": {
        "name": "nca.by Capital buildings and addresses",
        "provider_url": "http://vl.nca.by/",
        "prefix": "ncaby_radr",
        "proj": "EPSG:3857",
        "mimetype": "image/png",
        "scalable": False,  # could zN tile be constructed of four z(N+1) tiles
        "bounds": (23.16722, 51.25930, 32.82244, 56.18162),  # Belarus
        "fetch": "tms",
        "min_zoom": 15,
        "remote_url": "http://gisserver3.nca.by:8080/geoserver/wms?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&FORMAT=image/png&TRANSPARENT=true&layers=prod:radr&propertyName=obj_name,elementtyp,elementnam,addr_label,geom&TILED=true&STYLES=addr_ks&WIDTH={width}&HEIGHT={height}&CRS={proj}&BBOX={bbox}",
        "cache_ttl": 60 * 60 * 24 * 30,  # 1 month
    },
    "geoby_mapserver": {
        "name": "geo.by Belgeodesy Map",
        "provider_url": "https://geo.by/navigation/map",
        "prefix": "geoby_mapserver",
        "proj": "EPSG:3857",
        "mimetype": "image/png",
        "scalable": False,
        "bounds": (23.16722, 51.25930, 32.82244, 56.18162),  # Belarus
        "fetch": "tms",
        "remote_url": "https://mapserver.geo.by/mapcache/?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&LAYERS=mapserver_tileset&STYLES=&FORMAT=image/png&TRANSPARENT=true&HEIGHT={height}&WIDTH={width}&SRS={proj}&BBOX={bbox}",
        "headers": {"Referer": "https://geo.by/navigation/map"},
        "cache_ttl": 60 * 60 * 24 * 30,  # 1 month
    },
    # "kothic": {
    #    "name": "Kothic - Belarus",
    #    "prefix": "kothic",
    #    "cached": False,
    #    "scalable": False,                 # could zN tile be constructed of four z(N+1) tiles
    #    "fetch": fetchers.kothic_fetcher,    # function that fetches given tile. should return None if tile wasn't fetched
    #    "proj": "EPSG:3857",
    #    "empty_color": "#f2efe9",
    #    "bounds": (23.16722,51.25930,32.82244,56.18162),
    # },
    # "landsat":  {
    #      "name": "Landsat from onearth.jpl.nasa.gov",
    #      "prefix": "landsat",
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
    #     "mimetype": "image/png",
    #     "scalable": False,
    #     "fetch": 'tms',
    #     "remote_url": "https://map.navitel.su/navitms.fcgi?t=%08i,%08i,%02i";,
    #     "transform_tile_number": lambda z,x,y: (x, 2**(z-1)-y-1, z-1),
    #     "min_zoom": 5,
    #     "proj": "EPSG:3857",
    #     "bounds": (17.999999997494381, 39.999999995338634, 172.99999997592218, 77.999999996263981),
    # },
    # "latlonsat":  {
    #      "name": "Imagery from latlon.org",
    #      "prefix": "latlonsat",
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
    #      "scalable": False,
    #      "proj": "EPSG:3857",
    #      # Could add "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/16/20867/38349"
    # },
    "maxar_prem": {
        "name": "Maxar Premuim",
        "provider_url": "https://www.maxar.com/",
        "prefix": "maxar_prem",
        "proj": "EPSG:3857",
        "max_zoom": 18,  # Looks like artificial restriction
        "scalable": False,
        "fetch": "tms",
        # API key from JOSM
        "remote_url": "https://services.digitalglobe.com/earthservice/tmsaccess/tms/1.0.0/DigitalGlobe:ImageryTileService@EPSG:3857@jpg/{z}/{x}/{-y}.jpg?connectId=fa014fbc-6cbe-4b6f-b0ca-fbfb8d1e5b7d&foo=premium",
    },
    # "irs":  {
    #     "name": "Kosmosnimki.ru IRS Satellite",
    #     "prefix": "irs",
    #     "scalable": False,
    #     "fetch": 'tms',
    #     "remote_url": "https://maps.kosmosnimki.ru/TileSender.ashx?ModeKey=tile&MapName=F7B8CF651682420FA1749D894C8AD0F6&LayerName=950FA578D6DB40ADBDFC6EEBBA469F4A&z=%s&x=%s&y=%s";,
    #     "transform_tile_number": lambda z,x,y: (z-1,int(-((int(2**(z-1)))/ 2)+x),int(-((int(2**(z-1)))/ 2)+ int(2**(z-1)-(y+1)))),
    #     "dead_tile": {"size": 0, "md5": "d41d8cd98f00b204e9800998ecf8427e", "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
    #     "min_zoom": 2,
    #     "max_zoom": 16,
    #     "empty_color": "#000000",
    #     "proj": "EPSG:3395",
    #     "bounds": (26.0156238531320340,40.7707274153093520,69.257808718487752,67.610652011923932),
    # },
    # "yhsat": {
    #      "name": "Yahoo Satellite",
    #      "prefix": "yhsat",
    #      "scalable": False,
    #      "fetch": 'tms',
    #      "remote_url": "https://aerial.maps.yimg.com/ximg?v=1.8&t=a&s=256&r=1&x=%s&y=%s&z=%s",
    #      "transform_tile_number": lambda z,x,y: (x,((2**(z-1)/2)-1)-y,z),
    #      "min_zoom": 2,
    #      "max_zoom": 18,
    #      "proj": "EPSG:3857",
    # },
    "dzzby_orthophoto": {
        # [19] 30 cm most of Belarus
        # [20] 15 cm Minsk
        #     20 top for orthophoto, but in most places it just blurred 19
        # [21]
        # [22] 7.5~5 cm Unmanned airway vehicle "Геоскан-201" for садоводческие товарищества and towns
        #     22 top for UAV
        "name": "dzz.by Aerophotography (Belarus)",
        "provider_url": "https://www.dzz.by/izuchdzz/",
        "prefix": "dzzby_orthophoto",
        "proj": "EPSG:3857",
        "scalable": False,
        "bounds": (23.16722, 51.25930, 32.82244, 56.18162),  # Belarus
        "fetch": "tms",
        # nca.by has sane proxy (valid 404, SSL certificate)
        "remote_url": "https://api.nca.by/gis/dzz/tile/{z}/{y}/{x}",
        # https://gismap.by invalid certificate, weird 404 handling
        # "headers": {"Referer": "https://gismap.by/next/"},  # 403 without SSL
        # "remote_url": "https://gismap.by/next/proxy/proxy.ashx?https://www.dzz.by/arcgis/rest/services/georesursDDZ/Belarus_Web_Mercator_new/ImageServer/tile/%s/%s/%s",
        # ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1123)
        "transform_tile_number": lambda z, x, y: (z - 6, x, y),
        "min_zoom": 6,
        "max_zoom": 19,  # max_zoom is 20, but in most places it just blurred 19
    },
}
