import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	PSST_CONSOLE_DATABASE_URL: {
		description: 'Connection string for the psst_platform_console role (server only).',
		// Optional while building; the server refuses every request until it is set.
		schema: (value) => value ?? ''
	}
});
