import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [attention] = await sql`
		SELECT
			(SELECT count(*) FROM psst.tasks WHERE type = 'escalate' AND state IN ('queued', 'leased')) AS escalations,
			(SELECT count(*) FROM psst.tasks WHERE state = 'failed') AS failed_tasks,
			(SELECT count(*) FROM psst.reports WHERE state = 'open') AS open_reports,
			(SELECT count(*) FROM psst.audit_batches WHERE outcome = 'failed'
			   AND settled_at > now() - interval '14 days') AS failed_audits,
			(SELECT count(*) FROM psst.held_back) AS held_back,
			(SELECT count(*) FROM psst.tasks WHERE state = 'queued') AS queued,
			(SELECT count(*) FROM psst.tasks WHERE state = 'leased') AS leased,
			(SELECT min(created_at) FROM psst.tasks WHERE state = 'queued' AND type = 'tool_check') AS oldest_tool_check`;
	const workers = await sql`
		SELECT r.id, r.model, r.started_at, r.notes,
		       (SELECT max(leased_at) FROM psst.task_leases l WHERE l.run_id = r.id) AS last_lease,
		       (SELECT count(*) FROM psst.tasks t WHERE t.done_by = r.id) AS done
		FROM psst.runs r WHERE r.ended_at IS NULL AND r.kind = 'worker'
		ORDER BY r.started_at DESC LIMIT 50`;
	const cities = await sql`
		SELECT c.slug, c.name,
		       count(*) FILTER (WHERE i.type = 'story' AND i.state = 'published') AS published,
		       count(*) FILTER (WHERE i.type = 'story' AND i.state = 'accepted') AS accepted,
		       count(*) FILTER (WHERE i.type = 'story' AND i.state = 'checking') AS checking,
		       count(*) FILTER (WHERE i.type = 'story' AND i.state = 'draft') AS draft,
		       count(*) FILTER (WHERE i.type = 'guide' AND i.state IN ('accepted', 'published')) AS guides,
		       (SELECT count(*) FROM psst.research_cells r WHERE r.city_id = c.id) AS cells,
		       (SELECT count(*) FROM psst.research_cells r WHERE r.city_id = c.id AND r.state = 'researched') AS researched
		FROM psst.cities c LEFT JOIN psst.items i ON i.city_id = c.id
		GROUP BY c.id ORDER BY c.research_order`;
	return { attention, workers, cities };
};
