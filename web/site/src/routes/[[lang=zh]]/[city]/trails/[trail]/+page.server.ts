import { error } from '@sveltejs/kit';
import { cityBySlug, trailEntries } from '#lib/server/pages.ts';
import { placeSlug, trailSlug } from '#lib/links.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const { city, pack } = await cityBySlug(params.city);
	const trail = (pack.trails ?? []).find((t) => trailSlug(t) === params.trail);
	if (!trail) error(404, 'No such trail');
	const places = new Map(pack.places.map((p) => [p.id, p]));
	return {
		city: { name: city.name, names: city.names ?? {}, slug: params.city },
		trail: {
			title: trail.title, intro: trail.intro, translations: trail.translations ?? {},
			stops: trail.stops.map((stop, index) => {
				const place = places.get(stop.placeId)!;
				return { note: stop.note, noteZh: trail.translations?.['zh-Hans']?.stopNotes?.[index] ?? null,
					name: place.name, names: place.names ?? {}, localName: place.localName, href: placeSlug(place),
					lat: place.lat, lon: place.lon };
			})
		}
	};
};

export const entries = trailEntries;
