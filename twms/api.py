import urllib.parse
import xml.etree.ElementTree as ET

import twms
import twms.config


def get_tms_url(layer) -> str:
    return f"{twms.config.service_url}tiles/{layer['prefix']}/{{z}}/{{x}}/{{y}}{layer.get('ext', twms.config.default_ext)}"


def get_wms_url(layer) -> str:
    """TWMS has somewhat like WMS-C emulation for getting tiles directly."""
    return f"{twms.config.service_url}wms/{layer['prefix']}/{{z}}/{{x}}/{{y}}{layer.get('ext', twms.config.default_ext)}"


def get_fs_url(layer) -> str:
    return f"file://{twms.config.tiles_cache}{layer['prefix']}/{{z}}/{{x}}/{{y}}{layer.get('ext', twms.config.default_ext)}"


def maps_html():
    """Available TMS layers summary."""
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
        bbox = layer.get("bounds", twms.projections.projs[layer["proj"]]["bounds"])
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
            f"<b>Projection:</b> {layer['proj']}<br />"
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

        josm_params["url"] = get_tms_url(layer)
        resp.append(
            tms_tpl.format(
                josm_params=urllib.parse.urlencode(josm_params),
                tms_uri=josm_params["url"],
            )
        )
        # Add file:// uri for tiles stored in the same projection
        if layer["proj"] == "EPSG:3857":
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


def maps_xml():
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
    for layer_id, layer in twms.config.layers.items():
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


