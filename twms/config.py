# -*- coding: utf-8 -*-
#    This file is part of tWMS.

#   tWMS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.

#   tWMS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.

#   You should have received a copy of the GNU General Public License
#   along with tWMS.  If not, see <http://www.gnu.org/licenses/>.
import fetchers


debug = True
max_ram_cached_tiles = 256

tiles_cache = "/var/www/latlon/wms/cache/"                   # where to put cache
install_path = "/var/www/latlon/wms/"                        # where to look for broken tiles and other stuff
gpx_cache = "/var/www/latlon/wms/traces/"                    # where to store cached OSM GPX files
deadline = 4500                                                # number of seconds that are given to make up image
default_max_zoom = 18                                        # can be overridden per layer
geometry_color = {                                           # default color for overlayed vectors
        "LINESTRING": "#ff0000",
        "POLYGON": "#0000ff",
        "POINT": "#00ff00",
}
default_layers = ""                                          # layer(s) to show when no layers given explicitly. if False, overview is shown.
max_height = 4095                                            # maximal image proportions
max_width = 4095
output_quality = 75                                          # output image quality (matters for JPEG)
output_progressive = True                                    # should image be progressive? (matters for JPEG)
output_optimize = False                                      # should image be optimized? (matters for PNG)
default_background = "#ffffff"                               # default background for empty space

## stuff used for GetCapabilities
service_url = "http://wms.play.latlon.org/"                  # URL service installed at
wms_name = "latlon.org web map service"                      
default_bbox = (-180.0,-85.0511287798,180.0,85.0511287798)   # spherical mercator maximum. 
default_format = "image/jpeg"
contact_person = {
"mail": "",
"real_name": "",
"organization": ""
}

