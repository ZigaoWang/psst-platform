<script lang="ts">
	import type { Snippet } from 'svelte';

	// A message about what just happened or what needs attention. Errors are announced to screen readers.
	let { tone = 'info', children }: { tone?: 'info' | 'ok' | 'warn' | 'danger'; children: Snippet } = $props();
</script>

<div class="notice {tone}" role={tone === 'danger' ? 'alert' : 'status'}>{@render children()}</div>

<style>
	.notice {
		padding: var(--s3) var(--s4);
		border: 1px solid var(--line);
		border-radius: var(--r2);
		background: var(--surface);
		margin-bottom: var(--s4);
	}
	.ok {
		border-color: var(--ok);
		background: var(--ok-surface);
	}
	.warn {
		border-color: var(--warn);
		background: var(--warn-surface);
	}
	.danger {
		border-color: var(--danger);
		background: var(--danger-surface);
	}
</style>
