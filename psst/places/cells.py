"""The research grid: H3 cells at resolution 7 (about 5 km² each)."""

from __future__ import annotations

import h3

RESEARCH = 7
DEMAND = 5
DENSITY = 9  # about 100 meters across: the unit of the density target (decision 27)


def cell_for(lat: float, lon: float, resolution: int = RESEARCH) -> str:
    return str(h3.latlng_to_cell(lat, lon, resolution))


def polygon_wkt(cell: str) -> str:
    ring = [(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]
    ring.append(ring[0])
    return "POLYGON((" + ", ".join(f"{x} {y}" for x, y in ring) + "))"


def geojson(cell: str) -> dict[str, object]:
    ring = [[lng, lat] for lat, lng in h3.cell_to_boundary(cell)]
    return {"type": "Polygon", "coordinates": [ring + [ring[0]]]}


def density_hexagon(cell: str, city_id: int) -> dict[str, object]:
    return {"cell": cell, "city": city_id, "parent": str(h3.cell_to_parent(cell, RESEARCH)), "geom": geojson(cell)}


def children(cell: str, resolution: int = DENSITY) -> list[str]:
    return [str(c) for c in h3.cell_to_children(cell, resolution)]


def bounds(cell: str) -> tuple[float, float, float, float]:
    """south, west, north, east."""
    points = h3.cell_to_boundary(cell)
    lats, lngs = [p[0] for p in points], [p[1] for p in points]
    return min(lats), min(lngs), max(lats), max(lngs)


def covering(south: float, west: float, north: float, east: float) -> set[str]:
    """Cells covering a bounding box, padded by one ring so cells cut by the box edge aren't lost."""
    ring = [(south, west), (south, east), (north, east), (north, west)]
    inside = set(h3.geo_to_cells(h3.LatLngPoly(ring), RESEARCH))
    return inside | {n for c in inside for n in h3.grid_disk(c, 1)}
