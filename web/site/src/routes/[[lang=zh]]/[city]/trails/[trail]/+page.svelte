<script lang="ts">
	import { field, name, t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const language = $derived(data.language);
	const title = $derived(field(language, data.trail, 'title'));
</script>

<svelte:head>
	<title>{title} · Psst</title>
	<meta name="description" content={field(language, data.trail, 'intro')} />
</svelte:head>

<p class="muted"><a href={link(language, `/${data.city.slug}`)}>{language === 'zh-Hans' ? (data.city.names['zh-Hans'] ?? data.city.name) : data.city.name}</a></p>
<h1>{title}</h1>
<p>{field(language, data.trail, 'intro')}</p>

<h2>{t(language, 'Stops')}</h2>
<ol class="stops">
	{#each data.trail.stops as stop, i (i)}
		<li>
			<a href={link(language, `/${data.city.slug}/${stop.href}`)}>{name(language, stop)}</a>
			<p>{language === 'zh-Hans' && stop.noteZh ? stop.noteZh : stop.note}</p>
		</li>
	{/each}
</ol>

<style>
	.stops li {
		padding: var(--s2) 0;
	}
	.stops p {
		margin: var(--s1) 0 0;
	}
</style>
