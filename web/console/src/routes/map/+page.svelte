<script lang="ts">
	import 'maplibre-gl/dist/maplibre-gl.css';
	// MapLibre parses tiles in a worker; bundle it so it ships with the console's own assets.
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let container: HTMLDivElement | undefined = $state();

	$effect(() => {
		const city = data.city;
		if (!container || !city) return;
		let map: import('maplibre-gl').Map | undefined;
		let cancelled = false;
		const layersRequest = fetch(`/admin/map/data?city=${encodeURIComponent(city.slug)}`).then((r) => r.json());
		(async () => {
			const maplibre = await import('maplibre-gl');
			if (cancelled || !container) return;
			maplibre.setWorkerUrl(workerUrl);
			map = new maplibre.Map({
				container,
				style: 'https://tiles.openfreemap.org/styles/positron',
				bounds: [[city.west, city.south], [city.east, city.north]],
				attributionControl: { compact: true }
			});
			map.addControl(new maplibre.NavigationControl({ showCompass: false }));
			map.on('load', async () => {
				const layers = await layersRequest;
				if (!map || cancelled) return;
				map.addSource('cells', { type: 'geojson', data: layers.cells });
				map.addLayer({
					id: 'cells', type: 'fill', source: 'cells',
					paint: {
						'fill-color': ['match', ['get', 'state'], 'researched', '#146c2e', 'queued', '#1f5fbf', '#9aa0a6'],
						'fill-opacity': 0.18, 'fill-outline-color': '#6b6f76'
					}
				});
				map.addSource('places', { type: 'geojson', data: layers.places });
				map.addLayer({
					id: 'places', type: 'circle', source: 'places',
					paint: {
						'circle-radius': 4, 'circle-stroke-width': 1, 'circle-stroke-color': '#ffffff',
						'circle-color': ['case', ['get', 'live'], '#10182b', '#b3261e']
					}
				});
				map.on('click', 'places', (event) => {
					const id = event.features?.[0]?.properties?.id;
					if (id) window.location.href = `/admin/places/${id}`;
				});
			});
		})();
		return () => {
			cancelled = true;
			map?.remove();
		};
	});
</script>

<svelte:head><title>Map · Psst console</title></svelte:head>
<PageHeader title="Map" subtitle="Research cells by state, and places: dark when something about them is live, red when not yet." />

<form class="filters" method="GET">
	<label>City
		<select name="city">{#each data.cities as c (c.slug)}<option value={c.slug} selected={c.slug === data.city?.slug}>{c.name}</option>{/each}</select>
	</label>
	<button type="submit">Show</button>
</form>

{#if data.city}
	<div class="map" bind:this={container} role="region" aria-label={`Map of ${data.city.name}`}></div>
	<p class="muted">The same places are listed on the <a href={`/admin/places?city=${data.city.slug}`}>Places</a> page.</p>
{:else}
	<Empty>No cities are set up yet.</Empty>
{/if}

<style>
	.map {
		height: 70vh;
		border: 1px solid var(--line);
		border-radius: var(--r2);
	}
</style>
