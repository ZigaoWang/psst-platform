<script lang="ts">
	import { field, name, t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const language = $derived(data.language);
	const cityName = $derived(language === 'zh-Hans' ? (data.city.names['zh-Hans'] ?? data.city.name) : data.city.name);
	let query = $state('');
	const shown = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (!q) return data.places;
		return data.places.filter((p) => [p.name, p.localName?.name, ...Object.values(p.names), p.lead?.headline,
			p.neighborhood?.name].some((text) => text?.toLowerCase().includes(q)));
	});
</script>

<svelte:head>
	<title>{cityName} · Psst</title>
	<meta name="description" content={`${data.places.length} ${t(language, 'places')}: ${data.places.slice(0, 3).map((p) => p.name).join(', ')}`} />
</svelte:head>

<h1>{cityName}</h1>

{#if data.trails.length}
	<h2>{t(language, 'Trails')}</h2>
	<ul class="trails">
		{#each data.trails as trail (trail.slug)}
			<li><a href={link(language, `/${data.city.slug}/trails/${trail.slug}`)}>{field(language, trail, 'title')}</a>
				<span class="muted">{trail.stops} {t(language, 'Stops').toLowerCase()}</span></li>
		{/each}
	</ul>
{/if}

<h2>{t(language, 'Places')}</h2>
<label class="search">
	<span class="visually-hidden">{t(language, 'Search this city')}</span>
	<input type="search" bind:value={query} placeholder={t(language, 'Search this city')} />
</label>

{#if shown.length}
	<ul class="places">
		{#each shown as place (place.id)}
			<li>
				<a href={link(language, `/${data.city.slug}/${place.slug}`)} class="card">
					{#if place.thumb}<img src={`/images/${place.thumb.file}`} alt="" loading="lazy" />{/if}
					<span class="kind" style:--kind={`var(--kind-${place.kind}, var(--text-muted))`}>{t(language, place.kind)}</span>
					<span class="place-name">{name(language, place)}</span>
					{#if place.lead}
						<span class="headline">{field(language, place.lead, 'headline')}</span>
						<span class="short">{field(language, place.lead, 'short')}</span>
					{/if}
					{#if place.neighborhood}<span class="muted small">{place.neighborhood.name}</span>{/if}
				</a>
			</li>
		{/each}
	</ul>
{:else}
	<p class="muted">{t(language, 'No places match.')}</p>
{/if}

<style>
	.trails {
		padding-left: var(--s4);
	}
	.search input {
		width: 100%;
		max-width: 28rem;
		padding: var(--s2) var(--s3);
		border: 1px solid var(--line-strong);
		border-radius: var(--r2);
		background: var(--surface);
		color: var(--text);
		font: inherit;
		margin-bottom: var(--s4);
	}
	.places {
		list-style: none;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
		gap: var(--s3);
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--s1);
		height: 100%;
		padding: var(--s4);
		border: 1px solid var(--line);
		border-radius: var(--r3);
		background: var(--surface);
		color: var(--text);
		text-decoration: none;
		box-shadow: var(--shadow);
	}
	.card:hover {
		border-color: var(--line-strong);
	}
	.card img {
		width: calc(100% + 2 * var(--s4));
		margin: calc(-1 * var(--s4)) calc(-1 * var(--s4)) var(--s2);
		aspect-ratio: 16 / 9;
		object-fit: cover;
		border-radius: var(--r3) var(--r3) 0 0;
	}
	.kind {
		align-self: flex-start;
		font-size: var(--text-xs);
		font-weight: 700;
		color: var(--kind);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.place-name {
		font-weight: 700;
		font-size: var(--text-lg);
	}
	.headline {
		font-weight: 600;
	}
	.short {
		color: var(--text-muted);
		font-size: var(--text-sm);
	}
	.small {
		font-size: var(--text-sm);
	}
</style>
