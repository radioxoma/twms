import xml.etree.ElementTree as ET
from xml.dom import minidom

from twms import config, viewhtml


def maps_xml(pretty=True):
    """Create XML for JOSM 'imagery.layers.sites' property.


    XML spec https://josm.openstreetmap.de/wiki/Maps
    ELI https://github.com/osmlab/editor-layer-index
    JOSM source https://josm.openstreetmap.de/doc/org/openstreetmap/josm/data/imagery/ImageryLayerInfo.html

        Mandatory tags: <entry>: (<name>, <id>, <type> and <url>

    XML examples:
        https://josm.openstreetmap.de/maps%<?ids=>  # JOSM URL for fetching
        https://osmlab.github.io/editor-layer-index/imagery.xml
        http://www.imagico.de/map/osmim-imagicode.xml

    :rtype: str
    """
    # Green color means it already added
    # 1. category - shows as an icon
    # 2. country-code - empty for worldwide
    # 3. name
    # 4. url, but with tms prefox, min-max zoom
    imagery = ET.Element("imagery")
    for layer_id, layer in config.layers.items():
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
        if layer["proj"] == "EPSG:3857":
            ET.SubElement(entry, "url").text = viewhtml.get_tms_url(
                layer
            )  # Implement CDATA?
        else:
            # tms_handler not supports reprojection
            ET.SubElement(entry, "url").text = viewhtml.get_wms_url(
                layer
            )  # Implement CDATA?
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
            max_zoom.text = str(config.default_max_zoom)
            entry.append(
                ET.Comment("Overrided with default 'max_zoom' from current TWMS config")
            )

        if "min_zoom" in layer:
            ET.SubElement(entry, "min-zoom").text = str(layer["min_zoom"])

    imagery_xml = ET.tostring(imagery, encoding="unicode")
    if not pretty:
        return imagery_xml
    else:
        # return minidom.parseString(imagery_xml).toprettyxml(indent="  ")
        # Print node directly to skip XML header
        root = minidom.parseString(imagery_xml).childNodes[0]
        return root.toprettyxml(indent="  ")
