import { content } from '#lib/server/content.ts';
import { languageOf } from '#lib/language.ts';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = async ({ params }) => {
	const { manifest } = await content();
	return { language: languageOf(params.lang), version: manifest.contentVersion };
};
