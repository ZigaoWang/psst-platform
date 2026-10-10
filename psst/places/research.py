"""Research by cell: setting up a city, planning its cells, and queueing the most wanted cells with their leads."""

from __future__ import annotations

import math
from typing import Any

import h3
import psycopg
from psycopg.types.json import Jsonb

from psst import rules

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


SWEEP_DAYS = 7  # a cell's leads are swept again for a new pass once they are this old


def priorities(conn: Connection, city: dict[str, Any]) -> list[tuple[str, int]]:
    """Open cells with their priority, highest first. The score is absolute, so cells queued at different times
    compare: nearer the city's middle scores higher, each place the previous app had in the cell counts as 1 km
    nearer, so the densest cells come first, each earlier pass costs as much as 20 km, and an area app users looked
    at while it was empty gains 1 km per view once its views pass the rulebook's minimum."""
    minimum = int(rules.load().places["demand_min_views"])
    rows = conn.execute("""
        SELECT r.cell, r.passes,
               (SELECT count(*) FROM psst.legacy_places l WHERE ST_Intersects(l.geom, r.geom)) AS known
        FROM psst.research_cells r WHERE r.city_id = %s AND r.state = 'open'""", (city["id"],)).fetchall()
    demand = {r["cell"]: int(r["n"]) for r in conn.execute(
        "SELECT cell, sum(count) AS n FROM psst.demand WHERE day > current_date - 90 GROUP BY cell")}
    middle = (city["lat"], city["lon"])
    scored = []
    for row in rows:
        views = demand.get(str(h3.cell_to_parent(row["cell"], cells.DEMAND)), 0)
        km = _distance_km(h3.cell_to_latlng(row["cell"]), middle) + 20 * row["passes"] - row["known"]
        km -= views if views >= minimum else 0
        scored.append((row["cell"], max(0, 100_000 - round(km * 100))))
    return sorted(scored, key=lambda s: -s[1])


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
    chosen = priorities(conn, city)[:count]
    problems: list[str] = []
    entries = []
    fresh = {r["cell"] for r in conn.execute(
        "SELECT cell FROM psst.research_cells WHERE cell = ANY(%s) AND swept_at > now() - make_interval(days => %s)",
        ([c for c, _ in chosen], SWEEP_DAYS))}
    for cell, priority in chosen:
        if cell not in fresh:  # a cell swept in the last week keeps its leads; a dense one is worked many passes
            found, issues = leads.sweep(conn, cell, city["country_code"])
            problems += [f"{cell}: {issue}" for issue in issues]
            conn.execute("SELECT psst.record_leads(%s, %s, %s)", (token, cell, Jsonb(found)))
            conn.commit()
        entries.append({"cell": cell, "priority": priority})
    row = conn.execute("SELECT psst.queue_research(%s, %s) AS n", (token, Jsonb(entries))).fetchone()
    conn.commit()
    return {"queued": int(row["n"]) if row else 0, "problems": problems}


def sweep_cells(conn: Connection, token: str, cell_ids: list[str]) -> dict[str, Any]:
    """Sweep leads again for cells, recording new ones and skipping what isn't a place."""
    problems: list[str] = []
    for cell in cell_ids:
        country = conn.execute("""
            SELECT c.country_code FROM psst.research_cells r JOIN psst.cities c ON c.id = r.city_id
            WHERE r.cell = %s""", (cell,)).fetchone()
        if country is None:
            raise LookupError(f"{cell} isn't a planned research cell")
        found, issues = leads.sweep(conn, cell, country["country_code"])
        problems += [f"{cell}: {issue}" for issue in issues]
        conn.execute("SELECT psst.record_leads(%s, %s, %s)", (token, cell, Jsonb(found)))
        conn.commit()
    return {"swept": len(cell_ids), "problems": problems}
