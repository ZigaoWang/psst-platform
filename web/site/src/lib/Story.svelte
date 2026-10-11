<script lang="ts">
	// A story as a card: its label, headline, and short line, with the whole story a tap away. "Look" is an action:
	// it says where to stand and what to see, and brings the map to the place. The popular version, for a legend,
	// sits inside the opened story.
	import Icon from './Icon.svelte';
	import { field, t, type Language } from './i18n.ts';
	import { link } from './links.ts';
	import type { Story } from './types.ts';

	type ShownTag = { name: string; names: Record<string, string>; slug: string };
	let { story, language, open = false, onlook }: {
		story: Omit<Story, 'tags'> & { tags: ShownTag[] }; language: Language; open?: boolean; onlook?: () => void;
	} = $props();
	let expanded = $state(false);
	$effect(() => { expanded = open; });
	const paragraphs = $derived(field(language, story, 'long').split(/\n\n+/));
</script>

<article class="story" id={story.id} class:expanded style:--cat={`var(--cat-${story.category})`}>
	<p class="labels">
		<span class="category">{t(language, story.category)}</span>
		{#if story.veracity !== 'fact'}
			<span class="veracity {story.veracity}"><Icon name="legend" size={12} />{t(language, story.veracity === 'legend' ? 'Legend' : 'Disputed')}</span>
		{/if}
	</p>
	<h3>{field(language, story, 'headline')}</h3>
	<p class="short">{field(language, story, 'short')}</p>
	<div class="more" id={`${story.id}-more`} hidden={!expanded}>
		{#each paragraphs as paragraph, i (i)}<p>{paragraph}</p>{/each}
		{#if story.myth}
			<div class="myth">
				<strong>{t(language, 'The popular version')}</strong>
				<p>{field(language, story, 'myth')}</p>
			</div>
		{/if}
		{#if story.tags.length}
			<p class="tags">
				{#each story.tags as tag (tag.slug)}
					<a href={link(language, `/tags/${tag.slug}`)}>{language === 'zh-Hans' ? (tag.names['zh-Hans'] ?? tag.name) : tag.name}</a>
				{/each}
			</p>
		{/if}
	</div>
	<button type="button" class="toggle" aria-expanded={expanded} aria-controls={`${story.id}-more`}
		onclick={() => (expanded = !expanded)}>
		{expanded ? t(language, 'Show less') : t(language, 'Read the story')}
		<span class="chev" class:up={expanded}><Icon name="chevron" size={16} /></span>
	</button>
	{#if story.look}
		<button type="button" class="look" onclick={() => onlook?.()}>
			<span class="look-icon"><Icon name="eye" size={18} /></span>
			<span><strong>{t(language, 'Look')}</strong>{field(language, story, 'look')}</span>
		</button>
	{/if}
</article>

<style>
	.story {
		background: var(--surface);
		border-radius: 20px;
		padding: var(--s4);
		box-shadow: var(--shadow);
	}
	.labels {
		display: flex;
		gap: var(--s2);
		margin: 0 0 var(--s1);
		font-size: var(--text-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.category {
		color: var(--cat);
	}
	.veracity {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
	}
	.veracity.legend {
		color: var(--legend);
	}
	.veracity.disputed {
		color: var(--disputed);
	}
	h3 {
		margin: 0;
		font-size: 1.15rem;
		line-height: 1.3;
		letter-spacing: -0.01em;
	}
	.short {
		margin: var(--s2) 0 0;
		line-height: 1.5;
	}
	.more p {
		line-height: 1.6;
	}
	.myth {
		margin: var(--s3) 0;
		padding: var(--s3);
		border-left: 3px solid var(--legend);
		background: color-mix(in srgb, var(--legend) 8%, transparent);
		border-radius: 0 var(--r2) var(--r2) 0;
	}
	.myth p {
		margin: var(--s1) 0 0;
	}
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s2);
	}
	.tags a {
		font-size: var(--text-sm);
		color: var(--text-muted);
	}
	.toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		margin-top: var(--s2);
		padding: var(--s1) 0;
		border: 0;
		background: none;
		color: var(--link);
		font: inherit;
		font-weight: 600;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.chev {
		display: inline-flex;
		transition: transform 200ms ease;
	}
	.chev.up {
		transform: rotate(180deg);
	}
	.look {
		display: flex;
		gap: var(--s3);
		align-items: flex-start;
		width: 100%;
		margin-top: var(--s3);
		padding: var(--s3);
		border: 1px solid var(--line);
		border-radius: 14px;
		background: none;
		color: var(--text);
		font: inherit;
		text-align: left;
		cursor: pointer;
		transition: border-color 160ms ease, background 160ms ease;
	}
	.look:hover {
		border-color: var(--text-muted);
		background: var(--bg);
	}
	.look strong {
		display: block;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-muted);
	}
	.look-icon {
		flex: none;
		display: grid;
		place-items: center;
		width: 2.25rem;
		height: 2.25rem;
		border-radius: 50%;
		background: var(--ink);
		color: var(--paper);
	}
</style>
