<script lang="ts">
	import '@psst/ui/tokens.css';
	import { page } from '$app/state';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const sections = [
		['', 'Home'],
		['/cities', 'Cities'],
		['/places', 'Places'],
		['/checks', 'Checks'],
		['/quality', 'Quality'],
		['/tasks', 'Tasks'],
		['/runs', 'Runs'],
		['/publish', 'Publish'],
		['/reports', 'Reports'],
		['/demand', 'Demand'],
		['/map', 'Map'],
		['/settings', 'Settings'],
		['/health', 'Health']
	];

	function current(path: string) {
		const here = page.url.pathname.replace(/^\/admin/, '') || '';
		return path === '' ? here === '' || here === '/' : here.startsWith(path);
	}
</script>

<a class="skip" href="#main">Skip to content</a>

{#if data.editor}
	<div class="shell">
		<nav aria-label="Sections">
			<a class="brand" href="/admin">Psst console</a>
			<ul>
				{#each sections as [path, label] (path)}
					<li><a href={`/admin${path}`} aria-current={current(path) ? 'page' : undefined}>{label}</a></li>
				{/each}
			</ul>
			<form method="POST" action="/admin/login?/signOut" class="account">
				<span>{data.editor.name}</span>
				<button type="submit">Sign out</button>
			</form>
		</nav>
		<main id="main">{@render children()}</main>
	</div>
{:else}
	<main id="main" class="plain">{@render children()}</main>
{/if}

<style>
	.skip {
		position: absolute;
		left: -999px;
	}
	.skip:focus {
		left: var(--s3);
		top: var(--s3);
		z-index: 10;
		padding: var(--s2) var(--s3);
		background: var(--surface);
	}
	.shell {
		display: grid;
		grid-template-columns: 13rem 1fr;
		min-height: 100vh;
		background: linear-gradient(to right, var(--surface) 13rem, var(--bg) 13rem);
	}
	nav {
		display: flex;
		flex-direction: column;
		gap: var(--s4);
		padding: var(--s4);
		border-right: 1px solid var(--line);
		background: var(--surface);
		position: sticky;
		top: 0;
		height: 100vh;
	}
	.brand {
		font-weight: 700;
		color: var(--text);
		text-decoration: none;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	ul a {
		display: block;
		padding: var(--s1) var(--s2);
		border-radius: var(--r1);
		color: var(--text);
		text-decoration: none;
	}
	ul a:hover {
		background: var(--surface-sunk);
	}
	ul a[aria-current='page'] {
		background: var(--text);
		color: var(--bg);
	}
	.account {
		margin-top: auto;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--s2);
		font-size: var(--text-sm);
		color: var(--text-muted);
	}
	main {
		padding: var(--s5) var(--s6);
		min-width: 0;
		max-width: 80rem;
	}
	main.plain {
		margin: 10vh auto;
		max-width: 26rem;
	}
	@media (max-width: 52rem) {
		.shell {
			grid-template-columns: 1fr;
			background: var(--bg);
		}
		nav {
			position: static;
			height: auto;
			border-right: 0;
			border-bottom: 1px solid var(--line);
		}
		ul {
			flex-direction: row;
			overflow-x: auto;
		}
		ul a {
			white-space: nowrap;
		}
		main {
			padding: var(--s4);
		}
	}
	:global(table) {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	:global(th),
	:global(td) {
		padding: var(--s2) var(--s3);
		border-bottom: 1px solid var(--line);
		text-align: left;
		vertical-align: top;
	}
	:global(th) {
		color: var(--text-muted);
		font-weight: 600;
	}
	:global(td.num),
	:global(th.num) {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}
	:global(.table-wrap) {
		overflow-x: auto;
		border: 1px solid var(--line);
		border-radius: var(--r2);
		background: var(--surface);
	}
	:global(button),
	:global(.button) {
		display: inline-flex;
		align-items: center;
		gap: var(--s1);
		padding: var(--s1) var(--s3);
		border: 1px solid var(--line-strong);
		border-radius: var(--r1);
		background: var(--surface);
		color: var(--text);
		font: inherit;
		font-size: var(--text-sm);
		cursor: pointer;
		text-decoration: none;
	}
	:global(button.primary) {
		background: var(--text);
		border-color: var(--text);
		color: var(--bg);
	}
	:global(button.danger) {
		border-color: var(--danger);
		color: var(--danger);
	}
	:global(input),
	:global(select),
	:global(textarea) {
		padding: var(--s1) var(--s2);
		border: 1px solid var(--line-strong);
		border-radius: var(--r1);
		background: var(--surface);
		color: var(--text);
		font: inherit;
	}
	:global(label) {
		display: flex;
		flex-direction: column;
		gap: var(--s1);
		font-size: var(--text-sm);
		font-weight: 600;
	}
	:global(.filters) {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--s3);
		margin-bottom: var(--s4);
	}
	:global(section) {
		margin-bottom: var(--s6);
	}
	:global(h2) {
		font-size: var(--text-lg);
		margin: 0 0 var(--s3);
	}
	:global(.grid) {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
		gap: var(--s3);
	}
	:global(.muted) {
		color: var(--text-muted);
	}
	:global(dl.facts) {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--s1) var(--s4);
		margin: 0;
	}
	:global(dl.facts dt) {
		color: var(--text-muted);
	}
	:global(dl.facts dd) {
		margin: 0;
	}
</style>
