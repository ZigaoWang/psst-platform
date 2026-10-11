<script lang="ts">
	import { field, name, t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import { useMap } from '#lib/mapstate.svelte.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const language = $derived(data.language);
	const cityName = $derived(name(language, data.city));
	const map = useMap();
	const order = { featured: 0, story: 1, guide: 2 };
	// With the map running, the list follows what is in view; without it, every place is listed.
	const inView = $derived(map ? [...map.inView].sort((a, b) => order[a.tier] - order[b.tier]).slice(0, 80) : []);
</script>

<svelte:head>
	<title>{cityName} · Psst</title>
	<meta name="description" content={`${data.places.length} ${t(language, 'places')}: ${data.places.slice(0, 3).map((p) => p.name).join(', ')}`} />
</svelte:head>

<h1>{cityName}</h1>
{#if map && map.places.length}
	<p class="muted">{map.inView.length} {t(language, 'places in view')}</p>
	<ul class="places">
		{#each inView as place (place.id)}
			<li>
				<a href={link(language, `/${data.city.slug}/${place.slug}`)}>
					<span class="dot" style:--kind={`var(--kind-${place.kind})`} class:story={place.tier !== 'guide'}></span>
					<span><strong>{place.headline ?? place.name}</strong>{#if place.headline}<br /><span class="muted">{place.name}</span>{/if}</span>
				</a>
			</li>
		{/each}
	</ul>
{/if}

<noscript>
	{#if data.trails.length}
		<h2>{t(language, 'Trails')}</h2>
		<ul>{#each data.trails as trail (trail.slug)}<li><a href={link(language, `/${data.city.slug}/trails/${trail.slug}`)}>{field(language, trail, 'title')}</a></li>{/each}</ul>
	{/if}
	<h2>{t(language, 'Places')}</h2>
	<ul>{#each data.places as place (place.slug)}<li><a href={link(language, `/${data.city.slug}/${place.slug}`)}>{name(language, place)}</a></li>{/each}</ul>
</noscript>

<style>
	h1 {
		margin-top: 0;
	}
	.places {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.places a {
		display: flex;
		gap: var(--s3);
		align-items: flex-start;
		padding: var(--s2) 0;
		border-bottom: 1px solid var(--line);
		color: var(--text);
		text-decoration: none;
	}
	.dot {
		flex: none;
		width: 0.6rem;
		height: 0.6rem;
		margin-top: 0.35rem;
		border-radius: 50%;
		background: var(--kind);
	}
	.dot.story {
		width: 0.85rem;
		height: 0.85rem;
	}
</style>
