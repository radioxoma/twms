import mimetypes
import urllib.parse
import xml.etree.ElementTree as ET

import twms
import twms.config
import twms.projections


def get_tms_url(layer) -> str:
    ext = mimetypes.guess_extension(layer.get("mimetype", twms.config.default_mimetype))
    return f"{twms.config.service_url}/tiles/{layer['prefix']}/{{z}}/{{x}}/{{y}}{ext}"


def get_wms_url(layer) -> str:
    """TWMS has somewhat like WMS-C emulation for getting tiles directly."""
    ext = mimetypes.guess_extension(layer.get("mimetype", twms.config.default_mimetype))
    return f"{twms.config.service_url}/wms/{layer['prefix']}/{{z}}/{{x}}/{{y}}{ext}"


def get_fs_url(layer) -> str:
    ext = mimetypes.guess_extension(layer.get("mimetype", twms.config.default_mimetype))
    return f"file://{twms.config.tiles_cache}{layer['prefix']}/{{z}}/{{x}}/{{y}}{ext}"


def maps_html() -> str:
    """Render TMS layers summary."""
    resp = [
        f"""
        <!doctype html><html><head>
        <title>{twms.config.wms_name}</title>
        <style>
        .entry {{
            display: inline-block;
            vertical-align: top;
            width:256px;
            padding: 5px;
        }}
        </style>
        </head><body><h2>{twms.config.wms_name}</h2>
    """
    ]

    for layer_id, layer in twms.config.layers.items():
        proj = layer.get("proj", twms.config.default_src)
        bbox = layer.get("bounds", twms.projections.projs[proj]["bounds"])
        resp.append('<div class="entry">')

        if "min_zoom" in layer and layer["min_zoom"] > 8:
            # Too recursive
            resp.append("<p>Preview unavailable</p>")
        else:
            resp.append(
                f'<img src="wms?layers={layer_id}&amp;bbox=%s,%s,%s,%s&amp;width=200&amp;format=image/png" width="200" />'
                % bbox
            )

        if "provider_url" in layer:
            resp.append(
                f'<h3><a referrerpolicy="no-referrer" title="Visit tile provider website" href="{layer["provider_url"]}">{layer["name"]}</a></h3>'
            )
        else:
            resp.append(f"<h3>{layer['name']}</h3>")

        resp.append(
            f'<b>Bounding box: </b><a href="{"https://openstreetmap.org/?minlon=%s&amp;minlat=%s&amp;maxlon=%s&amp;maxlat=%s&amp;box=yes" % bbox}">{bbox}</a><br>'
            f"<b>Projection:</b> {proj}<br />"
            f"<b>WMS half-link:</b> {twms.config.service_url}?layers={layer_id}&amp;<br />"
        )
        # Links for JOSM remote control. See https://josm.openstreetmap.de/wiki/Help/RemoteControlCommands#imagery
        josm_link = "http://127.0.0.1:8111/"
        josm_params = {
            "title": layer["name"],
            "type": "tms",
            "valid-georeference": "true",  # Hide annoying warning
        }
        tms_tpl = f'<a title="Import layer with JOSM remote control" href="{josm_link}imagery?{{josm_params}}">tms:</a>{{tms_uri}}<br />'

        josm_params["url"] = get_wms_url(layer)
        resp.append(
            tms_tpl.format(
                josm_params=urllib.parse.urlencode(josm_params),
                tms_uri=josm_params["url"],
            )
        )

        # Faster URI for tiles stored in the same projection
        if proj == "EPSG:3857":
            josm_params["url"] = get_tms_url(layer)
            resp.append(
                tms_tpl.format(
                    josm_params=urllib.parse.urlencode(josm_params),
                    tms_uri=josm_params["url"],
                )
            )

            josm_params["url"] = get_fs_url(layer)
            resp.append(
                tms_tpl.format(
                    josm_params=urllib.parse.urlencode(josm_params),
                    tms_uri=josm_params["url"],
                )
            )
        resp.append("</div>")

    resp.append("</body></html>")
    return "".join(resp)


