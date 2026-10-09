"""Research by cell: setting up a city, planning its cells, and queueing the most wanted cells with their leads."""

from __future__ import annotations

import math
from typing import Any

import h3
import psycopg
from psycopg.types.json import Jsonb

from . import cells, coords, leads

Connection = psycopg.Connection[dict[str, Any]]


def setup_city(conn: Connection, token: str, area_id: int, slug: str, languages: list[str], order: int,
               wikidata: str | None = None) -> int:
    """Register the city and plan every research cell that touches its boundary. `wikidata` names the city's own
    item when the boundary data doesn't link one; its coordinate is the city's middle."""
    conn.execute("SELECT psst.add_city(%s, %s, %s, %s, %s, %s)", (token, area_id, slug, languages, order, wikidata))
    box = conn.execute("""
        SELECT ST_YMin(geom) AS south, ST_XMin(geom) AS west, ST_YMax(geom) AS north, ST_XMax(geom) AS east
        FROM psst.areas WHERE id = %s""", (area_id,)).fetchone()
    assert box
    candidates = sorted(cells.covering(box["south"], box["west"], box["north"], box["east"]))
    touching = [r["cell"] for r in conn.execute("""
        SELECT c.cell FROM unnest(%s::text[], %s::text[]) AS c(cell, wkt)
        WHERE EXISTS (SELECT 1 FROM psst.area_parts p WHERE p.area_id = %s
                      AND ST_Intersects(p.geom, ST_GeomFromText(c.wkt, 4326)))""",
                                                (candidates, [cells.polygon_wkt(c) for c in candidates], area_id))]
    row = conn.execute("SELECT psst.plan_cells(%s, %s, %s) AS n",
                       (token, area_id, Jsonb([{"cell": c, "wkt": cells.polygon_wkt(c)} for c in touching]))).fetchone()
    return int(row["n"]) if row else 0


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12_742 * math.asin(math.sqrt(h))


def order(conn: Connection, city: dict[str, Any]) -> list[str]:
    """Open cells, most wanted first: where app users looked at empty maps, then the fewest passes, then cells
    nearest the city's middle, so coverage grows outward from the densest parts."""
    rows = conn.execute("SELECT cell, passes FROM psst.research_cells WHERE city_id = %s AND state = 'open'",
                        (city["id"],)).fetchall()
    demand = {r["cell"]: int(r["n"]) for r in conn.execute(
        "SELECT cell, sum(count) AS n FROM psst.demand WHERE day > current_date - 90 GROUP BY cell")}
    middle = (city["lat"], city["lon"])

    def priority(row: dict[str, Any]) -> tuple[float, ...]:
        parent = str(h3.cell_to_parent(row["cell"], cells.DEMAND))
        return (-demand.get(parent, 0), row["passes"], _distance_km(h3.cell_to_latlng(row["cell"]), middle))

    return [r["cell"] for r in sorted(rows, key=priority)]


def queue(conn: Connection, token: str, slug: str, count: int) -> dict[str, Any]:
    """Sweep leads for the next `count` cells and queue a research task for each."""
    city = conn.execute("""
        SELECT c.id, c.country_code, coalesce(c.wikidata_id, a.wikidata_id) AS wikidata_id,
               ST_Y(ST_Centroid(a.geom)) AS lat, ST_X(ST_Centroid(a.geom)) AS lon
        FROM psst.cities c JOIN psst.areas a ON a.id = c.id WHERE c.slug = %s""", (slug,)).fetchone()
    if city is None:
        raise LookupError(f"no city with the slug {slug!r}")
    # The city's middle is its own coordinate on Wikidata (Charing Cross, People's Square), not the middle of its
    # boundary, which can lie in a country park.
    if city["wikidata_id"]:
        middle = coords.wikidata([city["wikidata_id"]]).get(city["wikidata_id"]) or []
        if len(middle) == 1:
            city = {**city, "lat": middle[0][0], "lon": middle[0][1]}
    chosen = order(conn, city)[:count]
    problems: list[str] = []
    entries = []
    for rank, cell in enumerate(chosen):
        found, issues = leads.sweep(conn, cell, city["country_code"])
        problems += [f"{cell}: {issue}" for issue in issues]
        conn.execute("SELECT psst.record_leads(%s, %s, %s)", (token, cell, Jsonb(found)))
        conn.commit()
        entries.append({"cell": cell, "priority": len(chosen) - rank})
    row = conn.execute("SELECT psst.queue_research(%s, %s) AS n", (token, Jsonb(entries))).fetchone()
    conn.commit()
    return {"queued": int(row["n"]) if row else 0, "problems": problems}
