<script lang="ts">
	import '@psst/ui/tokens.css';
	import { page } from '$app/state';
	import { t } from '#lib/i18n.ts';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();
	const language = $derived(data.language);
	// The same page in the other language.
	const other = $derived.by(() => {
		const path = page.url.pathname;
		if (language === 'en') return path === '/' ? '/zh' : `/zh${path}`;
		return path.replace(/^\/zh/, '') || '/';
	});
</script>

<a class="skip" href="#main">{t(language, 'Skip to content')}</a>
<header>
	<a class="brand" href={language === 'en' ? '/' : '/zh'}>Psst</a>
	<nav aria-label="Language">
		<a href={other} hreflang={language === 'en' ? 'zh-Hans' : 'en'} lang={language === 'en' ? 'zh-Hans' : 'en'}>
			{language === 'en' ? '中文' : 'English'}
		</a>
	</nav>
</header>

<main id="main">{@render children()}</main>

<footer>
	<p>{t(language, 'Surprising, sourced stories about places you can stand in front of.')}</p>
	<p class="small">Map data © OpenStreetMap contributors. Content version {data.version}.</p>
</footer>

<style>
	.skip {
		position: absolute;
		left: -999px;
	}
	.skip:focus {
		left: var(--s3);
		top: var(--s3);
		padding: var(--s2) var(--s3);
		background: var(--surface);
		z-index: 10;
	}
	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		max-width: 60rem;
		margin: 0 auto;
		padding: var(--s4);
	}
	.brand {
		font-size: var(--text-lg);
		font-weight: 800;
		letter-spacing: -0.02em;
		color: var(--text);
		text-decoration: none;
	}
	main {
		max-width: 60rem;
		margin: 0 auto;
		padding: 0 var(--s4) var(--s6);
	}
	footer {
		max-width: 60rem;
		margin: 0 auto;
		padding: var(--s5) var(--s4);
		border-top: 1px solid var(--line);
		color: var(--text-muted);
	}
	.small {
		font-size: var(--text-sm);
	}
	:global(h1) {
		font-size: var(--text-xl);
		line-height: 1.2;
		margin: var(--s4) 0 var(--s2);
	}
	:global(h2) {
		font-size: var(--text-lg);
		margin: var(--s5) 0 var(--s3);
	}
	:global(.muted) {
		color: var(--text-muted);
	}
</style>
