// Content format 2, as published (format/v2/*.schema.json). Optional fields are additions older apps ignore.
export interface PackEntry {
	file: string;
	sha256: string;
	bytes: number;
}

export interface Manifest {
	formatVersion: 2;
	contentVersion: string;
	generatedAt: string;
	common: PackEntry;
	cities: (PackEntry & { cityId: string })[];
	counts?: { places: number; facts: number; trails?: number };
}

export type Names = Record<string, string>;

export interface City {
	id: string;
	name: string;
	names?: Names;
	countryCode: string;
	bounds: { south: number; west: number; north: number; east: number };
	placeCount: number;
}

export interface Area {
	id: string;
	level: string;
	name: string;
	names?: Names;
	cityId: string;
}

export interface Tag {
	id: string;
	name: string;
	type: string;
	wikidataId?: string | null;
	names?: Names;
	aliases?: string[];
	placeCount: number;
}

export interface Common {
	cities: City[];
	areas: Area[];
	tags: Tag[];
	legacyIds: Record<string, string>;
}

export interface Source {
	title: string;
	publisher: string;
	url: string;
}

export interface Claim {
	text: string;
	sources: number[];
}

export interface Story {
	id: string;
	category: string;
	veracity: 'fact' | 'legend' | 'disputed';
	headline: string;
	short: string;
	long: string;
	look?: string;
	myth?: string;
	tags?: string[];
	sources: Source[];
	claims?: Claim[];
	lastVerified?: string | null;
	translations?: Record<string, Partial<Record<'headline' | 'short' | 'long' | 'look' | 'myth', string>>>;
}

export interface KeyFact {
	property: string;
	label: string;
	value: string;
}

export interface Guide {
	id: string;
	identifier: string;
	about: string;
	wikidataId?: string | null;
	sources: Source[];
	keyFacts: KeyFact[];
	claims?: Claim[];
	translations?: Record<string, Partial<Record<'identifier' | 'about', string>>>;
}

export interface Rendition {
	file: string;
	width: number;
	height: number;
}

export interface Photo {
	id: string;
	kind: 'photo' | 'historic';
	year?: number | null;
	alt: string;
	focus: [number, number];
	full: Rendition;
	thumb: Rendition;
	pair?: string;
	credit: { author: string; authorUrl?: string | null; license: string; licenseUrl?: string | null;
		sourceUrl: string; source?: string; title?: string | null };
}

export interface Place {
	id: string;
	name: string;
	localName?: { lang: string; name: string } | null;
	names?: Names;
	kind: string;
	size: 'small' | 'medium' | 'large';
	lat: number;
	lon: number;
	location: { source: 'wikidata' | 'osm'; ref: string; license: string };
	countryCode?: string | null;
	districtId?: string | null;
	neighborhoodId?: string | null;
	facts: Story[];
	guide?: Guide;
	images?: Photo[];
}

export interface Trail {
	id: string;
	title: string;
	intro: string;
	stops: { placeId: string; note: string }[];
	tags: string[];
	translations?: Record<string, { title?: string; intro?: string; stopNotes?: string[] }>;
}

export interface CityPack {
	formatVersion: 2;
	cityId: string;
	places: Place[];
	trails?: Trail[];
}
