import { sql } from '#lib/server/db.ts';
import { act, field } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [next, held, publications, requests] = await Promise.all([
		sql`SELECT c.name AS city, p.type, count(*) FILTER (WHERE p.is_new) AS new, count(*) AS total
		    FROM psst.publishable p JOIN psst.cities c ON c.id = p.city_id GROUP BY c.name, c.research_order, p.type
		    ORDER BY c.research_order, p.type`,
		sql`SELECT h.reason, h.type, c.name AS city, count(*) AS n FROM psst.held_back h JOIN psst.cities c ON c.id = h.city_id
		    GROUP BY h.reason, h.type, c.name ORDER BY c.name, h.type`,
		sql`SELECT id, content_version, state, counts, changes, held, checks, created_at, settled_at, notes
		    FROM psst.publications ORDER BY created_at DESC LIMIT 30`,
		sql`SELECT id, type, state, input, result, created_at, done_at FROM psst.tasks
		    WHERE type IN ('publish', 'rollback') ORDER BY created_at DESC LIMIT 10`
	]);
	return { next, held, publications, requests };
};

function request(type: 'publish' | 'rollback', input: (data: FormData) => object, done: string) {
	return async (event: Parameters<Actions[string]>[0]) => {
		const data = await event.request.formData();
		return act(event, (s) => sql`SELECT psst.console_request(${s}, ${type}, ${sql.json(input(data) as never)})`, done);
	};
}

export const actions: Actions = {
	check: request('publish', () => ({ only_staging: true }), 'A check of staging is queued; it runs within a minute.'),
	publish: request('publish', (d) => ({ allow_shrink: field(d, 'allow_shrink') || null }),
		'A publish is queued; it runs within a minute.'),
	rollback: request('rollback', () => ({}), 'A rollback is queued; it runs within a minute.')
};
