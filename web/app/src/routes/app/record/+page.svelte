<script lang="ts">
	import CalibrationChart from '#lib/components/CalibrationChart.svelte';
	import { pct0, pct1 } from '#lib/labels.js';
	import { reveal } from '#lib/reveal.js';
	import { shortDate } from '#lib/time.svelte.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const d = $derived(data.index);
	const L = $derived(d.live);
	const MIN_LIVE = 30;
	const lineName = (v: string) => (v.startsWith('goalscup-') ? 'European cups: goals, halves, timing and combinations' : v.startsWith('goals-') ? 'Goals, halves, timing and combinations' : v.startsWith('counts-') ? 'Corners, cards, shots, shots on target' : v.startsWith('players-') ? (v === 'players-0.2.0' || v === 'players-0.4.0' ? 'Player markets, with the announced lineup' : 'Player markets (experimental)') : '');
	const v = $derived(d.validation);
	const C = $derived(d.confidence.validation);
	const stored = $derived(d.fixtures.length * 945);
	const first = $derived(L.matches[0]);
	const last = $derived(L.matches[L.matches.length - 1]);
	const NAMES: Record<string, string> = { home: 'Home win', draw: 'Draw', away: 'Away win', BUNDESLIGA: 'Bundesliga', EPL: 'Premier League', LALIGA: 'La Liga', LIGUE1: 'Ligue 1', SERIEA: 'Serie A' };
	const FAMILIES: Record<string, string> = { B: 'Halves', C: 'Game flow', D: 'Minutes', E: 'Combinations', F: 'Corners', G: 'Cards', H: 'Shots and shots on target' };
	const marketRows = $derived<[string, { n: number; predicted: number | null; actual: number | null }][]>([
		['Home win', L.home], ['Draw', L.draw], ['Away win', L.away], ['Both teams to score', L.btts_yes], ['Over 2.5 goals', L.over25]
	]);
	const notes = $derived.by(() => {
		const out: string[] = [];
		const o = L.over25, h = L.home;
		if (o.actual! - o.predicted! > 0.08) out.push('Goals ran well above what the model expected.');
		if (o.predicted! - o.actual! > 0.08) out.push('Goals ran well below what the model expected.');
		if (h.actual! - h.predicted! > 0.08) out.push('Home teams won more often than predicted.');
		if (h.predicted! - h.actual! > 0.08) out.push('Home teams won less often than predicted.');
		return out;
	});
	const bt = $derived(d.value_backtest);
	const roiRows = $derived(bt ? bt.roi.filter((r) => r.timing === 'opening' && r.group === 'all' && r.price === 'best') : []);
	const everything = $derived(bt ? bt.back_everything.find((r) => r.timing === 'opening' && r.price === 'best') : undefined);
	const infoRows = $derived(
		bt
			? [
					{ name: 'Match result, opening prices', r: bt.information.opening['1x2'] },
					{ name: 'Match result, closing prices', r: bt.information.closing['1x2'] },
					{ name: 'Over/under 2.5, opening prices', r: bt.information.opening.ou25 },
					{ name: 'Over/under 2.5, closing prices', r: bt.information.closing.ou25 }
				]
			: []
	);
	const worseEverywhere = $derived(everything ? roiRows.filter((r) => r.min_edge >= 0.02).every((r) => r.roi < everything.roi) : false);
	const ret = (r: number) => `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r * 100).toFixed(1)}%`;
	const liveCalibration = $derived(L.calibration.map((c) => ({ ...c, to: c.from + 0.1 })));
</script>

<svelte:head><title>Track record · Pitchside</title></svelte:head>

