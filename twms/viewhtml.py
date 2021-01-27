from twms.config import *
from twms import projections


def get_tms_url(layer):
    return f"{service_url}{layer['prefix']}/{{z}}/{{x}}/{{y}}{layer.get('ext', default_ext)}"


def get_fs_url(layer):
    return f"file://{tiles_cache}{layer['prefix']}/{{z}}/{{x}}/{{y}}{layer.get('ext', default_ext)}"


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

    for layer_id, layer in layers.items():
        bbox = layer.get('data_bounding_box', projections.projs[layer['proj']]['bounds'])
        resp += "<div class=\"entry\"><img src=\"?layers=" + layer_id
        resp += "&amp;bbox=%s,%s,%s,%s&amp;width=200&amp;format=image/png\" width=\"200\" />" % bbox

        if 'provider_url' in layer:
            resp += f"<h3><a referrerpolicy=\"no-referrer\" title=\"Visit tile provider website\" href=\"{layer['provider_url']}\">{layer['name']}</a></h3>"
        else:
            resp += "<h3>"+ layer['name'] + "</h3>"

        resp += f"<b>Bounding box:</b> {bbox}"
        resp += f" (show on <a href=\"https://openstreetmap.org/?minlon=%s&amp;minlat=%s&amp;maxlon=%s&amp;maxlat=%s&amp;box=yes\">OSM</a>)<br />" % bbox
        resp += f"<b>Projection:</b> {layer['proj']}<br />"
        resp += f"<b>WMS half-link:</b> {service_url}?layers={layer_id}&amp;<br />"

        # Links for JOSM control. See https://josm.openstreetmap.de/wiki/Help/RemoteControlCommands#imagery
        # 127.0.0.1:8111 stands for local JOSM with remote control enabled
        # "&valid - georeference = true" to hide annoying message
        tms_url = get_tms_url(layer)
        resp += f"tms:<a title=\"Import layer with JOSM remote control\" href=\"http://127.0.0.1:8111/imagery?title={layer['name']}&amp;type=tms&amp;valid-georeference=true&amp;url={tms_url}\">{tms_url}</a><br />"
        if layer['proj'] == "EPSG:3857":
            file_url = get_fs_url(layer)
            resp += f"tms:<a title=\"Import layer with JOSM remote control\" href=\"http://127.0.0.1:8111/imagery?title={layer['name']}&amp;type=tms&amp;valid-georeference=true&amp;url={file_url}\">{file_url}</a>"
        resp += "</div>"

    resp += "</body></html>"
    return resp
