import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Runes mode for the project's own components. Can be removed in Svelte 6.
				runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
			},
			// Every page is prerendered from the published output; nothing runs on the server.
			adapter: adapter({ strict: true }),
			// Each route lists every page it has; a route with none (no trails yet) builds nothing.
			prerender: {
				entries: ['*', '/sitemap.xml', '/robots.txt'],
				handleMissingId: 'fail',
				// Photos are served beside the site from the images folder, never built into it; anything else missing fails.
				handleHttpError: ({ path, message }) => {
					if (path.startsWith('/images/')) return;
					throw new Error(message);
				},
				handleUnseenRoutes: 'ignore'
			},
			csp: {
				mode: 'hash',
				directives: {
					'default-src': ['self'],
					'script-src': ['self'],
					'style-src': ['self', 'unsafe-inline'],
					// The map: its style, tiles, fonts, and sprites come from OpenFreeMap, and MapLibre draws in a worker.
					'img-src': ['self', 'data:', 'blob:', 'https://tiles.openfreemap.org'],
					'connect-src': ['self', 'https://tiles.openfreemap.org'],
					'worker-src': ['self', 'blob:'],
					'child-src': ['blob:'],
					'base-uri': ['self'],
					'form-action': ['self'],
					'frame-ancestors': ['none']
				}
			}
		})
	]
});
