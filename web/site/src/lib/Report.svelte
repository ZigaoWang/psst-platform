<script lang="ts">
	// A reader's problem report, sent to the platform's intake. It needs JavaScript to send; the page reads fine without.
	import { t, type Language } from './i18n.ts';

	let { itemId, language }: { itemId: string; language: Language } = $props();
	let status: 'idle' | 'sent' | 'failed' = $state('idle');
	let reason = $state('wrong');
	let message = $state('');

	async function send(event: SubmitEvent) {
		event.preventDefault();
		try {
			const response = await fetch('/api/v1/reports', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ factId: itemId, reason, message, appVersion: 'web' })
			});
			status = response.ok ? 'sent' : 'failed';
		} catch {
			status = 'failed';
		}
	}
</script>

<details class="report">
	<summary>{t(language, 'Report a problem')}</summary>
	{#if status === 'sent'}
		<p role="status">{t(language, 'Thank you. It will be checked again.')}</p>
	{:else}
		<form onsubmit={send}>
			<label>{t(language, 'What is wrong?')}
				<select bind:value={reason}>
					<option value="wrong">{t(language, 'Wrong')}</option>
					<option value="outdated">{t(language, 'Outdated')}</option>
					<option value="location">{t(language, 'Wrong location')}</option>
					<option value="offensive">{t(language, 'Offensive')}</option>
					<option value="other">{t(language, 'Other')}</option>
				</select>
			</label>
			<label>{t(language, 'Details (optional)')}<textarea bind:value={message} maxlength="1000" rows="3"></textarea></label>
			<button type="submit">{t(language, 'Send')}</button>
			{#if status === 'failed'}<p role="alert">{t(language, 'That didn’t send. Try again later.')}</p>{/if}
		</form>
		<noscript><p class="muted">{t(language, 'Needs JavaScript to send.')}</p></noscript>
	{/if}
</details>

<style>
	.report {
		margin-top: var(--s5);
		color: var(--text-muted);
	}
	form {
		display: flex;
		flex-direction: column;
		gap: var(--s3);
		max-width: 28rem;
		margin-top: var(--s3);
	}
	label {
		display: flex;
		flex-direction: column;
		gap: var(--s1);
	}
	select,
	textarea,
	button {
		font: inherit;
		padding: var(--s2);
		border: 1px solid var(--line-strong);
		border-radius: var(--r1);
		background: var(--surface);
		color: var(--text);
	}
	button {
		align-self: flex-start;
		cursor: pointer;
	}
</style>
