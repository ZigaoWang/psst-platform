<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, date } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>Demand · Psst console</title></svelte:head>
<PageHeader title="Demand" subtitle="Empty map areas app users looked at in the last 90 days, most viewed first." />
{#if data.cells.length}
	<div class="table-wrap">
		<table>
			<thead><tr><th>Area (H3 resolution 5)</th><th class="num">Views</th><th>Last viewed</th></tr></thead>
			<tbody>{#each data.cells as c (c.cell)}<tr><td class="mono">{c.cell}</td><td class="num">{count(c.views)}</td><td>{date(c.last_day)}</td></tr>{/each}</tbody>
		</table>
	</div>
{:else}
	<Empty>No demand recorded yet.</Empty>
{/if}
