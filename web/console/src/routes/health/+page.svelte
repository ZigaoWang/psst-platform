<script lang="ts">
	import PageHeader from '@psst/ui/PageHeader.svelte';
	import Badge from '@psst/ui/Badge.svelte';
	import { relative } from '@psst/ui/format.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const stale = (value: unknown, hours: number) => !value || Date.now() - new Date(String(value)).getTime() > hours * 3600_000;
</script>

<svelte:head><title>Health · Psst console</title></svelte:head>
<PageHeader title="Health" />
<dl class="facts">
	<dt>Database</dt><dd><Badge state={data.database ? 'published' : 'failed'} label={data.database ? 'reachable' : 'unreachable'} /></dd>
	{#if data.status}
		{@const s = data.status}
		<dt>System worker</dt>
		<dd>
			<Badge state={s.oldest_tool_check && stale(s.oldest_tool_check, 0.25) ? 'failed' : 'published'}
				label={s.oldest_tool_check && stale(s.oldest_tool_check, 0.25) ? 'behind' : 'keeping up'} />
			last tool check {s.last_tool_check ? relative(s.last_tool_check) : 'never'}
		</dd>
		<dt>Fetch service</dt><dd>last snapshot {s.last_snapshot ? relative(s.last_snapshot) : 'never'}</dd>
		<dt>Last publish</dt><dd>{s.last_publish ? relative(s.last_publish) : 'never'}</dd>
		<dt>Expired leases</dt><dd>{s.expired_leases}</dd>
	{/if}
</dl>
