// The published output (content format 2), read at build time exactly as the app reads it: the manifest, then each
// pack, checked against its size and hash.
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { PSST_CONTENT_SOURCE } from '$app/env/private';
import type { City, CityPack, Common, Manifest, Place } from '#lib/types.ts';

async function read(path: string): Promise<Buffer> {
	if (/^https:\/\//.test(PSST_CONTENT_SOURCE)) {
		const response = await fetch(`${PSST_CONTENT_SOURCE.replace(/\/$/, '')}/${path}`);
		if (!response.ok) throw new Error(`${path}: ${response.status}`);
		return Buffer.from(await response.arrayBuffer());
	}
	return readFile(join(PSST_CONTENT_SOURCE, path));
}

async function pack<T>(entry: { file: string; sha256: string; bytes: number }): Promise<T> {
	const data = await read(entry.file);
	if (data.length !== entry.bytes || createHash('sha256').update(data).digest('hex') !== entry.sha256) {
		throw new Error(`${entry.file} doesn't match its hash`);
	}
	return JSON.parse(gunzipSync(data).toString('utf8')) as T;
}

export interface Content {
	manifest: Manifest;
	common: Common;
	cities: City[];
	places: Map<string, Place & { cityId: string }>;
	packs: Map<string, CityPack>;
}

let loaded: Promise<Content> | null = null;

export function content(): Promise<Content> {
	loaded ??= (async () => {
		if (!PSST_CONTENT_SOURCE) throw new Error('PSST_CONTENT_SOURCE is not set');
		const manifest = JSON.parse((await read('manifest.json')).toString('utf8')) as Manifest;
		const common = await pack<Common>(manifest.common);
		const packs = new Map<string, CityPack>();
		const places = new Map<string, Place & { cityId: string }>();
		for (const entry of manifest.cities) {
			const city = await pack<CityPack>(entry);
			packs.set(entry.cityId, city);
			for (const place of city.places) places.set(place.id, { ...place, cityId: entry.cityId });
		}
		return { manifest, common, cities: common.cities, places, packs };
	})();
	return loaded;
}
