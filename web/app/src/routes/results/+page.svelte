<script lang="ts">
	import { pct0 } from '#lib/labels.js';
	import { reveal } from '#lib/reveal.js';
	import { shortDate } from '#lib/time.svelte.js';
	import { ui } from '#lib/ui.svelte.js';
	import type { ResultEntry } from '#lib/types.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const index = $derived(data.index);

	const shown = $derived(index.results.filter((r) => ui.league === 'ALL' || r.league === ui.league));
	const days = $derived.by(() => {
		const groups = new Map<string, ResultEntry[]>();
		for (const r of shown) groups.set(r.date, [...(groups.get(r.date) ?? []), r]);
		return [...groups.entries()].sort(([a], [b]) => b.localeCompare(a));
	});
	const counts = $derived(Object.fromEntries(Object.keys(index.leagues).map((id) => [id, index.results.filter((r) => r.league === id).length])));
	const totals = $derived.by(() => {
		const t = { picks: 0, hit: 0, high: 0, highHit: 0, result: 0, resultHit: 0 };
		for (const r of shown) {
			t.picks += r.picks;
			t.hit += r.picks_hit;
			t.high += r.high_picks;
			t.highHit += r.high_hit;
			const best = (['home', 'draw', 'away'] as const).reduce((a, b) => ((r.p[b] ?? 0) > (r.p[a] ?? 0) ? b : a));
			t.result += 1;
			t.resultHit += best === r.actual ? 1 : 0;
		}
		return t;
	});
	const word = { home: 'Home win', draw: 'Draw', away: 'Away win' } as const;
</script>

<svelte:head><title>Results · Pitchside</title></svelte:head>

<div class="wrap">
	<div class="intro">
		<h1 class="display">How the predictions turned out</h1>
		<p class="lede">Every match from the last three weeks, with every prediction we stored before kickoff and whether it won or lost. Open a match to see all of its markets.</p>
		<div class="pills" role="group" aria-label="League">
			<button class="pill" aria-pressed={ui.league === 'ALL'} onclick={() => (ui.league = 'ALL')}>All leagues <span class="count">{index.results.length}</span></button>
			{#each Object.entries(index.leagues) as [id, name] (id)}
				<button class="pill" aria-pressed={ui.league === id} onclick={() => (ui.league = id)}>{name} <span class="count">{counts[id]}</span></button>
			{/each}
		</div>
		{#if shown.length}
			<div class="notice">
				<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4" /><circle cx="8" cy="4.8" r=".6" fill="currentColor" /></svg>
				<p>
					Across these {shown.length} matches the match-result pick was right {totals.resultHit} times ({pct0(totals.resultHit / totals.result)}), and the most likely side of all markets where only one thing can happen was right
					{totals.hit.toLocaleString()} of {totals.picks.toLocaleString()} times ({pct0(totals.hit / totals.picks)}). Where we rated the number High confidence: {totals.highHit.toLocaleString()} of {totals.high.toLocaleString()} ({pct0(totals.highHit / (totals.high || 1))}).
					A pick being right says little on its own: many picks are near-certainties such as “over 0.5 goals”. The track record page holds the proper scoring.
				</p>
			</div>
		{/if}
	</div>

	{#each days as [day, list], gi (day)}
		<section use:reveal style="--i:{Math.min(gi, 3)}">
			<h2 class="day">{shortDate(day)} {day.slice(0, 4)}</h2>
			<ol class="match-list">
				{#each list as r (r.id)}
					<li>
						<a class="match-card result-card" href="/results/{r.id}">
							<div class="kick"><span class="kick-time">{r.ft[0]}–{r.ft[1]}</span><span class="kick-league">{index.leagues[r.league]}</span></div>
							<div class="teams"><span>{r.home}</span><span><span class="vs">v </span>{r.away}</span></div>
							<div class="probs">
								<div class="pnums">
									{#each ['home', 'draw', 'away'] as const as side (side)}
										<span class:was={r.actual === side}><b>{pct0(r.p[side] ?? 0)}</b><small>{r.actual === side ? '✓ ' : ''}{word[side]}{#if r.actual === side}<span class="sr-only"> (happened)</span>{/if}</small></span>
									{/each}
								</div>
								<p class="muted small picks-line">Picks right: {r.picks_hit} of {r.picks}{r.high_picks ? ` · High confidence: ${r.high_hit} of ${r.high_picks}` : ''}</p>
							</div>
						</a>
					</li>
				{/each}
			</ol>
		</section>
	{/each}
	{#if !shown.length}
		<p class="empty">No finished matches with stored predictions yet. They appear here once matches are played and scored.</p>
	{/if}
</div>

<style>
	.result-card .probs { display: grid; gap: .5rem; }
	.pnums span.was b { text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: .2em; }
	.pnums span.was small { color: var(--ink); font-weight: 600; }
	.picks-line { margin: 0; }
</style>
