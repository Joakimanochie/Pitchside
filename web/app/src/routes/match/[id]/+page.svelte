<script lang="ts">
	import ConfBars from '#lib/components/ConfBars.svelte';
	import MarketCard from '#lib/components/MarketCard.svelte';
	import Story from '#lib/components/Story.svelte';
	import { TABS, matchesQuery, marketTitle, pct0, pct1, tabOf, type TabId } from '#lib/labels.js';
	import { kickoffLong, tzLabel } from '#lib/time.svelte.js';
	import { ui } from '#lib/ui.svelte.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const match = $derived(data.match);
	const index = $derived(data.index);
	const ctx = $derived({ home: match.home, away: match.away });

	let tab = $state<TabId>('main');
	let query = $state('');

	const markets = $derived(
		Object.entries(match.preds)
			.filter(([mid]) => index.markets[mid])
			.sort((a, b) => index.markets[a[0]].order - index.markets[b[0]].order)
	);
	const counts = $derived(Object.fromEntries(TABS.map((t) => [t.id, markets.filter(([mid]) => tabOf(mid, index.markets[mid]) === t.id).length])) as Record<TabId, number>);
	const q = $derived(query.trim());
	const visible = $derived(
		markets.filter(([mid]) => (q ? matchesQuery(marketTitle(index.markets[mid].name, ctx), q) : tabOf(mid, index.markets[mid]) === tab))
	);
	const x12 = $derived(Object.fromEntries((match.preds['1x2']?.null ?? []).map((r) => [r[0], r[3]])) as Record<string, number>);
	const highInView = $derived(visible.some(([, lines]) => Object.values(lines).some((rows) => rows.some((r) => r[3] === 0))));
	const v = $derived(index.confidence.validation);
	const c = $derived(match.ctx);
</script>

<svelte:head><title>{match.home} v {match.away} · Pitchside</title></svelte:head>

<div class="wrap wide">
	<a class="back" href="/"><svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3 5 8l5 5" /></svg>Fixtures</a>
	<header class="match-head">
		<h1 class="display">{match.home} v {match.away}</h1>
		<p class="meta"><span>{index.leagues[match.league]}</span><span>{kickoffLong(match.kickoff)}</span><span>Time zone: {tzLabel()}</span><a href="#deep-dive">Scores, recent results and head to head ↓</a></p>
	</header>

	<section aria-label="Match result probabilities">
		<div class="headline-card">
			{#each [['home', `${match.home} win`], ['draw', 'Draw'], ['away', `${match.away} win`]] as [key, label] (key)}
				{@const p = match.p[key as 'home' | 'draw' | 'away']}
				<div class="hp">
					<span class="who">{label}{#if key in x12}<ConfBars tier={x12[key]} />{/if}</span>
					<span class="big">{pct0(p)}</span>
					<span class="mini" aria-hidden="true"><i style="width:{(p * 100).toFixed(1)}%"></i></span>
				</div>
			{/each}
		</div>
		<div class="why">
			<dl>
				<div><dt>Expected goals</dt><dd>{match.home} {Number(c.lambda_home).toFixed(2)} · {match.away} {Number(c.lambda_away).toFixed(2)}</dd></div>
				<div><dt>History used</dt><dd>{Number(c.matches_used).toLocaleString()} finished {index.leagues[match.league]} matches</dd></div>
				<div><dt>Goals before half-time</dt><dd>{((c.first_half_goal_share ?? 0) * 100).toFixed(1)}% of all goals</dd></div>
				<div><dt>Simulated matches</dt><dd>{Number(c.n_sims).toLocaleString()}</dd></div>
				<div><dt>Model</dt><dd>{index.model_version}</dd></div>
			</dl>
			<p class="span">Lineups, injuries and suspensions are not used yet. The model knows past scores, how goals split between the halves, and when in a match goals tend to happen.</p>
		</div>
	</section>

	<div class="notice" style="margin-top:1rem">
		<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4" /><circle cx="8" cy="4.8" r=".6" fill="currentColor" /></svg>
		<p><strong>18+.</strong> These are statistical estimates, not advice or a promise of any result. Fair odds are simply 1 divided by the probability; they are not bookmaker prices.</p>
	</div>

	<h2 class="sr-only">Markets</h2>
	<div class="toolbar">
		<div class="conf-note">
			<button class="pill sm" aria-pressed={ui.highOnly} onclick={() => (ui.highOnly = !ui.highOnly)}>High confidence only</button>
			<span class="muted small">A “Pick” is the most likely outcome of a market where only one outcome can happen.</span>
		</div>
		<details class="conf-legend">
			<summary><ConfBars tier={0} /> What do the confidence bars mean?</summary>
			<div class="conf-body">
				<p>
					The bars rate how far this probability can be trusted, not how likely the outcome is. A High rating means that when the model gave predictions like this one (same market, similar probability),
					it was reliably better than simply using how often that outcome usually happens, and its numbers matched reality. Predictions close to the usual rate, or from markets where the model adds little, are rated Low.
				</p>
				{#if v}
					<p class="muted">
						Checked on {v.checked_on_matches} matches the ratings were not built from: High predictions beat the plain average by {pct1(v.tiers[0].skill)}, Medium by {pct1(v.tiers[1].skill)}, Low by {pct1(v.tiers[2].skill)}.
						Not yet included: how much a probability would move if the model were refitted.
					</p>
				{/if}
			</div>
		</details>
		<div class="tabs" role="group" aria-label="Market groups">
			{#each TABS as t (t.id)}
				<button class="pill" aria-pressed={!q && tab === t.id} onclick={() => { tab = t.id; query = ''; }}>{t.label} <span class="count">{counts[t.id]}</span></button>
			{/each}
		</div>
		<div class="search">
			<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.6" /><path d="m10.6 10.6 3.2 3.2" /></svg>
			<input type="search" placeholder="Find a market, e.g. first goal" aria-label="Find a market" bind:value={query} />
		</div>
		<p class="muted small" role="status">{q ? `${visible.length} market${visible.length === 1 ? '' : 's'} match “${q}”` : ''}</p>
	</div>

	<div class="markets">
		{#each visible as [mid, lines] (mid)}
			<MarketCard {mid} meta={index.markets[mid]} {lines} {ctx} highOnly={ui.highOnly} />
		{/each}
	</div>
	{#if !visible.length}
		<p class="empty">{q ? 'No market matches that search.' : 'Nothing in this group.'}</p>
	{:else if ui.highOnly && !highInView}
		<p class="empty">Nothing here is rated High confidence.</p>
	{/if}

	<div id="deep-dive"><Story {match} /></div>
</div>
