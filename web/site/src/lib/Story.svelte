<script lang="ts">
	import { field, t, type Language } from './i18n.ts';
	import { link } from './links.ts';
	import type { Story } from './types.ts';

	type ShownTag = { name: string; names: Record<string, string>; slug: string };
	let { story, language }: { story: Omit<Story, 'tags'> & { tags: ShownTag[] }; language: Language } = $props();
	const paragraphs = $derived(field(language, story, 'long').split(/\n\n+/));
</script>

<article class="story" id={story.id}>
	<p class="labels">
		<span class="category">{t(language, story.category)}</span>
		{#if story.veracity !== 'fact'}
			<span class="veracity {story.veracity}">{t(language, story.veracity === 'legend' ? 'Legend' : 'Disputed')}</span>
		{/if}
	</p>
	<h3>{field(language, story, 'headline')}</h3>
	<p class="short">{field(language, story, 'short')}</p>
	{#each paragraphs as paragraph, i (i)}<p>{paragraph}</p>{/each}
	{#if story.myth}
		<p class="myth"><strong>{t(language, 'The popular version')}:</strong> {field(language, story, 'myth')}</p>
	{/if}
	{#if story.look}
		<p class="look"><strong>{t(language, 'Look')}:</strong> {field(language, story, 'look')}</p>
	{/if}
	{#if story.tags.length}
		<p class="tags">
			{#each story.tags as tag (tag.slug)}
				<a href={link(language, `/tags/${tag.slug}`)}>{language === 'zh-Hans' ? (tag.names['zh-Hans'] ?? tag.name) : tag.name}</a>
			{/each}
		</p>
	{/if}
	<details>
		<summary>{t(language, 'Sources')} ({story.sources.length})</summary>
		<ol class="sources">
			{#each story.sources as source, i (i)}
				<li id={`${story.id}-source-${i + 1}`}><a href={source.url} rel="external noopener">{source.title}</a>, {source.publisher}</li>
			{/each}
		</ol>
		{#if story.claims?.length}
			<h4>{t(language, 'Claims and their sources')}</h4>
			<ul class="claims">
				{#each story.claims as claim, i (i)}
					<li>{claim.text}
						{#each claim.sources as index (index)}<a class="ref" href={`#${story.id}-source-${index + 1}`}>[{index + 1}]</a>{/each}
					</li>
				{/each}
			</ul>
		{/if}
		{#if story.lastVerified}<p class="muted small">{t(language, 'Last checked')}: {story.lastVerified}</p>{/if}
	</details>
</article>

<style>
	.story {
		padding: var(--s5) 0;
		border-top: 1px solid var(--line);
	}
	.labels {
		display: flex;
		gap: var(--s2);
		margin: 0;
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.category {
		color: var(--text-muted);
	}
	.veracity.legend {
		color: var(--legend);
	}
	.veracity.disputed {
		color: var(--disputed);
	}
	h3 {
		font-size: var(--text-lg);
		margin: var(--s2) 0;
	}
	.short {
		font-weight: 600;
	}
	.look,
	.myth {
		padding: var(--s3) var(--s4);
		border-radius: var(--r2);
		background: var(--surface-sunk);
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s2);
	}
	.tags a {
		padding: 0.1em 0.6em;
		border: 1px solid var(--line-strong);
		border-radius: 999px;
		font-size: var(--text-sm);
		text-decoration: none;
	}
	summary {
		cursor: pointer;
		color: var(--text-muted);
	}
	.sources,
	.claims {
		font-size: var(--text-sm);
	}
	h4 {
		font-size: var(--text-sm);
		margin: var(--s3) 0 var(--s1);
	}
	.ref {
		margin-left: 0.25em;
		text-decoration: none;
	}
	.small {
		font-size: var(--text-sm);
	}
</style>
