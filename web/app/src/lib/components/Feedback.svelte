<script lang="ts">
	let { matchId = null, page }: { matchId?: number | null; page: string } = $props();

	let useful = $state<boolean | null>(null);
	let comment = $state('');
	let status = $state<'idle' | 'sending' | 'done' | 'error'>('idle');

	async function send() {
		if (useful === null && !comment.trim()) return;
		status = 'sending';
		try {
			const res = await fetch('/api/feedback', {
				method: 'POST',
				headers: { 'content-type': 'application/json' },
				body: JSON.stringify({ match_id: matchId, page, useful, comment })
			});
			status = res.ok ? 'done' : 'error';
		} catch {
			status = 'error';
		}
	}
</script>

<section class="feedback" aria-label="Feedback">
	{#if status === 'done'}
		<p role="status"><strong>Thank you.</strong> Your feedback helps decide what gets built and fixed next.</p>
	{:else}
		<h2 class="fb-h">Was this page useful?</h2>
		<div class="pills" role="group" aria-label="Was this page useful?">
			<button class="pill" aria-pressed={useful === true} onclick={() => (useful = true)}>Yes</button>
			<button class="pill" aria-pressed={useful === false} onclick={() => (useful = false)}>Not really</button>
		</div>
		<label class="fb-l" for="fb-c">Anything missing, wrong or confusing? (optional)</label>
		<textarea id="fb-c" rows="3" maxlength="2000" bind:value={comment}></textarea>
		<div class="fb-row">
			<button class="pill" onclick={send} disabled={status === 'sending' || (useful === null && !comment.trim())}>{status === 'sending' ? 'Sending…' : 'Send feedback'}</button>
			{#if status === 'error'}<span role="alert">Could not send. Please try again.</span>{/if}
		</div>
		<p class="fb-note">We store your answer, your comment and the email you signed in with.</p>
	{/if}
</section>

<style>
	.feedback { margin-top: 2rem; padding: 1rem 1.1rem; border: 1px solid var(--line, #8883); border-radius: 12px; }
	.fb-h { font-size: 1.05rem; margin: 0 0 0.6rem; }
	.fb-l { display: block; margin: 0.9rem 0 0.3rem; font-size: 0.9rem; }
	textarea { width: 100%; box-sizing: border-box; font: inherit; padding: 0.6rem; border: 1px solid var(--line, #8886); border-radius: 8px; background: transparent; color: inherit; }
	.fb-row { display: flex; align-items: center; gap: 0.8rem; margin-top: 0.6rem; }
	.fb-note { font-size: 0.8rem; opacity: 0.7; margin: 0.6rem 0 0; }
</style>
