// What the map shell shares with the pages inside it: the city's places, the ones in view and the map's center, the
// place a list hovers over, and a way to move the map.
import { getContext, setContext } from 'svelte';
import type { FeedPlace } from './feed.ts';

export class MapState {
	places = $state<FeedPlace[]>([]);
	inView = $state<FeedPlace[]>([]);
	center = $state<{ lat: number; lon: number } | null>(null);
	hovered = $state<string | null>(null);
	show: (list: FeedPlace[]) => void = () => {};
}

const KEY = Symbol('map');

export function provideMap(state: MapState) {
	setContext(KEY, state);
}

export function useMap(): MapState | undefined {
	return getContext<MapState | undefined>(KEY);
}
