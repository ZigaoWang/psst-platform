<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import { time } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
	const t = $derived(data.task);
</script>

<svelte:head><title>{t.type} task · Psst console</title></svelte:head>
<PageHeader title={`${t.type} task`} subtitle={t.purpose}>
	{#snippet actions()}
		<Badge state={t.state} />
		{#if t.state === 'leased'}<form method="POST" action="?/release"><button type="submit">Release the lease</button></form>{/if}
		{#if ['failed', 'cancelled'].includes(t.state)}<form method="POST" action="?/requeue"><button type="submit">Queue again</button></form>{/if}
		{#if ['queued', 'leased', 'failed'].includes(t.state)}<form method="POST" action="?/cancel"><button type="submit" class="danger">Cancel</button></form>{/if}
	{/snippet}
</PageHeader>
{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<section>
	<dl class="facts">
		<dt>Task</dt><dd class="mono">{t.id}</dd>
		<dt>Model</dt><dd>{t.model ?? 'system'}</dd>
		{#if t.item_id}<dt>Item</dt><dd><a href={`/admin/items/${t.item_id}`}>{t.item_id}</a></dd>{/if}
		{#if t.place_id}<dt>Place</dt><dd><a href={`/admin/places/${t.place_id}`}>{t.place_id}</a></dd>{/if}
		<dt>Created</dt><dd>{time(t.created_at)} by <a class="mono" href={`/admin/runs/${t.created_by}`}>{t.created_by}</a></dd>
		{#if t.leased_until}<dt>Leased until</dt><dd>{time(t.leased_until)} by <a class="mono" href={`/admin/runs/${t.leased_by}`}>{t.leased_by}</a></dd>{/if}
		{#if t.done_at}<dt>Done</dt><dd>{time(t.done_at)} by <a class="mono" href={`/admin/runs/${t.done_by}`}>{t.done_by}</a></dd>{/if}
		<dt>Attempts</dt><dd>{t.attempts}</dd>
		{#if t.problem}<dt>Problem</dt><dd>{t.problem}</dd>{/if}
		{#if t.prompt}<dt>Prompt version</dt><dd class="mono">{t.prompt}</dd>{/if}
	</dl>
</section>

<section><h2>Input</h2><pre>{JSON.stringify(t.input, null, 2)}</pre></section>
{#if t.result}<section><h2>Result</h2><pre>{JSON.stringify(t.result, null, 2)}</pre></section>{/if}

<section>
	<h2>Leases</h2>
	<ul>{#each data.leases as l, i (i)}<li>{time(l.leased_at)}: <a class="mono" href={`/admin/runs/${l.run_id}`}>{l.run_id}</a> ({l.model ?? 'system'})</li>{:else}<li class="muted">Never leased.</li>{/each}</ul>
</section>

<style>
	pre {
		overflow-x: auto;
		padding: var(--s3);
		border-radius: var(--r2);
		background: var(--surface-sunk);
		font-size: var(--text-sm);
	}
</style>
