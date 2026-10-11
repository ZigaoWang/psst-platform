import { cityBySlug } from '#lib/server/pages.ts';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ params }) => {
	const { city } = await cityBySlug(params.city);
	return { city: { name: city.name, names: city.names ?? {}, slug: params.city, bounds: city.bounds } };
};
