import { PSST_SITE_ORIGIN } from '$app/env/private';
import { cityEntries, placeEntries, tagEntries, trailEntries } from '#lib/server/pages.ts';

// Every page, in English with its Simplified Chinese alternate.
export async function GET() {
	const origin = PSST_SITE_ORIGIN.replace(/\/$/, '');
	const english = <T extends { lang: string | undefined }>(entries: T[]) => entries.filter((e) => e.lang === undefined);
	const paths = ['/',
		...english(await cityEntries()).map((e) => `/${e.city}`),
		...english(await placeEntries()).map((e) => `/${e.city}/${e.place}`),
		...english(await trailEntries()).map((e) => `/${e.city}/trails/${e.trail}`),
		...english(await tagEntries()).map((e) => `/tags/${e.tag}`)];
	const url = (path: string) => `  <url><loc>${origin}${path}</loc>` +
		`<xhtml:link rel="alternate" hreflang="en" href="${origin}${path}"/>` +
		`<xhtml:link rel="alternate" hreflang="zh-Hans" href="${origin}/zh${path === '/' ? '' : path}"/></url>`;
	const body = `<?xml version="1.0" encoding="UTF-8"?>\n` +
		`<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n` +
		paths.map(url).join('\n') + '\n</urlset>\n';
	return new Response(body, { headers: { 'Content-Type': 'application/xml' } });
}
