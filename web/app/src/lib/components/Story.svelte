<script lang="ts">
	import RecentRates from './RecentRates.svelte';
	import { pct0, pct1 } from '#lib/labels.js';
	import { longDate, shortDate } from '#lib/time.svelte.js';
	import type { FormResult, MatchDetail } from '#lib/types.js';

	let { match }: { match: MatchDetail } = $props();

	const SIZE = 5; // scorelines 0-0 to 4-4
	const cs = $derived(match.preds.correct_score?.null ?? []);
	const prob = $derived(Object.fromEntries(cs.map(([sel, p]) => [sel, p])) as Record<string, number>);
	const top = $derived(Math.max(0, ...Object.entries(prob).filter(([k]) => k !== 'other').map(([, p]) => p)));
	const other = $derived(prob.other ?? 0);
	const likeliest = $derived(
		Object.entries(prob)
			.filter(([k]) => k !== 'other')
			.sort((a, b) => b[1] - a[1])
			.slice(0, 3)
	);
	const goalsRange = Array.from({ length: SIZE }, (_, i) => i);

	const lamH = $derived(match.ctx.lambda_home ?? 0);
	const lamA = $derived(match.ctx.lambda_away ?? 0);
	const lamMax = $derived(Math.max(lamH, lamA, 0.01));

	function tally(rs: FormResult[]) {
		const w = rs.filter((r) => r.result === 'W').length, d = rs.filter((r) => r.result === 'D').length;
		return { w, d, l: rs.length - w - d, gf: rs.reduce((s, r) => s + r.gf, 0), ga: rs.reduce((s, r) => s + r.ga, 0) };
	}
	const sides = $derived([
		{ name: match.home, results: match.form.home, t: tally(match.form.home.slice(0, 6)) },
		{ name: match.away, results: match.form.away, t: tally(match.form.away.slice(0, 6)) }
	]);
	const h2hHomeWins = $derived(match.h2h.filter((m) => (m.home === match.home ? m.ft_home > m.ft_away : m.ft_away > m.ft_home)).length);
	const h2hAwayWins = $derived(match.h2h.filter((m) => (m.home === match.away ? m.ft_home > m.ft_away : m.ft_away > m.ft_home)).length);
	const h2hDraws = $derived(match.h2h.filter((m) => m.ft_home === m.ft_away).length);
</script>

