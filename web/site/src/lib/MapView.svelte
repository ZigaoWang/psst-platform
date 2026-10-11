<script lang="ts">
	// The map: every place of the city as a pin colored by its kind (the app's colors), sized by what it holds (a
	// featured story, a story, or a guide), clustered when zoomed out. Hovering (or tapping, on touch screens) shows a
	// preview; clicking opens the place. MapLibre and its tiles load only in the browser.
	import { onMount } from 'svelte';
	import 'maplibre-gl/dist/maplibre-gl.css';
	import type { FeatureCollection, Point } from 'geojson';
	import type { FeedPlace } from './feed.ts';

	type Bounds = { south: number; west: number; north: number; east: number };
	interface Props {
		places: FeedPlace[];
		bounds: Bounds;
		selected: string | null;
		panelOpen: boolean;
		onopen: (place: FeedPlace) => void;
		onpreview: (preview: { place: FeedPlace; x: number; y: number } | null) => void;
		onview: (inView: FeedPlace[]) => void;
	}
	let { places, bounds, selected, panelOpen, onopen, onpreview, onview }: Props = $props();

	const KIND_COLORS: Record<string, string> = {
		transit: '#d3221b', crossing: '#0067b1', street: '#f2a900', building: '#1f3a93', worship: '#7a1f5c',
		memorial: '#74613f', green: '#00783a', water: '#00838c', culture: '#c4005f'
	};
	const STYLES = { light: 'https://tiles.openfreemap.org/styles/positron', dark: 'https://tiles.openfreemap.org/styles/dark' };

	let container: HTMLDivElement;
	let map: import('maplibre-gl').Map | undefined;
	let ready = $state(false);
	let me: import('maplibre-gl').Marker | undefined;
	const byId = $derived(new Map(places.map((p) => [p.id, p])));

	function geojson(list: FeedPlace[]): FeatureCollection {
		return {
			type: 'FeatureCollection',
			features: list.map((p) => ({
				type: 'Feature', id: undefined,
				geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
				properties: { id: p.id, name: p.name, tier: p.tier, color: KIND_COLORS[p.kind] ?? '#5f6368' }
			}))
		};
	}

	function dark(): boolean {
		const chosen = document.documentElement.dataset.theme;
		return chosen ? chosen === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
	}

	function addLayers(m: import('maplibre-gl').Map) {
		const paper = dark() ? '#141c2e' : '#ffffff';
		const ink = dark() ? '#f6f3ec' : '#10182b';
		m.addSource('places', { type: 'geojson', data: geojson(places), cluster: true, clusterRadius: 44, clusterMaxZoom: 15,
			clusterProperties: { featured: ['+', ['case', ['==', ['get', 'tier'], 'featured'], 1, 0]] } });
		m.addLayer({ id: 'clusters', type: 'circle', source: 'places', filter: ['has', 'point_count'], paint: {
			'circle-color': ink, 'circle-opacity': 0.88,
			'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 50, 23, 200, 28],
			'circle-stroke-width': ['case', ['>', ['get', 'featured'], 0], 3, 1.5],
			'circle-stroke-color': ['case', ['>', ['get', 'featured'], 0], '#f2a900', paper] } });
		m.addLayer({ id: 'cluster-count', type: 'symbol', source: 'places', filter: ['has', 'point_count'], layout: {
			'text-field': ['get', 'point_count_abbreviated'], 'text-font': ['Noto Sans Bold'], 'text-size': 12,
			'text-allow-overlap': true }, paint: { 'text-color': paper } });
		m.addLayer({ id: 'halo', type: 'circle', source: 'places',
			filter: ['all', ['!', ['has', 'point_count']], ['==', ['get', 'tier'], 'featured']], paint: {
				'circle-color': ['get', 'color'], 'circle-opacity': 0.22,
				'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 11, 17, 18] } });
		m.addLayer({ id: 'pins', type: 'circle', source: 'places', filter: ['!', ['has', 'point_count']], paint: {
			'circle-color': ['get', 'color'],
			'circle-radius': ['interpolate', ['linear'], ['zoom'],
				12, ['match', ['get', 'tier'], 'featured', 6.5, 'story', 5, 3],
				17, ['match', ['get', 'tier'], 'featured', 11, 'story', 8.5, 5.5]],
			'circle-stroke-width': ['match', ['get', 'tier'], 'guide', 1, 2],
			'circle-stroke-color': paper } });
		m.addLayer({ id: 'selected', type: 'circle', source: 'places',
			filter: ['==', ['get', 'id'], selected ?? ''], paint: {
				'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': ink, 'circle-stroke-width': 3,
				'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 11, 17, 16] } });
		m.addLayer({ id: 'names', type: 'symbol', source: 'places', minzoom: 16,
			filter: ['all', ['!', ['has', 'point_count']], ['!=', ['get', 'tier'], 'guide']], layout: {
				'text-field': ['get', 'name'], 'text-font': ['Noto Sans Regular'], 'text-size': 12,
				'text-offset': [0, 1.3], 'text-anchor': 'top', 'text-optional': true }, paint: {
				'text-color': ink, 'text-halo-color': paper, 'text-halo-width': 1.5 } });
	}

	function inView() {
		if (!map) return;
		const b = map.getBounds();
		onview(places.filter((p) => b.contains([p.lon, p.lat])));
	}

	function padding() {
		const wide = matchMedia('(min-width: 48rem)').matches;
		return wide ? { top: 80, bottom: 40, left: 40, right: panelOpen ? 460 : 40 }
			: { top: 80, bottom: panelOpen ? Math.round(innerHeight * 0.55) : 40, left: 24, right: 24 };
	}

	/** Moves the map to show places: one place closely, several together. */
	export function show(list: FeedPlace[]) {
		if (!map || !list.length) return;
		const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
		if (list.length === 1) {
			map.flyTo({ center: [list[0].lon, list[0].lat], zoom: Math.max(map.getZoom(), 17), padding: padding(),
				duration: reduce ? 0 : 1100, essential: true });
			return;
		}
		const lons = list.map((p) => p.lon);
		const lats = list.map((p) => p.lat);
		map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
			{ padding: padding(), maxZoom: 17, duration: reduce ? 0 : 1100 });
	}

	/** The reader's own position, as a dot. */
	export async function locate(lat: number, lon: number) {
		if (!map) return;
		const { Marker } = await import('maplibre-gl');
		const dot = document.createElement('div');
		dot.className = 'me';
		dot.setAttribute('aria-label', 'You are here');
		me?.remove();
		me = new Marker({ element: dot }).setLngLat([lon, lat]).addTo(map);
		map.flyTo({ center: [lon, lat], zoom: 16, padding: padding(), duration: 1100, essential: true });
	}

	onMount(() => {
		let cancelled = false;
		const scheme = matchMedia('(prefers-color-scheme: dark)');
		(async () => {
			const maplibre = await import('maplibre-gl');
			if (cancelled) return;
			const m = new maplibre.Map({
				container, style: dark() ? STYLES.dark : STYLES.light, attributionControl: { compact: true },
				bounds: [[bounds.west, bounds.south], [bounds.east, bounds.north]], fitBoundsOptions: { padding: 20 },
				dragRotate: false, pitchWithRotate: false, maxPitch: 0
			});
			m.touchZoomRotate.disableRotation();
			m.addControl(new maplibre.NavigationControl({ showCompass: false }), 'bottom-right');
			m.on('style.load', () => {
				addLayers(m);
				ready = true;
				inView();
			});
			m.on('moveend', inView);
			const touch = matchMedia('(hover: none)').matches;
			for (const layer of ['pins', 'halo']) {
				m.on('mouseenter', layer, () => (m.getCanvas().style.cursor = 'pointer'));
				m.on('mouseleave', layer, () => {
					m.getCanvas().style.cursor = '';
					if (!touch) onpreview(null);
				});
				m.on('mousemove', layer, (event) => {
					if (touch) return;
					const place = byId.get(String(event.features?.[0]?.properties?.id));
					if (place) onpreview({ place, x: event.point.x, y: event.point.y });
				});
				m.on('click', layer, (event) => {
					const place = byId.get(String(event.features?.[0]?.properties?.id));
					if (!place) return;
					// On a touch screen the first tap previews and the preview opens the place.
					if (touch) onpreview({ place, x: event.point.x, y: event.point.y });
					else onopen(place);
				});
			}
			m.on('click', 'clusters', async (event) => {
				const feature = event.features?.[0];
				if (!feature) return;
				const source = m.getSource('places') as import('maplibre-gl').GeoJSONSource;
				const zoom = await source.getClusterExpansionZoom(Number(feature.properties?.cluster_id));
				m.easeTo({ center: (feature.geometry as Point).coordinates as [number, number], zoom: zoom + 0.3,
					duration: 600 });
			});
			m.on('mouseenter', 'clusters', () => (m.getCanvas().style.cursor = 'pointer'));
			m.on('mouseleave', 'clusters', () => (m.getCanvas().style.cursor = ''));
			m.on('click', (event) => {
				if (!m.queryRenderedFeatures(event.point, { layers: ['pins', 'halo', 'clusters'] }).length) onpreview(null);
			});
			map = m;
		})();
		const restyle = () => {
			if (!map) return;
			ready = false;
			map.setStyle(dark() ? STYLES.dark : STYLES.light);
		};
		scheme.addEventListener('change', restyle);
		return () => {
			cancelled = true;
			scheme.removeEventListener('change', restyle);
			map?.remove();
		};
	});

	$effect(() => {
		const list = places;
		if (ready && map) (map.getSource('places') as import('maplibre-gl').GeoJSONSource | undefined)?.setData(geojson(list));
	});

	$effect(() => {
		const id = selected;
		if (!ready || !map) return;
		map.setFilter('selected', ['==', ['get', 'id'], id ?? '']);
		const place = id ? byId.get(id) : undefined;
		if (place) show([place]);
	});
</script>

<div class="map" bind:this={container} role="application" aria-label="Map of places"></div>

<style>
	.map {
		position: absolute;
		inset: 0;
		background: var(--surface-sunk);
	}
	.map :global(.me) {
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--focus);
		border: 3px solid #fff;
		box-shadow: 0 0 0 6px rgb(36 88 214 / 0.25);
	}
	.map :global(.maplibregl-ctrl-group) {
		border-radius: var(--r2);
		box-shadow: var(--shadow);
	}
</style>
