import { redirect } from '@sveltejs/kit';
import type { Handle } from '@sveltejs/kit/hooks';
import { PSST_CONSOLE_DATABASE_URL } from '$app/env/private';
import { COOKIE, editorFor } from '#lib/server/session.ts';

const OPEN = ['/admin/login'];

export const handle: Handle = async ({ event, resolve }) => {
	if (!PSST_CONSOLE_DATABASE_URL) {
		return new Response('The console has no database configured (PSST_CONSOLE_DATABASE_URL).', { status: 503 });
	}
	const token = event.cookies.get(COOKIE) ?? null;
	event.locals.editor = await editorFor(token ?? undefined);
	event.locals.session = event.locals.editor ? token : null;
	if (!event.locals.editor && !OPEN.some((path) => event.url.pathname.startsWith(path))) {
		redirect(303, `/admin/login?next=${encodeURIComponent(event.url.pathname + event.url.search)}`);
	}
	const response = await resolve(event);
	response.headers.set('Referrer-Policy', 'same-origin');
	response.headers.set('X-Content-Type-Options', 'nosniff');
	response.headers.set('Cache-Control', 'no-store');
	return response;
};
