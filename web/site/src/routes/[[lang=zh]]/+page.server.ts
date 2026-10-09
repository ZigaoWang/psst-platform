import { content } from '#lib/server/content.ts';
import { citySlug } from '#lib/links.ts';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async () => {
	const { cities, packs } = await content();
	return {
		cities: cities.map((city) => ({
			id: city.id, name: city.name, names: city.names ?? {}, slug: citySlug(city), places: city.placeCount,
			trails: packs.get(city.id)?.trails?.length ?? 0
		}))
	};
};

export const entries = () => [{ lang: undefined }, { lang: 'zh' }];
