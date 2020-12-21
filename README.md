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


### Running TWMS

Install dependencies and clone repo:

    $ sudo pacman -S python-pillow python-pyproj  # Packages for Archlinux
    $ git clone https://github.com/radioxoma/twms.git
    $ cd twms

Edit `twms/twms.conf` and set `tiles_cache` path to your `SAS.Planet/cache_gmt/`. 

Run TWMS and check [http://127.0.0.1:8080](http://127.0.0.1:8080) page in browser for discovered imagery and links. This fork intended to be run locally, as python webserver from standard library not considered secure.

    $ python -m twms 8080

Legacy webpy server preserved though. Install 'python-webpy' and run `$ python -m twms.twmswebpy` if needed.


### Setting up SAS.Planet

SAS.Planet works fine with [wine](https://www.winehq.org/). Open "Settings > Options > Cache tab > Set *Default cache type* to *GlobalMapper Tiles*". So tile path will be like `SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg`, i.e. `SAS.Planet/cache_gmt/vesat/z1/0/0.jpg`.

Download some tiles with SAS.Planet, which can be served later by TWMS.


### Setting up JOSM

At 2020 JOSM uses Java cache (not a directory with tiles), so it can't be shared. It also cannot be disabled. So we move it to RAM disk:

1. Set default cache path `~/.cache/JOSM/tiles` (property 'imagery.generic.loader.cachedir') to `/dev/shm/JOSM/tiles`. Or start JOSM with parameter `-Djosm.cache=/dev/shm/JOSM/tiles`.
2. Set 'imagery.cache.max_disk_size' to 64 Mb, to not exceed RAM


#### TMS, WMS tiles via HTTP

1. Check for a link on [http://127.0.0.1:8080](http://127.0.0.1:8080) web page
2. Open JOSM Imagery > Imagery preferences > Press *+TMS*, *Selected entries* and paste link. Link examples:

    tms:http://localhost:8080/vesat/{z}/{x}/{y}.jpg


#### Tiles via `file://` without TWMS

JOSM supports `file://` uri pointing to 256x256 tiles in EPSG:3857 projection (like OSM, Bing or Google, but not Yandex as it uses EPSG:3395). So it's possible to make JOSM loading tiles directly from disk, without running TWMS server.

1. Check for a link on [http://127.0.0.1:8080](http://127.0.0.1:8080) web page
2. Open JOSM Imagery > Imagery preferences > Press <button>+TMS</button>, *Selected entries* and paste link. Link examples:

    tms:file:///home/user/dev/gis/sasplanet/SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg
    tms[18]:file:///c:/SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg  # Windows


Conventions
===========

* Inside tWMS, only EPSG:4326 latlon should be used for transmitting coordinates.
