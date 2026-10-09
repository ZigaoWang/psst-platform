import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url }) => {
	const cities = await sql`
		SELECT c.slug, c.name, ST_XMin(a.geom) AS west, ST_YMin(a.geom) AS south, ST_XMax(a.geom) AS east,
		       ST_YMax(a.geom) AS north
		FROM psst.cities c JOIN psst.areas a ON a.id = c.id ORDER BY c.research_order`;
	const slug = url.searchParams.get('city') ?? (cities[0]?.slug as string | undefined) ?? '';
	return { cities, city: cities.find((c) => c.slug === slug) ?? null };
};
