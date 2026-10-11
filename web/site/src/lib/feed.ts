// The map's view of a city: one compact entry per place (see cityFeed), and the searches and filters over them.
export interface FeedPlace {
	id: string;
	slug: string;
	name: string;
	kind: string;
	lat: number;
	lon: number;
	tier: 'featured' | 'story' | 'guide';
	categories: string[];
	headline: string | null;
	short: string | null;
	neighborhood: string | null;
	thumb: string | null;
}

export interface Feed {
	city: { name: string; slug: string; bounds: { south: number; west: number; north: number; east: number } };
	places: FeedPlace[];
}

export const KINDS = ['transit', 'crossing', 'street', 'building', 'worship', 'memorial', 'green', 'water', 'culture'];
// The app's order for categories: the most surprising first.
export const CATEGORIES = ['pop', 'hidden', 'name', 'quirk', 'people', 'history', 'design', 'engineering'];

const STREET = /\b((?:[A-Z][\w'’.-]*\s)+(?:Street|Road|Lane|Row|Place|Square|Walk|Avenue|Gardens|Hill|Court|Mews|Terrace|Way|Grove|Crescent|Close|Yard|Passage|Alley|Embankment|Circus|Gate|Parade|Market))\b/;

export interface Hit {
	type: 'place' | 'street' | 'area';
	label: string;
	detail: string;
	places: FeedPlace[];
}

/** Places, streets, and neighborhoods matching a query, best first. A street or neighborhood is found through the
 * places on it. */
export function search(places: FeedPlace[], query: string, limit = 8): Hit[] {
	const q = query.trim().toLowerCase();
	if (q.length < 2) return [];
	const hits: Hit[] = [];
	const groups = (key: (p: FeedPlace) => string | null) => {
		const found = new Map<string, FeedPlace[]>();
		for (const place of places) {
			const value = key(place);
			if (value && value.toLowerCase().includes(q)) found.set(value, [...(found.get(value) ?? []), place]);
		}
		return found;
	};
	const named = places.filter((p) => p.name.toLowerCase().includes(q) || p.headline?.toLowerCase().includes(q));
	named.sort((a, b) => Number(!a.name.toLowerCase().startsWith(q)) - Number(!b.name.toLowerCase().startsWith(q))
		|| ['featured', 'story', 'guide'].indexOf(a.tier) - ['featured', 'story', 'guide'].indexOf(b.tier));
	for (const [street, on] of groups((p) => STREET.exec(p.name)?.[1] ?? null)) {
		hits.push({ type: 'street', label: street, detail: String(on.length), places: on });
	}
	for (const [area, on] of groups((p) => p.neighborhood)) {
		hits.push({ type: 'area', label: area, detail: String(on.length), places: on });
	}
	hits.push(...named.map((p) => ({ type: 'place' as const, label: p.name, detail: p.headline ?? p.neighborhood ?? '',
		places: [p] })));
	return hits.slice(0, limit);
}

/** The places a reader's filters keep: no category chosen keeps every place; a chosen category keeps the places with a
 * story in it. */
export function filtered(places: FeedPlace[], categories: Set<string>): FeedPlace[] {
	if (!categories.size) return places;
	return places.filter((p) => p.categories.some((c) => categories.has(c)));
}

export function distanceKm(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
	const rad = Math.PI / 180;
	const dLat = (b.lat - a.lat) * rad;
	const dLon = (b.lon - a.lon) * rad;
	const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
	return 12742 * Math.asin(Math.sqrt(h));
}
