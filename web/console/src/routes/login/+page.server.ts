import { fail, redirect } from '@sveltejs/kit';
import { sql } from '#lib/server/db.ts';
import { forget, remember } from '#lib/server/session.ts';
import type { Actions, PageServerLoad } from './$types';

export const load: PageServerLoad = ({ locals }) => {
	if (locals.editor) redirect(303, '/admin');
};

function safeNext(value: string | null) {
	return value && value.startsWith('/admin') && !value.startsWith('//') ? value : '/admin';
}

export const actions: Actions = {
	signIn: async ({ request, cookies, url }) => {
		const data = await request.formData();
		const name = String(data.get('name') ?? '').trim().toLowerCase();
		const password = String(data.get('password') ?? '');
		if (!name || !password) return fail(400, { name, error: 'Enter your name and password.' });
		const [row] = await sql`SELECT psst.console_sign_in(${name}, ${password}) AS token`;
		if (!row?.token) return fail(400, { name, error: 'That name and password don’t match an account.' });
		remember(cookies, row.token);
		redirect(303, safeNext(url.searchParams.get('next')));
	},
	signOut: async ({ cookies, locals }) => {
		if (locals.session) await sql`SELECT psst.console_sign_out(${locals.session})`;
		forget(cookies);
		redirect(303, '/admin/login');
	}
};
