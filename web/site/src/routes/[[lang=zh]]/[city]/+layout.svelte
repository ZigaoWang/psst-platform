<script lang="ts">
	// The city is the map. Search, filters, and "near me" sit over it; a place opens in a panel beside the map (a sheet
	// from the bottom on a phone) at the place's own link, so the map never reloads.
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import MapView from '#lib/MapView.svelte';
	import { CATEGORIES, distanceKm, filtered, search, type Feed, type FeedPlace, type Hit } from '#lib/feed.ts';
	import { name, t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import { MapState, provideMap } from '#lib/mapstate.svelte.ts';
	import { onMount } from 'svelte';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();
	const language = $derived(data.language);
	const cityName = $derived(name(language, data.city));
	const shared = new MapState();
	provideMap(shared);

	let mapView: MapView | undefined = $state();
	let categories = $state(new Set<string>());
	let showFilters = $state(false);
	let query = $state('');
	let active = $state(0);
	let searchOpen = $state(false);
	let searchInput: HTMLInputElement | undefined = $state();
	let preview = $state<{ place: FeedPlace; x: number; y: number } | null>(null);
	let locating = $state<'idle' | 'busy' | 'failed'>('idle');
	let loadFailed = $state(false);
	let listOpen = $state(false);

	const shown = $derived(filtered(shared.places, categories));
	const hits = $derived<Hit[]>(search(shared.places, query));
	const placeOpen = $derived(page.route.id?.endsWith('[place]') ?? false);
	const panelOpen = $derived(placeOpen || listOpen);
	const selected = $derived(placeOpen ? (page.data as { place?: { id: string } }).place?.id ?? null : null);
	const touch = $derived(typeof matchMedia !== 'undefined' && matchMedia('(hover: none)').matches);

	shared.show = (list) => mapView?.show(list);

	onMount(async () => {
		try {
			const response = await fetch(link(language, `/${data.city.slug}/places.json`));
			const feed = (await response.json()) as Feed;
			shared.places = feed.places;
		} catch {
			loadFailed = true;
		}
	});

	function open(place: FeedPlace) {
		preview = null;
		listOpen = false;
		searchOpen = false;
		goto(link(language, `/${data.city.slug}/${place.slug}`), { reset: false });
	}

	function choose(hit: Hit) {
		query = '';
		searchOpen = false;
		if (hit.type === 'place') open(hit.places[0]);
		else mapView?.show(hit.places);
	}

	function onSearchKey(event: KeyboardEvent) {
		if (event.key === 'ArrowDown') { active = Math.min(active + 1, hits.length - 1); event.preventDefault(); }
		else if (event.key === 'ArrowUp') { active = Math.max(active - 1, 0); event.preventDefault(); }
		else if (event.key === 'Enter' && hits[active]) { choose(hits[active]); event.preventDefault(); }
		else if (event.key === 'Escape') { query = ''; searchOpen = false; }
	}

	function toggle(category: string) {
		const next = new Set(categories);
		if (next.has(category)) next.delete(category);
		else next.add(category);
		categories = next;
	}

	function nearMe() {
		if (!navigator.geolocation) { locating = 'failed'; return; }
		locating = 'busy';
		navigator.geolocation.getCurrentPosition((position) => {
			locating = 'idle';
			const here = { lat: position.coords.latitude, lon: position.coords.longitude };
			const nearest = [...shown].sort((a, b) => distanceKm(here, a) - distanceKm(here, b))[0];
			// Outside the city, go to its nearest place instead of an empty map.
			if (nearest && distanceKm(here, nearest) > 30) mapView?.show([nearest]);
			else mapView?.locate(here.lat, here.lon);
		}, () => (locating = 'failed'), { enableHighAccuracy: true, timeout: 10000 });
	}

	function close() {
		listOpen = false;
		if (!placeOpen) return;
		goto(link(language, `/${data.city.slug}`), { reset: false });
	}

	function onKey(event: KeyboardEvent) {
		const typing = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement;
		if (event.key === '/' && !typing) { searchInput?.focus(); event.preventDefault(); }
		else if (event.key === 'Escape' && !typing) {
			if (preview) preview = null;
			else if (panelOpen) close();
		}
	}
</script>

<svelte:window onkeydown={onKey} />
<svelte:head>
	<link rel="preconnect" href="https://tiles.openfreemap.org" crossorigin="anonymous" />
	<!-- Without JavaScript there is no map: the panel becomes the page. -->
	<noscript><style>.panel { position: static !important; transform: none !important; width: auto !important;
		height: auto !important; box-shadow: none !important; } .shell { position: static !important; }
		.bar, .tools { display: none !important; }</style></noscript>
</svelte:head>

<div class="shell">
	<MapView bind:this={mapView} places={shown} bounds={data.city.bounds} {selected} {panelOpen}
		onopen={open} onpreview={(p) => (preview = p)} onview={(list) => (shared.inView = list)} />

	<header class="bar">
		<a class="brand" href={link(language, '/')}>Psst</a>
		<span class="city">{cityName}</span>
		<div class="search" role="search">
			<label class="visually-hidden" for="find">{t(language, 'Search places and streets')}</label>
			<input id="find" bind:this={searchInput} type="search" autocomplete="off" bind:value={query}
				placeholder={t(language, 'Search places and streets')} role="combobox" aria-expanded={searchOpen && hits.length > 0}
				aria-controls="hits" aria-activedescendant={hits.length ? `hit-${active}` : undefined}
				oninput={() => { searchOpen = true; active = 0; }} onfocus={() => (searchOpen = true)} onkeydown={onSearchKey}
				onblur={() => setTimeout(() => (searchOpen = false), 150)} />
			{#if searchOpen && hits.length}
				<ul id="hits" role="listbox">
					{#each hits as hit, i (hit.type + hit.label + i)}
						<li id={`hit-${i}`} role="option" aria-selected={i === active} class:active={i === active}>
							<button type="button" tabindex="-1" onmousedown={(e) => e.preventDefault()} onclick={() => choose(hit)}>
								<span class="hit-type">{t(language, hit.type === 'place' ? 'Place' : hit.type === 'street' ? 'Street' : 'Area')}</span>
								<span class="hit-label">{hit.label}</span>
								{#if hit.detail}<span class="hit-detail">{hit.type === 'place' ? hit.detail : `${hit.detail} ${t(language, 'places')}`}</span>{/if}
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
		<div class="tools">
			<button type="button" class="tool" aria-pressed={showFilters} aria-controls="filters" onclick={() => (showFilters = !showFilters)}>
				{t(language, 'Filter')}{#if categories.size} · {categories.size}{/if}
			</button>
			<button type="button" class="tool" aria-pressed={listOpen} onclick={() => { listOpen = !listOpen; if (placeOpen) close(); }}>
				{t(language, 'List')}
			</button>
			<button type="button" class="tool" onclick={nearMe} disabled={locating === 'busy'}>
				{locating === 'busy' ? t(language, 'Finding you') : t(language, 'Near me')}
			</button>
			<a class="tool lang" href={language === 'en' ? `/zh${page.url.pathname}` : page.url.pathname.replace(/^\/zh/, '') || '/'}
				hreflang={language === 'en' ? 'zh-Hans' : 'en'}>{language === 'en' ? '中文' : 'EN'}</a>
		</div>
	</header>

	{#if showFilters}
		<div class="filters" id="filters" role="group" aria-label={t(language, 'Filter')}>
			{#each CATEGORIES as category (category)}
				<button type="button" class="chip" class:on={categories.has(category)} aria-pressed={categories.has(category)}
					style:--chip={`var(--cat-${category})`} onclick={() => toggle(category)}>{t(language, category)}</button>
			{/each}
			{#if categories.size}<button type="button" class="chip clear" onclick={() => (categories = new Set())}>{t(language, 'All')}</button>{/if}
		</div>
	{/if}

	{#if locating === 'failed'}<p class="toast" role="status">{t(language, 'Your location isn’t available.')}</p>{/if}
	{#if loadFailed}<p class="toast" role="status">{t(language, 'The map couldn’t load its places. Try again later.')}</p>{/if}

	{#if preview}
		<a class="preview" class:docked={touch} href={link(language, `/${data.city.slug}/${preview.place.slug}`)}
			style:--x={`${preview.x}px`} style:--y={`${preview.y}px`}
			onclick={(e) => { e.preventDefault(); if (preview) open(preview.place); }}>
			{#if preview.place.thumb}<img src={`/images/${preview.place.thumb}`} alt="" />{/if}
			<span class="kind" style:--kind={`var(--kind-${preview.place.kind})`}>{t(language, preview.place.kind)}</span>
			<strong>{preview.place.headline ?? preview.place.name}</strong>
			{#if preview.place.headline}<span class="muted">{preview.place.name}</span>
			{:else if preview.place.short}<span class="muted">{preview.place.short}</span>{/if}
		</a>
	{/if}

	<aside class="panel" class:open={panelOpen} aria-label={t(language, placeOpen ? 'Place' : 'Places here')}>
		{#if panelOpen}
			<button type="button" class="close" onclick={close} aria-label={t(language, 'Close')}>×</button>
		{/if}
		<div class="panel-body">{@render children()}</div>
	</aside>
</div>

<style>
	.shell {
		position: fixed;
		inset: 0;
		overflow: hidden;
		--cat-pop: #c0185f; --cat-hidden: #08766c; --cat-name: #1d5fc4; --cat-quirk: #6e6100;
		--cat-people: #3f6b12; --cat-history: #8a5a1c; --cat-design: #b2440e; --cat-engineering: #4b5663;
	}
	@media (prefers-color-scheme: dark) {
		.shell {
			--cat-pop: #ff6fa3; --cat-hidden: #4fd1c0; --cat-name: #74a7ff; --cat-quirk: #d9c24a;
			--cat-people: #9bd65a; --cat-history: #e0a65a; --cat-design: #ff8f5a; --cat-engineering: #a8b3c0;
		}
	}
	.bar {
		position: absolute;
		top: var(--s3);
		left: var(--s3);
		right: var(--s3);
		display: flex;
		align-items: center;
		gap: var(--s2);
		flex-wrap: wrap;
		pointer-events: none;
	}
	.bar > * {
		pointer-events: auto;
	}
	.brand {
		font-weight: 800;
		font-size: var(--text-lg);
		letter-spacing: -0.02em;
		color: var(--paper);
		background: var(--ink);
		padding: var(--s1) var(--s3);
		border-radius: var(--r2);
		text-decoration: none;
	}
	.city {
		font-weight: 700;
		background: var(--surface);
		padding: var(--s1) var(--s3);
		border-radius: var(--r2);
		box-shadow: var(--shadow);
	}
	.search {
		position: relative;
		flex: 1 1 16rem;
		max-width: 26rem;
	}
	.search input {
		width: 100%;
		padding: var(--s2) var(--s3);
		border: 1px solid var(--line);
		border-radius: var(--r2);
		background: var(--surface);
		color: var(--text);
		font: inherit;
		box-shadow: var(--shadow);
	}
	#hits {
		position: absolute;
		top: calc(100% + var(--s1));
		left: 0;
		right: 0;
		margin: 0;
		padding: var(--s1);
		list-style: none;
		background: var(--surface);
		border-radius: var(--r2);
		box-shadow: var(--shadow);
		max-height: 60vh;
		overflow: auto;
	}
	#hits button {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0 var(--s2);
		width: 100%;
		text-align: left;
		padding: var(--s2);
		border: 0;
		border-radius: var(--r1);
		background: none;
		color: var(--text);
		font: inherit;
		cursor: pointer;
	}
	#hits li.active button {
		background: var(--surface-sunk);
	}
	.hit-type {
		font-size: var(--text-xs);
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding-top: 2px;
	}
	.hit-detail {
		grid-column: 2;
		font-size: var(--text-sm);
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.tools {
		display: flex;
		gap: var(--s2);
	}
	.tool, .chip {
		padding: var(--s2) var(--s3);
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--surface);
		color: var(--text);
		font: inherit;
		font-size: var(--text-sm);
		box-shadow: var(--shadow);
		cursor: pointer;
		text-decoration: none;
	}
	.tool[aria-pressed='true'] {
		background: var(--ink);
		color: var(--paper);
	}
	.filters {
		position: absolute;
		top: 4.25rem;
		left: var(--s3);
		right: var(--s3);
		display: flex;
		flex-wrap: wrap;
		gap: var(--s2);
	}
	.chip {
		color: var(--chip);
		font-weight: 600;
	}
	.chip.on {
		background: var(--chip);
		color: #fff;
		border-color: var(--chip);
	}
	.chip.clear {
		color: var(--text-muted);
		font-weight: 400;
	}
	.toast {
		position: absolute;
		bottom: var(--s5);
		left: 50%;
		transform: translateX(-50%);
		margin: 0;
		background: var(--surface);
		padding: var(--s2) var(--s4);
		border-radius: var(--r2);
		box-shadow: var(--shadow);
	}
	.preview {
		position: absolute;
		left: clamp(var(--s3), calc(var(--x) - 8rem), calc(100% - 17rem));
		top: calc(var(--y) + 16px);
		width: 16rem;
		display: grid;
		gap: var(--s1);
		padding: var(--s3);
		background: var(--surface);
		color: var(--text);
		border-radius: var(--r3);
		box-shadow: 0 6px 24px rgb(16 24 43 / 0.18);
		text-decoration: none;
		animation: rise 140ms ease-out;
	}
	.preview.docked {
		left: var(--s3);
		right: var(--s3);
		top: auto;
		bottom: var(--s3);
		width: auto;
	}
	.preview img {
		width: 100%;
		height: 7rem;
		object-fit: cover;
		border-radius: var(--r2);
	}
	.kind {
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--kind);
	}
	.muted {
		color: var(--text-muted);
		font-size: var(--text-sm);
	}
	.panel {
		position: absolute;
		top: 0;
		right: 0;
		bottom: 0;
		width: min(28rem, 100%);
		background: var(--bg);
		box-shadow: -8px 0 32px rgb(16 24 43 / 0.16);
		transform: translateX(105%);
		transition: transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1);
		overflow: auto;
		overscroll-behavior: contain;
	}
	.panel.open {
		transform: none;
	}
	.panel-body {
		padding: var(--s5) var(--s5) var(--s7);
	}
	.close {
		position: sticky;
		top: var(--s3);
		float: right;
		margin: var(--s3) var(--s3) 0 0;
		width: 2.25rem;
		height: 2.25rem;
		border-radius: 50%;
		border: 1px solid var(--line);
		background: var(--surface);
		color: var(--text);
		font-size: 1.4rem;
		line-height: 1;
		cursor: pointer;
		z-index: 1;
	}
	@media (max-width: 47.99rem) {
		.city {
			display: none;
		}
		.panel {
			top: auto;
			left: 0;
			width: 100%;
			height: 58vh;
			border-radius: var(--r3) var(--r3) 0 0;
			box-shadow: 0 -8px 32px rgb(16 24 43 / 0.18);
			transform: translateY(105%);
		}
		.panel.open {
			transform: none;
		}
		.panel-body {
			padding: var(--s4) var(--s4) var(--s7);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.panel, .preview {
			transition: none;
			animation: none;
		}
	}
	@keyframes rise {
		from { opacity: 0; transform: translateY(4px); }
		to { opacity: 1; transform: none; }
	}
	:global(.visually-hidden) {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}
	:global(:focus-visible) {
		outline: 3px solid var(--focus);
		outline-offset: 2px;
	}
</style>
