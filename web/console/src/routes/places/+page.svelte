<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import Pager from '@psst/ui/Pager.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>Places · Psst console</title></svelte:head>
<PageHeader title="Places" />

<form class="filters" method="GET" role="search">
	<label>Name, place id, Wikidata item, or OSM element <input name="q" value={data.q} /></label>
	<label>City
		<select name="city">
			<option value="">All cities</option>
			{#each data.cities as c (c.slug)}<option value={c.slug} selected={c.slug === data.city}>{c.name}</option>{/each}
		</select>
	</label>
	<button type="submit">Search</button>
</form>

{#if data.places.length}
	<div class="table-wrap">
		<table>
			<thead><tr><th>Place</th><th>Kind</th><th>Neighborhood</th><th>State</th><th class="num">Published</th><th class="num">In work</th></tr></thead>
			<tbody>
				{#each data.places as place (place.id)}
					<tr>
						<td>
							<a href={`/admin/places/${place.id}`}>{place.name ?? place.id}</a>
							{#if place.local_name}<span class="muted">{place.local_name}</span>{/if}
						</td>
						<td>{place.kind}</td>
						<td>{place.neighborhood ?? ''}</td>
						<td><Badge state={place.state === 'active' ? 'published' : place.state === 'pending' ? 'checking' : 'retired'} label={place.state} /></td>
						<td class="num">{count(place.published)}</td>
						<td class="num">{count(place.in_work)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<Pager next={data.next} first={data.first} />
{:else}
	<Empty>No places match.</Empty>
{/if}
