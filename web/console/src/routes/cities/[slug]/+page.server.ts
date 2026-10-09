import { error } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import { act } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const [city] = await sql`SELECT * FROM psst.cities WHERE slug = ${params.slug}`;
	if (!city) error(404, 'No such city');
	const [items, cells, tasks, audits] = await Promise.all([
		sql`SELECT type, state, count(*) AS n FROM psst.items WHERE city_id = ${city.id} GROUP BY type, state`,
		sql`SELECT state, count(*) AS n FROM psst.research_cells WHERE city_id = ${city.id} GROUP BY state`,
		sql`SELECT type, state, count(*) AS n FROM psst.tasks WHERE city_id = ${city.id} AND state IN ('queued', 'leased', 'failed')
		    GROUP BY type, state ORDER BY type`,
		sql`SELECT id, type, size, sample_size, errors, rate, threshold, outcome, created_at
		    FROM psst.audit_batches WHERE city_id = ${city.id} ORDER BY created_at DESC LIMIT 20`
	]);
	const [untranslated] = await sql`
		SELECT count(*) AS n FROM psst.items i
		WHERE i.city_id = ${city.id} AND i.type IN ('story', 'guide', 'trail') AND i.published_revision IS NOT NULL
		  AND i.state <> 'retired' AND NOT EXISTS (
		      SELECT 1 FROM psst.items t WHERE t.translates = i.id AND t.state <> 'retired')`;
	return { city, items, cells, tasks, audits, untranslated: untranslated.n };
};

export const actions: Actions = {
	translate: async (event) => {
		const city = event.params.slug;
		return act(event, async (session) => {
			const items = await sql`
				SELECT i.id FROM psst.items i JOIN psst.cities c ON c.id = i.city_id
				WHERE c.slug = ${city} AND i.type IN ('story', 'guide', 'trail') AND i.published_revision IS NOT NULL
				  AND i.state <> 'retired' AND NOT EXISTS (
				      SELECT 1 FROM psst.items t WHERE t.translates = i.id AND t.state <> 'retired')
				  AND NOT EXISTS (SELECT 1 FROM psst.tasks k WHERE k.type = 'translate' AND k.item_id = i.id
				                  AND k.state IN ('queued', 'leased'))
				LIMIT 500`;
			for (const item of items) {
				await sql`SELECT psst.console_queue(${session}, 'translate', NULL, NULL, ${item.id}, '{}')`;
			}
		}, 'Translation tasks queued.');
	}
};
