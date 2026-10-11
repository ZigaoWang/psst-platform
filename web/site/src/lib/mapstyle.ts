// The map's own style, after the app: warm paper and quiet streets by day, deep ink by night, with color left to the
// pins. Tiles, fonts, and data come from OpenFreeMap (OpenMapTiles schema); no sprite, since the pins are drawn here.
import type { StyleSpecification } from 'maplibre-gl';

interface Palette {
	land: string; park: string; wood: string; water: string; waterLine: string; building: string; buildingLine: string;
	minor: string; major: string; motorway: string; casing: string; rail: string; boundary: string;
	label: string; labelSoft: string; halo: string; waterLabel: string;
}

const LIGHT: Palette = {
	land: '#f6f3ec', park: '#e3ead5', wood: '#d9e3c9', water: '#cfdde3', waterLine: '#b8cdd6', building: '#ebe6db',
	buildingLine: '#ddd6c8', minor: '#ffffff', major: '#fffdf8', motorway: '#f7e9cf', casing: '#ddd7ca', rail: '#cfc8b9',
	boundary: '#c4bcab', label: '#10182b', labelSoft: '#59606e', halo: '#f6f3ec', waterLabel: '#5b7f8e'
};

const DARK: Palette = {
	land: '#10182b', park: '#152a2a', wood: '#142826', water: '#0b2233', waterLine: '#123247', building: '#18223a',
	buildingLine: '#1f2b46', minor: '#1d2840', major: '#26324d', motorway: '#3a3a3f', casing: '#0c1220', rail: '#2a3550',
	boundary: '#3a4663', label: '#ecebe6', labelSoft: '#a7adba', halo: '#10182b', waterLabel: '#7fa3b8'
};

const REGULAR = ['Noto Sans Regular'];
const BOLD = ['Noto Sans Bold'];
const ITALIC = ['Noto Sans Italic'];

