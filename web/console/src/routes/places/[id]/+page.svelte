<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const p = $derived(data.place);
	const display = $derived(data.names.find((n) => n.role === 'display')?.name ?? p.id);

	function summary(item: { body?: unknown }) {
		const body = (item.body ?? {}) as Record<string, string | undefined>;
		return body.headline ?? body.identifier ?? body.title ?? body.alt ?? '';
	}
</script>

<svelte:head><title>{display} · Psst console</title></svelte:head>
<PageHeader title={display} subtitle={[p.neighborhood, p.district, p.city].filter(Boolean).join(', ')} />

<section>
	<dl class="facts">
		<dt>Id</dt><dd class="mono">{p.id}</dd>
		<dt>State</dt><dd>{p.state}{p.state_reason ? `: ${p.state_reason}` : ''}</dd>
		<dt>Kind and size</dt><dd>{p.kind}, {p.size}</dd>
		{#if p.lat}<dt>Pin</dt><dd>{p.lat.toFixed(6)}, {p.lon.toFixed(6)} from {p.coord_source} ({p.coord_ref})</dd>{/if}
		{#if p.wikidata_id}<dt>Wikidata</dt><dd><a href={`https://www.wikidata.org/wiki/${p.wikidata_id}`}>{p.wikidata_id}</a></dd>{/if}
		{#if p.osm_ref}<dt>OpenStreetMap</dt><dd><a href={`https://www.openstreetmap.org/${p.osm_ref}`}>{p.osm_ref}</a></dd>{/if}
		{#if data.identity.length}<dt>Previous ids</dt><dd class="mono">{data.identity.map((i) => i.legacy_id).join(', ')}</dd>{/if}
	</dl>
</section>

<section>
	<h2>Names</h2>
	<ul>
		{#each data.names as name (name.role + name.lang)}
			<li>{name.name} <span class="muted">({name.role}, {name.lang}, from {name.source})</span></li>
		{/each}
	</ul>
</section>

<section>
	<h2>Content</h2>
	{#if data.items.length}
		<div class="table-wrap">
			<table>
				<thead><tr><th>Type</th><th>Text</th><th>State</th><th>Live</th></tr></thead>
				<tbody>
					{#each data.items as item (item.id)}
						<tr>
							<td>{item.type}{item.language !== 'en' ? ` (${item.language})` : ''}</td>
							<td><a href={`/admin/items/${item.id}`}>{summary(item) || item.id}</a></td>
							<td><Badge state={item.state} /></td>
							<td>{item.live ? 'yes' : 'no'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<Empty>No content yet.</Empty>
	{/if}
</section>
