// Plain formatting shared by the console and the website.

const dateFormat = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' });
const timeFormat = new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' });
const numberFormat = new Intl.NumberFormat('en-US');

/** @param {string | Date | null | undefined} value */
export function date(value) {
	return value ? dateFormat.format(new Date(value)) : '';
}

/** A date and time in UTC, which every server log and record uses. */
/** @param {string | Date | null | undefined} value */
export function time(value) {
	return value ? `${timeFormat.format(new Date(value))} UTC` : '';
}

/** @param {number | string | null | undefined} value */
export function count(value) {
	return value === null || value === undefined ? '' : numberFormat.format(Number(value));
}

/** @param {number | string | null | undefined} value */
export function percent(value) {
	if (value === null || value === undefined) return '';
	return `${(Number(value) * 100).toFixed(1)}%`;
}

/** "3 minutes ago", "in 2 hours". @param {string | Date | null | undefined} value */
export function relative(value, now = Date.now()) {
	if (!value) return '';
	const seconds = Math.round((new Date(value).getTime() - now) / 1000);
	const units = /** @type {const} */ ([['day', 86400], ['hour', 3600], ['minute', 60], ['second', 1]]);
	const rtf = new Intl.RelativeTimeFormat('en-US', { numeric: 'auto' });
	for (const [unit, size] of units) {
		if (Math.abs(seconds) >= size || unit === 'second') return rtf.format(Math.round(seconds / size), unit);
	}
	return '';
}
