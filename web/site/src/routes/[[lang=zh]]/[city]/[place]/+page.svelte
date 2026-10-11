<script lang="ts">
	// A place in the panel: its photo, its name and what it is, the guide, its stories as cards, ways to get there or
	// pass it on, and its sources and a problem report at the end.
	import Icon from '#lib/Icon.svelte';
	import PlaceThumb from '#lib/PlaceThumb.svelte';
	import Report from '#lib/Report.svelte';
	import Story from '#lib/Story.svelte';
	import { field, keyFactLabel, name, t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import { useMap } from '#lib/mapstate.svelte.ts';
	import { onMount } from 'svelte';
	import type { PageProps } from './$types';

	// Where a photo comes from, as its credit names it.
	const SOURCES: Record<string, string> = { commons: 'Wikimedia Commons' };

	let { data }: PageProps = $props();
	const language = $derived(data.language);
	const place = $derived(data.place);
	const title = $derived(name(language, place));
	const photo = $derived(place.images?.[0] ?? null);
	const description = $derived(place.facts[0] ? field(language, place.facts[0], 'short') : (place.guide?.about ?? ''));
	const map = useMap();
	let apple = $state(false);
	let copied = $state(false);
	let canShare = $state(false);

	// Every source once, in the order the stories and guide cite them.
	const sources = $derived.by(() => {
		const seen = new Map<string, { title: string; publisher: string; url: string }>();
		for (const source of [...place.facts.flatMap((s) => s.sources), ...(place.guide?.sources ?? [])]) {
			if (!seen.has(source.url)) seen.set(source.url, source);
		}
		return [...seen.values()];
	});

	const directions = $derived(apple
		? `https://maps.apple.com/?daddr=${place.lat},${place.lon}&q=${encodeURIComponent(place.name)}`
		: `https://www.google.com/maps/dir/?api=1&destination=${place.lat},${place.lon}`);

	onMount(() => {
		apple = /iPhone|iPad|Macintosh/.test(navigator.userAgent);
		canShare = typeof navigator.share === 'function';
	});

	function lookHere() {
		const here = map?.places.find((p) => p.id === place.id);
		if (here) map?.show([here]);
	}

	async function share() {
		try {
			await navigator.share({ title, text: description, url: location.href });
		} catch {
			/* the reader closed the share sheet */
		}
	}

	async function copy() {
		await navigator.clipboard.writeText(location.href);
		copied = true;
		setTimeout(() => (copied = false), 1800);
	}
</script>

<svelte:head>
	<title>{title} · {data.city.name} · Psst</title>
	<meta name="description" content={description} />
	<meta property="og:title" content={title} />
	<meta property="og:description" content={description} />
	{#if photo}<meta property="og:image" content={`/images/${photo.full.file}`} />{/if}
</svelte:head>

<article class="place">
	<figure class="hero" class:empty={!photo}>
		{#if photo}
			<img src={`/images/${photo.full.file}`} alt={photo.alt} width={photo.full.width} height={photo.full.height}
				style:object-position={`${photo.focus[0] * 100}% ${photo.focus[1] * 100}%`} />
			<figcaption>
				{#if photo.kind === 'historic' && photo.year}{photo.year} · {/if}
				{#if photo.credit.authorUrl}<a href={photo.credit.authorUrl} rel="external noopener">{photo.credit.author}</a>{:else}{photo.credit.author}{/if},
				{#if photo.credit.licenseUrl}<a href={photo.credit.licenseUrl} rel="external noopener">{photo.credit.license}</a>{:else}{photo.credit.license}{/if}
				· <a href={photo.credit.sourceUrl} rel="external noopener">{SOURCES[photo.credit.source ?? 'commons'] ?? photo.credit.source}</a>
			</figcaption>
		{:else}
			<PlaceThumb kind={place.kind} size={44} />
		{/if}
	</figure>

	<header class="head">
		<p class="crumbs">
			<span class="dot" style:--kind={`var(--kind-${place.kind})`}></span>{t(language, place.kind)}
			{#if data.neighborhood}· {data.neighborhood}{/if}
		</p>
		<h1>{title}</h1>
		{#if place.localName && place.localName.name !== title}<p class="local" lang={place.localName.lang}>{place.localName.name}</p>{/if}
		{#if place.guide}<p class="identifier">{field(language, place.guide, 'identifier')}</p>{/if}
	</header>

	<nav class="actions" aria-label={t(language, 'Actions')}>
		<a class="action primary" href={directions} rel="external noopener"><Icon name="directions" size={16} />{t(language, 'Directions')}</a>
		{#if canShare}<button type="button" class="action" onclick={share}><Icon name="share" size={16} />{t(language, 'Share')}</button>{/if}
		<button type="button" class="action" onclick={copy} aria-live="polite">
			<Icon name={copied ? 'check' : 'link'} size={16} />{copied ? t(language, 'Copied') : t(language, 'Copy link')}
		</button>
	</nav>

	{#if place.guide}
		<section class="guide" aria-label={t(language, 'Guide')}>
			<p>{field(language, place.guide, 'about')}</p>
			{#if place.guide.keyFacts.length}
				<ul class="facts">
					{#each place.guide.keyFacts as fact (fact.property)}
						<li><span>{keyFactLabel(language, fact)}</span> {fact.value}</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}

	{#if place.facts.length}
		<section class="stories" aria-labelledby="stories">
			<h2 id="stories">{t(language, place.facts.length === 1 ? 'Story' : 'Stories')}</h2>
			{#each place.facts as story, i (story.id)}
				<Story {story} {language} open={i === 0 && place.facts.length === 1} onlook={lookHere} />
			{/each}
		</section>
	{/if}

	<section class="end">
		<details>
			<summary>{t(language, 'Sources')} ({sources.length})</summary>
			<ol>{#each sources as source (source.url)}<li><a href={source.url} rel="external noopener">{source.title}</a>, {source.publisher}</li>{/each}</ol>
			{#each place.facts as story (story.id)}
				{#if story.claims?.length}
					<p class="claims-title">{field(language, story, 'headline')}</p>
					<ul class="claims">{#each story.claims as claim, i (i)}<li>{claim.text}</li>{/each}</ul>
				{/if}
			{/each}
		</details>
		{#if place.facts[0]}<Report itemId={place.facts[0].id} {language} />
		{:else if place.guide}<Report itemId={place.guide.id} {language} />{/if}
		<p class="back"><a href={link(language, `/${data.city.slug}`)}>{name(language, data.city)}</a></p>
	</section>
</article>

<style>
	.hero {
		margin: 0;
		position: relative;
		height: 15rem;
		overflow: hidden;
		background: var(--surface-sunk);
	}
	.hero.empty {
		height: 7rem;
	}
	.hero img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
		animation: fade 400ms ease;
	}
	figcaption {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		padding: var(--s4) var(--s3) var(--s2);
		font-size: var(--text-xs);
		color: rgb(255 255 255 / 0.85);
		background: linear-gradient(transparent, rgb(0 0 0 / 0.55));
	}
	figcaption a {
		color: inherit;
	}
	.head {
		padding: var(--s4) var(--s4) 0;
	}
	.crumbs {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		margin: 0;
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
	h1 {
		margin: var(--s1) 0 0;
		font-size: 1.6rem;
		line-height: 1.15;
		letter-spacing: -0.02em;
	}
	.local {
		margin: 0;
		color: var(--text-muted);
	}
	.identifier {
		margin: var(--s1) 0 0;
		color: var(--text-muted);
		font-weight: 500;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s2);
		padding: var(--s4) var(--s4) 0;
	}
	.action {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.5rem 0.9rem;
		border: 0;
		border-radius: 999px;
		background: var(--surface);
		color: var(--text);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: 600;
		text-decoration: none;
		box-shadow: var(--shadow);
		cursor: pointer;
	}
	.action.primary {
		background: var(--ink);
		color: var(--paper);
	}
	.guide {
		padding: var(--s4) var(--s4) 0;
	}
	.guide p {
		margin: 0;
		line-height: 1.6;
	}
	.facts {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s1) var(--s4);
		list-style: none;
		margin: var(--s3) 0 0;
		padding: 0;
		font-size: var(--text-sm);
	}
	.facts span {
		color: var(--text-muted);
	}
	.stories {
		display: grid;
		gap: var(--s3);
		padding: var(--s5) var(--s4) 0;
	}
	h2 {
		margin: 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-muted);
	}
	.end {
		padding: var(--s5) var(--s4) 0;
		font-size: var(--text-sm);
		color: var(--text-muted);
	}
	.end summary {
		cursor: pointer;
		font-weight: 600;
		padding: var(--s2) 0;
	}
	.end ol {
		padding-left: 1.2rem;
	}
	.claims-title {
		margin: var(--s3) 0 0;
		font-weight: 600;
		color: var(--text);
	}
	.claims {
		padding-left: 1.2rem;
	}
	.back {
		margin-top: var(--s4);
	}
	@keyframes fade {
		from { opacity: 0; }
		to { opacity: 1; }
	}
</style>
