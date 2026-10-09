<script lang="ts">
	import Story from '#lib/Story.svelte';
	import Report from '#lib/Report.svelte';
	import { field, keyFactLabel, name, t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const language = $derived(data.language);
	const place = $derived(data.place);
	const title = $derived(name(language, place));
	const description = $derived(place.facts[0] ? field(language, place.facts[0], 'short') : (place.guide?.about ?? ''));
	const osm = $derived(`https://www.openstreetmap.org/?mlat=${place.lat}&mlon=${place.lon}#map=18/${place.lat}/${place.lon}`);
</script>

<svelte:head>
	<title>{title} · {data.city.name} · Psst</title>
	<meta name="description" content={description} />
	<meta property="og:title" content={title} />
	<meta property="og:description" content={description} />
	{#if place.images?.[0]}<meta property="og:image" content={`/images/${place.images[0].full.file}`} />{/if}
</svelte:head>

<p class="crumbs"><a href={link(language, `/${data.city.slug}`)}>{language === 'zh-Hans' ? (data.city.names['zh-Hans'] ?? data.city.name) : data.city.name}</a>
	{#if data.neighborhood}· {data.neighborhood}{/if}</p>
<h1>{title}</h1>
{#if place.localName && place.localName.name !== title}<p class="local" lang={place.localName.lang}>{place.localName.name}</p>{/if}
{#if place.guide}<p class="identifier">{field(language, place.guide, 'identifier')}</p>{/if}

{#if place.images?.length}
	<figure class="photo">
		<img src={`/images/${place.images[0].full.file}`} alt={place.images[0].alt} width={place.images[0].full.width}
			height={place.images[0].full.height} style:object-position={`${place.images[0].focus[0] * 100}% ${place.images[0].focus[1] * 100}%`} />
		<figcaption>
			{#if place.images[0].kind === 'historic' && place.images[0].year}{place.images[0].year}. {/if}
			{t(language, 'Photo by')} {#if place.images[0].credit.authorUrl}<a href={place.images[0].credit.authorUrl}>{place.images[0].credit.author}</a>{:else}{place.images[0].credit.author}{/if},
			{#if place.images[0].credit.licenseUrl}<a href={place.images[0].credit.licenseUrl}>{place.images[0].credit.license}</a>{:else}{place.images[0].credit.license}{/if},
			<a href={place.images[0].credit.sourceUrl}>{place.images[0].credit.source ?? 'source'}</a>
		</figcaption>
	</figure>
{/if}

<section aria-labelledby="stories">
	<h2 id="stories">{t(language, 'Stories')}</h2>
	{#each place.facts as story (story.id)}
		<Story {story} {language} />
		<Report itemId={story.id} {language} />
	{/each}
</section>

{#if place.guide}
	<section aria-labelledby="guide">
		<h2 id="guide">{t(language, 'Guide')}</h2>
		<p>{field(language, place.guide, 'about')}</p>
		{#if place.guide.keyFacts.length}
			<dl class="facts">
				{#each place.guide.keyFacts as fact (fact.property)}<dt>{keyFactLabel(language, fact)}</dt><dd>{fact.value}</dd>{/each}
			</dl>
		{/if}
		<details>
			<summary>{t(language, 'Sources')} ({place.guide.sources.length})</summary>
			<ol>{#each place.guide.sources as source, i (i)}<li><a href={source.url} rel="external noopener">{source.title}</a>, {source.publisher}</li>{/each}</ol>
		</details>
	</section>
{/if}

<section aria-labelledby="where">
	<h2 id="where">{t(language, 'Map')}</h2>
	<p><a href={osm} rel="external noopener">{t(language, 'Open in OpenStreetMap')}</a>
		<span class="muted">({place.lat.toFixed(5)}, {place.lon.toFixed(5)}; {t(language, 'Location from')} {place.location.source === 'wikidata' ? 'Wikidata' : 'OpenStreetMap'})</span></p>
</section>

<style>
	.crumbs {
		margin: 0;
		color: var(--text-muted);
	}
	.local {
		margin: 0;
		font-size: var(--text-lg);
		color: var(--text-muted);
	}
	.identifier {
		font-weight: 600;
	}
	.photo {
		margin: var(--s4) 0;
	}
	.photo img {
		width: 100%;
		height: auto;
		max-height: 32rem;
		object-fit: cover;
		border-radius: var(--r3);
	}
	figcaption {
		font-size: var(--text-sm);
		color: var(--text-muted);
	}
	.facts {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--s1) var(--s4);
	}
	.facts dt {
		color: var(--text-muted);
		text-transform: capitalize;
	}
	.facts dd {
		margin: 0;
	}
</style>
