import { cityBySlug, cityEntries } from '#lib/server/pages.ts';
import { placeSlug, trailSlug } from '#lib/links.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const { city, pack, common } = await cityBySlug(params.city);
	const areas = new Map(common.areas.map((a) => [a.id, a]));
	const places = pack.places.map((place) => {
		const lead = place.facts[0];
		return {
			id: place.id, slug: placeSlug(place), name: place.name, names: place.names ?? {}, localName: place.localName,
			kind: place.kind, identifier: place.guide?.identifier ?? null,
			guideTranslations: place.guide?.translations ?? {},
			neighborhood: place.neighborhoodId ? areas.get(place.neighborhoodId) ?? null : null,
			lead: lead ? { headline: lead.headline, short: lead.short, veracity: lead.veracity, category: lead.category,
				translations: lead.translations ?? {} } : null,
			thumb: place.images?.[0] ? { file: place.images[0].thumb.file, alt: place.images[0].alt } : null
		};
	}).sort((a, b) => (a.neighborhood?.name ?? '~').localeCompare(b.neighborhood?.name ?? '~') || a.name.localeCompare(b.name));
	const trails = (pack.trails ?? []).map((trail) => ({ slug: trailSlug(trail), title: trail.title,
		translations: trail.translations ?? {}, stops: trail.stops.length }));
	return { city: { name: city.name, names: city.names ?? {}, slug: params.city }, places, trails };
};

export const entries = cityEntries;
