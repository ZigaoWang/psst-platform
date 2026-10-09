import { fail, type RequestEvent } from '@sveltejs/kit';
import { problem } from './db.ts';

/** Runs an editor action and turns a refusal from the database into a message on the page. */
export async function act<T>(event: RequestEvent, run: (session: string) => Promise<T>, done: string) {
	const session = event.locals.session;
	if (!session) return fail(401, { error: 'Sign in again.' });
	try {
		await run(session);
		return { done };
	} catch (error) {
		return fail(400, { error: problem(error) });
	}
}

export function field(data: FormData, name: string): string {
	return String(data.get(name) ?? '').trim();
}
