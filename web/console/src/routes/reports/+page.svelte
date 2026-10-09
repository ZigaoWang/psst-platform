<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { time } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>Reports · Psst console</title></svelte:head>
<PageHeader title="Reports" subtitle="Problems readers reported. Each one sends its item back to checking." />
{#if data.reports.length}
	<div class="table-wrap">
		<table>
			<thead><tr><th>Received</th><th>About</th><th>Reason</th><th>Message</th></tr></thead>
			<tbody>
				{#each data.reports as r (r.id)}
					<tr>
						<td>{time(r.created_at)}</td>
						<td><a href={`/admin/items/${r.item_id}`}>{r.type} at {r.place ?? r.item_id}</a></td>
						<td>{r.reason}</td><td>{r.message ?? ''}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	<Empty>No open reports.</Empty>
{/if}
