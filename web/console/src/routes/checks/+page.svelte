<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, percent, relative } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
</script>

<svelte:head><title>Checks · Psst console</title></svelte:head>
<PageHeader title="Checks" subtitle="Escalations, audits, and how often each model's verdicts were overturned." />
{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<section>
	<h2>Escalations</h2>
	{#if data.escalations.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Item</th><th>City</th><th class="num">Claims</th><th>State</th><th>Waiting since</th></tr></thead>
				<tbody>
					{#each data.escalations as t (t.id)}
						<tr>
							<td><a href={`/admin/items/${t.item_id}`}>{t.item_id}</a></td>
							<td>{t.city ?? ''}</td>
							<td class="num">{t.input.claims?.length ?? 0}{t.input.item ? ' and the item' : ''}</td>
							<td><Badge state={t.state} /></td>
							<td>{relative(t.created_at)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No escalations are waiting.</Empty>
	{/if}
</section>

<section>
	<h2>Audits</h2>
	<form method="POST" action="?/plan" class="filters">
		<label>Batch groups smaller than the minimum
			<select name="force"><option value="no">No, wait for full batches</option><option value="yes">Yes, audit what is waiting now</option></select>
		</label>
		<button type="submit">Plan audits</button>
	</form>
	{#if data.batches.length}
		<div class="table-wrap">
			<table>
				<thead>
					<tr><th>Batch</th><th>City</th><th>Type</th><th class="num">Size</th><th class="num">Sampled</th>
						<th class="num">Waiting</th><th class="num">Error rate</th><th class="num">Threshold</th><th>Outcome</th></tr>
				</thead>
				<tbody>
					{#each data.batches as b (b.id)}
						<tr>
							<td class="mono">{b.id}</td><td>{b.city}</td><td>{b.type}</td>
							<td class="num">{count(b.size)}</td><td class="num">{count(b.sample_size)}</td>
							<td class="num">{count(b.waiting)}</td>
							<td class="num">{b.rate === null ? '' : `${percent(b.rate)} (${b.errors})`}</td>
							<td class="num">{percent(b.threshold)}</td>
							<td><Badge state={b.outcome === 'passed' ? 'published' : b.outcome === 'failed' ? 'failed' : 'checking'} label={b.outcome} /></td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No audits yet.</Empty>
	{/if}
</section>

<section>
	<h2>Measured accuracy</h2>
	<p class="muted">A verdict counts as judged once a later escalation, audit, or editor ruled on the same claim or item.</p>
	{#if data.accuracy.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Check</th><th>Model</th><th class="num">Verdicts</th><th class="num">Judged</th><th class="num">Overturned</th><th class="num">Error rate</th></tr></thead>
				<tbody>
					{#each data.accuracy as row (row.kind + row.model)}
						<tr>
							<td>{row.kind}</td><td>{row.model}</td><td class="num">{count(row.verdicts)}</td>
							<td class="num">{count(row.judged)}</td><td class="num">{count(row.overturned)}</td>
							<td class="num">{percent(row.error_rate)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No model verdicts yet.</Empty>
	{/if}
</section>
