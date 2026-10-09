<script lang="ts">
	// A state (draft, checking, published, leased, failed, ...) in the one color scale every list uses.
	let { state, label }: { state: string; label?: string } = $props();
</script>

<span class="badge" style:--color={`var(--state-${state}, var(--text-muted))`}>{label ?? state}</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 0.35em;
		padding: 0.05em 0.55em;
		border: 1px solid color-mix(in srgb, var(--color) 45%, transparent);
		border-radius: 999px;
		color: var(--color);
		font-size: var(--text-xs);
		font-weight: 600;
		line-height: 1.6;
		white-space: nowrap;
	}
	.badge::before {
		content: '';
		width: 0.5em;
		height: 0.5em;
		border-radius: 50%;
		background: var(--color);
	}
</style>
