import { error } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const [place] = await sql`
		SELECT p.*, ST_Y(p.geom) AS lat, ST_X(p.geom) AS lon,
		       (SELECT name FROM psst.areas a WHERE a.id = p.city_id) AS city,
		       (SELECT name FROM psst.areas a WHERE a.id = p.district_id) AS district,
		       (SELECT name FROM psst.areas a WHERE a.id = p.neighborhood_id) AS neighborhood
		FROM psst.places p WHERE p.id = ${params.id}`;
	if (!place) error(404, 'No such place');
	const [names, items, identity] = await Promise.all([
		sql`SELECT role, lang, name, source FROM psst.place_names WHERE place_id = ${place.id} ORDER BY role, lang`,
		sql`SELECT i.id, i.type, i.state, i.language, i.position, r.body, r.number,
		           (i.published_revision IS NOT NULL) AS live
		    FROM psst.items i LEFT JOIN psst.revisions r ON r.id = i.current_revision
		    WHERE i.place_id = ${place.id} ORDER BY i.type, i.position, i.id`,
		sql`SELECT legacy_id, kind FROM psst.place_identity WHERE place_id = ${place.id} ORDER BY legacy_id`
	]);
	return { place, names, items, identity };
};
