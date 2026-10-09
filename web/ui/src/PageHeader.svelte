<script lang="ts">
	import type { Snippet } from 'svelte';

	let { title, subtitle, actions }: { title: string; subtitle?: string; actions?: Snippet } = $props();
</script>

<header>
	<div>
		<h1>{title}</h1>
		{#if subtitle}<p>{subtitle}</p>{/if}
	</div>
	{#if actions}<div class="actions">{@render actions()}</div>{/if}
</header>

<style>
	header {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		justify-content: space-between;
		gap: var(--s3);
		margin-bottom: var(--s5);
	}
	h1 {
		margin: 0;
		font-size: var(--text-xl);
		line-height: 1.2;
	}
	p {
		margin: var(--s1) 0 0;
		color: var(--text-muted);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--s2);
	}
</style>
