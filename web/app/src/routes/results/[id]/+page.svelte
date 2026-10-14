<script lang="ts">
	import MarketBoard from '#lib/components/MarketBoard.svelte';
	import { pct0 } from '#lib/labels.js';
	import { longDate } from '#lib/time.svelte.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const r = $derived(data.result);
	const index = $derived(data.index);
	const ctx = $derived({ home: r.home, away: r.away });
	const word = { home: 'Home win', draw: 'Draw', away: 'Away win' } as const;
	const statRows = $derived(
		(
			[
				['Corners', 'corners'],
				['Cards', 'cards'],
				['Shots', 'shots'],
				['Shots on target', 'sot']
			] as const
		)
			.map(([label, key]) => ({ label, home: r.stats.home?.[key] ?? null, away: r.stats.away?.[key] ?? null }))
			.filter((s) => s.home !== null && s.away !== null)
	);
</script>

<svelte:head><title>{r.home} {r.ft[0]}–{r.ft[1]} {r.away} · Pitchside</title></svelte:head>

<div class="wrap wide">
	<a class="back" href="/results"><svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3 5 8l5 5" /></svg>Results</a>
	<header class="match-head">
		<h1 class="display">{r.home} {r.ft[0]}–{r.ft[1]} {r.away}</h1>
		<p class="meta"><span>{index.leagues[r.league]}</span><span>{longDate(r.date)}</span>{#if r.ht}<span>Half-time {r.ht[0]}–{r.ht[1]}</span>{/if}</p>
	</header>

	<section aria-label="What we said and what happened">
		<div class="headline-card">
			{#each ['home', 'draw', 'away'] as const as side (side)}
				<div class="hp">
					<span class="who">{side === 'home' ? `${r.home} win` : side === 'away' ? `${r.away} win` : word.draw}{r.actual === side ? ' ✓' : ''}{#if r.actual === side}<span class="sr-only"> (happened)</span>{/if}</span>
					<span class="big">{pct0(r.p[side] ?? 0)}</span>
					<span class="mini" aria-hidden="true"><i style="width:{((r.p[side] ?? 0) * 100).toFixed(1)}%"></i></span>
				</div>
			{/each}
		</div>
		<div class="why">
			<dl>
				<div><dt>Picks right</dt><dd>{r.picks_hit} of {r.picks}</dd></div>
				<div><dt>High-confidence picks right</dt><dd>{r.high_hit} of {r.high_picks}</dd></div>
				<div><dt>Predictions not scored</dt><dd>{r.not_scored.toLocaleString()}</dd></div>
				<div><dt>Models</dt><dd>{r.versions.join(' · ')}</dd></div>
				{#each statRows as s (s.label)}
					<div><dt>{s.label}</dt><dd>{r.home} {s.home} · {r.away} {s.away}</dd></div>
				{/each}
			</dl>
			<p class="span">
				These are the predictions stored before kickoff, never edited. “Not scored” are markets we could not settle for this match, for example goal-minute markets when the goal times were not verified.
				A Pick is the most likely outcome of a market where only one outcome can happen; it can lose even when it was the best guess.
			</p>
		</div>
	</section>

	<MarketBoard preds={r.preds} {index} {ctx} results />
</div>
