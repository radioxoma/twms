# twms web map server

Serve map tiles to the WMS-enabled applications. Also, twms can act as a proxy to external resources.


## About this fork

* [`http.server`](https://docs.python.org/3/library/http.server.html) from standard python library is used instead of [webpy](https://webpy.org/)
* GlobalMapper Tiles cache format, compatible both with both [JOSM](https://josm.openstreetmap.de/) and [SAS.Planet](http://www.sasgis.org/sasplaneta/)
* Functional regression - unsupported code has been [dropped](https://github.com/radioxoma/twms/commit/8a3a6bc6e562f5aeea480399c2bd00c345d34a12) (e.g. filters).
* [JOSM remote control](https://josm.openstreetmap.de/wiki/Help/RemoteControlCommands) support
* Due to huge refactoring and removing half of the original code the changes ineligible for a pull request


## Setting up TWMS

Install dependencies and clone repo:

    $ sudo pacman -S python-pillow python-pyproj  # Packages for Archlinux
    $ git clone https://github.com/radioxoma/twms.git
    $ cd twms

Edit `twms/twms.conf` and set `tiles_cache` path to your `SAS.Planet/cache_gmt/`. 

Run TWMS and check [http://127.0.0.1:8080](http://127.0.0.1:8080) page in browser for discovered imagery and links. This fork intended to be run locally, as python webserver from standard library not considered secure.

    $ python -m twms


## Setting up SAS.Planet

SAS.Planet works fine with [wine](https://www.winehq.org/). Open "Settings > Options > Cache tab > Set *Default cache type* to *GlobalMapper Tiles*". So tile path will be like `SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg`, i.e. `SAS.Planet/cache_gmt/vesat/z1/0/0.jpg`.

Download some tiles with SAS.Planet, which can be served later by TWMS.


## Setting up JOSM

At 2020 JOSM uses Java cache (not a directory with tiles), so it can't be shared. It also cannot be disabled. So we move it to RAM disk:

1. Set property 'imagery.generic.loader.cachedir' to `/dev/shm/JOSM/tiles` or start JOSM with parameter `-Djosm.cache=/dev/shm/JOSM/tiles`.
2. Set property 'imagery.cache.max_disk_size' to reasonable value, e.g. 64 Mb, to not exceed RAM


### Load tiles wia TWMS HTTP proxy

1. Check [http://127.0.0.1:8080](http://127.0.0.1:8080) for available `tms:` links
2. Open JOSM Imagery > Imagery preferences > Press *+TMS*, *Selected entries* and paste link. E.g.:


    tms:http://localhost:8080/vesat/{z}/{x}/{y}.jpg


### Load tiles directly from disk

JOSM supports `file://` URI pointing to 256x256 tiles in EPSG:3857 projection (like OSM, Bing or Google, but not Yandex as it uses EPSG:3395). So it's possible to make JOSM loading tiles directly from disk, without running TWMS server.

1. Check [http://127.0.0.1:8080](http://127.0.0.1:8080) for available `file://` links
2. Open JOSM Imagery > Imagery preferences > Press *+TMS*, *Selected entries* and paste link. E.g.:


    tms:file:///home/user/dev/gis/sasplanet/SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg
    tms[18]:file:///c:/SAS.Planet/cache_gmt/vesat/z{z}/{y}/{x}.jpg  # Windows
