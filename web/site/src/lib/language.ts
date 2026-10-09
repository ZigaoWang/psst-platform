import type { Language } from './i18n.ts';

export function languageOf(param: string | undefined): Language {
	return param === 'zh' ? 'zh-Hans' : 'en';
}
