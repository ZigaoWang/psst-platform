<script lang="ts">
	// Keyset paging: "next" carries the last key of this page, so every page is one index range, at any size.
	let { next, first }: { next?: string | null; first?: string | null } = $props();
</script>

{#if next || first}
	<nav class="pager" aria-label="Pages">
		{#if first}<a href={first}>First page</a>{/if}
		{#if next}<a href={next} rel="next">Next page</a>{/if}
	</nav>
{/if}

<style>
	.pager {
		display: flex;
		justify-content: flex-end;
		gap: var(--s4);
		margin-top: var(--s4);
	}
</style>
