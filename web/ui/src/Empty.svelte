<script lang="ts">
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();
</script>

<p class="empty">{@render children()}</p>

<style>
	.empty {
		margin: 0;
		padding: var(--s5) var(--s4);
		border: 1px dashed var(--line-strong);
		border-radius: var(--r2);
		color: var(--text-muted);
		text-align: center;
	}
</style>
