<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Empty from '@psst/ui/Empty.svelte';
	import { count } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

<svelte:head><title>Cities · Psst console</title></svelte:head>
<PageHeader title="Cities" subtitle="In research order." />

{#if data.cities.length}
	<div class="table-wrap">
		<table>
			<thead>
				<tr><th>City</th><th>Country</th><th>Local languages</th><th class="num">Places</th>
					<th class="num">Stories published</th><th class="num">Cells researched</th></tr>
			</thead>
			<tbody>
				{#each data.cities as city (city.slug)}
					<tr>
						<td><a href={`/admin/cities/${city.slug}`}>{city.name}</a></td>
						<td>{city.country_code}</td>
						<td>{city.local_languages.join(', ') || 'English'}</td>
						<td class="num">{count(city.places)}</td>
						<td class="num">{count(city.published)}</td>
						<td class="num">{count(city.researched)} of {count(city.cells)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	<Empty>No cities are set up yet. Set one up with <code>psst city add</code>.</Empty>
{/if}
