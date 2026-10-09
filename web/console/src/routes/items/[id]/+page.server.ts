import { error, fail } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import { act, field } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

const CONTEXT = 400;

export const load: PageServerLoad = async ({ params, url }) => {
	const [item] = await sql`
		SELECT i.*, (SELECT name FROM psst.place_names n WHERE n.place_id = i.place_id AND n.role = 'display') AS place_name
		FROM psst.items i WHERE i.id = ${params.id}`;
	if (!item) error(404, 'No such item');
	const revisions = await sql`
		SELECT r.id, r.number, r.created_at, r.reason, r.rulebook, r.created_by_run, r.translation_of, ru.model
		FROM psst.revisions r JOIN psst.runs ru ON ru.id = r.created_by_run
		WHERE r.item_id = ${item.id} ORDER BY r.number DESC`;
	const shown = url.searchParams.get('revision') ?? item.current_revision;
	const [revision] = await sql`SELECT * FROM psst.revisions WHERE id = ${shown} AND item_id = ${item.id}`;
	const claims = revision ? await sql`
		SELECT c.id, c.n, c.text, c.kind, c.role, c."values",
		       coalesce(jsonb_agg(jsonb_build_object(
		           'quote', e.quote, 'matched', e.matched,
		           'before', CASE WHEN e.matched THEN substr(n.text, greatest(1, e.quote_start - ${CONTEXT} + 1),
		                                                least(${CONTEXT}, e.quote_start)) END,
		           'exact', CASE WHEN e.matched THEN substr(n.text, e.quote_start + 1, e.quote_end - e.quote_start) END,
		           'after', CASE WHEN e.matched THEN substr(n.text, e.quote_end + 1, ${CONTEXT}) END,
		           'snapshot', n.id, 'title', s.title, 'publisher', s.publisher, 'kind', s.kind, 'url', s.url,
		           'via', n.via, 'fetched', n.fetched_at) ORDER BY e.id) FILTER (WHERE e.id IS NOT NULL), '[]') AS evidence
		FROM psst.claims c LEFT JOIN psst.evidence e ON e.claim_id = c.id
		LEFT JOIN psst.snapshots n ON n.id = e.snapshot_id LEFT JOIN psst.sources s ON s.id = n.source_id
		WHERE c.revision_id = ${revision.id} GROUP BY c.id ORDER BY c.n` : [];
	const checks = revision ? await sql`
		SELECT k.id, k.claim_id, k.kind, k.verdict, k.note, k.model, k.run_id, k.created_at, k.details
		FROM psst.checks k WHERE k.revision_id = ${revision.id} ORDER BY k.id` : [];
	const transitions = await sql`
		SELECT from_state, to_state, revision_id, run_id, reason, at FROM psst.transitions
		WHERE item_id = ${item.id} ORDER BY id DESC LIMIT 100`;
	const tasks = await sql`
		SELECT id, type, state, problem, created_at FROM psst.tasks WHERE item_id = ${item.id}
		ORDER BY created_at DESC LIMIT 50`;
	const translations = await sql`SELECT id, language, state FROM psst.items WHERE translates = ${item.id}`;
	return { item, revisions, revision, claims, checks, transitions, tasks, translations };
};

export const actions: Actions = {
	recheck: async (event) => {
		const reason = field(await event.request.formData(), 'reason');
		return act(event, (s) => sql`SELECT psst.console_recheck(${s}, ${event.params.id}, ${reason})`,
			'Sent back to checking. It stays live meanwhile.');
	},
	retire: async (event) => {
		const reason = field(await event.request.formData(), 'reason');
		return act(event, (s) => sql`SELECT psst.console_retire(${s}, ${event.params.id}, ${reason})`, 'Retired.');
	},
	verdict: async (event) => {
		const data = await event.request.formData();
		const claim = field(data, 'claim') || null;
		const note = field(data, 'note');
		if (!note) return fail(400, { error: 'Say what you checked.' });
		return act(event, (s) => sql`SELECT psst.console_verdict(${s}, ${field(data, 'revision')}, ${claim},
			${field(data, 'verdict')}, ${note})`, 'Your verdict is recorded.');
	}
};
