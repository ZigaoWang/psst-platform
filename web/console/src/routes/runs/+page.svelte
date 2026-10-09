<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Pager from '@psst/ui/Pager.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, time } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>Runs · Psst console</title></svelte:head>
<PageHeader title="Runs" subtitle="Every worker, system, publisher, and editor run." />

<form class="filters" method="GET">
	<label>Kind
		<select name="kind"><option value="">All kinds</option>
			{#each ['worker', 'system', 'publisher', 'editor'] as k (k)}<option value={k} selected={k === data.kind}>{k}</option>{/each}
		</select>
	</label>
	<button type="submit">Show</button>
</form>

{#if data.runs.length}
	<div class="table-wrap">
		<table>
			<thead><tr><th>Run</th><th>Kind</th><th>Model</th><th>Started</th><th>Ended</th><th class="num">Tasks done</th></tr></thead>
			<tbody>
				{#each data.runs as r (r.id)}
					<tr>
						<td><a class="mono" href={`/admin/runs/${r.id}`}>{r.id}</a></td>
						<td>{r.kind}</td><td>{r.model ?? ''}</td><td>{time(r.started_at)}</td>
						<td>{r.ended_at ? time(r.ended_at) : 'running'}</td><td class="num">{count(r.done)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<Pager next={data.next} first={data.first} />
{:else}
	<Empty>No runs yet.</Empty>
{/if}
