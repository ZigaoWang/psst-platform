<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, time } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
	const stateFor: Record<string, string> = { promoted: 'published', staged: 'checking', failed: 'failed', rolled_back: 'retired' };
</script>

<svelte:head><title>Publish · Psst console</title></svelte:head>
<PageHeader title="Publish" subtitle="What the next publish contains, what waits, and every version so far." />
{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<section>
	<h2>Next publish</h2>
	{#if data.next.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>City</th><th>Type</th><th class="num">New or changed</th><th class="num">In the output</th></tr></thead>
				<tbody>
					{#each data.next as row, i (i)}
						<tr><td>{row.city}</td><td>{row.type}</td><td class="num">{count(row.new)}</td><td class="num">{count(row.total)}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>Nothing has passed its audit yet.</Empty>
	{/if}
	<div class="buttons">
		<form method="POST" action="?/check"><button type="submit">Check without publishing</button></form>
		<form method="POST" action="?/publish">
			<label>If fewer places or stories is expected, say why <input name="allow_shrink" /></label>
			<button type="submit" class="primary">Publish</button>
		</form>
		<form method="POST" action="?/rollback"><button type="submit" class="danger">Roll back to the version before</button></form>
	</div>
</section>

<section>
	<h2>Waiting</h2>
	{#if data.held.length}
		<ul>{#each data.held as h, i (i)}<li>{h.city}: {count(h.n)} {h.type} {h.reason}</li>{/each}</ul>
	{:else}
		<Empty>Nothing accepted is waiting.</Empty>
	{/if}
</section>

<section>
	<h2>Requests</h2>
	{#if data.requests.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Asked</th><th>What</th><th>State</th><th>Outcome</th></tr></thead>
				<tbody>
					{#each data.requests as r (r.id)}
						<tr>
							<td>{time(r.created_at)}</td>
							<td>{r.type}{r.input?.only_staging ? ' (check only)' : ''}</td>
							<td><Badge state={r.state} /></td>
							<td>
								{#if r.result}
									{r.result.ok ? (r.result.promoted ? `promoted ${r.result.version}` : r.result.to ? `rolled back to ${r.result.to}` : `staging checked: ${r.result.version}`) : r.result.error}
									{#if r.result.problems?.length}<ul>{#each r.result.problems as p, i (i)}<li>{p}</li>{/each}</ul>{/if}
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No requests yet.</Empty>
	{/if}
</section>

<section>
	<h2>Versions</h2>
	{#if data.publications.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Version</th><th>State</th><th class="num">Places</th><th class="num">Stories</th><th>Changes</th><th>Checks</th></tr></thead>
				<tbody>
					{#each data.publications as p (p.id)}
						<tr>
							<td class="mono">{p.content_version}</td>
							<td><Badge state={stateFor[p.state] ?? 'draft'} label={p.state.replace('_', ' ')} /></td>
							<td class="num">{count(p.counts.places)}</td>
							<td class="num">{count(p.counts.facts)}</td>
							<td>{p.changes.added?.length ?? 0} added, {p.changes.updated?.length ?? 0} updated, {p.changes.removed?.length ?? 0} removed</td>
							<td>{p.checks.length ? p.checks.join('; ') : 'passed'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>Nothing has been published yet.</Empty>
	{/if}
</section>

<style>
	.buttons {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--s4);
		margin-top: var(--s4);
	}
	.buttons form {
		display: flex;
		align-items: flex-end;
		gap: var(--s2);
	}
</style>
