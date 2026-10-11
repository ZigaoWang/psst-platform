<script lang="ts">
	// Browse: the places in view, nearest the map's center first, each with its picture and best line. The list
	// follows the map as it moves, and hovering a card marks its pin.
	import PlaceThumb from '#lib/PlaceThumb.svelte';
	import { distanceKm } from '#lib/feed.ts';
	import { field, name, t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import { useMap } from '#lib/mapstate.svelte.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const language = $derived(data.language);
	const cityName = $derived(name(language, data.city));
	const map = useMap();
	const nearby = $derived.by(() => {
		if (!map?.center) return [];
		const center = map.center;
		return [...map.inView].sort((a, b) => distanceKm(center, a) - distanceKm(center, b)).slice(0, 60);
	});

	function distance(place: { lat: number; lon: number }): string {
		if (!map?.center) return '';
		const km = distanceKm(map.center, place);
		return km < 1 ? `${Math.round(km * 100) * 10} m` : `${km.toFixed(1)} km`;
	}
</script>

<svelte:head>
	<title>{cityName} · Psst</title>
	<meta name="description" content={`${data.places.length} ${t(language, 'places')}: ${data.places.slice(0, 3).map((p) => p.name).join(', ')}`} />
</svelte:head>

<div class="browse">
	<h1>{cityName}</h1>
	{#if map && map.places.length}
		<p class="count">{map.inView.length} {t(language, 'places in view')}</p>
		<ul class="cards">
			{#each nearby as place (place.id)}
				<li>
					<a href={link(language, `/${data.city.slug}/${place.slug}`)}
						onmouseenter={() => { if (map) map.hovered = place.id; }}
						onmouseleave={() => { if (map) map.hovered = null; }}
						onfocus={() => { if (map) map.hovered = place.id; }} onblur={() => { if (map) map.hovered = null; }}>
						<span class="art"><PlaceThumb kind={place.kind} photo={place.thumb} /></span>
						<span class="text">
							<span class="meta"><span class="dot" style:--kind={`var(--kind-${place.kind})`}></span>
								{t(language, place.kind)} · {distance(place)}</span>
							<strong>{place.name}</strong>
							{#if place.headline}<span class="line">{place.headline}</span>
							{:else if place.short}<span class="line muted">{place.short}</span>{/if}
						</span>
					</a>
				</li>
			{/each}
		</ul>
		{#if !nearby.length}<p class="muted">{t(language, 'Move the map to see places here.')}</p>{/if}
	{/if}
</div>

<noscript>
	<div class="browse">
		{#if data.trails.length}
			<h2>{t(language, 'Trails')}</h2>
			<ul>{#each data.trails as trail (trail.slug)}<li><a href={link(language, `/${data.city.slug}/trails/${trail.slug}`)}>{field(language, trail, 'title')}</a></li>{/each}</ul>
		{/if}
		<h2>{t(language, 'Places')}</h2>
		<ul>{#each data.places as place (place.slug)}<li><a href={link(language, `/${data.city.slug}/${place.slug}`)}>{name(language, place)}</a></li>{/each}</ul>
	</div>
</noscript>

<style>
	.browse {
		padding: var(--s5) var(--s4) 0;
	}
	h1 {
		margin: 0;
		font-size: var(--text-xl);
		letter-spacing: -0.02em;
	}
	.count {
		margin: var(--s1) 0 var(--s4);
		color: var(--text-muted);
		font-size: var(--text-sm);
	}
	.cards {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: var(--s2);
	}
	.cards a {
		display: grid;
		grid-template-columns: 4.75rem 1fr;
		gap: var(--s3);
		align-items: center;
		padding: var(--s2);
		border-radius: 18px;
		color: var(--text);
		text-decoration: none;
		transition: background 160ms ease;
	}
	.cards a:hover, .cards a:focus-visible {
		background: var(--surface);
	}
	.art {
		width: 4.75rem;
		height: 4.75rem;
		border-radius: 14px;
		overflow: hidden;
	}
	.text {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.meta {
		display: flex;
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
	.line {
		font-size: var(--text-sm);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.muted {
		color: var(--text-muted);
	}
</style>
