import { defineEnvVars } from '@sveltejs/kit/env';

export const variables = defineEnvVars({
	PSST_CONTENT_SOURCE: {
		description: 'Where the published output is read from at build time: a local directory or an https address of a v2 channel.',
		static: true
	},
	PSST_SITE_ORIGIN: {
		description: 'The public address of the site, for canonical links and the sitemap.',
		static: true,
		schema: (value) => value ?? 'https://psst-platform.67-230-170-225.sslip.io'
	}
});
