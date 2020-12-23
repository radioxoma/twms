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
        bbox = layers[i].get(
            "data_bounding_box", projections.projs[layers[i]["proj"]]["bounds"]
        )
        resp += "<tr><td><img src=\"?layers=" + i
        resp += "&amp;bbox=%s,%s,%s,%s&amp;width=200&amp;format=image/png\" width=\"200\" /></td><td>" % bbox

        if 'provider_url' in layers[i]:
            resp += "<h3><a href=\"{}\">{}</a></h3>".format(layers[i]['provider_url'], layers[i]['name'])
        else:
            resp += "<h3>"+ layers[i]['name'] + "</h3>"

        resp += (
            "<b>Bounding box:</b> " + str(bbox)
            + ' (show on <a href="http://openstreetmap.org/?minlon=%s&amp;minlat=%s&amp;maxlon=%s&amp;maxlat=%s&amp;box=yes">OSM</a>' % bbox
            + ")<br />"
        )
        resp += "<b>Projection:</b> " + layers[i]["proj"] + "<br />"
        resp += "<b>WMS half-link:</b> " + service_url + "?layers=" + i + "&amp;<br />"
        resp += "<b>TMS URL:</b> tms:{}{}/{{z}}/{{x}}/{{y}}.{}<br />".format(service_url, i, layers[i].get("ext", "jpg"))
        if layers[i]['proj'] == "EPSG:3857":
            resp += "<b>File URI:</b> tms:file://{}{}/z{{z}}/{{y}}/{{x}}.{}".format(tiles_cache, layers[i]['prefix'], layers[i].get("ext", "jpg"))
        resp += "</td></tr>"
    resp += "</table></body></html>"
    return resp
