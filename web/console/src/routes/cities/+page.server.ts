import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => ({
	cities: await sql`
		SELECT c.slug, c.name, c.country_code, c.local_languages,
		       (SELECT count(*) FROM psst.places p WHERE p.city_id = c.id AND p.state = 'active') AS places,
		       (SELECT count(*) FROM psst.items i WHERE i.city_id = c.id AND i.type = 'story' AND i.state = 'published')
		           AS published,
		       (SELECT count(*) FROM psst.research_cells r WHERE r.city_id = c.id AND r.state = 'researched') AS researched,
		       (SELECT count(*) FROM psst.research_cells r WHERE r.city_id = c.id) AS cells
		FROM psst.cities c ORDER BY c.research_order`
});
