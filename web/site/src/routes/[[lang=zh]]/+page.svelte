<script lang="ts">
	import { t } from '#lib/i18n.ts';
	import { link } from '#lib/links.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const language = $derived(data.language);
</script>

<svelte:head>
	<title>Psst</title>
	<meta name="description" content={t(language, 'Surprising, sourced stories about places you can stand in front of.')} />
</svelte:head>

<h1>{t(language, 'Surprising, sourced stories about places you can stand in front of.')}</h1>

<h2>{t(language, 'Cities')}</h2>
<ul class="cities">
	{#each data.cities as city (city.id)}
		<li>
			<a href={link(language, `/${city.slug}`)}>
				<span class="name">{language === 'zh-Hans' ? (city.names['zh-Hans'] ?? city.name) : city.name}</span>
				<span class="muted">{city.places} {t(language, 'places')}</span>
			</a>
		</li>
	{/each}
</ul>

<style>
	.cities {
		list-style: none;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
		gap: var(--s3);
	}
	.cities a {
		display: flex;
		flex-direction: column;
		gap: var(--s1);
		padding: var(--s4);
		border: 1px solid var(--line);
		border-radius: var(--r3);
		background: var(--surface);
		color: var(--text);
		text-decoration: none;
		box-shadow: var(--shadow);
	}
	.cities a:hover {
		border-color: var(--line-strong);
	}
	.name {
		font-size: var(--text-lg);
		font-weight: 700;
	}
</style>