<div class="wrap record">
	<div>
		<h1 class="display">The record, kept honestly</h1>
		<p class="lede" style="margin-top:1rem">
			Every prediction is stored before kickoff and scored after the match, and the stored predictions cannot be edited. Below: how it has done on real matches so far, then how the model did in tests on matches it had never seen.
		</p>
		<p class="status-line"><b>{L.n}</b> matches played and scored so far. <b>{stored.toLocaleString()}</b> predictions are stored for {d.fixtures.length} upcoming matches.</p>
	</div>

	{#if L.n > 0}
	<section use:reveal>
		<h2 class="h2">The live record so far</h2>
		<p class="muted">
			{L.n} real matches between {shortDate(first.date)} and {shortDate(last.date)}, scored against the predictions stored before kickoff. {L.n} matches is a small sample: a few results either way can move every number below, so read this as a first look, not a verdict.
		</p>
		<div class="panel" style="margin-top:1.25rem">
			<p class="status-line" style="margin:0 0 1rem">
				<b>{L.pick_hits} of {L.n}</b> match results picked correctly ({pct0(L.pick_hits / L.n)}). On the match result the model scored <b>{L.log_loss.toFixed(3)}</b> against {L.log_loss_base.toFixed(3)} for simply using how often each outcome usually happens (lower is better).
			</p>
			<div class="tbl-wrap">
				<table>
					<thead><tr><th scope="col">Market</th><th scope="col">Predicted on average</th><th scope="col">What happened</th></tr></thead>
					<tbody>{#each marketRows as [t, r] (t)}<tr><td>{t}</td><td>{pct1(r.predicted!)}</td><td>{pct1(r.actual!)}</td></tr>{/each}</tbody>
				</table>
			</div>
			{#if notes.length}
				<p class="muted" style="margin-top:1rem">{notes.join(' ')} The model has a known tendency to expect too few goals; this many matches is too few to say whether that is luck or that flaw.</p>
			{/if}
		</div>
		<div class="panel" style="margin-top:1rem">
			<details class="data">
				<summary>Every match scored ({L.n})</summary>
				<div class="tbl-wrap">
					<table>
						<thead><tr><th scope="col">Date</th><th scope="col">League</th><th scope="col">Match</th><th scope="col">Score</th><th scope="col">Home / draw / away</th><th scope="col">Model’s pick</th><th scope="col"><span class="sr-only">Result</span></th></tr></thead>
						<tbody>
							{#each L.matches as m (m.date + m.home)}
								<tr><td>{shortDate(m.date)}</td><td>{NAMES[m.league] ?? m.league}</td><td>{m.home} v {m.away}</td><td>{m.score[0]}–{m.score[1]}</td>
									<td>{pct0(m.p.home)} / {pct0(m.p.draw)} / {pct0(m.p.away)}</td><td>{NAMES[m.pick]}</td><td><strong>{m.hit ? 'Right' : 'Missed'}</strong></td></tr>
							{/each}
						</tbody>
					</table>
				</div>
			</details>
		</div>
		<div class="panel" style="margin-top:1rem">
			<details class="data">
				<summary>All {L.selections.toLocaleString()} scored predictions, grouped by probability</summary>
				<div class="chart-wrap" style="margin-top:1rem">
					<CalibrationChart points={liveCalibration} />
					<div class="tbl-wrap">
						<table>
							<thead><tr><th scope="col">Predicted range</th><th scope="col">Average predicted</th><th scope="col">Actually happened</th><th scope="col">Predictions</th></tr></thead>
							<tbody>{#each liveCalibration as p (p.from)}<tr><td>{Math.round(p.from * 100)}–{Math.round(Math.min(p.to, 1) * 100)}%</td><td>{pct1(p.predicted)}</td><td>{pct1(p.actual)}</td><td>{p.n.toLocaleString()}</td></tr>{/each}</tbody>
						</table>
					</div>
					<p class="muted">Predictions from the same match move together, so this is closer to {L.n} independent results than {L.selections.toLocaleString()}.</p>
				</div>
			</details>
		</div>
		<div class="panel" style="margin-top:1rem">
			<h3 class="h3">Live record by model version</h3>
			<p class="muted">Each kind of prediction is its own model version, with its own live record. A version shows numbers once matches it predicted have finished; below {MIN_LIVE} matches it is too early to read.</p>
			<div class="tbl-wrap">
				<table>
					<thead><tr><th scope="col">Model version</th><th scope="col">Covers</th><th scope="col">Matches scored</th><th scope="col">Predicted on average</th><th scope="col">What happened</th></tr></thead>
					<tbody>
						{#each L.lines as l (l.version)}
							<tr>
								<td>{l.version}</td>
								<td>{lineName(l.version)}</td>
								<td>{l.matches}</td>
								{#if l.matches === 0}
									<td colspan="2">Waiting for its {l.stored_for ?? 0} predicted matches to finish</td>
								{:else if l.matches < MIN_LIVE}
									<td>{pct1(l.predicted!)}</td><td>{pct1(l.actual!)} <span class="muted">(too early)</span></td>
								{:else}
									<td>{pct1(l.predicted!)}</td><td>{pct1(l.actual!)}</td>
								{/if}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="muted">“Predicted on average” and “what happened” compare across every selection scored for that version. They should be close if the numbers are well calibrated.</p>
		</div>
		{#if L.waiting_minutes}
			<p class="muted" style="margin-top:1rem">{L.waiting_minutes.toLocaleString()} more predictions (first goal, goal times and similar) are waiting for verified goal minutes and are not counted yet.</p>
		{/if}
	</section>
	{:else}
		<section use:reveal>
			<h2 class="h2">The live record so far</h2>
			<p class="muted">No finished match has been scored yet.</p>
		</section>
	{/if}

	{#if C}
		<section use:reveal>
			<h2 class="h2">Does the confidence rating mean anything?</h2>
			<p class="muted">
				Each prediction is rated High, Medium or Low from how the model did on past predictions of the same kind. The ratings were built from {C.fitted_on_matches} matches, then checked on the next {C.checked_on_matches} matches (played after {C.until}) that were not used to build them. A rating is only worth showing if higher ratings really did better.
			</p>
			<div class="panel" style="margin-top:1.25rem">
				<div class="tbl-wrap">
					<table>
						<thead><tr><th scope="col">Rating</th><th scope="col">Share of predictions</th><th scope="col">Model said</th><th scope="col">Actually happened</th><th scope="col">Better than the plain average by</th></tr></thead>
						<tbody>{#each C.tiers as t (t.tier)}<tr><td>{t.tier}</td><td>{pct0(t.share)}</td><td>{pct1(t.predicted)}</td><td>{pct1(t.happened)}</td><td><strong>{pct1(t.skill)}</strong></td></tr>{/each}</tbody>
					</table>
				</div>
			</div>
		</section>
	{/if}

	{#if bt}
		<section id="bookmakers" use:reveal>
			<h2 class="h2">Does comparing with the bookmakers help?</h2>
			<p class="muted">
				We compared our probabilities with the bookmakers’ prices from football-data.co.uk over {bt.period.matches.toLocaleString()} matches ({shortDate(bt.period.from)} {bt.period.from.slice(0, 4)} to {shortDate(bt.period.to)} {bt.period.to.slice(0, 4)}),
				for the match result and over/under 2.5 goals. The model never saw these matches, and “opening” prices are the ones published a few days before kickoff, which is what the match page shows.
			</p>
			<div class="panel" style="margin-top:1.25rem">
				<h3 class="h3">Who predicted better?</h3>
				<p class="muted small" style="margin-top:.4rem">Log loss on the later 40% of matches; lower is better. “Both blended” mixes our probabilities with the bookmakers’, with weights fitted on the earlier matches.</p>
				<div class="tbl-wrap">
					<table>
						<thead><tr><th scope="col">Market and prices</th><th scope="col">Bookmakers</th><th scope="col">Our model</th><th scope="col">Both blended</th></tr></thead>
						<tbody>
							{#each infoRows as { name, r } (name)}
								<tr><td>{name}</td><td><strong>{r.market.toFixed(4)}</strong></td><td>{r.model.toFixed(4)}</td><td>{r.blend.toFixed(4)}</td></tr>
							{/each}
						</tbody>
					</table>
				</div>
				<p class="muted" style="margin-top:1rem">The bookmakers’ prices predicted better than our model everywhere, and mixing our probabilities in added essentially nothing. Their prices already contain what our model knows, and more.</p>
			</div>
			<div class="panel" style="margin-top:1rem">
				<h3 class="h3">Would backing our gaps have paid?</h3>
				<p class="muted small" style="margin-top:.4rem">One unit staked on every selection where our probability was at least this many points above the bookmakers’, at the best opening price listed. Match result and over/under 2.5 together.</p>
				<div class="tbl-wrap">
					<table>
						<thead><tr><th scope="col">Our probability above theirs by</th><th scope="col">Bets</th><th scope="col">Won</th><th scope="col">Return per unit staked</th><th scope="col">Margin of error</th></tr></thead>
						<tbody>
							{#if everything}
								<tr><td>Back every selection</td><td>{everything.bets.toLocaleString()}</td><td>—</td><td><strong>{ret(everything.roi)}</strong></td><td>—</td></tr>
							{/if}
							{#each roiRows as r (r.min_edge)}
								<tr><td>{r.min_edge === 0 ? 'Any gap' : `${Math.round(r.min_edge * 100)} points or more`}</td><td>{r.bets.toLocaleString()}</td><td>{pct0(r.hit_rate)}</td><td><strong>{ret(r.roi)}</strong></td><td>±{((r.roi_ci ?? 0) * 100).toFixed(1)}%</td></tr>
							{/each}
						</tbody>
					</table>
				</div>
				<p class="muted" style="margin-top:1rem">
					{#if worseEverywhere}
						Backing our gaps returned less than backing everything at every threshold, and the bigger the gap, the worse it did. When we disagreed with the bookmakers, it was usually our number that was wrong.
					{:else}
						Read the margins of error: the groups with few bets are too small to trust.
					{/if}
					Prices are the best across the bookmakers on football-data.co.uk; real accounts face stake limits and the best price is not always available. Nothing here is advice.
				</p>
			</div>
		</section>
	{/if}

	<section use:reveal>
		<h2 class="h2">When it says 70%, does it happen 70% of the time?</h2>
		<p class="muted">
			A held-out test: 500 real matches from the 2025/26 and 2026/27 seasons, scored on about 330,000 predictions. Each point is a group of predictions with a similar probability. Points on the dashed line mean the model’s numbers match reality. This is a test, not the live record.
		</p>
		<div class="panel chart-wrap" style="margin-top:1.25rem">
			<CalibrationChart points={v.calibration} />
			<div class="legend"><span><i></i>What actually happened</span><span><i class="dash"></i>Perfect match with the predictions</span></div>
			<details class="data">
				<summary>Show the numbers</summary>
				<div class="tbl-wrap">
					<table>
						<thead><tr><th scope="col">Predicted range</th><th scope="col">Average predicted</th><th scope="col">Actually happened</th><th scope="col">Predictions</th></tr></thead>
						<tbody>{#each v.calibration as p (p.from)}<tr><td>{Math.round(p.from * 100)}–{Math.round(Math.min(p.to, 1) * 100)}%</td><td>{pct1(p.predicted)}</td><td>{pct1(p.actual)}</td><td>{p.n.toLocaleString()}</td></tr>{/each}</tbody>
					</table>
				</div>
			</details>
		</div>
	</section>

	<section use:reveal>
		<h2 class="h2">Does it add anything beyond a plain average?</h2>
		<p class="muted">Compared with simply guessing how often each outcome usually happens. A higher share removed means the model carries real information. Lower log loss is better.</p>
		<div class="panel" style="margin-top:1.25rem">
			<div class="tbl-wrap">
				<table>
					<thead><tr><th scope="col">Group of markets</th><th scope="col">Predictions tested</th><th scope="col">Model log loss</th><th scope="col">Plain-average log loss</th><th scope="col">Share removed</th></tr></thead>
					<tbody>{#each v.families as f (f.family)}<tr><td>{FAMILIES[f.family]}</td><td>{f.selections.toLocaleString()}</td><td>{f.model.toFixed(4)}</td><td>{f.base.toFixed(4)}</td><td><strong>{f.skill >= 0 ? '+' : ''}{(f.skill * 100).toFixed(1)}%</strong></td></tr>{/each}</tbody>
				</table>
			</div>
		</div>
	</section>

	<section use:reveal>
		<h2 class="h2">Against the bookmakers on the match result</h2>
		<p class="muted">The model beats a league average in every league, but the bookmakers’ closing odds still predict the result better. That is expected: they use lineups and team news, and this model does not.</p>
		<div class="panel" style="margin-top:1.25rem">
			<div class="tbl-wrap">
				<table>
					<thead><tr><th scope="col">League</th><th scope="col">Matches</th><th scope="col">Model</th><th scope="col">League average</th><th scope="col">Bookmakers</th><th scope="col">Right result: model</th><th scope="col">Right result: bookmakers</th></tr></thead>
					<tbody>{#each v.leagues as r (r.id)}<tr><td>{r.name}</td><td>{r.matches.toLocaleString()}</td><td>{r.model.toFixed(3)}</td><td>{r.base.toFixed(3)}</td><td>{r.book.toFixed(3)}</td><td>{(r.right_model * 100).toFixed(1)}%</td><td>{(r.right_book * 100).toFixed(1)}%</td></tr>{/each}</tbody>
				</table>
			</div>
		</div>
	</section>

	<section use:reveal>
		<h2 class="h2">What it does not know</h2>
		<ul class="list" style="margin-top:1rem">
			<li><strong>Lineups, injuries and suspensions.</strong> Not used yet.</li>
			<li><strong>How stable a probability is.</strong> The confidence ratings do not yet include how much a number would move if the model were refitted.</li>
			<li><strong>A long live record.</strong> Only {L.n} matches have been scored so far, which is too few to judge the model. The tests further down are not live results.</li>
			<li><strong>Player markets, and half-by-half corners and cards.</strong> Not built: they need lineups and half-level data we do not have.</li>
		</ul>
	</section>
</div>

<style>
	.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
