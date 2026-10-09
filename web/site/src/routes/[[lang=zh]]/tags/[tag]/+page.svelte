<script lang="ts">
	import { field, name, t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const language = $derived(data.language);
	const title = $derived(language === 'zh-Hans' ? (data.tag.names['zh-Hans'] ?? data.tag.name) : data.tag.name);
</script>

<svelte:head>
	<title>{title} · Psst</title>
	<meta name="description" content={`${t(language, 'Places with this tag')}: ${data.places.map((p) => p.name).join(', ')}`} />
</svelte:head>

<h1>{title}</h1>
<p class="muted">{t(language, 'Places with this tag')}</p>
<ul class="list">
	{#each data.places as place (place.id)}
		<li>
			<a href={link(language, place.href)}>{name(language, place)}</a>
			<span class="muted">{place.city}</span>
			<p>{field(language, place, 'headline')}</p>
		</li>
	{/each}
</ul>

<style>
	.list {
		list-style: none;
		padding: 0;
	}
	.list li {
		padding: var(--s3) 0;
		border-bottom: 1px solid var(--line);
	}
	.list p {
		margin: var(--s1) 0 0;
	}
</style>
