from config import *
import projections


def html():
    """Available TMS layers summary.
    """
    resp = "<!doctype html>"
    resp += "<html><head><title>" + wms_name
    resp += "</title></head><body><h2>"
    resp += wms_name
    resp += "</h2><table>"
    for i in layers:
        bbox = layers[i].get(
            "data_bounding_box", projections.projs[layers[i]["proj"]]["bounds"]
        )
        resp += "<tr><td><img src=\"?layers=" + i
        resp += "&amp;bbox=%s,%s,%s,%s&amp;width=200&amp;format=image/png\" width=\"200\" /></td><td><h3>" % bbox

        resp += layers[i]["name"]
        resp += (
            "</h3><b>Bounding box:</b> " + str(bbox)
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