## Available layers. 
layers = {\
"DGsat": { \
     "name": "Digital Globe Satellite",
     "prefix": "DGsat",			# tile directory
     "ext": "jpg",			# tile images extension
     "scalable": True,			# could zN tile be constructed of four z(N+1) tiles
     "proj": "EPSG:3857",
},\
"yhsat": { \
     "name": "Yahoo Satellite",
     "prefix": "yhsat",			# tile directory
     "ext": "jpg",			# tile images extension
     "scalable": False,			# could zN tile be constructed of four z(N+1) tiles
     "fetch": fetchers.Tile,		# function that fetches given tile. should return None if tile wasn't fetched
     "remote_url": "http://aerial.maps.yimg.com/ximg?v=1.8&t=a&s=256&r=1&x=%s&y=%s&z=%s",
     "transform_tile_number": lambda z,x,y: (x,((2**(z-1)/2)-1)-y,z),
     "dead_tile": install_path + "yahoo_nxt.jpg",
     "min_zoom": 2,
     "max_zoom": 18,
     "proj": "EPSG:3857",
},\
"yasat": { \
     "name": "Yandex Satellite",
     "prefix": "yasat",			# tile directory
     "ext": "jpg",			# tile images extension
     "scalable": False,			# could zN tile be constructed of four z(N+1) tiles
     "fetch": fetchers.Tile,	# function that fetches given tile. should return None if tile wasn't fetched
     "remote_url": "http://sat01.maps.yandex.net/tiles?l=sat&v=1.14.0&x=%s&y=%s&z=%s",
     "transform_tile_number": lambda z,x,y: (x,y,z-1),
     "dead_tile": install_path + "yandex_nxt.jpg",
     "proj": "EPSG:3395",
},\
"osm": { \
     "name": "OpenStreetMap mapnik",
     "prefix": "osm",			# tile directory
     "ext": "png",			# tile images extension
     "scalable": False,			# could zN tile be constructed of four z(N+1) tiles
     "fetch": fetchers.Tile,	# function that fetches given tile. should return None if tile wasn't fetched
     "remote_url": "http://c.tile.openstreetmap.org/%s/%s/%s.png",
     "transform_tile_number": lambda z,x,y: (z-1,x,y),
     "proj": "EPSG:3857",
     "empty_color": "#F1EEE8",
     "cache_ttl": 864000,
},\
"osm-be": { \
     "name": "OpenStreetMap mapnik - Belarus",
     "cached": False,
     "scalable": False,                 # could zN tile be constructed of four z(N+1) tiles
     "fetch": fetchers.Tile,    # function that fetches given tile. should return None if tile wasn't fetched
     "remote_url": "http://tile.latlon.org/tiles/%s/%s/%s.png",
     "transform_tile_number": lambda z,x,y: (z-1,x,y),
     "proj": "EPSG:3857",
     "empty_color": "#f2efe9",
     "data_bounding_box": (23.16722,51.25930,32.82244,56.18162),
},\

"irs":  { \
     "name": "Kosmosnimki.ru IRS Satellite",
     "prefix": "irs",                   # tile directory
     "ext": "jpg",                      # tile images extension
     "scalable": False,                 # could zN tile be constructed of four z(N+1) tiles
     "fetch": fetchers.Tile, # function that fetches given tile. should return None if tile wasn't fetched
     "remote_url": "http://maps.kosmosnimki.ru/TileSender.ashx?ModeKey=tile&MapName=F7B8CF651682420FA1749D894C8AD0F6&LayerName=950FA578D6DB40ADBDFC6EEBBA469F4A&z=%s&x=%s&y=%s",
     "transform_tile_number": lambda z,x,y: (z-1,int(-((int(2**(z-1)))/ 2)+x),int(-((int(2**(z-1)))/ 2)+ int(2**(z-1)-(y+1)))),
     "dead_tile": install_path + "irs_nxt.jpg",
     "min_zoom": 3,
     "max_zoom": 16,
     "empty_color": "#000000",
     "proj": "EPSG:3395",
     "data_bounding_box": (26.0156238531320340,40.7707274153093520,69.257808718487752,67.610652011923932),
},\
"SAT":  { \
     "name": "Google Satellite Partial",
     "prefix": "SAT",                   # tile directory
     "ext": "jpg",                      # tile images extension
     "scalable": True,                 # could zN tile be constructed of four z(N+1) tiles
     "max_zoom": 19,
     "proj": "EPSG:3857",
      "fetch": fetchers.Tile, # function that fetches given tile. should return None if tile wasn't fetched
      #              http://khm1.google.com/kh/v=57&x=63&y=98&z=8&s=Galileo
      #"remote_url": "http://khm1.google.com/kh/v=57&x=%s&y=%s&z=%s&s=%s",
      "transform_tile_number": lambda z,x,y: ( x, y, z-1, "Galileo"[ 0 : ((x*3+y)%8) ] ),
},\
"navitel":  { \
     "name": "Navitel Navigator Maps",
     "prefix": "Navitel",                   # tile directory
     "ext": "png",                      # tile images extension
     "scalable": False,                 # could zN tile be constructed of four z(N+1) tiles
     "fetch": fetchers.Tile, # function that fetches given tile. should return None if tile wasn't fetched
     "remote_url": "http://map.navitel.su/navitms.fcgi?t=%08i,%08i,%02i",
     "transform_tile_number": lambda z,x,y: (x, 2**(z-1)-y-1, z-1),
     "min_zoom": 6,
     "proj": "EPSG:3857",
     "data_bounding_box": (17.999999997494381, 39.999999995338634, 172.99999997592218, 77.999999996263981),
},\
"gshtab":  { \
     "name": "Genshtab 100k maps of Belarus",
     "prefix": "gshtab",                   # tile directory
     "ext": "png",                      # tile images extension
     "scalable": False,                 # could zN tile be constructed of four z(N+1) tiles
     "fetch": fetchers.WMS, # function that fetches given tile. should return None if tile wasn't fetched
     "remote_url": "http://wms.latlon.org/cgi-bin/ms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=GS-100k-N-34,GS-100k-N-35,GS-100k-N-36&STYLES=&FORMAT=image/png&", # string without srs, height, width and bbox
     "max_zoom": 16,
     #"cached": False,
     "empty_color": "#FFFFFF",
     "proj": "EPSG:3857",
     "wms_proj": "EPSG:3857",  # what projection to ask from wms
     "data_bounding_box": (23.16722,51.25930,32.82244,56.18162),
},\

}