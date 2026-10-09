<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, date, percent } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
	const states = ['draft', 'checking', 'accepted', 'published', 'retired'];
	const types = ['story', 'guide', 'photo', 'trail', 'translation'];
	function n(type: string, state: string) {
		return Number(data.items.find((r) => r.type === type && r.state === state)?.n ?? 0);
	}
</script>

<svelte:head><title>{data.city.name} · Psst console</title></svelte:head>
<PageHeader title={data.city.name} subtitle={`${data.city.country_code} · local languages: ${data.city.local_languages.join(', ') || 'English'}`}>
	{#snippet actions()}
		<a class="button" href={`/admin/places?city=${data.city.slug}`}>Places</a>
		<a class="button" href={`/admin/map?city=${data.city.slug}`}>Map</a>
	{/snippet}
</PageHeader>

{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<section>
	<h2>Content by state</h2>
	<div class="table-wrap">
		<table>
			<thead><tr><th>Type</th>{#each states as state (state)}<th class="num"><Badge {state} /></th>{/each}</tr></thead>
			<tbody>
				{#each types as type (type)}
					<tr><td>{type}</td>{#each states as state (state)}<td class="num">{count(n(type, state))}</td>{/each}</tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>

<section>
	<h2>Research coverage</h2>
	{#if data.cells.length}
		<div class="grid">
			{#each data.cells as cell (cell.state)}
				<div class="table-wrap pad"><strong>{count(cell.n)}</strong> cells {cell.state}</div>
			{/each}
		</div>
	{:else}
		<Empty>No research cells are planned for this city.</Empty>
	{/if}
</section>

<section>
	<h2>Queue research</h2>
	<form method="POST" action="?/research" class="filters">
		<label>Cells, most wanted first <input name="cells" type="number" min="1" max="50" value="10" /></label>
		<button type="submit">Queue research</button>
	</form>
</section>

<section>
	<h2>Photos</h2>
	<form method="POST" action="?/photos"><button type="submit">Queue photo searches</button></form>
</section>

<section>
	<h2>Open tasks</h2>
	{#if data.tasks.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Type</th><th>State</th><th class="num">Tasks</th></tr></thead>
				<tbody>
					{#each data.tasks as row (row.type + row.state)}
						<tr>
							<td><a href={`/admin/tasks?type=${row.type}&state=${row.state}`}>{row.type}</a></td>
							<td><Badge state={row.state} /></td>
							<td class="num">{count(row.n)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No open tasks.</Empty>
	{/if}
</section>

<section>
	<h2>Translations</h2>
	<p>{count(data.untranslated)} published items have no Simplified Chinese translation.</p>
	{#if Number(data.untranslated) > 0}
		<form method="POST" action="?/translate"><button type="submit">Queue translations</button></form>
	{/if}
</section>

<section>
	<h2>Audits</h2>
	{#if data.audits.length}
		<div class="table-wrap">
			<table>
				<thead>
					<tr><th>Batch</th><th>Type</th><th class="num">Size</th><th class="num">Sampled</th>
						<th class="num">Errors</th><th class="num">Rate</th><th class="num">Threshold</th><th>Outcome</th><th>Planned</th></tr>
				</thead>
				<tbody>
					{#each data.audits as batch (batch.id)}
						<tr>
							<td class="mono">{batch.id}</td><td>{batch.type}</td>
							<td class="num">{count(batch.size)}</td><td class="num">{count(batch.sample_size)}</td>
							<td class="num">{batch.errors ?? ''}</td><td class="num">{percent(batch.rate)}</td>
							<td class="num">{percent(batch.threshold)}</td>
							<td><Badge state={batch.outcome === 'passed' ? 'published' : batch.outcome === 'failed' ? 'failed' : 'checking'} label={batch.outcome} /></td>
							<td>{date(batch.created_at)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No audits yet.</Empty>
	{/if}
</section>

<style>
	.pad {
		padding: var(--s3) var(--s4);
	}
</style>
