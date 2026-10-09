import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => ({
	cells: await sql`
		SELECT cell, sum(count) AS views, max(day) AS last_day FROM psst.demand
		WHERE day > current_date - 90 GROUP BY cell ORDER BY views DESC LIMIT 100`
});
