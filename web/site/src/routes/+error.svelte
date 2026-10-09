<script lang="ts">
	import '@psst/ui/tokens.css';
	import { page } from '$app/state';
</script>

<svelte:head><title>Not found · Psst</title></svelte:head>

<main>
	<h1>{page.status === 404 ? 'This page isn’t here' : 'Something went wrong'}</h1>
	<p><a href="/">Psst home</a> · <a href="/zh">中文首页</a></p>
</main>

<style>
	main {
		max-width: 40rem;
		margin: 15vh auto;
		padding: 0 var(--s4);
	}
</style>
