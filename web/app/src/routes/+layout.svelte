<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { clock } from '#lib/time.svelte.js';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();

	const onRecord = $derived(page.url.pathname.startsWith('/record'));
	const route = $derived(onRecord ? 'record' : page.url.pathname.startsWith('/results') ? 'results' : 'fixtures');
	const stamp = $derived(
		new Date(data.index.generated_at).toLocaleString('en-GB', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: clock.local ? undefined : 'UTC' })
	);

	// Pages are built once a day. If the daily job has silently stopped, say so rather than show old numbers as current.
	let stale = $state(false);
	// Count page views (first-party, no cookies; see the privacy notice). Failures are ignored: counting must never affect the page.
	let first = true;
	afterNavigate(() => {
		const path = location.pathname;
		if (path.startsWith('/admin')) return;
		const q = new URLSearchParams(location.search);
		const body = JSON.stringify({
			path,
			referrer: first ? document.referrer : '',
			utm: q.get('utm_source') ?? q.get('ref'),
			device: window.matchMedia('(max-width: 760px)').matches ? 'mobile' : 'desktop'
		});
		first = false;
		try {
			void fetch('/api/track', { method: 'POST', headers: { 'content-type': 'application/json' }, body, keepalive: true }).catch(() => {});
		} catch {
			/* ignore */
		}
	});

	onMount(() => {
		clock.local = true;
		stale = Date.now() - new Date(data.index.generated_at).getTime() > 36 * 3600 * 1000;
	});
</script>

<svelte:head>
	<title>Pitchside · match predictions</title>
	<meta name="description" content="A probability for every market on every match in Europe's top five leagues, stored before kickoff and scored after." />
</svelte:head>

<div class="shell" class:on-record={onRecord}>
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
			<div class="nav-links">
				<a href="/" aria-current={route === 'fixtures' ? 'page' : undefined} data-route="fixtures">Fixtures</a>
				<a href="/results" aria-current={route === 'results' ? 'page' : undefined} data-route="results">Results</a>
				<a href="/record" aria-current={route === 'record' ? 'page' : undefined} data-route="record">Track record</a>
			</div>
			<span class="nav-note">18+ · Estimates, not advice</span>
		</nav>
	</header>

	{#if stale}
		<p class="stale" role="status">These predictions were last refreshed on {stamp}. The daily update may have stopped, so newer matches or results may be missing.</p>
	{/if}

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
			<p class="foot-meta">Private · data from {stamp} · model {data.index.model_version}</p>
		</div>
	</footer>
</div>