def maps_xml_josm() -> str:
    """Create XML for JOSM 'imagery.layers.sites' property.

    XML spec https://josm.openstreetmap.de/wiki/Maps
    ELI https://github.com/osmlab/editor-layer-index
    JOSM source https://josm.openstreetmap.de/doc/org/openstreetmap/josm/data/imagery/ImageryLayerInfo.html

        Mandatory tags: <entry>: (<name>, <id>, <type>, <url>)

    XML examples:
        https://josm.openstreetmap.de/maps%<?ids=>  # JOSM URL for fetching
        https://osmlab.github.io/editor-layer-index/imagery.xml
        http://www.imagico.de/map/osmim-imagicode.xml
    """
    # Green color means it already added
    # 1. category - shows as an icon
    # 2. country-code - empty for worldwide
    # 3. name
    # 4. url, but with tms prefox, min-max zoom
    imagery = ET.Element("imagery")
    for layer_id, layer in twms.config.layers.items():
        proj = layer.get("proj", twms.config.default_src)
        entry = ET.SubElement(imagery, "entry")
        if "overlay" in layer and layer["overlay"] is True:
            entry.attrib["overlay"] = "true"
        # entry.attrib['eli-best'] = 'true'  # Some JOSM hint/tooltip
        ET.SubElement(
            entry, "default"
        ).text = "true"  # Will be added on first JOSM run?

        ET.SubElement(entry, "name").text = f"twms {layer_id}"  # Must be in English
        ET.SubElement(entry, "id").text = "twms_" + layer_id
        ET.SubElement(entry, "type").text = "tms"
        if proj == "EPSG:3857":
            ET.SubElement(entry, "url").text = get_tms_url(layer)  # Implement CDATA?
        else:
            # tms_handler not supports reprojection
            ET.SubElement(entry, "url").text = get_wms_url(layer)  # Implement CDATA?
        # Optional tags below
        ET.SubElement(entry, "description").text = layer["name"]  # Must be in English
        if "bounds" in layer:
            ET.SubElement(entry, "bounds").attrib.update(
                {
                    "min-lon": str(layer["bounds"][0]),
                    "min-lat": str(layer["bounds"][1]),
                    "max-lon": str(layer["bounds"][2]),
                    "max-lat": str(layer["bounds"][3]),
                }
            )

        if "dead_tile" in layer:
            no_tile = ET.SubElement(entry, "no-tile-checksum")
            no_tile.attrib["type"] = "MD5"  # Upper case only
            no_tile.attrib["value"] = layer["dead_tile"]["md5"]
        ET.SubElement(
            entry, "valid-georeference"
        ).text = "true"  # Don't annoy with banner

        if "max_zoom" in layer:
            ET.SubElement(entry, "max-zoom").text = str(layer["max_zoom"])
        else:
            max_zoom = ET.SubElement(entry, "max-zoom")
            max_zoom.text = str(twms.config.default_max_zoom)
            entry.append(
                ET.Comment("Overrided with default 'max_zoom' from current TWMS config")
            )

        if "min_zoom" in layer:
            ET.SubElement(entry, "min-zoom").text = str(layer["min_zoom"])
    return ET.tostring(imagery, encoding="unicode")


