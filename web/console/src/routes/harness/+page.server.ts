import { sql } from '#lib/server/db.ts';
import { act, field } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [[money], cities, routes, bakeoff, quoting, costs, recent] = await Promise.all([
		sql`SELECT psst.harness_spend(NULL) AS spend, psst.setting('harness.budget_usd') AS budget,
		           psst.setting('harness.city_daily_usd') AS daily, psst.setting('harness.city_monthly_usd') AS monthly,
		           psst.setting('harness.credit') AS credit, psst.setting('harness.paused') AS paused,
		           psst.setting('harness.paused_cities') AS paused_cities,
		           (SELECT coalesce(sum(cost_usd), 0) FROM psst.harness_calls
		            WHERE created_at >= date_trunc('day', now())) AS today`,
		sql`SELECT c.id, c.slug, c.name,
		           (SELECT count(*)::int FROM psst.tasks t WHERE t.city_id = c.id AND t.state = 'queued') AS queued,
		           (SELECT count(*)::int FROM psst.tasks t WHERE t.city_id = c.id AND t.state = 'leased') AS leased,
		           (SELECT coalesce(sum(cost_usd), 0) FROM psst.harness_calls h WHERE h.city_id = c.id
		              AND h.created_at >= date_trunc('day', now())) AS today,
		           (SELECT coalesce(sum(cost_usd), 0) FROM psst.harness_calls h WHERE h.city_id = c.id
		              AND h.created_at >= date_trunc('month', now())) AS month,
		           (SELECT count(*)::int FROM psst.items i WHERE i.city_id = c.id AND i.state = 'published'
		              AND i.type IN ('story', 'guide')) AS published
		    FROM psst.cities c ORDER BY c.research_order`,
		sql`SELECT t.name AS type, psst.task_model(t.name, '{}') AS model FROM psst.task_types t
		    WHERE t.runner = 'worker' AND t.active ORDER BY t.name`,
		// The golden set as a test, per model: the latest calibration of each fold, for the current golden set.
		sql`SELECT model, sum(pos_agreed)::int AS published, sum(pos_marked)::int AS good,
		           sum(neg_caught)::int AS caught, sum(neg_marked)::int AS negatives,
		           sum(tier_agreed)::int AS tier_agreed, sum(tier_marked)::int AS tier_marked, max(created_at) AS at,
		           (SELECT coalesce(sum(cost_usd), 0) FROM psst.harness_calls h
		            WHERE h.step = 'calibrate' AND h.model = latest.model) AS cost
		    FROM (SELECT DISTINCT ON (model, fold) * FROM psst.calibrations
		          WHERE golden_version = psst.golden_version() AND neg_marked IS NOT NULL
		          ORDER BY model, fold, created_at DESC) latest
		    GROUP BY model ORDER BY min(pos_agreed::numeric / pos_marked) DESC`,
		sql`SELECT model, count(*)::int AS answers, sum((quotes ->> 'quotes')::int)::int AS quotes,
		           sum((quotes ->> 'exact')::int)::int AS exact, sum((quotes ->> 'repaired')::int)::int AS repaired,
		           sum((quotes ->> 'invented')::int)::int AS invented,
		           sum((quotes ->> 'unknown_snapshot')::int)::int AS unknown
		    FROM psst.harness_calls WHERE quotes IS NOT NULL GROUP BY model ORDER BY model`,
		sql`SELECT step, model, count(*)::int AS calls, sum(input_tokens)::bigint AS input,
		           sum(cached_tokens)::bigint AS cached, sum(output_tokens)::bigint AS output,
		           sum(cost_usd) AS cost, round(avg(latency_ms))::int AS latency
		    FROM psst.harness_calls GROUP BY step, model ORDER BY step, cost DESC`,
		sql`SELECT h.id, h.task_id, h.step, h.model, h.cost_usd, h.error, h.created_at,
		           (SELECT count(*)::int FROM psst.harness_tool_calls x WHERE x.call_id = h.id) AS tools
		    FROM psst.harness_calls h ORDER BY h.id DESC LIMIT 25`
	]);
	return { money, cities, routes, bakeoff, quoting, costs, recent };
};

async function setPaused(event: Parameters<Actions[string]>[0], pause: boolean) {
	const data = await event.request.formData();
	const slug = field(data, 'city');
	const [row] = await sql`SELECT psst.setting('harness.paused_cities') AS v`;
	const current = (row.v as string[]).filter((s) => s !== slug);
	const next = pause ? [...current, slug] : current;
	return act(event, (s) => sql`SELECT psst.console_change_setting(${s}, 'harness.paused_cities', ${sql.json(next)},
		${`${pause ? 'paused' : 'resumed'} ${slug} from the Harness page`})`, pause ? 'Paused.' : 'Resumed.');
}

export const actions: Actions = {
	pause: (event) => setPaused(event, true),
	resume: (event) => setPaused(event, false)
};
