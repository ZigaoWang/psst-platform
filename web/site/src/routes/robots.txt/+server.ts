import { PSST_SITE_ORIGIN } from '$app/env/private';

export function GET() {
	const origin = PSST_SITE_ORIGIN.replace(/\/$/, '');
	return new Response(`User-agent: *\nDisallow: /admin\nDisallow: /api/\nSitemap: ${origin}/sitemap.xml\n`, {
		headers: { 'Content-Type': 'text/plain' }
	});
}

// Built once, with the rest of the site.
export const prerender = true;
