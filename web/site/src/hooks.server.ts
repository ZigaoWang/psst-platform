import type { Handle } from '@sveltejs/kit/hooks';

// The page's language, for <html lang>.
export const handle: Handle = ({ event, resolve }) =>
	resolve(event, {
		transformPageChunk: ({ html }) =>
			html.replace('%sveltekit.lang%', event.url.pathname === '/zh' || event.url.pathname.startsWith('/zh/') ? 'zh-Hans' : 'en')
	});
