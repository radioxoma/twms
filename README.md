About
=====

twms is a script that connects World of Tiles and World of WMS.
The name ‘twms’ stands for twms web map server.

The primary purpose of twms is to export your map tiles to the
WMS-enabled applications.

twms can export a set of raster tiles as a WMS service
so GIS applications that support WMS protocol can access
this tile set. Also, twms can act as a proxy and perform
WMS requests to external services and serve the tile cache


About this fork
===============

* [`http.server`](https://docs.python.org/3/library/http.server.html) from standard python library is used instead of [webpy](https://webpy.org/)
* GlobalMapper Tiles cache format, compatible both with both [JOSM](https://josm.openstreetmap.de/) and [SAS.Planet](http://www.sasgis.org/sasplaneta/)
* Functional regression - unsupported code has been [dropped](https://github.com/radioxoma/twms/commit/8a3a6bc6e562f5aeea480399c2bd00c345d34a12) (e.g. filters).
* Due to huge refactoring and removing half of the original code the changes ineligible for a pull request


### Setting up SAS.Planet

Settings > Options > Cache tab > Set *Default cache type* to *GlobalMapper Tiles*. So tile path will be like `SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg`, i.e. `SAS.Planet/cache_gmt/vesat/z1/0/0.jpg`.

Download some tiles with SAS.Planet, which can be served later by TWMS.


### Setting up JOSM

Notes at 2020:

JOSM uses Java cache (not a directory with tiles), so it can't be shared and useless. It also cannot be disabled. So we move it to RAM disk:

    1. Set default cache path `~/.cache/JOSM/tiles` (property 'imagery.generic.loader.cachedir') to `/dev/shm/JOSM/tiles`. Or start JOSM with parameter `-Djosm.cache=/dev/shm/JOSM/tiles`.
    2. Set 'imagery.cache.max_disk_size' to 64 Mb, should be enough

JOSM supports `file://` uri pointing to 256x256 tiles in EPSG:3857 projection (like OSM, Bing or Google, but not Yandex as it uses EPSG:3395). So it's possible to make JOSM to load such tiles directly, without TWMS.

    tms:file:///home/user/dev/gis/sasplanet/SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg
    tms[18]:file:///c:/SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg  # Windows


### Running TWMS

This TWMS fork intended to be run locally, as default webserver not considered secure.

    $ git clone https://github.com/radioxoma/twms.git
    $ cd twms
    # Edit `twms/twms.conf` and set `tiles_cache` path to `SAS.Planet/cache_gmt/`

Install dependencies, i.e. for Archlinux package names will be as such:

    $ sudo pacman -S python-pillow python-pyproj

Run twms and check [http://127.0.0.1:8080](http://127.0.0.1:8080) page in browser.

    $ python -m twms 8080  # Default http.server

Legacy webpy server preserved. If one needs it, install 'python-webpy' and run:

    $ python -m twms.twmswebpy 8080


Conventions
===========

* Inside tWMS, only EPSG:4326 latlon should be used for transmitting coordinates.
