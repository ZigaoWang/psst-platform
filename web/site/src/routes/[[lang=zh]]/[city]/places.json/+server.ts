import { json } from '@sveltejs/kit';
import { languageOf } from '#lib/language.ts';
import { cityEntries, cityFeed } from '#lib/server/pages.ts';
import type { RequestHandler } from './$types';

export const prerender = true;

export const GET: RequestHandler = async ({ params }) => json(await cityFeed(params.city, languageOf(params.lang)));

export const entries = cityEntries;
