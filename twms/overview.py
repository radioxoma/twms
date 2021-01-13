from config import *
import projections


def html():
    """Available TMS layers summary.
    """
    resp = "<!doctype html><html><head>"
    resp += "<title>" + wms_name + "</title>"
    resp += """<style>\
    .entry {
        display: inline-block;
        vertical-align: top;
        width:256px;
        padding: 5px;
    }
    </style>
    """
    resp += f"</head><body><h2>{wms_name}</h2>"

    for i in layers:
        bbox = layers[i].get('data_bounding_box', projections.projs[layers[i]['proj']]['bounds'])
        resp += "<div class=\"entry\"><img src=\"?layers=" + i
        resp += "&amp;bbox=%s,%s,%s,%s&amp;width=200&amp;format=image/png\" width=\"200\" />" % bbox

        if 'provider_url' in layers[i]:
            resp += f"<h3><a referrerpolicy=\"no-referrer\" title=\"Visit tile provider website\" href=\"{layers[i]['provider_url']}\">{layers[i]['name']}</a></h3>"
        else:
            resp += "<h3>"+ layers[i]['name'] + "</h3>"

        resp += f"<b>Bounding box:</b> {bbox}"
        resp += f" (show on <a href=\"https://openstreetmap.org/?minlon=%s&amp;minlat=%s&amp;maxlon=%s&amp;maxlat=%s&amp;box=yes\">OSM</a>)<br />" % bbox
        resp += f"<b>Projection:</b> {layers[i]['proj']}<br />"
        resp += f"<b>WMS half-link:</b> {service_url}?layers={i}&amp;<br />"

        # Links for JOSM control. See https://josm.openstreetmap.de/wiki/Help/RemoteControlCommands#imagery
        # 127.0.0.1:8111 stands for local JOSM with remote control enabled
        # "&valid - georeference = true" to hide annoying message
        tms_url = f"{service_url}{i}/{{z}}/{{x}}/{{y}}.{layers[i].get('ext', 'jpg')}"
        resp += f"tms:<a title=\"Import layer with JOSM remote control\" href=\"http://127.0.0.1:8111/imagery?title={layers[i]['name']}&amp;type=tms&amp;valid-georeference=true&amp;url={tms_url}\">{tms_url}</a><br />"
        if layers[i]['proj'] == "EPSG:3857":
            file_uri = f"file://{tiles_cache}{layers[i]['prefix']}/{{z}}/{{y}}/{{x}}.{layers[i].get('ext', 'jpg')}"
            resp += f"tms:<a title=\"Import layer with JOSM remote control\" href=\"http://127.0.0.1:8111/imagery?title={layers[i]['name']}&amp;type=tms&amp;valid-georeference=true&amp;url={file_uri}\">{file_uri}</a>"
        resp += "</div>"

    resp += "</body></html>"
    return resp
