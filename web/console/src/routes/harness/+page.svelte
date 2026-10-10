<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count, relative } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
	const usd = (v: unknown) => `$${Number(v ?? 0).toFixed(Number(v ?? 0) < 1 ? 4 : 2)}`;
	const spent = $derived(Number(data.money.spend.total));
	const budget = $derived(Number(data.money.budget));
	const credit = $derived(data.money.credit as { key_spent: number; account_remaining: number; at: string } | null);
	const paused = $derived(new Set(data.money.paused_cities as string[]));
</script>

<svelte:head><title>Harness · Psst console</title></svelte:head>
<PageHeader title="Harness" subtitle="API models working the queue: spend against budget, cities, models per step, the golden set as a test, and every call." />
{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<section>
	<h2>Spend</h2>
	{#if data.money.paused === true}<Notice tone="warn">Paused everywhere.</Notice>{/if}
	<p><strong>{usd(spent)}</strong> of the {usd(budget)} budget ({Math.round((spent / budget) * 100)} percent); {usd(data.money.today)} today.
		The harness stops before the budget is reached.</p>
	{#if credit}
		<p class="muted">The provider reports {usd(credit.key_spent)} spent on this key and {usd(credit.account_remaining)} of credit left on the account, {relative(credit.at)}.</p>
	{/if}
	<p class="muted">Per city: {data.money.daily === null ? 'no daily budget' : `${usd(data.money.daily)} a day`},
		{data.money.monthly === null ? 'no monthly budget' : `${usd(data.money.monthly)} a month`}. Budgets and models are set on the <a href="/admin/settings">Settings</a> page (harness.* and routing.*).</p>
</section>

<section>
	<h2>Cities</h2>
	<div class="table-wrap">
		<table>
			<thead><tr><th>City</th><th class="num">Queued</th><th class="num">Working</th><th class="num">Published</th><th class="num">Today</th><th class="num">This month</th><th class="num">Per published item</th><th></th></tr></thead>
			<tbody>
				{#each data.cities as c (c.slug)}
					<tr>
						<td>{c.name}{#if paused.has(c.slug)} <span class="muted">(paused)</span>{/if}</td>
						<td class="num">{count(c.queued)}</td><td class="num">{count(c.leased)}</td><td class="num">{count(c.published)}</td>
						<td class="num">{usd(c.today)}</td><td class="num">{usd(c.month)}</td>
						<td class="num">{c.published ? usd(Number(c.month) / c.published) : 'n/a'}</td>
						<td>
							<form method="POST" action={paused.has(c.slug) ? '?/resume' : '?/pause'}>
								<input type="hidden" name="city" value={c.slug} />
								<button type="submit">{paused.has(c.slug) ? 'Resume' : 'Pause'}</button>
							</form>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>

<section>
	<h2>Models per step</h2>
	<p class="muted">A model named provider:model runs in the harness; any other is left to a worker session.</p>
	<ul>{#each data.routes as r (r.type)}<li><span class="mono">{r.type}</span>: <span class="mono">{r.model}</span></li>{/each}</ul>
</section>

<section>
	<h2>The gate, per model</h2>
	<p class="muted">Each model's latest calibration: the editor's good stories it publishes, and the defects (bad stories and constructed negatives) it catches. A model reviews only with 90 percent or more on both. Tier is reported, not gated.</p>
	{#if data.bakeoff.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Model</th><th class="num">Good published</th><th class="num">Defects caught</th><th class="num">Tier</th><th class="num">Cost</th><th>When</th></tr></thead>
				<tbody>
					{#each data.bakeoff as b (b.model)}
						<tr class:pass={b.published / b.good >= 0.9 && b.caught / b.negatives >= 0.9}>
							<td class="mono">{b.model}</td><td class="num">{b.published} of {b.good}</td><td class="num">{b.caught} of {b.negatives}</td>
							<td class="num">{b.tier_agreed} of {b.tier_marked}</td><td class="num">{usd(b.cost)}</td><td>{relative(b.at)}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}<Empty>No calibration for the current golden set yet.</Empty>{/if}
</section>

<section>
	<h2>Quotes, per writer model</h2>
	<p class="muted">Of the quotes a writer gave: copied exactly, repaired to the source's exact text (0.95 similarity or more), or invented. A writer that invents often doesn't qualify.</p>
	{#if data.quoting.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Model</th><th class="num">Answers</th><th class="num">Quotes</th><th class="num">Exact</th><th class="num">Repaired</th><th class="num">Invented</th><th class="num">Unknown snapshot</th></tr></thead>
				<tbody>
					{#each data.quoting as q (q.model)}
						<tr><td class="mono">{q.model}</td><td class="num">{q.answers}</td><td class="num">{q.quotes}</td><td class="num">{q.exact}</td>
							<td class="num">{q.repaired}</td><td class="num">{q.invented}</td><td class="num">{q.unknown}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}<Empty>No writing yet.</Empty>{/if}
</section>

<section>
	<h2>Cost and time per step</h2>
	<p class="muted">The last seven days, per step and model, and per place written ({data.costs[0]?.places ?? 0} places). Targets: under $0.015 and a few seconds per place.</p>
	{#if data.costs.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Step</th><th>Model</th><th class="num">Calls</th><th class="num">Fix rounds</th><th class="num">Input</th><th class="num">Cached</th><th class="num">Output</th><th class="num">Reasoning</th><th class="num">Cost</th><th class="num">Per place</th><th class="num">Model s</th><th class="num">Tool s</th></tr></thead>
				<tbody>
					{#each data.costs as c (c.step + c.model)}
						<tr><td>{c.step}</td><td class="mono">{c.model}</td><td class="num">{count(c.calls)}</td><td class="num">{count(c.fix_rounds)}</td>
							<td class="num">{count(c.input)}</td><td class="num">{count(c.cached)}</td><td class="num">{count(c.output)}</td><td class="num">{count(c.reasoning)}</td>
							<td class="num">{usd(c.cost)}</td><td class="num">{c.places ? usd(Number(c.cost) / c.places) : 'n/a'}</td>
							<td class="num">{count(c.model_seconds)}</td><td class="num">{count(c.tool_seconds)}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}<Empty>No calls in the last seven days.</Empty>{/if}
</section>

<section>
	<h2>Recent calls</h2>
	{#if data.recent.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>When</th><th>Step</th><th>Model</th><th class="num">Tools</th><th class="num">Cost</th><th>Task</th></tr></thead>
				<tbody>
					{#each data.recent as r (r.id)}
						<tr><td>{relative(r.created_at)}</td><td>{r.step}</td><td class="mono">{r.model}</td><td class="num">{r.tools}</td><td class="num">{usd(r.cost_usd)}</td>
							<td>{#if r.task_id}<a href={`/admin/harness/trace?task=${r.task_id}`}>{r.task_id}</a>{/if}{#if r.error} <span class="muted">failed: {r.error}</span>{/if}</td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}<Empty>No calls yet.</Empty>{/if}
</section>

<style>
	tr.pass td { font-weight: 600; }
</style>
