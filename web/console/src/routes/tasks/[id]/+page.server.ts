import { error } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import { act } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const [task] = await sql`SELECT * FROM psst.tasks WHERE id = ${params.id}`;
	if (!task) error(404, 'No such task');
	const leases = await sql`
		SELECT l.run_id, l.leased_at, r.model FROM psst.task_leases l JOIN psst.runs r ON r.id = l.run_id
		WHERE l.task_id = ${task.id} ORDER BY l.leased_at`;
	return { task, leases };
};

function control(action: 'release' | 'cancel' | 'requeue', done: string) {
	return (event: Parameters<Actions[string]>[0]) =>
		act(event, (s) => sql`SELECT psst.console_task(${s}, ${event.params.id ?? ''}, ${action})`, done);
}

export const actions: Actions = {
	release: control('release', 'Released back to the queue.'),
	cancel: control('cancel', 'Cancelled.'),
	requeue: control('requeue', 'Queued again.')
};
