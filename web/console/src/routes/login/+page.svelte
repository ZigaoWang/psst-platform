<script lang="ts">
	import Notice from '@psst/ui/Notice.svelte';
	import type { PageProps } from './$types';

	let { form }: PageProps = $props();
</script>

<svelte:head><title>Sign in · Psst console</title></svelte:head>

<h1>Psst console</h1>
{#if form?.error}<Notice tone="danger">{form.error}</Notice>{/if}
<form method="POST" action="?/signIn">
	<label>Name <input name="name" autocomplete="username" required value={form?.name ?? ''} /></label>
	<label>Password <input name="password" type="password" autocomplete="current-password" required /></label>
	<button class="primary" type="submit">Sign in</button>
</form>

<style>
	h1 {
		font-size: var(--text-xl);
	}
	form {
		display: flex;
		flex-direction: column;
		gap: var(--s4);
	}
	button {
		align-self: flex-start;
	}
</style>
