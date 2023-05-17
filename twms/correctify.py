import os

from twms import config, projections


def distance(z, x, y, g):
    return ((z - y) ** 2 + (x - g) ** 2) ** (0.5)


def rectify(layer, point):
    corrfile = config.tiles_cache + layer.get("prefix", "") + "/rectify.txt"
    srs = layer["proj"]
    if not os.path.exists(corrfile):
        return point
    with open(corrfile) as f:
        corr = f.read()
    lons, lats = point
    loni, lati, lona, lata = projections.projs[projections.proj_alias.get(srs, srs)][
        "bounds"
    ]
    if (lons is loni and lats is lati) or (lons is lona and lats is lata):
        return point
    # print(pickle.dumps(coefs[layer]), file=sys.stderr)
    #    sys.stderr.flush()
    lonaz, loniz, lataz, latiz = lona, loni, lata, lati
    maxdist = 1.80
    for line in corr:
        d, c, b, a, user, ts = line.split()
        d, c, b, a = (float(d), float(c), float(b), float(a))
        # for d,c,b,a in coefs[layer]:
        # print(a,b, distance(lons, lats, b, a), file=sys.stderr)
        if distance(b, a, lons, lats) < maxdist:
            if a > lats:
                if distance(a, b, lats, lons) <= distance(lata, lona, lats, lons):
                    lata = a
                    lataz = c
            if a < lats:
                if distance(a, b, lats, lons) <= distance(lati, loni, lats, lons):
                    lati = a
                    latiz = c
            if b > lons:
                if distance(a, b, lats, lons) <= distance(lata, lona, lats, lons):
                    lona = b
                    lonaz = d
            if b < lons:
                if distance(a, b, lats, lons) <= distance(lati, loni, lats, lons):
                    loni = b
                    loniz = d
    #    print(loni, lati, lona, lata, distance(loni, lati, lona, lata), file=sys.stderr)
    #    print("clat:", (lata-lati)/(lataz-latiz), (lona-loni)/(lonaz-loniz), file=sys.stderr)
    #    sys.stderr.flush()

    lons, lats = projections.from4326(point, srs)
    lona, lata = projections.from4326((lona, lata), srs)
    loni, lati = projections.from4326((loni, lati), srs)
    lonaz, lataz = projections.from4326((lonaz, lataz), srs)
    loniz, latiz = projections.from4326((loniz, latiz), srs)

    latn = (lats - lati) / (lata - lati)
    latn = (latn * (lataz - latiz)) + latiz
    lonn = (lons - loni) / (lona - loni)
    lonn = (lonn * (lonaz - loniz)) + loniz
    return projections.to4326((lonn, latn), srs)


def r_bbox(layer, bbox):
    corrfile = config.tiles_cache + layer.get("prefix", "") + "/rectify.txt"
    srs = layer["proj"]
    if not os.path.exists(corrfile):
        return bbox
    a, b, c, d = projections.from4326(bbox, srs)
    cx, cy = (a + c) / 2, (b + d) / 2
    cx1, cy1 = projections.from4326(
        rectify(layer, projections.to4326((cx, cy), srs)), srs
    )
    a1, b1 = projections.from4326(rectify(layer, projections.to4326((a, b), srs)), srs)
    c1, d1 = projections.from4326(rectify(layer, projections.to4326((c, d), srs)), srs)

    dx, dy = (
        ((cx1 - cx) + (a1 - a) + (c1 - c)) / 3,
        ((cy1 - cy) + (b1 - b) + (d1 - d)) / 3,
    )
    return projections.to4326((a + dx, b + dy, c + dx, d + dy), srs)
