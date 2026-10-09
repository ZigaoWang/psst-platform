<script lang="ts">
	let { label, value, href, tone }: { label: string; value: string | number; href?: string; tone?: 'warn' | 'danger' } =
		$props();
</script>

<svelte:element this={href ? 'a' : 'div'} {href} class="stat {tone ?? ''}">
	<span class="value">{value}</span>
	<span class="label">{label}</span>
</svelte:element>

<style>
	.stat {
		display: flex;
		flex-direction: column;
		gap: var(--s1);
		padding: var(--s3) var(--s4);
		border: 1px solid var(--line);
		border-radius: var(--r2);
		background: var(--surface);
		color: var(--text);
		text-decoration: none;
		box-shadow: var(--shadow);
	}
	a.stat:hover {
		border-color: var(--line-strong);
	}
	.value {
		font-size: var(--text-lg);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.label {
		color: var(--text-muted);
		font-size: var(--text-sm);
	}
	.warn .value {
		color: var(--warn);
	}
	.danger .value {
		color: var(--danger);
	}
</style>
