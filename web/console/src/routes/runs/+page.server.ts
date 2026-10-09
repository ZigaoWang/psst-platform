import { sql } from '#lib/server/db.ts';
import type { PageServerLoad } from './$types';

const PAGE = 50;

export const load: PageServerLoad = async ({ url }) => {
	const kind = url.searchParams.get('kind') ?? '';
	const after = url.searchParams.get('after') ?? '';
	const runs = await sql`
		SELECT r.id, r.kind, r.model, r.operator, r.started_at, r.ended_at, r.notes,
		       (SELECT count(*) FROM psst.tasks t WHERE t.done_by = r.id) AS done
		FROM psst.runs r
		WHERE (${kind} = '' OR r.kind = ${kind}) AND (${after} = '' OR r.id < ${after})
		ORDER BY r.id DESC LIMIT ${PAGE + 1}`;
	const shown = runs.slice(0, PAGE);
	return { kind, runs: shown, next: runs.length > PAGE ? `?kind=${kind}&after=${shown.at(-1)?.id}` : null,
		first: after ? `?kind=${kind}` : null };
};
