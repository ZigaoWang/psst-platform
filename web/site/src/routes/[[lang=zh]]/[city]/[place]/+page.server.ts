import { placeBySlug, placeEntries } from '#lib/server/pages.ts';
import { slug } from '#lib/links.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ params }) => {
	const { city, place, common } = await placeBySlug(params.city, params.place);
	const areas = new Map(common.areas.map((a) => [a.id, a]));
	const tags = new Map(common.tags.map((tag) => [tag.id, { name: tag.name, names: tag.names ?? {}, slug: slug(tag.name) }]));
	return {
		city: { name: city.name, names: city.names ?? {}, slug: params.city },
		place: {
			...place,
			// Format 2 also carries `look` as the last paragraph of `long`, for apps that don't read it; shown once here.
			facts: place.facts.map((story) => ({
				...story,
				long: story.look && story.long.endsWith(`\n\n${story.look}`)
					? story.long.slice(0, -(story.look.length + 2)) : story.long,
				tags: (story.tags ?? []).map((id) => tags.get(id)).filter((tag) => tag !== undefined)
			}))
		},
		neighborhood: place.neighborhoodId ? areas.get(place.neighborhoodId)?.name ?? null : null,
		district: place.districtId ? areas.get(place.districtId)?.name ?? null : null
	};
};

export const entries = placeEntries;
