// Stable links. A place's link carries its name for readers and its id for permanence: a renamed place keeps working
// because pages are found by the id at the end.
import type { City, Place, Trail } from './types.ts';

export function slug(text: string): string {
	const ascii = text.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
	return ascii.replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'place';
}

export function citySlug(city: Pick<City, 'name'>): string {
	return slug(city.name);
}

export function placeSlug(place: Pick<Place, 'id' | 'name'>): string {
	return `${slug(place.name)}-${place.id.slice(3)}`;
}

export function placeId(segment: string): string {
	return `pl_${segment.slice(segment.lastIndexOf('-') + 1)}`;
}

export function trailSlug(trail: Pick<Trail, 'id' | 'title'>): string {
	return `${slug(trail.title)}-${trail.id.slice(3)}`;
}

/** Links within the site, with the language prefix when the page isn't English. */
export function link(language: string, path: string): string {
	return language === 'en' ? path : `/zh${path === '/' ? '' : path}`;
}
