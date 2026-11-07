"""Public parcel-envelope imagery for site intake."""

import math


def parcel_extent(context, latitude, longitude):
    records = context.get("parcels", {}).get("records", [])
    points = [
        p
        for r in records
        for ring in r.get("geometry", {}).get("rings", [])
        for p in ring
    ]
    if points:
        return [
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        ]
    # A small, explicitly labeled search envelope when no parcel was returned.
    return [
        longitude - 0.0005,
        latitude - 0.0005,
        longitude + 0.0005,
        latitude + 0.0005,
    ]


def imagery_tiles(context, latitude, longitude, *, max_tiles=9):
    """Cover the full parcel envelope by reducing zoom instead of truncating tiles."""
    bbox = parcel_extent(context, latitude, longitude)

    def tile(x, y, z):
        return int((x + 180) / 360 * 2**z), int(
            (1 - math.asinh(math.tan(math.radians(y))) / math.pi) / 2 * 2**z
        )

    zoom = 19
    while True:
        x1, y1 = tile(bbox[0], bbox[3], zoom)
        x2, y2 = tile(bbox[2], bbox[1], zoom)
        if (x2 - x1 + 1) * (y2 - y1 + 1) <= max_tiles or zoom == 0:
            break
        zoom -= 1
    return zoom, [(x, y) for x in range(x1, x2 + 1) for y in range(y1, y2 + 1)], bbox
