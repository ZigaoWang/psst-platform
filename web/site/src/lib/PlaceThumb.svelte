<script lang="ts">
	// A place's picture: its photo, or its kind's color with the kind's glyph, as the app shows a place without one.
	import Icon from './Icon.svelte';
	import { KIND_COLORS, onKind } from './icons.ts';

	let { kind, photo = null, size = 22 }: { kind: string; photo?: string | null; size?: number } = $props();
</script>

<span class="thumb" style:--kind={KIND_COLORS[kind] ?? '#5f6368'} style:color={onKind(kind)}>
	{#if photo}<img src={`/images/${photo}`} alt="" loading="lazy" decoding="async" />
	{:else}<Icon name={kind} {size} />{/if}
</span>

<style>
	.thumb {
		display: grid;
		place-items: center;
		width: 100%;
		height: 100%;
		background: var(--kind);
		overflow: hidden;
	}
	img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
</style>
