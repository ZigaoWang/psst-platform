<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, relative } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const show = (v: unknown) => JSON.stringify(v, null, 2);
</script>

<svelte:head><title>Trace · Psst console</title></svelte:head>
<PageHeader title={`Trace of ${data.task.id}`} subtitle={`${data.task.type}, ${data.task.state}${data.task.problem ? `: ${data.task.problem}` : ''}`} />
<p><a href="/admin/harness">Back to the Harness page</a> · <a href={`/admin/tasks?task=${data.task.id}`}>Task controls</a></p>

{#each data.calls as c, n (c.id)}
	<section class="call">
		<h2>{n + 1}. {c.step} on <span class="mono">{c.model}</span></h2>
		<p class="muted">{relative(c.created_at)}; {count(c.input_tokens)} tokens in ({count(c.cached_tokens)} cached), {count(c.output_tokens)} out;
			${Number(c.cost_usd).toFixed(5)}; {(c.latency_ms / 1000).toFixed(1)} s; prompt <span class="mono">{c.prompt_version}</span>, tools <span class="mono">{c.tools_version}</span></p>
		{#if c.error}<p><strong>Failed:</strong> {c.error}</p>{/if}
		<details><summary>Sent</summary><pre>{show(c.request)}</pre></details>
		<details open><summary>Answered</summary><pre>{show(c.response)}</pre></details>
		{#each c.tools as t, i (i)}
			<details><summary>Tool {t.tool}{t.error ? ' (error)' : ''}</summary><pre>{show({ input: t.input, output: t.output })}</pre></details>
		{/each}
	</section>
{:else}
	<Empty>The harness made no calls for this task.</Empty>
{/each}

{#if data.task.result}
	<section><h2>Submitted result</h2><pre>{show(data.task.result)}</pre></section>
{/if}

<style>
	pre { white-space: pre-wrap; word-break: break-word; max-height: 30rem; overflow: auto; }
	.call { border-top: 1px solid var(--line); padding-top: var(--s3); }
</style>
