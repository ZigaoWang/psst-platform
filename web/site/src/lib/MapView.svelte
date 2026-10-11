<script lang="ts">
	// The map: every place of the city as a pin like the app's, a balloon in its kind's color with the kind's glyph,
	// larger for a featured story; a place with a guide alone is a small dot. Pins cluster when zoomed out, and a
	// cluster opens with a smooth zoom. Hovering (or tapping, on touch screens) shows a preview; clicking opens the
	// place. MapLibre, its worker, and the tiles load only in the browser.
	import { onMount } from 'svelte';
	import 'maplibre-gl/dist/maplibre-gl.css';
	// MapLibre draws tiles in a worker; the build bundles it as a file of its own on this site.
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
	import type { FeatureCollection, Point } from 'geojson';
	import type { ExpressionSpecification } from 'maplibre-gl';
	import type { FeedPlace } from './feed.ts';
	import { ICONS, KIND_COLORS, onKind } from './icons.ts';
	import { mapStyle } from './mapstyle.ts';

	type Bounds = { south: number; west: number; north: number; east: number };
	interface Props {
		places: FeedPlace[];
		bounds: Bounds;
		selected: string | null;
		hovered: string | null;
		panelOpen: boolean;
		onopen: (place: FeedPlace) => void;
		onpreview: (preview: { place: FeedPlace; x: number; y: number } | null) => void;
		onview: (inView: FeedPlace[], center: { lat: number; lon: number }) => void;
	}
	let { places, bounds, selected, hovered, panelOpen, onopen, onpreview, onview }: Props = $props();

	let container: HTMLDivElement;
	let map: import('maplibre-gl').Map | undefined;
	let ready = $state(false);
	let me: import('maplibre-gl').Marker | undefined;
	const byId = $derived(new Map(places.map((p) => [p.id, p])));
	const PIXEL_RATIO = 2;

	function dark(): boolean {
		return matchMedia('(prefers-color-scheme: dark)').matches;
	}

	function geojson(list: FeedPlace[]): FeatureCollection {
		return {
			type: 'FeatureCollection',
			features: list.map((p) => ({
				type: 'Feature',
				geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
				properties: { id: p.id, name: p.name, tier: p.tier, kind: KIND_COLORS[p.kind] ? p.kind : 'building',
					rank: p.tier === 'featured' ? 0 : p.tier === 'story' ? 1 : 2 }
			}))
		};
	}

	/** A balloon pin like the app's markers: the kind's color, its glyph in white, a paper rim. */
	function pin(kind: string, scale: number, rim: string): ImageData {
		const w = Math.round(30 * scale * PIXEL_RATIO);
		const h = Math.round(40 * scale * PIXEL_RATIO);
		const canvas = document.createElement('canvas');
		canvas.width = w;
		canvas.height = h;
		const g = canvas.getContext('2d')!;
		g.scale(scale * PIXEL_RATIO, scale * PIXEL_RATIO);
		g.shadowColor = 'rgba(16, 24, 43, 0.28)';
		g.shadowBlur = 3;
		g.shadowOffsetY = 1;
		g.beginPath();
		g.arc(15, 14, 12.5, Math.PI * 0.82, Math.PI * 2.18);
		g.lineTo(15, 37.5);
		g.closePath();
		g.fillStyle = KIND_COLORS[kind];
		g.fill();
		g.shadowColor = 'transparent';
		g.lineWidth = 1.6;
		g.strokeStyle = rim;
		g.stroke();
		g.save();
		g.translate(15 - 7.2, 14 - 7.2);
		g.scale(0.6, 0.6);
		g.strokeStyle = onKind(kind);
		g.lineWidth = 2.4;
		g.lineCap = 'round';
		g.lineJoin = 'round';
		for (const d of ICONS[kind]) g.stroke(new Path2D(d));
		g.restore();
		return g.getImageData(0, 0, w, h);
	}

	function addLayers(m: import('maplibre-gl').Map) {
		const paper = dark() ? '#10182b' : '#ffffff';
		const ink = dark() ? '#ecebe6' : '#10182b';
		for (const kind of Object.keys(KIND_COLORS)) {
			for (const [tier, scale] of [['featured', 1.25], ['story', 0.95]] as const) {
				const name = `pin-${kind}-${tier}`;
				if (!m.hasImage(name)) m.addImage(name, pin(kind, scale, paper), { pixelRatio: PIXEL_RATIO });
			}
		}
		m.addSource('places', { type: 'geojson', data: geojson(places), cluster: true, clusterRadius: 46, clusterMaxZoom: 15 });
		m.addLayer({ id: 'clusters', type: 'circle', source: 'places', filter: ['has', 'point_count'], paint: {
			'circle-color': ink,
			'circle-radius': ['step', ['get', 'point_count'], 15, 10, 18, 50, 22, 200, 27],
			'circle-stroke-width': 2, 'circle-stroke-color': paper,
			'circle-opacity-transition': { duration: 300 } } });
		m.addLayer({ id: 'cluster-count', type: 'symbol', source: 'places', filter: ['has', 'point_count'], layout: {
			'text-field': ['get', 'point_count_abbreviated'], 'text-font': ['Noto Sans Bold'], 'text-size': 13,
			'text-allow-overlap': true }, paint: { 'text-color': paper } });
		m.addLayer({ id: 'dots', type: 'circle', source: 'places',
			filter: ['all', ['!', ['has', 'point_count']], ['==', ['get', 'tier'], 'guide']], paint: {
				'circle-color': ['match', ['get', 'kind'], ...Object.entries(KIND_COLORS).flat(), '#5f6368'] as unknown as string,
				'circle-radius': ['interpolate', ['linear'], ['zoom'], 13, 3.5, 18, 7],
				'circle-stroke-width': 1.5, 'circle-stroke-color': paper } });
		m.addLayer({ id: 'pins', type: 'symbol', source: 'places',
			filter: ['all', ['!', ['has', 'point_count']], ['!=', ['get', 'tier'], 'guide']], layout: {
				'icon-image': ['concat', 'pin-', ['get', 'kind'], '-', ['get', 'tier']], 'icon-anchor': 'bottom',
				'icon-allow-overlap': true, 'symbol-sort-key': ['get', 'rank'],
				'text-field': ['step', ['zoom'], '', 16, ['get', 'name']], 'text-font': ['Noto Sans Bold'],
				'text-size': 12, 'text-anchor': 'top', 'text-offset': [0, 0.3], 'text-optional': true },
			paint: { 'text-color': ink, 'text-halo-color': paper, 'text-halo-width': 1.5 } });
	}

	function report() {
		if (!map) return;
		const b = map.getBounds();
		const center = map.getCenter();
		onview(places.filter((p) => b.contains([p.lon, p.lat])), { lat: center.lat, lon: center.lng });
	}

	function padding() {
		const wide = matchMedia('(min-width: 48rem)').matches;
		return wide ? { top: 80, bottom: 40, left: 40, right: panelOpen ? 470 : 40 }
			: { top: 110, bottom: panelOpen ? Math.round(innerHeight * 0.58) : 40, left: 24, right: 24 };
	}

	/** Moves the map to show places: one place closely, several together. */
	export function show(list: FeedPlace[]) {
		if (!map || !list.length) return;
		const duration = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 900;
		if (list.length === 1) {
			map.flyTo({ center: [list[0].lon, list[0].lat], zoom: Math.max(map.getZoom(), 17), padding: padding(),
				duration, curve: 1.3, essential: true });
			return;
		}
		const lons = list.map((p) => p.lon);
		const lats = list.map((p) => p.lat);
		map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
			{ padding: padding(), maxZoom: 17, duration });
	}

	/** The reader's own position, as a dot. */
	export async function locate(lat: number, lon: number) {
		if (!map) return;
		const { Marker } = await import('maplibre-gl');
		const dot = document.createElement('div');
		dot.className = 'me';
		me?.remove();
		me = new Marker({ element: dot }).setLngLat([lon, lat]).addTo(map);
		map.flyTo({ center: [lon, lat], zoom: 16, padding: padding(), duration: 900, essential: true });
	}

	onMount(() => {
		let cancelled = false;
		const scheme = matchMedia('(prefers-color-scheme: dark)');
		(async () => {
			const maplibre = await import('maplibre-gl');
			if (cancelled) return;
			maplibre.setWorkerUrl(workerUrl);
			const m = new maplibre.Map({
				container, style: mapStyle(dark()), attributionControl: false,
				bounds: [[bounds.west, bounds.south], [bounds.east, bounds.north]], fitBoundsOptions: { padding: 20 },
				dragRotate: false, pitchWithRotate: false, maxPitch: 0, fadeDuration: 200
			});
			m.touchZoomRotate.disableRotation();
			m.addControl(new maplibre.NavigationControl({ showCompass: false }), 'top-right');
			m.addControl(new maplibre.AttributionControl({ compact: true }), 'bottom-left');
			m.on('style.load', () => {
				addLayers(m);
				ready = true;
				report();
			});
			m.on('moveend', report);
			const touch = matchMedia('(hover: none)').matches;
			for (const layer of ['pins', 'dots']) {
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
				m.easeTo({ center: (feature.geometry as Point).coordinates as [number, number], zoom: zoom + 0.4, duration: 650 });
			});
			m.on('mouseenter', 'clusters', () => (m.getCanvas().style.cursor = 'pointer'));
			m.on('mouseleave', 'clusters', () => (m.getCanvas().style.cursor = ''));
			m.on('click', (event) => {
				if (!m.queryRenderedFeatures(event.point, { layers: ['pins', 'dots', 'clusters'] }).length) onpreview(null);
			});
			map = m;
		})();
		const restyle = () => {
			if (!map) return;
			ready = false;
			map.setStyle(mapStyle(dark()));
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

	// The open place, and the one a list hovers over, stand out: a pin grows, a dot grows and takes a darker rim.
	$effect(() => {
		const ids = [selected, hovered].filter((id): id is string => !!id);
		if (!ready || !map) return;
		const marked: ExpressionSpecification = ['in', ['get', 'id'], ['literal', ids]];
		map.setLayoutProperty('pins', 'icon-size', ['case', marked, 1.35, 1]);
		map.setPaintProperty('dots', 'circle-stroke-width', ['case', marked, 3, 1.5]);
		map.setPaintProperty('dots', 'circle-stroke-color',
			['case', marked, dark() ? '#ecebe6' : '#10182b', dark() ? '#10182b' : '#ffffff']);
	});

	$effect(() => {
		const id = selected;
		if (!ready || !map) return;
		const place = id ? byId.get(id) : undefined;
		if (place) show([place]);
	});
</script>

<div class="map" class:sheet={panelOpen} bind:this={container} role="application" aria-label="Map of places"></div>

<style>
	.map {
		position: absolute;
		inset: 0;
		background: var(--bg);
	}
	.map :global(.me) {
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--focus);
		border: 3px solid #fff;
		box-shadow: 0 0 0 6px rgb(36 88 214 / 0.25);
	}
	/* Zoom buttons sit under the toolbar and step aside for the panel; on a phone, pinching zooms and the credit
	   rises above an open sheet. */
	.map :global(.maplibregl-ctrl-top-right) {
		top: 4.5rem;
		transition: right 280ms cubic-bezier(0.2, 0.8, 0.2, 1);
	}
	.map.sheet :global(.maplibregl-ctrl-top-right) {
		right: min(28rem, 100%);
	}
	@media (max-width: 47.99rem) {
		.map :global(.maplibregl-ctrl-top-right) {
			display: none;
		}
		.map.sheet :global(.maplibregl-ctrl-bottom-left) {
			bottom: 58vh;
		}
	}
	.map :global(.maplibregl-ctrl-group) {
		border-radius: var(--r3);
		box-shadow: var(--shadow);
		border: 0;
	}
</style>