export function mapStyle(dark: boolean): StyleSpecification {
	const c = dark ? DARK : LIGHT;
	const width = (base: number) => ['interpolate', ['exponential', 1.5], ['zoom'], 12, base * 0.6, 15, base * 2, 18, base * 6];
	return {
		version: 8,
		glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
		sources: { openmaptiles: { type: 'vector', url: 'https://tiles.openfreemap.org/planet',
			attribution: '<a href="https://openfreemap.org">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/">OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' } },
		layers: [
			{ id: 'land', type: 'background', paint: { 'background-color': c.land } },
			{ id: 'wood', type: 'fill', source: 'openmaptiles', 'source-layer': 'landcover',
				filter: ['in', ['get', 'class'], ['literal', ['wood', 'grass', 'farmland']]], paint: { 'fill-color': c.wood, 'fill-opacity': 0.6 } },
			{ id: 'park', type: 'fill', source: 'openmaptiles', 'source-layer': 'park', paint: { 'fill-color': c.park } },
			{ id: 'landuse-green', type: 'fill', source: 'openmaptiles', 'source-layer': 'landuse',
				filter: ['in', ['get', 'class'], ['literal', ['cemetery', 'pitch', 'stadium', 'playground']]], paint: { 'fill-color': c.park, 'fill-opacity': 0.7 } },
			{ id: 'water', type: 'fill', source: 'openmaptiles', 'source-layer': 'water', paint: { 'fill-color': c.water } },
			{ id: 'waterway', type: 'line', source: 'openmaptiles', 'source-layer': 'waterway',
				paint: { 'line-color': c.waterLine, 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.5, 16, 3] } },
			{ id: 'building', type: 'fill', source: 'openmaptiles', 'source-layer': 'building', minzoom: 14,
				paint: { 'fill-color': c.building, 'fill-outline-color': c.buildingLine,
					'fill-opacity': ['interpolate', ['linear'], ['zoom'], 14, 0, 15, 1] } },
			{ id: 'road-casing', type: 'line', source: 'openmaptiles', 'source-layer': 'transportation', minzoom: 13,
				filter: ['in', ['get', 'class'], ['literal', ['primary', 'secondary', 'tertiary', 'trunk', 'motorway']]],
				layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': c.casing, 'line-width': width(1.6) } },
			{ id: 'road-minor', type: 'line', source: 'openmaptiles', 'source-layer': 'transportation',
				filter: ['in', ['get', 'class'], ['literal', ['minor', 'service', 'path', 'track', 'pedestrian']]],
				layout: { 'line-cap': 'round', 'line-join': 'round' },
				paint: { 'line-color': c.minor, 'line-width': width(0.9),
					'line-opacity': ['interpolate', ['linear'], ['zoom'], 12, 0.4, 14, 1] } },
			{ id: 'road-major', type: 'line', source: 'openmaptiles', 'source-layer': 'transportation',
				filter: ['in', ['get', 'class'], ['literal', ['primary', 'secondary', 'tertiary', 'trunk']]],
				layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': c.major, 'line-width': width(1.4) } },
			{ id: 'road-motorway', type: 'line', source: 'openmaptiles', 'source-layer': 'transportation',
				filter: ['==', ['get', 'class'], 'motorway'], layout: { 'line-cap': 'round', 'line-join': 'round' },
				paint: { 'line-color': c.motorway, 'line-width': width(1.8) } },
			{ id: 'rail', type: 'line', source: 'openmaptiles', 'source-layer': 'transportation',
				filter: ['==', ['get', 'class'], 'rail'], paint: { 'line-color': c.rail, 'line-width': 1, 'line-dasharray': [3, 2] } },
			{ id: 'boundary', type: 'line', source: 'openmaptiles', 'source-layer': 'boundary',
				filter: ['<=', ['get', 'admin_level'], 4], paint: { 'line-color': c.boundary, 'line-dasharray': [2, 2] } },
			{ id: 'water-name-line', type: 'symbol', source: 'openmaptiles', 'source-layer': 'water_name',
				filter: ['==', ['geometry-type'], 'LineString'],
				layout: { 'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']], 'text-font': ITALIC, 'text-size': 12,
					'symbol-placement': 'line' },
				paint: { 'text-color': c.waterLabel, 'text-halo-color': c.halo, 'text-halo-width': 1 } },
			{ id: 'water-name-point', type: 'symbol', source: 'openmaptiles', 'source-layer': 'water_name',
				filter: ['==', ['geometry-type'], 'Point'],
				layout: { 'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']], 'text-font': ITALIC, 'text-size': 12 },
				paint: { 'text-color': c.waterLabel, 'text-halo-color': c.halo, 'text-halo-width': 1 } },
			{ id: 'street-name', type: 'symbol', source: 'openmaptiles', 'source-layer': 'transportation_name', minzoom: 14,
				layout: { 'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']], 'text-font': REGULAR,
					'text-size': ['interpolate', ['linear'], ['zoom'], 14, 10, 18, 13], 'symbol-placement': 'line',
					'text-max-angle': 30 },
				paint: { 'text-color': c.labelSoft, 'text-halo-color': c.halo, 'text-halo-width': 1.2 } },
			{ id: 'place-name', type: 'symbol', source: 'openmaptiles', 'source-layer': 'place',
				filter: ['in', ['get', 'class'], ['literal', ['city', 'town', 'suburb', 'neighbourhood', 'quarter']]],
				layout: { 'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
					'text-font': ['match', ['get', 'class'], ['city', 'town'], ['literal', BOLD], ['literal', REGULAR]],
					'text-size': ['match', ['get', 'class'], 'city', 16, 'town', 14, 12],
					'text-transform': ['match', ['get', 'class'], ['suburb', 'neighbourhood', 'quarter'], 'uppercase', 'none'],
					'text-letter-spacing': ['match', ['get', 'class'], ['suburb', 'neighbourhood', 'quarter'], 0.08, 0] },
				paint: { 'text-color': c.labelSoft, 'text-halo-color': c.halo, 'text-halo-width': 1.5 } }
		]
	} as StyleSpecification;
}
