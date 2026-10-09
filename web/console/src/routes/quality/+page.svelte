<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, relative } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
	const latest = $derived(data.calibrations.slice(0, 2));
	const agreement = $derived(latest.length === 2
		? latest.reduce((n, c) => n + c.agreed, 0) / latest.reduce((n, c) => n + c.marked, 0) : null);
</script>

<svelte:head><title>Quality · Psst console</title></svelte:head>
<PageHeader title="Quality" subtitle="The review gate, the golden set, and this month's sample to mark." />
{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<section>
	<h2>Review gate</h2>
	{#if data.gate?.open}
		<Notice tone="ok">Open: the reviewer agrees with the editor's marks, so reviews run and publishing may proceed.</Notice>
	{:else}
		<Notice tone="warn">Closed: reviews wait and nothing publishes until a calibration reaches {Math.round(Number(data.gate?.needed ?? 0.9) * 100)} percent agreement.</Notice>
	{/if}
	{#if agreement !== null}<p>Latest agreement: <strong>{Math.round(agreement * 100)} percent</strong> over both folds.</p>{/if}
	{#if data.calibrations.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>When</th><th>Fold</th><th>Model</th><th>Prompt</th><th>Bar</th><th class="num">Agreed</th></tr></thead>
				<tbody>
					{#each data.calibrations as c (c.created_at)}
						<tr><td>{relative(c.created_at)}</td><td>{c.fold}</td><td>{c.model}</td><td class="mono">{c.prompt_version}</td>
							<td class="mono">{c.bar_version ?? 'none'}</td><td class="num">{c.agreed} of {c.marked}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No calibration has run yet.</Empty>
	{/if}
	<p class="muted">Golden set: {data.golden.map((g) => `${count(g.n)} ${g.mark}`).join(', ') || 'empty'}.</p>
</section>

<section>
	<h2>Mark a sample</h2>
	<p class="muted">Optional. Ten published stories, the same all month. Each mark joins the golden set; nothing waits on it.</p>
	{#each data.sample as s (s.id)}
		<article class="card">
			<h3>{s.headline}</h3>
			<p class="muted">{s.place} · {s.city}</p>
			<p><strong>{s.short}</strong></p>
			<p>{s.long}</p>
			{#if s.look}<p class="muted">Look: {s.look}</p>{/if}
			<form method="POST" action="?/mark" class="filters">
				<input type="hidden" name="item" value={s.id} />
				<label>Mark <select name="mark"><option>good</option><option>weak</option><option>bad</option></select></label>
				<label>Why <input name="reason" required /></label>
				<button type="submit">Save mark</button>
			</form>
		</article>
	{:else}
		<Empty>Nothing to mark this month.</Empty>
	{/each}
</section>

<section>
	<h2>Golden bar</h2>
	{#if data.bar}
		<p class="muted">Version <span class="mono">{data.bar.version}</span>, {relative(data.bar.created_at)}.</p>
		<pre class="bar">{data.bar.body}</pre>
	{:else}
		<Empty>No golden bar yet.</Empty>
	{/if}
</section>

<style>
	.card {
		border: 1px solid var(--line);
		border-radius: var(--radius);
		padding: var(--s3);
		margin: var(--s3) 0;
	}
	.bar {
		white-space: pre-wrap;
		font-family: inherit;
	}
</style>
