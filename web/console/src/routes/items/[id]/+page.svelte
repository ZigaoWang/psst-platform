<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Notice from '@psst/ui/Notice.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { time } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data, form }: PageProps = $props();
	const item = $derived(data.item);
	const body = $derived((data.revision?.body ?? {}) as Record<string, unknown>);
	// Fields in reading order (the database stores them unordered).
	const ORDER = ['headline', 'identifier', 'title', 'short', 'about', 'intro', 'long', 'look', 'myth', 'alt',
		'category', 'veracity', 'kind', 'year', 'key_facts', 'stops', 'tags'];
	const rank = (key: string) => (ORDER.indexOf(key) + ORDER.length + 1) % (ORDER.length + 1);
	const fields = $derived(Object.entries(body).sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b)));
	const prose = $derived(fields.filter(([, v]) => typeof v === 'string') as [string, string][]);
	const other = $derived(fields.filter(([, v]) => typeof v !== 'string'));
	const title = $derived(String(body.headline ?? body.identifier ?? body.title ?? body.alt ?? item.id));

	function checksFor(claim: string | null) {
		return data.checks.filter((k) => k.claim_id === claim);
	}
	const verdictState: Record<string, string> = {
		supported: 'published', pass: 'published', unsupported: 'failed', contradicted: 'failed', fail: 'failed',
		unclear: 'checking'
	};
</script>

