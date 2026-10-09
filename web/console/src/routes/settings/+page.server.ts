import { fail } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import { act, field } from '#lib/server/act.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const [settings, changes] = await Promise.all([
		sql`SELECT key, value, note, updated_at FROM psst.settings ORDER BY key`,
		sql`SELECT c.key, c.old_value, c.new_value, c.reason, c.at, r.operator
		    FROM psst.setting_changes c JOIN psst.runs r ON r.id = c.run_id ORDER BY c.id DESC LIMIT 30`
	]);
	return { settings, changes };
};

export const actions: Actions = {
	change: async (event) => {
		const data = await event.request.formData();
		let value: unknown;
		try {
			value = JSON.parse(field(data, 'value'));
		} catch {
			return fail(400, { error: 'The value must be a number, or text in double quotes.' });
		}
		return act(event, (s) => sql`SELECT psst.console_change_setting(${s}, ${field(data, 'key')},
			${sql.json(value as never)}, ${field(data, 'reason')})`, 'Setting changed.');
	}
};
