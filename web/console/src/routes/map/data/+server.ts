import { error } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import type { RequestHandler } from './$types';

// One city's research cells (colored by state) and places (with whether anything about them is live), as GeoJSON.
export const GET: RequestHandler = async ({ url }) => {
	const [city] = await sql`SELECT id FROM psst.cities WHERE slug = ${url.searchParams.get('city') ?? ''}`;
	if (!city) error(404, 'No such city');
	const [cells] = await sql`
		SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(geom)::jsonb,
		       'properties', jsonb_build_object('cell', cell, 'state', state))), '[]') AS features
		FROM psst.research_cells WHERE city_id = ${city.id}`;
	const [places] = await sql`
		SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(p.geom)::jsonb,
		       'properties', jsonb_build_object('id', p.id, 'kind', p.kind,
		           'live', EXISTS (SELECT 1 FROM psst.items i WHERE i.place_id = p.id AND i.published_revision IS NOT NULL
		                            AND i.state <> 'retired')))), '[]') AS features
		FROM psst.places p WHERE p.city_id = ${city.id} AND p.state = 'active'`;
	// Published things per resolution 9 hexagon (decision 27), with the gaps below the target.
	const [density] = await sql`
		SELECT coalesce(jsonb_agg(jsonb_build_object('type', 'Feature', 'geometry', ST_AsGeoJSON(geom)::jsonb,
		       'properties', jsonb_build_object('cell', cell, 'things', stories + guide_only, 'featured', featured))),
		       '[]') AS features,
		       count(*) AS hexagons,
		       count(*) FILTER (WHERE stories + guide_only >= (SELECT (value #>> '{}')::int FROM psst.settings
		                                                      WHERE key = 'density.target')) AS at_target
		FROM psst.hexagon_density WHERE city_id = ${city.id}`;
	return Response.json({ cells: { type: 'FeatureCollection', features: cells.features },
		places: { type: 'FeatureCollection', features: places.features },
		density: { type: 'FeatureCollection', features: density.features },
		densityStats: { hexagons: Number(density.hexagons), atTarget: Number(density.at_target) } });
};
