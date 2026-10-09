import { error } from '@sveltejs/kit';
import { content } from '#lib/server/content.ts';
import { tagEntries } from '#lib/server/pages.ts';
import { citySlug, placeSlug, slug } from '#lib/links.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const { common, packs } = await content();
	const tag = common.tags.find((t) => slug(t.name) === params.tag);
	if (!tag) error(404, 'No such tag');
	const places = common.cities.flatMap((city) => (packs.get(city.id)?.places ?? [])
		.map((place) => ({ place, story: place.facts.find((f) => f.tags?.includes(tag.id)) }))
		.filter((entry) => entry.story)
		.map(({ place, story }) => ({
			id: place.id, name: place.name, names: place.names ?? {}, localName: place.localName,
			city: city.name, href: `/${citySlug(city)}/${placeSlug(place)}`,
			headline: story!.headline, translations: story!.translations ?? {}
		})));
	return { tag: { name: tag.name, names: tag.names ?? {}, type: tag.type }, places };
};

export const entries = tagEntries;
