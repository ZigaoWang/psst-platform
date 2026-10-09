import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

const PAGE = 50;

export const load: PageServerLoad = async ({ url }) => {
	const type = url.searchParams.get('type') ?? '';
	const state = url.searchParams.get('state') ?? '';
	const after = url.searchParams.get('after') ?? '';
	const [types, stranded, tasks] = await Promise.all([
		sql`SELECT name FROM psst.task_types WHERE active ORDER BY name`,
		// Queued work no open run can take: its model has no worker running.
		sql`SELECT t.type, s.value #>> '{}' AS model, count(*) AS waiting
		    FROM psst.tasks t JOIN psst.task_types y ON y.name = t.type AND y.runner = 'worker'
		    JOIN psst.settings s ON s.key = 'routing.' || t.type
		    WHERE t.state = 'queued' AND NOT EXISTS (
		        SELECT 1 FROM psst.runs r WHERE r.kind = 'worker' AND r.ended_at IS NULL AND r.model = s.value #>> '{}')
		    GROUP BY t.type, s.value ORDER BY t.type`,
		sql`SELECT t.id, t.type, t.state, t.model, t.attempts, t.problem, t.created_at, t.leased_until, t.item_id,
		           c.name AS city
		    FROM psst.tasks t LEFT JOIN psst.cities c ON c.id = t.city_id
		    WHERE (${type} = '' OR t.type = ${type}) AND (${state} = '' OR t.state = ${state})
		      AND (${after} = '' OR t.id < ${after})
		    ORDER BY t.id DESC LIMIT ${PAGE + 1}`
	]);
	const shown = tasks.slice(0, PAGE);
	const params = new URLSearchParams({ type, state });
	return {
		type, state, types: types.map((t) => t.name as string), stranded, tasks: shown,
		next: tasks.length > PAGE ? `?${params}&after=${shown.at(-1)?.id}` : null,
		first: after ? `?${params}` : null
	};
};
