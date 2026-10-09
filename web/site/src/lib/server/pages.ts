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
