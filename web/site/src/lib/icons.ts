// Line icons (24 by 24, stroked), from Lucide (ISC license): one per kind of place, as the app has, and the few the
// interface needs. Drawn inline as SVG and onto the map's pins, so nothing is fetched for them.
export const ICONS: Record<string, string[]> = {
	transit: ['M8 3h8a4 4 0 0 1 4 4v8a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4z', 'M4 11h16', 'M12 3v8', 'm8 19-2 3',
		'm18 22-2-3', 'M8 15h.01', 'M16 15h.01'],
	crossing: ['M8 3 4 7l4 4', 'M4 7h16', 'm16 21 4-4-4-4', 'M20 17H4'],
	street: ['M12 3v3', 'M18.5 13h-13L2 9.5 5.5 6h13L22 9.5Z', 'M12 13v8'],
	building: ['M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z', 'M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2',
		'M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2', 'M10 6h4', 'M10 10h4', 'M10 14h4', 'M10 18h4'],
	worship: ['M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9', 'M10.3 21a1.94 1.94 0 0 0 3.4 0'],
	memorial: ['M3 22h18', 'M6 18v-7', 'M10 18v-7', 'M14 18v-7', 'M18 18v-7', 'M12 2l8 5H4Z'],
	green: ['M8 19a4 4 0 0 1-2.24-7.32A3.5 3.5 0 0 1 9 6.03V6a3 3 0 1 1 6 0v.04a3.5 3.5 0 0 1 3.24 5.65A4 4 0 0 1 16 19Z',
		'M12 19v3'],
	water: ['M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z'],
	culture: ['M12 22a10 10 0 1 1 10-10c0 2.2-1.8 4-4 4h-1.5a2 2 0 0 0-1.5 3.3A2 2 0 0 1 12 22Z', 'M7.5 10.5h.01',
		'M10.5 7h.01', 'M15 7.5h.01'],
	eye: ['M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z', 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z'],
	directions: ['m3 11 19-9-9 19-2-8-8-2z'],
	share: ['M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8', 'm16 6-4-4-4 4', 'M12 2v13'],
	link: ['M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71',
		'M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71'],
	check: ['M20 6 9 17l-5-5'],
	close: ['M18 6 6 18', 'm6 6 12 12'],
	chevron: ['m6 9 6 6 6-6'],
	search: ['M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16z', 'm21 21-4.3-4.3'],
	locate: ['M12 2v3', 'M12 19v3', 'M2 12h3', 'M19 12h3', 'M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z'],
	browse: ['M3 6h.01', 'M3 12h.01', 'M3 18h.01', 'M8 6h13', 'M8 12h13', 'M8 18h13'],
	filter: ['M3 6h18', 'M7 12h10', 'M10 18h4'],
	legend: ['M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20']
};

export const KIND_COLORS: Record<string, string> = {
	transit: '#d3221b', crossing: '#0067b1', street: '#f2a900', building: '#1f3a93', worship: '#7a1f5c',
	memorial: '#74613f', green: '#00783a', water: '#00838c', culture: '#c4005f'
};

/** The glyph color on a kind's color: dark on the yellow of streets, white on the rest (as the app). */
export function onKind(kind: string): string {
	return kind === 'street' ? '#1a1a1a' : '#ffffff';
}
