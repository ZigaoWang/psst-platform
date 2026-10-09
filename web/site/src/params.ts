import { defineParams } from '@sveltejs/kit/params';

export const params = defineParams({
	// The optional language prefix: /zh/... is the Simplified Chinese interface.
	zh: (value) => (value === 'zh' ? value : undefined)
});
