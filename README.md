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


Running in Archlinux:

    $ sudo pacman -S python-pillow python-pyproj
    $ python -m twms 8080


Conventions
===========

* Inside tWMS, only EPSG:4326 latlon should be used for transmitting coordinates.
