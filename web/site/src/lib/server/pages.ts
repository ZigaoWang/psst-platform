// Finding a page's records by its link, and the entries every prerendered route lists.
import { error } from '@sveltejs/kit';
import { citySlug, placeId, placeSlug, slug, trailSlug } from '#lib/links.ts';
import { content } from './content.ts';

export async function cityBySlug(segment: string) {
	const data = await content();
	const city = data.cities.find((c) => citySlug(c) === segment);
	if (!city) error(404, 'No such city');
	const pack = data.packs.get(city.id);
	if (!pack) error(404, 'No such city');
	return { ...data, city, pack };
}

export async function placeBySlug(citySegment: string, placeSegment: string) {
	const data = await cityBySlug(citySegment);
	const place = data.pack.places.find((p) => p.id === placeId(placeSegment));
	if (!place || placeSlug(place) !== placeSegment) error(404, 'No such place');
	return { ...data, place };
}

const LANGUAGES = [undefined, 'zh'] as const;

export async function cityEntries() {
	const { cities } = await content();
	return LANGUAGES.flatMap((lang) => cities.map((city) => ({ lang, city: citySlug(city) })));
}

export async function placeEntries() {
	const { cities, packs } = await content();
	return LANGUAGES.flatMap((lang) => cities.flatMap((city) =>
		(packs.get(city.id)?.places ?? []).map((place) => ({ lang, city: citySlug(city), place: placeSlug(place) }))));
}

export async function trailEntries() {
	const { cities, packs } = await content();
	return LANGUAGES.flatMap((lang) => cities.flatMap((city) =>
		(packs.get(city.id)?.trails ?? []).map((trail) => ({ lang, city: citySlug(city), trail: trailSlug(trail) }))));
}

export async function tagEntries() {
	const { common } = await content();
	return LANGUAGES.flatMap((lang) => common.tags.map((tag) => ({ lang, tag: slug(tag.name) })));
}

/** What the map needs for every place of a city, compact: where it is, how to draw its pin, what its preview card
 * says, and what search and the filters read. Built once per city and language; the place itself loads on demand. */
export async function cityFeed(segment: string, language: 'en' | 'zh-Hans') {
	const { city, pack, common } = await cityBySlug(segment);
	const areas = new Map(common.areas.map((a) => [a.id, a]));
	const zh = language === 'zh-Hans';
	const pick = (value: string, translations: Record<string, Record<string, unknown> | undefined> | undefined,
		key: string) => {
		const translated = zh ? translations?.['zh-Hans']?.[key] : undefined;
		return typeof translated === 'string' && translated ? translated : value;
	};
	const places = pack.places.map((place) => {
		const lead = place.facts[0];
		const area = place.neighborhoodId ? areas.get(place.neighborhoodId) : undefined;
		return {
			id: place.id,
			slug: placeSlug(place),
			name: zh ? (place.names?.['zh-Hans'] ?? place.name) : place.name,
			kind: place.kind,
			lat: Math.round(place.lat * 1e6) / 1e6,
			lon: Math.round(place.lon * 1e6) / 1e6,
			tier: lead ? (place.facts.some((f) => f.featured) ? 'featured' : 'story') : 'guide',
			categories: [...new Set(place.facts.map((f) => f.category))],
			headline: lead ? pick(lead.headline, lead.translations, 'headline') : null,
			short: lead ? pick(lead.short, lead.translations, 'short')
				: place.guide ? pick(place.guide.identifier, place.guide.translations, 'identifier') : null,
			neighborhood: area ? (zh ? (area.names?.['zh-Hans'] ?? area.name) : area.name) : null,
			thumb: place.images?.[0] ? place.images[0].thumb.file : null
		};
	});
	return {
		city: { name: zh ? (city.names?.['zh-Hans'] ?? city.name) : city.name, slug: segment, bounds: city.bounds },
		places
	};
}
