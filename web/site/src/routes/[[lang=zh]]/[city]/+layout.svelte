<script lang="ts">
	// The city is the map. Search, filters, browse, and "near me" sit over it; a place opens in a panel beside the map
	// (a sheet from the bottom on a phone) at the place's own link, so the map never reloads.
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import Icon from '#lib/Icon.svelte';
	import MapView from '#lib/MapView.svelte';
	import PlaceThumb from '#lib/PlaceThumb.svelte';
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
	let browsing = $state(false);
	let tall = $state(false);

	const shown = $derived(filtered(shared.places, categories));
	const hits = $derived<Hit[]>(search(shared.places, query));
	const placeOpen = $derived(page.route.id?.endsWith('[place]') ?? false);
	const panelOpen = $derived(placeOpen || browsing);
	const selected = $derived(placeOpen ? (page.data as { place?: { id: string } }).place?.id ?? null : null);
	const touch = $derived(typeof matchMedia !== 'undefined' && matchMedia('(hover: none)').matches);

	shared.show = (list) => mapView?.show(list);

	onMount(async () => {
		try {
			const response = await fetch(link(language, `/${data.city.slug}/places.json`));
			shared.places = ((await response.json()) as Feed).places;
		} catch {
			loadFailed = true;
		}
	});

	function open(place: FeedPlace) {
		preview = null;
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
			browsing = true;
		}, () => (locating = 'failed'), { enableHighAccuracy: true, timeout: 10000 });
	}

	function close() {
		if (placeOpen) goto(link(language, `/${data.city.slug}`), { reset: false });
		else browsing = false;
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
		.bar, .handle, .close { display: none !important; }</style></noscript>
</svelte:head>

<div class="shell">
	<MapView bind:this={mapView} places={shown} bounds={data.city.bounds} {selected} hovered={shared.hovered} {panelOpen}
		onopen={open} onpreview={(p) => (preview = p)}
		onview={(list, center) => { shared.inView = list; shared.center = center; }} />

	<header class="bar">
		<a class="brand" href={link(language, '/')} aria-label="Psst">Psst</a>
		<div class="search" role="search">
			<span class="search-icon"><Icon name="search" size={16} /></span>
			<label class="visually-hidden" for="find">{t(language, 'Search places and streets')}</label>
			<input id="find" bind:this={searchInput} type="search" autocomplete="off" bind:value={query}
				placeholder={`${t(language, 'Search')} ${cityName}`} role="combobox" aria-expanded={searchOpen && hits.length > 0}
				aria-controls="hits" aria-activedescendant={hits.length ? `hit-${active}` : undefined}
				oninput={() => { searchOpen = true; active = 0; }} onfocus={() => (searchOpen = true)} onkeydown={onSearchKey}
				onblur={() => setTimeout(() => (searchOpen = false), 150)} />
			{#if searchOpen && hits.length}
				<ul id="hits" role="listbox">
					{#each hits as hit, i (hit.type + hit.label + i)}
						<li id={`hit-${i}`} role="option" aria-selected={i === active} class:active={i === active}>
							<button type="button" tabindex="-1" onmousedown={(e) => e.preventDefault()} onclick={() => choose(hit)}>
								<span class="hit-thumb">
									{#if hit.type === 'place'}<PlaceThumb kind={hit.places[0].kind} photo={hit.places[0].thumb} size={14} />
									{:else}<span class="hit-glyph"><Icon name={hit.type === 'street' ? 'street' : 'locate'} size={14} /></span>{/if}
								</span>
								<span class="hit-text">
									<span class="hit-label">{hit.label}</span>
									<span class="hit-detail">{hit.type === 'place' ? hit.detail
										: `${t(language, hit.type === 'street' ? 'Street' : 'Area')} · ${hit.detail} ${t(language, 'places')}`}</span>
								</span>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
		<nav class="tools" aria-label={t(language, 'Map tools')}>
			<button type="button" class="tool" aria-pressed={browsing} onclick={() => { browsing = !browsing; if (placeOpen) close(); }}>
				<Icon name="browse" size={16} /><span>{t(language, 'Browse')}</span>
			</button>
			<button type="button" class="tool" aria-pressed={showFilters} aria-controls="filters" onclick={() => (showFilters = !showFilters)}>
				<Icon name="filter" size={16} /><span>{t(language, 'Filter')}{#if categories.size}&nbsp;· {categories.size}{/if}</span>
			</button>
			<button type="button" class="tool" onclick={nearMe} disabled={locating === 'busy'} aria-label={t(language, 'Near me')}>
				<Icon name="locate" size={16} /><span>{locating === 'busy' ? t(language, 'Finding you') : t(language, 'Near me')}</span>
			</button>
			<a class="tool lang" href={language === 'en' ? `/zh${page.url.pathname}` : page.url.pathname.replace(/^\/zh/, '') || '/'}
				hreflang={language === 'en' ? 'zh-Hans' : 'en'}>{language === 'en' ? '中文' : 'EN'}</a>
		</nav>
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
		<a class="preview" class:docked={touch} class:photo={preview.place.thumb}
			href={link(language, `/${data.city.slug}/${preview.place.slug}`)}
			style:--x={`${preview.x}px`} style:--y={`${preview.y}px`}
			onclick={(e) => { e.preventDefault(); if (preview) open(preview.place); }}>
			<span class="preview-art"><PlaceThumb kind={preview.place.kind} photo={preview.place.thumb} size={30} /></span>
			<span class="preview-text">
				<span class="kind"><span class="dot" style:--kind={`var(--kind-${preview.place.kind})`}></span>{t(language, preview.place.kind)}</span>
				<strong>{preview.place.name}</strong>
				{#if preview.place.headline}<span class="line">{preview.place.headline}</span>
				{:else if preview.place.short}<span class="line">{preview.place.short}</span>{/if}
			</span>
		</a>
	{/if}

	<aside class="panel" class:open={panelOpen} class:tall aria-label={t(language, placeOpen ? 'Place' : 'Browse')}>
		<button type="button" class="handle" aria-expanded={tall} onclick={() => (tall = !tall)}
			aria-label={t(language, tall ? 'Show more map' : 'Show more of this place')}></button>
		{#if panelOpen}
			<button type="button" class="close" onclick={close} aria-label={t(language, 'Close')}><Icon name="close" size={18} /></button>
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
		--glass: color-mix(in srgb, var(--surface) 92%, transparent);
		--ease: cubic-bezier(0.2, 0.8, 0.2, 1);
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
		letter-spacing: -0.03em;
		color: var(--paper);
		background: var(--ink);
		padding: 0.3rem 0.8rem;
		border-radius: var(--r3);
		text-decoration: none;
		box-shadow: var(--shadow);
	}
	.search {
		position: relative;
		flex: 1 1 15rem;
		max-width: 24rem;
	}
	.search-icon {
		position: absolute;
		left: 0.85rem;
		top: 50%;
		transform: translateY(-50%);
		color: var(--text-muted);
		display: flex;
		z-index: 1;
		pointer-events: none;
	}
	.search input {
		width: 100%;
		padding: 0.6rem 0.9rem 0.6rem 2.3rem;
		border: 0;
		border-radius: 999px;
		background: var(--glass);
		backdrop-filter: blur(12px);
		color: var(--text);
		font: inherit;
		box-shadow: var(--shadow);
	}
	#hits {
		position: absolute;
		top: calc(100% + var(--s2));
		left: 0;
		right: 0;
		margin: 0;
		padding: var(--s1);
		list-style: none;
		background: var(--surface);
		border-radius: var(--r3);
		box-shadow: 0 10px 30px rgb(16 24 43 / 0.16);
		max-height: 60vh;
		overflow: auto;
		animation: rise 140ms var(--ease);
	}
	#hits button {
		display: flex;
		gap: var(--s3);
		align-items: center;
		width: 100%;
		text-align: left;
		padding: var(--s2);
		border: 0;
		border-radius: var(--r2);
		background: none;
		color: var(--text);
		font: inherit;
		cursor: pointer;
	}
	#hits li.active button {
		background: var(--surface-sunk);
	}
	.hit-thumb {
		flex: none;
		width: 2.25rem;
		height: 2.25rem;
		border-radius: var(--r2);
		overflow: hidden;
	}
	.hit-glyph {
		display: grid;
		place-items: center;
		width: 100%;
		height: 100%;
		background: var(--surface-sunk);
		color: var(--text-muted);
	}
	.hit-text {
		display: grid;
		min-width: 0;
	}
	.hit-label {
		font-weight: 600;
	}
	.hit-detail {
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
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.55rem 0.85rem;
		border: 0;
		border-radius: 999px;
		background: var(--glass);
		backdrop-filter: blur(12px);
		color: var(--text);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: 600;
		box-shadow: var(--shadow);
		cursor: pointer;
		text-decoration: none;
		transition: background 160ms var(--ease), color 160ms var(--ease);
	}
	.tool[aria-pressed='true'] {
		background: var(--ink);
		color: var(--paper);
	}
	.filters {
		position: absolute;
		top: 4.1rem;
		left: var(--s3);
		right: var(--s3);
		display: flex;
		flex-wrap: wrap;
		gap: var(--s2);
		animation: rise 160ms var(--ease);
	}
	.chip {
		color: var(--chip);
	}
	.chip.on {
		background: var(--chip);
		color: #fff;
	}
	.chip.clear {
		color: var(--text-muted);
	}
	.toast {
		position: absolute;
		bottom: var(--s5);
		left: 50%;
		transform: translateX(-50%);
		margin: 0;
		background: var(--surface);
		padding: var(--s2) var(--s4);
		border-radius: 999px;
		box-shadow: var(--shadow);
	}
	.preview {
		position: absolute;
		left: clamp(var(--s3), calc(var(--x) - 9rem), calc(100% - 19rem));
		top: calc(var(--y) + 14px);
		width: 18rem;
		display: grid;
		grid-template-columns: 4.5rem 1fr;
		gap: var(--s3);
		padding: var(--s2);
		background: var(--surface);
		color: var(--text);
		border-radius: 20px;
		box-shadow: 0 10px 30px rgb(16 24 43 / 0.2);
		text-decoration: none;
		animation: rise 150ms var(--ease);
	}
	.preview-art {
		width: 4.5rem;
		height: 4.5rem;
		border-radius: 14px;
		overflow: hidden;
	}
	.preview.photo {
		grid-template-columns: 1fr;
		padding: 0;
		overflow: hidden;
	}
	.preview.photo .preview-art {
		width: 100%;
		height: 9rem;
		border-radius: 0;
	}
	.preview.photo .preview-text {
		padding: 0 var(--s3) var(--s3);
	}
	.preview-text {
		display: grid;
		align-content: center;
		gap: 2px;
		min-width: 0;
	}
	.preview .line {
		font-size: var(--text-sm);
		color: var(--text-muted);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.preview.docked {
		left: var(--s3);
		right: var(--s3);
		top: auto;
		bottom: var(--s3);
		width: auto;
	}
	.kind {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-muted);
	}
	.dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: var(--kind);
	}
	.panel {
		position: absolute;
		top: 0;
		right: 0;
		bottom: 0;
		width: min(28rem, 100%);
		background: var(--bg);
		box-shadow: -10px 0 40px rgb(16 24 43 / 0.14);
		transform: translateX(105%);
		transition: transform 300ms var(--ease);
		overflow: auto;
		overscroll-behavior: contain;
	}
	.panel.open {
		transform: none;
	}
	.panel-body {
		padding: 0 0 var(--s7);
	}
	.handle {
		display: none;
	}
	.close {
		position: sticky;
		top: var(--s3);
		float: right;
		margin: var(--s3) var(--s3) -3rem 0;
		width: 2.25rem;
		height: 2.25rem;
		display: grid;
		place-items: center;
		border-radius: 50%;
		border: 0;
		background: var(--glass);
		backdrop-filter: blur(12px);
		color: var(--text);
		cursor: pointer;
		z-index: 2;
		box-shadow: var(--shadow);
	}
	@media (max-width: 47.99rem) {
		/* Labels leave the screen, not the buttons' names. */
		.tool span {
			position: absolute;
			width: 1px;
			height: 1px;
			overflow: hidden;
			clip: rect(0 0 0 0);
			white-space: nowrap;
		}
		.tool {
			padding: 0.6rem;
		}
		.panel {
			top: auto;
			left: 0;
			width: 100%;
			height: 58vh;
			border-radius: 22px 22px 0 0;
			box-shadow: 0 -10px 40px rgb(16 24 43 / 0.18);
			transform: translateY(105%);
			transition: transform 300ms var(--ease), height 240ms var(--ease);
		}
		.panel.open {
			transform: none;
		}
		.panel.tall {
			height: 92vh;
		}
		.handle {
			display: block;
			position: sticky;
			top: 0;
			width: 100%;
			height: 1.4rem;
			border: 0;
			background: transparent;
			cursor: pointer;
			z-index: 3;
		}
		.handle::after {
			content: '';
			display: block;
			width: 2.5rem;
			height: 0.3rem;
			margin: 0.5rem auto 0;
			border-radius: 999px;
			background: var(--line-strong);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.panel, .preview, #hits, .filters {
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
