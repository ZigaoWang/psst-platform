import process from 'node:process';
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	// The map library is one large chunk, loaded only on the map page.
	build: { chunkSizeWarningLimit: 1200 },
	plugins: [
		sveltekit({
			compilerOptions: {
				// Runes mode for the project's own components. Can be removed in Svelte 6.
				runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
			},
			adapter: adapter(),
			// The public origin, for CSRF checks on form actions (set when building for a server).
			paths: { base: '/admin', origin: process.env.PSST_CONSOLE_ORIGIN },
			csp: {
				mode: 'auto',
				directives: {
					'default-src': ['self'],
					'script-src': ['self'],
					'style-src': ['self', 'unsafe-inline'],
					'img-src': ['self', 'data:', 'blob:'],
					'connect-src': ['self', 'https://tiles.openfreemap.org'],
					'worker-src': ['self', 'blob:'],
					'font-src': ['self', 'https://tiles.openfreemap.org'],
					'frame-ancestors': ['none'],
					'form-action': ['self'],
					'base-uri': ['self']
				}
			}
		})
	]
});
