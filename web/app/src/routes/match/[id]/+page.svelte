<script lang="ts">
	import ConfBars from '#lib/components/ConfBars.svelte';
	import Feedback from '#lib/components/Feedback.svelte';
	import KeyNumbers from '#lib/components/KeyNumbers.svelte';
	import MarketBoard from '#lib/components/MarketBoard.svelte';
	import OddsCompare from '#lib/components/OddsCompare.svelte';
	import Story from '#lib/components/Story.svelte';
	import { pct0 } from '#lib/labels.js';
	import { kickoffLong, tzLabel } from '#lib/time.svelte.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const match = $derived(data.match);
	const index = $derived(data.index);
	const ctx = $derived({ home: match.home, away: match.away, players: match.players });

	const x12 = $derived(Object.fromEntries((match.preds['1x2']?.null ?? []).map((r) => [r[0], r[3]])) as Record<string, number>);
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

	{#if match.league === 'CHAMP'}
		<p class="span" style="margin-top:1rem">Championship predictions are new. They come from the same models as the top five leagues, but the confidence bars are not rated here yet (empty bars): they are built from tests on the top five leagues, and the Championship is harder to predict. Player markets are not available for this league.</p>
	{/if}

	<KeyNumbers preds={match.preds} {index} {ctx} />

	<OddsCompare {match} {index} />

	<div class="notice" style="margin-top:1rem">
		<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4" /><circle cx="8" cy="4.8" r=".6" fill="currentColor" /></svg>
		<p><strong>18+.</strong> These are statistical estimates, not advice or a promise of any result. Fair odds are simply 1 divided by the probability; they are not bookmaker prices.</p>
	</div>

	<MarketBoard preds={match.preds} {index} {ctx} />

	<div id="deep-dive"><Story {match} /></div>

	<Feedback matchId={match.id} page="/match/{match.id}" />
</div>
