import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

const PAGE = 50;

export const load: PageServerLoad = async ({ url }) => {
	const q = url.searchParams.get('q')?.trim() ?? '';
	const city = url.searchParams.get('city') ?? '';
	const after = url.searchParams.get('after') ?? '';
	const cities = await sql`SELECT slug, name FROM psst.cities ORDER BY research_order`;
	const places = await sql`
		SELECT p.id, p.kind, p.state, p.wikidata_id, p.osm_ref,
		       (SELECT name FROM psst.place_names n WHERE n.place_id = p.id AND n.role = 'display') AS name,
		       (SELECT name FROM psst.place_names n WHERE n.place_id = p.id AND n.role = 'local') AS local_name,
		       (SELECT name FROM psst.areas a WHERE a.id = p.neighborhood_id) AS neighborhood,
		       (SELECT count(*) FROM psst.items i WHERE i.place_id = p.id AND i.type = 'story' AND i.state = 'published') AS published,
		       (SELECT count(*) FROM psst.items i WHERE i.place_id = p.id AND i.type = 'story' AND i.state NOT IN ('published', 'retired')) AS in_work
		FROM psst.places p
		WHERE (${city} = '' OR p.city_id = (SELECT id FROM psst.cities WHERE slug = ${city}))
		  AND (${q} = '' OR p.id = ${q} OR p.wikidata_id = ${q} OR p.osm_ref = ${q} OR EXISTS (
		       SELECT 1 FROM psst.place_names n WHERE n.place_id = p.id AND lower(n.name) LIKE '%' || lower(${q}) || '%'))
		  AND (${after} = '' OR p.id > ${after})
		ORDER BY p.id LIMIT ${PAGE + 1}`;
	const more = places.length > PAGE;
	const shown = places.slice(0, PAGE);
	const params = new URLSearchParams({ q, city });
	return {
		q, city, cities, places: shown,
		next: more ? `?${params}&after=${shown.at(-1)?.id}` : null,
		first: after ? `?${params}` : null
	};
};
