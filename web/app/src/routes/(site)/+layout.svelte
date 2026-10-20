<script lang="ts">
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<div class="shell">
	<a class="skip" href="#main">Skip to content</a>

	<header class="nav-wrap">
		<nav class="nav" aria-label="Main">
			<a class="brand" href="/" aria-label="Pitchside, home">
				<svg class="brand-mark" viewBox="0 0 28 28" width="26" height="26" aria-hidden="true">
					<defs>
						<linearGradient id="mark" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff8a1f" /><stop offset="1" stop-color="#ee222e" /></linearGradient>
					</defs>
					<rect x="2" y="3" width="24" height="22" rx="6" fill="none" stroke="url(#mark)" stroke-width="2.2" />
					<path d="M14 3v22" stroke="url(#mark)" stroke-width="2.2" />
					<circle cx="14" cy="14" r="4.2" fill="none" stroke="url(#mark)" stroke-width="2.2" />
				</svg>
				<span class="brand-name">Pitchside</span>
			</a>
			<div class="nav-links site-links">
				<a href="/#how">How it works</a>
				<a href="/#covered">What is covered</a>
				<a href="/about">The method</a>
			</div>
			<!-- The app sits behind Cloudflare Access, so this is a full page load, not a client-side navigation. -->
			<a class="nav-signin" href="/app" data-sveltekit-reload>Sign in</a>
		</nav>
	</header>

	<main id="main" tabindex="-1">
		{@render children()}
	</main>

	<footer class="foot">
		<div class="foot-inner">
			<p class="foot-rg">
				<strong>Please gamble responsibly.</strong> You must be 18 or over. Pitchside shows statistical estimates, not advice, tips or a promise of any result. Football is uncertain and
				no model removes that. It does not take bets. If gambling is affecting you or someone you know, free and confidential help is available from your national gambling-support service.
			</p>
			<nav class="foot-links" aria-label="About and policies">
				<a href="/about">How it works</a>
				<a href="/responsible-gambling">Responsible gambling</a>
				<a href="/terms">Terms</a>
				<a href="/privacy">Privacy</a>
			</nav>
			<p class="foot-meta">Private preview · estimates, not advice · 18+</p>
		</div>
	</footer>
</div>

<style>
	.site-links { margin-right: .25rem; }
	.nav-signin {
		text-decoration: none; font-weight: 600; font-size: .95rem; padding: .55rem 1.1rem; border-radius: 999px; background: var(--ink); color: #fff;
		transition: background-color .2s var(--ease), transform .2s var(--ease);
	}
	.nav-signin:hover { background: #000; transform: translateY(-1px); }
	@media (max-width: 760px) {
		.site-links { display: none; }
	}
	/* the public header has only the brand and one button, so the name fits even on a narrow phone */
	.nav :global(.brand-name) { display: inline !important; }
	@media (prefers-reduced-motion: reduce) {
		.nav-signin:hover { transform: none; }
	}
</style>
