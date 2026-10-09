import { sql } from '#lib/server/db.ts';
import { act } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [escalations, batches, accuracy] = await Promise.all([
		sql`SELECT t.id, t.state, t.item_id, t.created_at, t.input, c.name AS city
		    FROM psst.tasks t LEFT JOIN psst.cities c ON c.id = t.city_id
		    WHERE t.type = 'escalate' AND t.state IN ('queued', 'leased', 'failed') ORDER BY t.created_at LIMIT 100`,
		sql`SELECT b.*, c.name AS city,
		           (SELECT count(*) FROM psst.tasks t WHERE t.type = 'audit' AND t.input ->> 'batch' = b.id
		              AND t.state <> 'done') AS waiting
		    FROM psst.audit_batches b JOIN psst.cities c ON c.id = b.city_id ORDER BY b.created_at DESC LIMIT 50`,
		sql`SELECT * FROM psst.model_accuracy ORDER BY kind, model`
	]);
	return { escalations, batches, accuracy };
};

export const actions: Actions = {
	plan: async (event) => {
		const force = (await event.request.formData()).get('force') === 'yes';
		return act(event, (s) => sql`SELECT psst.console_plan_audits(${s}, ${force})`, 'Audits planned.');
	}
};