<section class="story" aria-label="The match in detail">
	<div class="block">
		<h2 class="h3">What the model expects</h2>
		<div class="xg">
			<div class="xg-row"><span>{match.home}</span><span class="bar"><i style="width:{(lamH / lamMax) * 100}%"></i></span><b>{lamH.toFixed(2)}</b></div>
			<div class="xg-row"><span>{match.away}</span><span class="bar away"><i style="width:{(lamA / lamMax) * 100}%"></i></span><b>{lamA.toFixed(2)}</b></div>
		</div>
		<p class="muted small">Expected goals, from each side’s attack and defence over the past seasons, with recent matches counting more.</p>
		{#if likeliest.length}
			<p class="likely">Likeliest scores:
				{#each likeliest as [s, p], i (s)}<strong>{s.replace(':', '–')}</strong> ({pct1(p)}){i < likeliest.length - 1 ? ', ' : ''}{/each}.
			</p>
		{/if}
	</div>

	{#if cs.length}
		<div class="block grid-block">
			<h2 class="h3">Score by score</h2>
			<p class="muted small">Down the side: {match.home} goals. Across the top: {match.away} goals.</p>
			<div class="tbl-wrap" tabindex="0" role="region" aria-label="Table, scrolls sideways">
				<table class="score-grid">
					<caption class="sr-only">Probability of each final score, {match.home} goals down the side, {match.away} goals across the top</caption>
					<thead>
						<tr><th scope="col" class="corner"><span class="sr-only">Goals</span></th>{#each goalsRange as a (a)}<th scope="col">{a}</th>{/each}</tr>
					</thead>
					<tbody>
						{#each goalsRange as h (h)}
							<tr>
								<th scope="row">{h}</th>
								{#each goalsRange as a (a)}
									{@const p = prob[`${h}:${a}`] ?? 0}
									<td style="--shade:{top ? (p / top).toFixed(3) : 0}" class:is-top={p === top}>{p >= 0.0005 ? pct0(p) === '0%' ? pct1(p) : pct0(p) : '·'}</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="muted small">Any other score (five or more goals for a side): {pct1(other)}.</p>
		</div>
	{/if}

	<div class="block">
		<h2 class="h3">Recent results</h2>
		<div class="form-cols">
			{#each sides as s (s.name)}
				<div>
					<h3 class="team">{s.name}</h3>
					{#if s.results.length}
						<p class="muted small">Last {Math.min(6, s.results.length)}: won {s.t.w}, drawn {s.t.d}, lost {s.t.l}. Scored {s.t.gf}, conceded {s.t.ga}.</p>
						<ol class="results">
							{#each s.results.slice(0, 6) as r (r.date + r.opponent)}
								<li><span class="r r-{r.result}" aria-label={r.result === 'W' ? 'Win' : r.result === 'D' ? 'Draw' : 'Loss'}>{r.result}</span>
									<span class="opp">{r.home ? 'v' : 'at'} {r.opponent}</span><span class="sc">{r.gf}–{r.ga}</span><span class="dt">{shortDate(r.date)}</span></li>
							{/each}
						</ol>
					{:else}
						<p class="muted small">No earlier results in the database.</p>
					{/if}
				</div>
			{/each}
		</div>
	</div>

	<div class="block">
		<h2 class="h3">Head to head</h2>
		{#if match.h2h.length}
			<p class="muted small">Last {match.h2h.length} meetings: {match.home} won {h2hHomeWins}, {match.away} won {h2hAwayWins}, drawn {h2hDraws}.</p>
			<ol class="results">
				{#each match.h2h as m (m.date)}
					<li><span class="opp">{m.home} v {m.away}</span><span class="sc">{m.ft_home}–{m.ft_away}</span><span class="dt">{longDate(m.date)}</span></li>
				{/each}
			</ol>
		{:else}
			<p class="muted small">These sides have not met in the matches stored.</p>
		{/if}
	</div>

	<RecentRates {match} />

	<p class="muted small context-note">Results and head-to-head are shown for context. The model does not use them directly: in tests, adding recent form or head-to-head did not make its predictions better than its team ratings already are.</p>
</section>

<style>
	.story { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.25rem; margin-top: 1.25rem; }
	.block { background: var(--surface); border-radius: var(--radius-lg); padding: 1.35rem 1.5rem; box-shadow: var(--shadow-card); display: grid; gap: .75rem; align-content: start; min-width: 0; }
	.h3 { font-size: 1.25rem; line-height: 1.25; }
	.xg { display: grid; gap: .55rem; }
	.xg-row { display: grid; grid-template-columns: minmax(0, 9rem) 1fr 3rem; align-items: center; gap: .75rem; font-size: .95rem; }
	.xg-row span:first-child { overflow-wrap: anywhere; }
	.xg-row b { text-align: right; font-weight: 600; }
	.bar { height: 8px; border-radius: 999px; background: var(--panel); overflow: hidden; }
	.bar i { display: block; height: 100%; border-radius: 999px; background: var(--blue); }
	.bar.away i { background: var(--ink); }
	.likely { color: var(--ink-2); }
	.likely strong { color: var(--ink); font-weight: 600; }
	.score-grid { width: 100%; border-collapse: separate; border-spacing: 3px; font-size: .85rem; text-align: center; }
	.score-grid th, .score-grid td { padding: .4rem .25rem; border: 0; text-align: center; white-space: nowrap; }
	.score-grid thead th { color: var(--ink-3); font-weight: 500; }
	.score-grid th.corner { width: 2rem; }
	.score-grid tbody th { color: var(--ink-3); font-weight: 500; }
	.score-grid td { border-radius: 6px; background: color-mix(in srgb, var(--blue) calc(var(--shade) * 62%), var(--panel)); color: var(--ink); font-weight: 500; }
	.score-grid td.is-top { outline: 2px solid var(--ink); outline-offset: -2px; }
	.form-cols { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.25rem; }
	.team { font: 600 1rem/1.3 var(--font-text); font-style: normal; margin-bottom: .2rem; }
	.results { display: grid; gap: .35rem; margin-top: .5rem; }
	.results li { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: baseline; gap: .6rem; font-size: .9rem; }
	.results li:not(:has(.r)) { grid-template-columns: minmax(0, 1fr) auto auto; }
	.opp { overflow-wrap: anywhere; }
	.sc { font-weight: 600; }
	.dt { color: var(--ink-3); font-size: .8rem; min-width: 3.4rem; text-align: right; }
	.r { display: inline-grid; place-items: center; width: 1.45rem; height: 1.45rem; border-radius: 6px; font-size: .75rem; font-weight: 600; }
	.r-W { background: var(--ink); color: #fff; }
	.r-D { background: var(--panel); color: var(--ink-2); }
	.r-L { background: transparent; color: var(--ink-2); box-shadow: inset 0 0 0 1.5px var(--line-strong); }
	.grid-block { grid-column: auto; }
	.context-note { grid-column: 1 / -1; max-width: 70ch; }
	.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
	@media (max-width: 760px) {
		.story { grid-template-columns: minmax(0, 1fr); }
		.form-cols { grid-template-columns: minmax(0, 1fr); }
		.block { padding: 1.1rem; }
	}
</style>
