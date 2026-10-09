import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

const PAGE = 50;

export const load: PageServerLoad = async ({ url }) => {
	const type = url.searchParams.get('type') ?? '';
	const state = url.searchParams.get('state') ?? '';
	const after = url.searchParams.get('after') ?? '';
	const [types, tasks] = await Promise.all([
		sql`SELECT name FROM psst.task_types ORDER BY name`,
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
		type, state, types: types.map((t) => t.name as string), tasks: shown,
		next: tasks.length > PAGE ? `?${params}&after=${shown.at(-1)?.id}` : null,
		first: after ? `?${params}` : null
	};
};
