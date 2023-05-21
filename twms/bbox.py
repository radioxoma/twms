from twms import projections

Bbox = tuple[float, float, float, float]
Point = tuple[float, float]
Bbox4 = tuple[Point, Point, Point, Point]


def point_is_in(bbox: Bbox, point: Point) -> bool:
    """Check whether EPSG:4326 point is in bbox."""
    # bbox = normalize(bbox)[0]
    return (
        point[0] >= bbox[0]
        and point[0] <= bbox[2]
        and point[1] >= bbox[1]
        and point[1] <= bbox[3]
    )


def bbox_is_in(bbox_outer: Bbox, bbox_to_check: Bbox, fully: bool = True) -> bool:
    """Check whether EPSG:4326 bbox is inside outer."""
    bo = normalize(bbox_outer)[0]
    bc = normalize(bbox_to_check)[0]
    if fully:
        return (bo[0] <= bc[0] and bo[2] >= bc[2]) and (
            bo[1] <= bc[1] and bo[3] >= bc[3]
        )
    else:
        if bo[0] > bc[0]:
            bo, bc = bc, bo
        if bc[0] <= bo[2]:
            if bo[1] > bc[1]:
                bo, bc = bc, bo
            return bc[1] <= bo[3]
        return False


def add(b1: Bbox, b2: Bbox) -> Bbox:
    """Return bbox containing two bboxes."""
    return min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3])


def expand_to_point(b1: Bbox, p1: Bbox4) -> Bbox:
    """Expand bbox b1 to contain p1: [(x,y),(x,y)]."""
    for p in p1:
        b1 = add(b1, (p[0], p[1], p[0], p[1]))
    return b1


def normalize(bbox) -> tuple[Bbox, bool]:
    """Normalise EPSG:4326 bbox order.

    Returns normalized bbox, and whether it was flipped on horizontal axis.
    """
    flip_h = False
    bbox = list(bbox)
    while bbox[0] < -180.0:
        bbox[0] += 360.0
        bbox[2] += 360.0
    if bbox[0] > bbox[2]:
        bbox = (bbox[0], bbox[1], bbox[2] + 360, bbox[3])
        # bbox = (bbox[2],bbox[1],bbox[0],bbox[3])
    if bbox[1] > bbox[3]:
        flip_h = True
        bbox = (bbox[0], bbox[3], bbox[2], bbox[1])

    return bbox, flip_h


def zoom_for_bbox(
    bbox: Bbox,
    size: tuple[int, int],
    layer,
    min_zoom: int = 1,
    max_zoom: int = 18,
    max_size: tuple[int, int] = (10000, 10000),
) -> int:
    """Calculate a best-fit zoom level."""
    h, w = size
    for i in range(min_zoom, max_zoom):
        cx1, cy1, cx2, cy2 = projections.tile_by_bbox(bbox, i, layer["proj"])
        if w != 0:
            if (cx2 - cx1) * 256 >= w * 0.9:
                return i
        if h != 0:
            if (cy1 - cy2) * 256 >= h * 0.9:
                return i
        if (cy1 - cy2) * 256 >= max_size[0] / 2:
            return i
        if (cx2 - cx1) * 256 >= max_size[1] / 2:
            return i
    return max_zoom
