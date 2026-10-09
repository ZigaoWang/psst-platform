<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import { count, time } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
	const r = $derived(data.run);
</script>

<svelte:head><title>Run {r.id} · Psst console</title></svelte:head>
<PageHeader title={`Run ${r.id}`} subtitle={`${r.kind}${r.model ? `, ${r.model}` : ''}`}>
	{#snippet actions()}
		{#if !r.ended_at && r.kind !== 'editor'}
			<form method="POST" action="?/end"><button type="submit" class="danger">End this run</button></form>
		{/if}
	{/snippet}
</PageHeader>
{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<section>
	<dl class="facts">
		<dt>Operator</dt><dd>{r.operator}</dd>
		<dt>Started</dt><dd>{time(r.started_at)}</dd>
		<dt>Ended</dt><dd>{r.ended_at ? time(r.ended_at) : 'still running'}</dd>
		{#if r.notes}<dt>Notes</dt><dd>{r.notes}</dd>{/if}
	</dl>
</section>

<section>
	<h2>Work done</h2>
	<ul>
		{#each data.tasks as t (t.type)}<li>{count(t.n)} {t.type}</li>{:else}<li class="muted">No tasks finished.</li>{/each}
		{#each data.leased as t (t.id)}<li>Holding <a href={`/admin/tasks/${t.id}`}>{t.type}</a> until {time(t.leased_until)}</li>{/each}
	</ul>
</section>

<section>
	<h2>Verdicts given</h2>
	<ul>{#each data.checks as c (c.kind + c.verdict)}<li>{c.kind}: {count(c.n)} {c.verdict}</li>{:else}<li class="muted">None.</li>{/each}</ul>
</section>

<section>
	<h2>Revisions written</h2>
	<ul>
		{#each data.revisions as rv (rv.id)}
			<li><a href={`/admin/items/${rv.item_id}?revision=${rv.id}`}>{rv.type} {rv.item_id}, revision {rv.number}</a> <Badge state={rv.state} /></li>
		{:else}<li class="muted">None.</li>{/each}
	</ul>
</section>
