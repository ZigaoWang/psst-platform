<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import { time } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
</script>

<svelte:head><title>Settings · Psst console</title></svelte:head>
<PageHeader title="Settings" subtitle="Audit thresholds, model routing, and lease lengths. Every change is kept with its reason." />
{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<div class="table-wrap">
	<table>
		<thead><tr><th>Setting</th><th>What it does</th><th>Value</th><th>Change</th></tr></thead>
		<tbody>
			{#each data.settings as s (s.key)}
				<tr>
					<td class="mono">{s.key}</td>
					<td>{s.note}</td>
					<td class="mono">{JSON.stringify(s.value)}</td>
					<td>
						<form method="POST" action="?/change" class="change">
							<input type="hidden" name="key" value={s.key} />
							<label><span class="visually-hidden">New value for {s.key}</span><input name="value" value={JSON.stringify(s.value)} size="18" /></label>
							<label><span class="visually-hidden">Why</span><input name="reason" placeholder="Why" required /></label>
							<button type="submit">Save</button>
						</form>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<section>
	<h2>Recent changes</h2>
	<ul>
		{#each data.changes as c, i (i)}
			<li>{time(c.at)}: <span class="mono">{c.key}</span> from {JSON.stringify(c.old_value)} to {JSON.stringify(c.new_value)} by {c.operator}, because {c.reason}</li>
		{:else}<li class="muted">No changes yet.</li>{/each}
	</ul>
</section>

<style>
	.change {
		display: flex;
		gap: var(--s1);
	}
</style>
