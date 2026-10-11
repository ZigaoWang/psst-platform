import { cityBySlug, cityEntries } from '#lib/server/pages.ts';
import { placeSlug, trailSlug } from '#lib/links.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const { pack } = await cityBySlug(params.city);
	// Every place as a plain link, so the city reads without JavaScript and search engines find each place.
	const places = pack.places.map((place) => ({ slug: placeSlug(place), name: place.name, names: place.names ?? {},
		kind: place.kind, story: place.facts.length > 0 }))
		.sort((a, b) => Number(b.story) - Number(a.story) || a.name.localeCompare(b.name));
	const trails = (pack.trails ?? []).map((trail) => ({ slug: trailSlug(trail), title: trail.title,
		translations: trail.translations ?? {}, stops: trail.stops.length }));
	return { places, trails };
};

export const entries = cityEntries;
