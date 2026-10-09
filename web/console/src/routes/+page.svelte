<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Stat from '@psst/ui/Stat.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, relative } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const a = $derived(data.attention);
</script>

<svelte:head><title>Home · Psst console</title></svelte:head>

<PageHeader title="Home" subtitle="What is running, what needs an editor, and where each city stands." />

<section aria-labelledby="attention">
	<h2 id="attention">Needs an editor</h2>
	<div class="grid">
		<Stat label="Escalations waiting" value={count(a.escalations)} href="/admin/checks" />
		<Stat label="Failed tasks" value={count(a.failed_tasks)} href="/admin/tasks?state=failed"
			tone={Number(a.failed_tasks) ? 'danger' : undefined} />
		<Stat label="Open reader reports" value={count(a.open_reports)} href="/admin/reports"
			tone={Number(a.open_reports) ? 'warn' : undefined} />
		<Stat label="Audits failed in 14 days" value={count(a.failed_audits)} href="/admin/checks"
			tone={Number(a.failed_audits) ? 'danger' : undefined} />
		<Stat label="Accepted, not yet publishable" value={count(a.held_back)} href="/admin/publish" />
	</div>
</section>

<section aria-labelledby="queue">
	<h2 id="queue">Queue</h2>
	<div class="grid">
		<Stat label="Tasks waiting" value={count(a.queued)} href="/admin/tasks?state=queued" />
		<Stat label="Tasks leased" value={count(a.leased)} href="/admin/tasks?state=leased" />
		<Stat label="Oldest tool check waiting" value={a.oldest_tool_check ? relative(a.oldest_tool_check) : 'none'}
			tone={a.oldest_tool_check ? 'warn' : undefined} />
	</div>
</section>

<section aria-labelledby="workers">
	<h2 id="workers">Workers running</h2>
	{#if data.workers.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Run</th><th>Model</th><th>Started</th><th>Last lease</th><th class="num">Tasks done</th></tr></thead>
				<tbody>
					{#each data.workers as run (run.id)}
						<tr>
							<td><a href={`/admin/runs/${run.id}`} class="mono">{run.id}</a></td>
							<td>{run.model}</td>
							<td>{relative(run.started_at)}</td>
							<td>{run.last_lease ? relative(run.last_lease) : 'none yet'}</td>
							<td class="num">{count(run.done)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No workers are running.</Empty>
	{/if}
</section>

<section aria-labelledby="cities">
	<h2 id="cities">Cities</h2>
	{#if data.cities.length}
		<div class="table-wrap">
			<table>
				<thead>
					<tr>
						<th>City</th><th class="num">Cells researched</th><th class="num">Stories published</th>
						<th class="num">Accepted</th><th class="num">Checking</th><th class="num">Draft</th>
						<th class="num">Guides ready</th>
					</tr>
				</thead>
				<tbody>
					{#each data.cities as city (city.slug)}
						<tr>
							<td><a href={`/admin/cities/${city.slug}`}>{city.name}</a></td>
							<td class="num">{count(city.researched)} of {count(city.cells)}</td>
							<td class="num">{count(city.published)}</td>
							<td class="num">{count(city.accepted)}</td>
							<td class="num">{count(city.checking)}</td>
							<td class="num">{count(city.draft)}</td>
							<td class="num">{count(city.guides)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No cities are set up yet.</Empty>
	{/if}
</section>
