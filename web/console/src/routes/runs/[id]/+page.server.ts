import { error } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import { act } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const [run] = await sql`SELECT id, kind, model, operator, started_at, ended_at, notes FROM psst.runs WHERE id = ${params.id}`;
	if (!run) error(404, 'No such run');
	const [tasks, checks, revisions, leased] = await Promise.all([
		sql`SELECT type, count(*) AS n FROM psst.tasks WHERE done_by = ${run.id} GROUP BY type ORDER BY type`,
		sql`SELECT kind, verdict, count(*) AS n FROM psst.checks WHERE run_id = ${run.id} GROUP BY kind, verdict ORDER BY kind, verdict`,
		sql`SELECT r.id, r.item_id, r.number, i.state, i.type FROM psst.revisions r JOIN psst.items i ON i.id = r.item_id
		    WHERE r.created_by_run = ${run.id} ORDER BY r.created_at DESC LIMIT 100`,
		sql`SELECT id, type, leased_until FROM psst.tasks WHERE leased_by = ${run.id} AND state = 'leased'`
	]);
	return { run, tasks, checks, revisions, leased };
};

export const actions: Actions = {
	end: (event) => act(event, (s) => sql`SELECT psst.console_end_run(${s}, ${event.params.id})`,
		'Run ended; its leased tasks are back in the queue.')
};