def maps_wms(version, ref):
    content_type = "text/xml"

    if version == "1.0.0":
        req = (
            """
<?xml version="1.0" standalone="no"?>
<!-- The DTD (Document Type Definition) given here must correspond to the version number declared in the WMT_MS_Capabilities element below. -->
<!DOCTYPE WMT_MS_Capabilities SYSTEM "http://www2.demis.nl/WMS/capabilities_1_0_0.dtd"
<!ENTITY % KnownFormats " SGI | GIF | JPEG | PNG | WebCGM | SVG | GML.1
 | WMS_XML | MIME | INIMAGE | PPM | BLANK " >
<!ELEMENT SGI EMPTY> <!-- Silicon Graphics RGB Format -->

 <!-- other vendor-specific elements defined here -->
 <!ELEMENT VendorSpecificCapabilities (YMD)>
 <!ELEMENT YMD (Title, Abstract)>
 <!ATTLIST YMD required (0 | 1) "0">

 ]>

<!-- end of DOCTYPE declaration -->
<!-- The version number listed in the WMT_MS_Capabilities element here must correspond to the DTD declared above.  See the WMT specification document for how to respond when a client requests a version number not implemented by the server. -->
<WMT_MS_Capabilities version=\""""
            + str(version)
            + """">
        <Service>
                <!-- The WMT-defined name for this type of service -->
                <Name>GetMap</Name>
                <!-- Human-readable title for pick lists -->
                <Title>"""
            + twms.config.wms_name
            + """</Title>
                <!-- Narrative description providing additional information -->

                <Abstract>None</Abstract>
                <Keywords></Keywords>
                <!-- Top-level address of service or service provider.  See also onlineResource attributes of <DCPType> children. -->
                <OnlineResource>"""
            + ref
            + """</OnlineResource>
                <!-- Fees or access constraints imposed. -->
                <Fees>none</Fees>
                <AccessConstraints>none</AccessConstraints>

        </Service>
        <Capability>
                <Request>
                        <Map>
                                <Format>
                                        <GIF/>
                                        <JPEG/>
                                        <PNG/>
                                        <BMP/>

                                </Format>
                                <DCPType>
                                        <HTTP>
                                                <!-- The URL here for HTTP GET requests includes only the prefix before the query string.-->
                                                <Get onlineResource=\""""
            + ref
            + """?"/>
                                        </HTTP>
                                </DCPType>
                        </Map>
                        <Capabilities>

                                <Format>
                                        <WMS_XML/>
                                </Format>
                                <DCPType>
                                        <HTTP>
                                                <!-- The URL here for HTTP GET requests includes only the prefix before the query string.-->
                                                <Get onlineResource=\""""
            + ref
            + """?"/>
                                        </HTTP>
                                </DCPType>

                        </Capabilities>
                </Request>
                <Exception>
                        <Format>
                                <WMS_XML/>
                                <INIMAGE/>
                                <BLANK/>

                        </Format>
                </Exception>
                <Layer>
                        <Title>"""
            + twms.config.wms_name
            + """</Title>
                        <Abstract/>"""
        )
        pset = set(twms.projections.projs.keys())
        pset = pset.union(set(twms.projections.proj_alias.keys()))
        for proj in pset:
            req += "<SRS>%s</SRS>" % proj
        req += """<LatLonBoundingBox minx="-180" miny="-85.0511287798" maxx="180" maxy="85.0511287798"/>
                        <BoundingBox SRS="EPSG:4326" minx="-184" miny="85.0511287798" maxx="180" maxy="85.0511287798"/>
"""

        lala = """<Layer queryable="1">
                                <Name>%s</Name>
                                <Title>%s</Title>
                                <BoundingBox SRS="EPSG:4326" minx="%s" miny="%s" maxx="%s" maxy="%s"/>
                                <ScaleHint min="0" max="124000"/>
                        </Layer>"""
        for i in twms.config.layers.keys():
            b = twms.config.layers[i].get("bbox", twms.config.default_bbox)
            req += lala % (i, twms.config.layers[i]["name"], b[0], b[1], b[2], b[3])

        req += """          </Layer>
        </Capability>
</WMT_MS_Capabilities>"""

    else:
        content_type = "application/vnd.ogc.wms_xml"
        req = (
            """<?xml version="1.0"?>
<!DOCTYPE WMT_MS_Capabilities SYSTEM "http://www2.demis.nl/WMS/capabilities_1_1_1.dtd" [
 <!-- Vendor-specific elements are defined here if needed. -->
 <!-- If not needed, just leave this EMPTY declaration.  Do not
  delete the declaration entirely. -->
 <!ELEMENT VendorSpecificCapabilities EMPTY>
 ]>
<WMT_MS_Capabilities version=\""""
            + str(version)
            + """">
        <!-- Service Metadata -->
        <Service>
                <!-- The WMT-defined name for this type of service -->
                <Name>twms</Name>
                <!-- Human-readable title for pick lists -->
                <Title>"""
            + twms.config.wms_name
            + """</Title>
                <!-- Narrative description providing additional information -->
                <Abstract>None</Abstract>
                <!-- Top-level web address of service or service provider.  See also OnlineResource
  elements under <DCPType>. -->
                <OnlineResource xmlns:xlink="http://www.w3.org/1999/xlink" xlink:type="simple" xlink:href=\""""
            + ref
            + """"/>
                <!-- Contact information -->
                <ContactInformation>
                        <ContactPersonPrimary>
                                <ContactPerson>"""
            + twms.config.contact_person["real_name"]
            + """</ContactPerson>
                                <ContactOrganization>"""
            + twms.config.contact_person["organization"]
            + """</ContactOrganization>
                        </ContactPersonPrimary>
                        <ContactElectronicMailAddress>"""
            + twms.config.contact_person["mail"]
            + """</ContactElectronicMailAddress>
                </ContactInformation>
                <!-- Fees or access constraints imposed. -->
                <Fees>none</Fees>
                <AccessConstraints>none</AccessConstraints>
        </Service>
        <Capability>
                <Request>
                        <GetCapabilities>
                                <Format>application/vnd.ogc.wms_xml</Format>
                                <DCPType>
                                        <HTTP>
                                                <Get>
                                                        <!-- The URL here for invoking GetCapabilities using HTTP GET
            is only a prefix to which a query string is appended. -->
                                                        <OnlineResource xmlns:xlink="http://www.w3.org/1999/xlink" xlink:type="simple" xlink:href=\""""
            + ref
            + """?"/>
                                                </Get>
                                        </HTTP>
                                </DCPType>
                        </GetCapabilities>
                        <GetMap>
                                <Format>image/png</Format>
                                <Format>image/jpeg</Format>
                                <Format>image/gif</Format>
                                <Format>image/bmp</Format>
                                <DCPType>
                                        <HTTP>
                                                <Get>
                                                        <!-- The URL here for invoking GetCapabilities using HTTP GET
            is only a prefix to which a query string is appended. -->
                                                        <OnlineResource xmlns:xlink="http://www.w3.org/1999/xlink" xlink:type="simple" xlink:href=\""""
            + ref
            + """?"/>
                                                </Get>
                                        </HTTP>
                                </DCPType>
                        </GetMap>
                </Request>
                <Exception>
                        <Format>application/vnd.ogc.se_inimage</Format>
                        <Format>application/vnd.ogc.se_blank</Format>
                        <Format>application/vnd.ogc.se_xml</Format>
                        <Format>text/xml</Format>
                        <Format>text/plain</Format>
                </Exception>
                <VendorSpecificCapabilities/>
                <Layer>
                        <Title>World Map</Title>"""
        )
        pset = set(twms.projections.projs.keys())
        pset = pset.union(set(twms.projections.proj_alias.keys()))
        for proj in pset:
            req += "<SRS>%s</SRS>" % proj
        req += """
                        <LatLonBoundingBox minx="-180" miny="-85.0511287798" maxx="180" maxy="85.0511287798"/>
                        <BoundingBox SRS="EPSG:4326" minx="-180" miny="-85.0511287798" maxx="180" maxy="85.0511287798"/>
"""
        lala = """
                        <Layer queryable="0" opaque="1">
                                <Name>%s</Name>
                                <Title>%s</Title>
                                <BoundingBox SRS="EPSG:4326" minx="%s" miny="%s" maxx="%s" maxy="%s"/>
                                <ScaleHint min="0" max="124000"/>
                        </Layer>
"""
        for i in twms.config.layers.keys():
            b = twms.config.layers[i].get("bbox", twms.config.default_bbox)
            req += lala % (i, twms.config.layers[i]["name"], b[0], b[1], b[2], b[3])

        req += """          </Layer>
        </Capability>
</WMT_MS_Capabilities>"""

    return content_type, req
