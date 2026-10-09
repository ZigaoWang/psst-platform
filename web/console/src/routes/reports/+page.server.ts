import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => ({
	reports: await sql`
		SELECT r.id, r.item_id, r.reason, r.message, r.app_version, r.created_at, i.type,
		       (SELECT name FROM psst.place_names n WHERE n.place_id = i.place_id AND n.role = 'display') AS place
		FROM psst.reports r JOIN psst.items i ON i.id = r.item_id
		WHERE r.state = 'open' ORDER BY r.created_at LIMIT 200`
});
