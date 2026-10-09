<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Pager from '@psst/ui/Pager.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { relative } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const states = ['queued', 'leased', 'done', 'failed', 'cancelled'];
</script>

<svelte:head><title>Tasks · Psst console</title></svelte:head>
<PageHeader title="Tasks" />

<form class="filters" method="GET">
	<label>Type
		<select name="type"><option value="">All types</option>
			{#each data.types as t (t)}<option value={t} selected={t === data.type}>{t}</option>{/each}
		</select>
	</label>
	<label>State
		<select name="state"><option value="">All states</option>
			{#each states as s (s)}<option value={s} selected={s === data.state}>{s}</option>{/each}
		</select>
	</label>
	<button type="submit">Show</button>
</form>

{#if data.tasks.length}
	<div class="table-wrap">
		<table>
			<thead><tr><th>Task</th><th>Type</th><th>City</th><th>Model</th><th>State</th><th class="num">Attempts</th><th>Created</th><th>Problem</th></tr></thead>
			<tbody>
				{#each data.tasks as t (t.id)}
					<tr>
						<td><a class="mono" href={`/admin/tasks/${t.id}`}>{t.id}</a></td>
						<td>{t.type}</td><td>{t.city ?? ''}</td><td>{t.model ?? 'system'}</td>
						<td><Badge state={t.state} /></td><td class="num">{t.attempts}</td>
						<td>{relative(t.created_at)}</td><td>{t.problem ?? ''}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<Pager next={data.next} first={data.first} />
{:else}
	<Empty>No tasks match.</Empty>
{/if}
