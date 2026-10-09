import postgres from 'postgres';
import { PSST_CONSOLE_DATABASE_URL } from '$app/env/private';

// The console reads through its own role, which can read everything and change content only through the
// console functions (design.md, section 14).
export const sql = postgres(PSST_CONSOLE_DATABASE_URL, {
	max: 8,
	idle_timeout: 60,
	connection: { search_path: 'psst, public', application_name: 'psst-console' },
	types: { bigint: postgres.BigInt },
	transform: { undefined: null }
});

/** The message a database function raised, in plain words, for showing on the page. */
export function problem(error: unknown): string {
	if (error && typeof error === 'object' && 'message' in error) return String(error.message);
	return 'Something went wrong. Try again.';
}
