<script lang="ts">
	import ConfBars from '#lib/components/ConfBars.svelte';
	import { pct0 } from '#lib/labels.js';
	import { clock, dayKey, shortDate, timeLabel } from '#lib/time.svelte.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const odds = $derived(data.odds);

	const TARGETS = [2, 3, 5, 10, 20, 30];
	// Today and the days ahead first (soonest first), then earlier days (newest first).
	const today = $derived.by(() => {
		void clock.local;
		return clock.now ? dayKey(new Date(clock.now).toISOString()) : odds.generated_at.slice(0, 10);
	});
	const ahead = $derived(odds.days.filter((d) => d.date >= today).sort((a, b) => a.date.localeCompare(b.date)));
	const earlier = $derived(odds.days.filter((d) => d.date < today));
	const all = $derived([...ahead, ...earlier]);

	let pickedDay = $state<string | null>(null);
	let pickedTarget = $state(5);
	const day = $derived(all.find((d) => d.date === pickedDay) ?? all[0]);
	const slip = $derived(day?.slips.find((s) => s.target === pickedTarget));
	const legs = $derived(slip ? [...slip.legs].sort((a, b) => a.kickoff.localeCompare(b.kickoff)) : []);
	const has = (t: number) => !!day?.slips.some((s) => s.target === t);

	const mark: Record<number, string> = { 1: '✓', 0: '✗', 2: '↺', 3: '' };
	const markWord: Record<number, string> = { 1: 'won', 0: 'lost', 2: 'stake returned', 3: 'not played yet' };
	const statusWord = { pending: 'Not finished', won: 'Every bet won', lost: 'A bet lost' } as const;
	const record = $derived(odds.record.filter((r) => r.slips > 0));
</script>

<svelte:head><title>Odds · Pitchside</title></svelte:head>

<div class="wrap">
	<div class="intro">
		<h1 class="display">Odds slips</h1>
		<p class="lede">
			Each day, the model’s most likely outcomes combined into slips of about 2, 3, 5, 10, 20 and 30 odds. Every bet is in a market the betting sites list (result, double chance, total goals, a team’s goals, both teams to score).
		</p>
		<div class="notice">
			<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4" /><circle cx="8" cy="4.8" r=".6" fill="currentColor" /></svg>
			<p>
				<strong>Read this first.</strong> The odds shown are <em>fair odds</em> from our model (1 ÷ the chance), not bookmaker prices: a bookmaker pays less on every bet, so the real total is lower, and a site may not offer a market for a particular match.
				The chance that a whole slip wins is its bets’ chances multiplied together, which comes to about 1 ÷ the odds: a 30-odds slip wins about one time in thirty, however carefully it is built. No slip is “safe”. In our tests, backing our numbers against bookmaker prices lost money.
			</p>
		</div>
	</div>

	{#if !all.length}
		<p class="empty">No slips yet. They are made each morning once the day’s matches have predictions.</p>
	{:else}
		<div class="pills" role="group" aria-label="Day">
			{#each all as d (d.date)}
				<button class="pill" aria-pressed={day?.date === d.date} onclick={() => (pickedDay = d.date)}>{shortDate(d.date)}{#if d.date === today}&nbsp;· today{/if}</button>
			{/each}
		</div>
		<div class="pills target-pills" role="group" aria-label="Target odds">
			{#each TARGETS as t (t)}
				<button class="pill" aria-pressed={pickedTarget === t} disabled={!has(t)} onclick={() => (pickedTarget = t)}>{t} odds</button>
			{/each}
		</div>

		{#if slip}
			<section class="slip" aria-label="{slip.target} odds slip">
				<header class="slip-head">
					<div><span class="big-odds">{slip.fair_odds.toFixed(2)}</span><span class="muted"> fair odds · {slip.legs.length} {slip.legs.length === 1 ? 'bet' : 'bets'}</span></div>
					<div class="chance"><b>{pct0(slip.p)}</b><small>chance every bet wins</small></div>
					<span class="status status-{slip.status}">{statusWord[slip.status]}</span>
				</header>
				<ol class="legs">
					{#each legs as leg (leg.match)}
						<li>
							<span class="when">{timeLabel(leg.kickoff)}</span>
							<span class="what"><b>{leg.bet}</b><small>{leg.home} v {leg.away}</small></span>
							<span class="chance-leg">{pct0(leg.p)}<ConfBars tier={leg.tier} /></span>
							<span class="out out-{leg.outcome}" role="img" aria-label={markWord[leg.outcome]}>{mark[leg.outcome]}</span>
						</li>
					{/each}
				</ol>
				<p class="muted small">Stored before the first kickoff and never changed. Place each bet separately on the site you use, and check the price and that the market is open for that match.</p>
			</section>
		{:else}
			<p class="empty">No {pickedTarget}-odds slip for this day: there are not enough matches to reach it. Try a smaller target.</p>
		{/if}

		{#if record.length}
			<section class="panel record">
				<h2>How past slips did</h2>
				<p class="muted">Finished slips against what the model expected of them. A model that is honest wins about as often as its chances say.</p>
				<div class="tbl-wrap" tabindex="0" role="region" aria-label="Table, scrolls sideways">
					<table>
						<thead><tr><th scope="col">Target</th><th scope="col" class="num">Finished slips</th><th scope="col" class="num">Won</th><th scope="col" class="num">Expected to win</th></tr></thead>
						<tbody>
							{#each record as r (r.target)}
								<tr><th scope="row">{r.target} odds</th><td class="num">{r.slips}</td><td class="num">{r.won}</td><td class="num">{r.expected.toFixed(1)}</td></tr>
							{/each}
						</tbody>
					</table>
				</div>
			</section>
		{/if}
	{/if}
</div>

<style>
	.target-pills { margin-top: .75rem; }
	.slip { margin-top: 1.5rem; background: var(--surface); border-radius: var(--radius-lg); box-shadow: var(--shadow-card); padding: 1.25rem 1.5rem; display: grid; gap: 1rem; }
	.slip-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: .5rem 1.5rem; }
	.big-odds { font-size: 2rem; font-weight: 600; }
	.chance { display: grid; text-align: right; }
	.chance b { font-size: 1.3rem; }
	.chance small { color: var(--ink-3); }
	.status { font-size: .8rem; font-weight: 600; padding: .15rem .6rem; border-radius: 999px; background: var(--panel); color: var(--ink-2); }
	.status-won { background: var(--ink); color: #fff; }
	.legs { display: grid; gap: .1rem; margin: 0; padding: 0; list-style: none; }
	.legs li { display: grid; grid-template-columns: 4.5rem minmax(0, 1fr) auto 1.5rem; align-items: center; gap: .75rem; padding: .7rem 0; border-top: 1px solid var(--line); }
	.what { display: grid; min-width: 0; }
	.what small { color: var(--ink-3); overflow-wrap: anywhere; }
	.when { color: var(--ink-2); font-weight: 600; }
	.chance-leg { font-weight: 600; white-space: nowrap; }
	.out { text-align: center; font-weight: 700; }
	.out-0 { color: #a3262a; }
	.record { margin-top: 2.5rem; }
	.record h2 { margin: 0 0 .5rem; }
	@media (max-width: 760px) {
		.legs li { grid-template-columns: 3.6rem minmax(0, 1fr) auto; }
		.out { display: none; }
		.chance { text-align: left; }
	}
</style>
