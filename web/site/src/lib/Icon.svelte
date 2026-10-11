<script lang="ts">
	import { ICONS } from './icons.ts';

	let { name, size = 18, stroke = 2 }: { name: string; size?: number; stroke?: number } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width={stroke}
	stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
	{#each ICONS[name] ?? [] as d, i (i)}<path {d} />{/each}
</svg>
