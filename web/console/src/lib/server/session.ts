import type { Cookies } from '@sveltejs/kit';
import { sql } from './db.ts';

export const COOKIE = 'psst_console';

export async function editorFor(token: string | undefined) {
	if (!token) return null;
	const [row] = await sql`SELECT account_id, name FROM psst.console_session(${token})`;
	return row ? { accountId: row.account_id as string, name: row.name as string } : null;
}

export function remember(cookies: Cookies, token: string) {
	cookies.set(COOKIE, token, { path: '/admin', httpOnly: true, sameSite: 'strict', maxAge: 12 * 3600 });
}

export function forget(cookies: Cookies) {
	cookies.delete(COOKIE, { path: '/admin' });
}
