import { sql } from '#lib/server/db.ts';
import { act, field } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [[gate], calibrations, golden, sample, [bar]] = await Promise.all([
		sql`SELECT (value #>> '{}')::boolean AS open, (SELECT value #>> '{}' FROM psst.settings
		     WHERE key = 'gate.min_agreement') AS needed FROM psst.settings WHERE key = 'gate.open'`,
		sql`SELECT c.created_at, c.fold, c.model, c.prompt_version, c.bar_version, c.golden_version, c.marked, c.agreed
		    FROM psst.calibrations c ORDER BY c.created_at DESC LIMIT 12`,
		sql`SELECT mark, count(*)::int AS n FROM psst.golden_stories GROUP BY mark ORDER BY mark`,
		// This month's sample: ten published stories, the same all month, not yet marked.
		sql`SELECT i.id, r.body ->> 'headline' AS headline, r.body ->> 'short' AS short, r.body ->> 'long' AS long,
		           r.body ->> 'look' AS look, n.name AS place, c.name AS city
		    FROM psst.items i JOIN psst.revisions r ON r.id = i.published_revision
		    JOIN psst.cities c ON c.id = i.city_id
		    LEFT JOIN psst.place_names n ON n.place_id = i.place_id AND n.role = 'display'
		    WHERE i.type = 'story' AND i.state = 'published'
		      AND NOT EXISTS (SELECT 1 FROM psst.golden_stories g WHERE g.item_id = i.id)
		    ORDER BY md5(i.id || to_char(now(), 'YYYY-MM')) LIMIT 10`,
		sql`SELECT version, body, created_at FROM psst.current_guidance('golden_bar') WHERE version IS NOT NULL`
	]);
	return { gate, calibrations, golden, sample, bar: bar ?? null };
};

export const actions: Actions = {
	mark: async (event) => {
		const form = await event.request.formData();
		return act(event,
			(s) => sql`SELECT psst.console_mark_story(${s}, ${field(form, 'item')}, ${field(form, 'mark')}, ${field(form, 'reason')},
				${field(form, 'mark') === 'good' ? field(form, 'tier') : null})`,
			'Marked; it joins the golden set and the next calibration uses it.');
	}
};
