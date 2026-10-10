import { error } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

// Everything the harness did for one task: each model call in order, with what it was sent, what it answered, the
// tools it ran, and what the task's checks and review decided.
export const load: PageServerLoad = async ({ url }) => {
	const task = url.searchParams.get('task') ?? '';
	const [info] = await sql`SELECT id, type, state, problem, result, created_at FROM psst.tasks WHERE id = ${task}`;
	if (!info) error(404, 'No such task');
	const calls = await sql`
		SELECT h.id, h.step, h.model, h.prompt_version, h.tools_version, h.request, h.response, h.error,
		       h.input_tokens, h.cached_tokens, h.output_tokens, h.cost_usd, h.latency_ms, h.created_at,
		       coalesce((SELECT jsonb_agg(jsonb_build_object('tool', x.tool, 'input', x.input, 'output', x.output,
		                 'error', x.error) ORDER BY x.id) FROM psst.harness_tool_calls x WHERE x.call_id = h.id), '[]') AS tools
		FROM psst.harness_calls h WHERE h.task_id = ${task} ORDER BY h.id`;
	return { task: info, calls };
};