<svelte:head><title>{title} · Psst console</title></svelte:head>
<PageHeader {title} subtitle={`${item.type}${item.place_name ? ` at ${item.place_name}` : ''}`}>
	{#snippet actions()}<Badge state={item.state} />{/snippet}
</PageHeader>

{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
{#if form?.done}<Notice tone="ok">{form.done}</Notice>{/if}

<section>
	<dl class="facts">
		<dt>Item</dt><dd class="mono">{item.id}</dd>
		{#if item.place_id}<dt>Place</dt><dd><a href={`/admin/places/${item.place_id}`}>{item.place_name ?? item.place_id}</a></dd>{/if}
		{#if item.translates}<dt>Translates</dt><dd><a href={`/admin/items/${item.translates}`}>{item.translates}</a></dd>{/if}
		<dt>Live revision</dt><dd>{data.revisions.find((r) => r.id === item.published_revision)?.number ?? 'none'}</dd>
		{#if data.translations.length}
			<dt>Translations</dt>
			<dd>{#each data.translations as t (t.id)}<a href={`/admin/items/${t.id}`}>{t.language}</a> <Badge state={t.state} /> {/each}</dd>
		{/if}
	</dl>
</section>

{#if data.revision}
	<section aria-labelledby="text">
		<h2 id="text">Revision {data.revision.number}{data.revision.id === item.current_revision ? ' (current)' : ''}</h2>
		<dl class="facts">
			{#each prose as [key, value] (key)}<dt>{key}</dt><dd>{value}</dd>{/each}
			{#each other as [key, value] (key)}<dt>{key}</dt><dd><code>{JSON.stringify(value)}</code></dd>{/each}
		</dl>
	</section>

	<section aria-labelledby="claims">
		<h2 id="claims">Claims and evidence</h2>
		{#each data.claims as claim (claim.id)}
			<article class="claim">
				<h3>{claim.n}. {claim.text}</h3>
				<p class="muted">{claim.kind}{claim.role === 'myth' ? ', the popular version' : ''}{claim.values.length ? ` · values: ${claim.values.map((v: { value: string }) => v.value).join(', ')}` : ''}</p>
				{#each claim.evidence as e, i (i)}
					<blockquote>
						{#if e.matched}<span class="context">…{e.before}</span><mark>{e.exact}</mark><span class="context">{e.after}…</span>
						{:else if e.matched === false}<mark class="missing">{e.quote}</mark> <strong>(not found in the snapshot)</strong>
						{:else}<mark>{e.quote}</mark> <span class="muted">(waiting for the tool check)</span>{/if}
						<footer>
							<a href={e.url}>{e.title}</a>, {e.publisher} · {e.kind}{e.via !== 'live' ? ` · read from ${e.via}` : ''} ·
							<span class="mono">{e.snapshot}</span>
						</footer>
					</blockquote>
				{/each}
				<ul class="verdicts">
					{#each checksFor(claim.id) as k (k.id)}
						<li><Badge state={verdictState[k.verdict] ?? 'draft'} label={k.verdict} /> {k.kind}{k.model ? `, ${k.model}` : ''}: {k.note}</li>
					{/each}
				</ul>
				<form method="POST" action="?/verdict" class="verdict-form">
					<input type="hidden" name="revision" value={data.revision.id} />
					<input type="hidden" name="claim" value={claim.id} />
					<label>Your verdict
						<select name="verdict">
							<option value="supported">Supported</option>
							<option value="unsupported">Unsupported</option>
							<option value="contradicted">Contradicted</option>
						</select>
					</label>
					<label class="grow">What you checked <input name="note" required /></label>
					<button type="submit">Record</button>
				</form>
			</article>
		{:else}
			<Empty>This revision has no claims.</Empty>
		{/each}
	</section>

	<section aria-labelledby="whole">
		<h2 id="whole">Whole-item checks</h2>
		<ul class="verdicts">
			{#each checksFor(null) as k (k.id)}
				<li>
					<Badge state={verdictState[k.verdict] ?? 'draft'} label={k.verdict} /> {k.kind}{k.model ? `, ${k.model}` : ''}: {k.note}
					{#if k.details?.untraced?.length}<br /><span class="muted">Untraced: {k.details.untraced.join('; ')}</span>{/if}
					{#if k.details?.refusals?.length}<br /><span class="muted">{k.details.refusals.join('; ')}</span>{/if}
				</li>
			{:else}
				<li class="muted">None yet.</li>
			{/each}
		</ul>
		<form method="POST" action="?/verdict" class="verdict-form">
			<input type="hidden" name="revision" value={data.revision.id} />
			<label>Your verdict on the whole item
				<select name="verdict"><option value="pass">Pass</option><option value="fail">Fail</option></select>
			</label>
			<label class="grow">What you checked <input name="note" required /></label>
			<button type="submit">Record</button>
		</form>
	</section>
{/if}

<section aria-labelledby="act">
	<h2 id="act">Act on this item</h2>
	<div class="acts">
		<form method="POST" action="?/recheck">
			<label>Check again, because <input name="reason" required /></label>
			<button type="submit">Send to checking</button>
		</form>
		<form method="POST" action="?/retire">
			<label>Retire, because <input name="reason" required /></label>
			<button type="submit" class="danger">Retire</button>
		</form>
	</div>
</section>

<section aria-labelledby="revisions">
	<h2 id="revisions">Revisions</h2>
	<div class="table-wrap">
		<table>
			<thead><tr><th>Number</th><th>Written</th><th>By</th><th>Reason</th></tr></thead>
			<tbody>
				{#each data.revisions as r (r.id)}
					<tr>
						<td><a href={`?revision=${r.id}`}>{r.number}</a></td>
						<td>{time(r.created_at)}</td>
						<td><a href={`/admin/runs/${r.created_by_run}`}>{r.model ?? r.created_by_run}</a></td>
						<td>{r.reason}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>

<section aria-labelledby="history">
	<h2 id="history">History</h2>
	<div class="table-wrap">
		<table>
			<thead><tr><th>When</th><th>Change</th><th>Why</th><th>Run</th></tr></thead>
			<tbody>
				{#each data.transitions as t, i (i)}
					<tr>
						<td>{time(t.at)}</td>
						<td>{t.from_state ?? 'new'} to <Badge state={t.to_state} /></td>
						<td>{t.reason}</td>
						<td><a class="mono" href={`/admin/runs/${t.run_id}`}>{t.run_id}</a></td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>

<section aria-labelledby="tasks">
	<h2 id="tasks">Tasks</h2>
	{#if data.tasks.length}
		<ul>
			{#each data.tasks as t (t.id)}
				<li><a href={`/admin/tasks/${t.id}`}>{t.type}</a> <Badge state={t.state} /> {t.problem ?? ''}</li>
			{/each}
		</ul>
	{:else}
		<Empty>No tasks.</Empty>
	{/if}
</section>

<style>
	.claim {
		padding: var(--s4);
		margin-bottom: var(--s3);
		border: 1px solid var(--line);
		border-radius: var(--r2);
		background: var(--surface);
	}
	h3 {
		margin: 0;
		font-size: var(--text-md);
	}
	blockquote {
		margin: var(--s3) 0;
		padding: var(--s2) var(--s3);
		border-left: 3px solid var(--line-strong);
		background: var(--surface-sunk);
		font-size: var(--text-sm);
	}
	.context {
		color: var(--text-muted);
	}
	mark {
		background: color-mix(in srgb, var(--warn) 25%, transparent);
		color: inherit;
	}
	mark.missing {
		background: var(--danger-surface);
	}
	footer {
		margin-top: var(--s2);
		color: var(--text-muted);
	}
	.verdicts {
		list-style: none;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--s1);
		font-size: var(--text-sm);
	}
	.verdict-form,
	.acts form {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--s2);
		margin-top: var(--s3);
	}
	.grow {
		flex: 1 1 16rem;
	}
	.acts {
		display: grid;
		gap: var(--s4);
	}
</style>
