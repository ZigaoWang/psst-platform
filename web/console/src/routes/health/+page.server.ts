import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	try {
		const [row] = await sql`
			SELECT now() AS now,
			       (SELECT max(done_at) FROM psst.tasks WHERE type = 'tool_check') AS last_tool_check,
			       (SELECT min(created_at) FROM psst.tasks WHERE type = 'tool_check' AND state = 'queued') AS oldest_tool_check,
			       (SELECT max(fetched_at) FROM psst.snapshots) AS last_snapshot,
			       (SELECT max(settled_at) FROM psst.publications WHERE state = 'promoted') AS last_publish,
			       (SELECT count(*) FROM psst.tasks WHERE state = 'leased' AND leased_until < now()) AS expired_leases`;
		return { database: true, status: row };
	} catch {
		return { database: false, status: null };
	}
};
