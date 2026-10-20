<svelte:head>
	<title>Sign in · Pitchside</title>
	<meta name="description" content="Probabilities for every market on every match in Europe's top leagues, stored before kickoff and scored after. Sign in with Google." />
</svelte:head>

<div class="wrap welcome">
	<section class="hero">
		<p class="eyebrow">Private preview</p>
		<h1 class="display">Match probabilities you can check afterwards</h1>
		<p class="lede">
			A probability for every market a betting site offers, on every match in Europe’s top leagues. Each one is stored before kickoff, never edited, and scored once the match is played.
		</p>

		<div class="signin">
			<!-- Cloudflare Access signs the visitor in with Google and brings them back to the fixtures. -->
			<a class="google" href="/" data-sveltekit-reload>
				<svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true">
					<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
					<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
					<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
					<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
				</svg>
				<span>Continue with Google</span>
			</a>
			<p class="fine">
				New here? Continuing creates your account. We receive your email address and name from Google, and nothing else. By continuing you confirm you are 18 or over and accept the
				<a href="/terms">Terms</a> and <a href="/privacy">Privacy notice</a>.
			</p>
		</div>
	</section>

	<section class="points" aria-label="What you get">
		<div>
			<h2>Every market, every match</h2>
			<p>Result, goals, halves, corners, cards, shots, card timing and player markets: about 210 per match, with fair odds beside each probability.</p>
		</div>
		<div>
			<h2>A confidence rating on each number</h2>
			<p>High, Medium or Low, set from how the model did on thousands of past predictions of the same kind.</p>
		</div>
		<div>
			<h2>A public track record</h2>
			<p>Every prediction is scored against what happened, and the results page shows the misses as well as the hits.</p>
		</div>
	</section>

	<p class="notice">
		<strong>Estimates, not advice.</strong> In our own tests bookmaker prices predicted results better than ours, and following our numbers against them lost money. Pitchside does not take bets or give tips.
		For people aged 18 and over. <a href="/responsible-gambling">Responsible gambling</a>
	</p>
</div>

<style>
	.welcome { padding-top: 1.5rem; }
	.eyebrow { font-size: 0.85rem; letter-spacing: 0.04em; text-transform: uppercase; color: var(--ink-3); margin: 0 0 0.6rem; }
	.hero { max-width: 40rem; }
	.hero .lede { margin-top: 1rem; }
	.signin { margin-top: 1.75rem; }
	.google {
		display: inline-flex; align-items: center; gap: 0.75rem; min-height: 48px; padding: 0.6rem 1.25rem; border-radius: 999px;
		background: #fff; color: #1f1f1f; border: 1px solid #dadce0; font-weight: 500; font-size: 1rem; text-decoration: none;
		transition: box-shadow 0.15s ease, background-color 0.15s ease;
	}
	.google:hover { background: #f8f9fa; box-shadow: 0 1px 3px rgba(60, 64, 67, 0.3); }
	.google:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }
	.fine { margin-top: 0.9rem; font-size: 0.85rem; color: var(--ink-3); max-width: 34rem; }
	.fine a, .notice a { text-decoration: underline; text-underline-offset: 2px; }
	.points { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1.25rem; margin: 2.5rem 0 1.5rem; }
	.points h2 { font-size: 1.1rem; margin-bottom: 0.35rem; }
	.points p { font-size: 0.95rem; color: var(--ink-2); }
	.notice { margin-top: 0.5rem; padding: 0.9rem 1.1rem; border: 1px solid var(--line); border-radius: 12px; font-size: 0.9rem; }
</style>
