from config import *
import projections


def html():
    """Available TMS layers summary.
    """
    resp = "<!doctype html><html>"
    resp += "<head><title>" + wms_name + "</title></head><body>"
    resp += "<h2>" + wms_name + "</h2>"
    resp += "<table>"
    for i in layers:
        bbox = layers[i].get('data_bounding_box', projections.projs[layers[i]['proj']]['bounds'])
        resp += "<tr><td><img src=\"?layers=" + i
        resp += "&amp;bbox=%s,%s,%s,%s&amp;width=200&amp;format=image/png\" width=\"200\" /></td><td>" % bbox

        if 'provider_url' in layers[i]:
            resp += "<h3><a referrerpolicy=\"no-referrer\" title=\"Visit tile provider website\" href=\"{}\">{}</a></h3>".format(layers[i]['provider_url'], layers[i]['name'])
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
        resp += f"tms:<a title=\"Import layer with JOSM remote control\" href=\"http://127.0.0.1:8111/imagery?title={layers[i]['name']}&type=tms&valid-georeference=true&url={tms_url}\">{tms_url}</a><br />"
        if layers[i]['proj'] == "EPSG:3857":
            file_uri = f"file://{tiles_cache}{layers[i]['prefix']}/z{{z}}/{{y}}/{{x}}.{layers[i].get('ext', 'jpg')}"
            resp += f"tms:<a title=\"Import layer with JOSM remote control\" href=\"http://127.0.0.1:8111/imagery?title={layers[i]['name']}&type=tms&valid-georeference=true&url={file_uri}\">{file_uri}</a>"
        resp += "</td></tr>"
    resp += "</table></body></html>"
    return resp