def maps_xml_wms111() -> str:
    """Minimal WMS GetCapabilities v1.1.1 XML implementation.

    Returns:
        XML "application/vnd.ogc.wms_xml"
    """

    def add_url(parent) -> None:
        """Pass link with path to client."""
        ET.SubElement(
            ET.SubElement(
                ET.SubElement(ET.SubElement(parent, "DCPType"), "HTTP"), "Get"
            ),
            "OnlineResource",
            attrib={
                "{http://www.w3.org/1999/xlink}type": "simple",
                "{http://www.w3.org/1999/xlink}href": twms.config.service_wms_url,
            },
        )

    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    # See 7.2.4 GetCapabilities response
    root = ET.Element(
        "WMT_MS_Capabilities",
        attrib={"version": "1.1.1"},
    )
    service = ET.SubElement(root, "Service")
    # It shall include a Name, Title, and Online Resource URL
    ET.SubElement(service, "Name").text = "OGC:WMS"  # Shall  be "OGC:WMS" for v1.1.1
    ET.SubElement(service, "Title").text = twms.config.wms_name
    # This is superseeded by DCPType/HTTP/Get anuway
    ET.SubElement(
        service,
        "OnlineResource",
        attrib={
            "{http://www.w3.org/1999/xlink}type": "simple",
            "{http://www.w3.org/1999/xlink}href": twms.config.service_wms_url,
        },
    )
    capability = ET.SubElement(root, "Capability")
    request = ET.SubElement(capability, "Request")

    get_capabilities = ET.SubElement(request, "GetCapabilities")
    ET.SubElement(get_capabilities, "Format").text = "application/vnd.ogc.wms_xml"
    add_url(get_capabilities)

    get_map = ET.SubElement(request, "GetMap")
    for image_mimetype in ("image/jpeg", "image/png", "image/webp"):
        ET.SubElement(get_map, "Format").text = image_mimetype
    add_url(get_map)

    exceptions = ET.SubElement(capability, "Exception")
    for exc_mimetype in (
        "application/vnd.ogc.se_xml",
        "application/vnd.ogc.se_inimage",
        "application/vnd.ogc.se_blank",
    ):
        ET.SubElement(exceptions, "Format").text = exc_mimetype

    parent_layer = ET.SubElement(capability, "Layer")
    ET.SubElement(parent_layer, "Title").text = twms.config.wms_name

    for proj in sorted(
        twms.projections.projs.keys() | twms.projections.proj_alias.keys()
    ):
        ET.SubElement(parent_layer, "SRS").text = proj

    for layer_id, layer_item in twms.config.layers.items():
        layer = ET.SubElement(parent_layer, "Layer")
        ET.SubElement(layer, "Title").text = layer_item["name"]
        ET.SubElement(layer, "Name").text = layer_id
        # Only "named layers" shall be requested by a client
        # ET.SubElement(layer, "SRS").text = layer_item.get(
        #     "proj", twms.config.default_src
        # )
        bbox = tuple(map(str, layer_item.get("bounds", twms.config.default_bbox)))
        ET.SubElement(
            layer,
            "LatLonBoundingBox",  # EPSG: 4326
            attrib={
                "minx": bbox[0],
                "miny": bbox[1],
                "maxx": bbox[2],
                "maxy": bbox[3],
            },
        )
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def maps_xml_wms130() -> str:
    """Minimal WMS GetCapabilities v1.3.0 XML implementation.

    WMS_Capabilities
        Service
            Name
            OnlineResource
        Capability
            Request
            Exception
            Layer
    See https://github.com/JOSM/josm/blob/master/src/org/openstreetmap/josm/io/imagery/WMSImagery.java

    1.1.1 vs 1.3.0
        https://docs.qgis.org/3.28/en/docs/server_manual/services/wms.html
        https://docs.geoserver.org/latest/en/user/services/wms/basics.html

    Returns:
        XML
    """
    ET.register_namespace("", "http://www.opengis.net/wms")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    # See 7.2.4 GetCapabilities response
    root = ET.Element(
        "{http://www.opengis.net/wms}WMS_Capabilities",
        attrib={"version": "1.3.0"},
    )
    service = ET.SubElement(root, "Service")
    # It shall include a Name, Title, and Online Resource URL
    ET.SubElement(service, "Name").text = "WMS"  # Shall always be "WMS"
    ET.SubElement(service, "Title").text = twms.config.wms_name
    # This is superseeded by DCPType/HTTP/Get anuway
    ET.SubElement(
        service,
        "OnlineResource",
        attrib={"{http://www.w3.org/1999/xlink}href": twms.config.service_wms_url},
    )
    capability = ET.SubElement(root, "Capability")
    request = ET.SubElement(capability, "Request")

    getmap = ET.SubElement(request, "GetMap")
    for image_mimetype in ("image/jpeg", "image/png", "image/webp"):
        ET.SubElement(getmap, "Format").text = image_mimetype
    # Way to pass link with path to client
    ET.SubElement(
        ET.SubElement(ET.SubElement(ET.SubElement(getmap, "DCPType"), "HTTP"), "Get"),
        "OnlineResource",
        attrib={"{http://www.w3.org/1999/xlink}href": twms.config.service_wms_url},
    )

    for layer_id, layer_item in twms.config.layers.items():
        layer = ET.SubElement(capability, "Layer")
        ET.SubElement(layer, "Title").text = layer_id
        # Only "named layers" shall be requested by a client
        ET.SubElement(layer, "Name").text = layer_id  # layer_item["name"]
        # CRS="CRS:84 May be inherited from parent

        # Not sure about coordinates reprojection
        bbox = tuple(map(str, layer_item.get("bounds", twms.config.default_bbox)))
        geo_bbox = ET.SubElement(layer, "EX_GeographicBoundingBox")
        ET.SubElement(geo_bbox, "westBoundLongitude").text = bbox[0]
        ET.SubElement(geo_bbox, "eastBoundLongitude").text = bbox[2]
        ET.SubElement(geo_bbox, "southBoundLatitude").text = bbox[1]
        ET.SubElement(geo_bbox, "northBoundLatitude").text = bbox[3]
        # May be inherited from parent. May be multiple.
        ET.SubElement(layer, "CRS").text = "EPSG:4326"
        # ET.SubElement(layer, "CRS").text = layer_item.get("proj", twms.config.default_src)
        # Lower left and upper right corners in a specified CRS
        ET.SubElement(
            layer,
            "BoundingBox",
            attrib={
                "CRS": "EPSG:4326",  # WGS84, note the "CoordinateRS"
                "minx": bbox[0],
                "miny": bbox[1],
                "maxx": bbox[2],
                "maxy": bbox[3],
            },
        )
    ET.indent(root)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)
