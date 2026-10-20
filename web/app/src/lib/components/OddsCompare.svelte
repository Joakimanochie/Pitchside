<script lang="ts">
	import ConfBars from './ConfBars.svelte';
	import { pct0, pct1, selectionLabel } from '#lib/labels.js';
	import type { Index, MatchDetail, OddsMarket } from '#lib/types.js';

	let { match, index }: { match: MatchDetail; index: Index } = $props();

	const ctx = $derived({ home: match.home, away: match.away });
	const odds = $derived(match.odds);
	const bt = $derived(index.value_backtest);

	const title = (m: OddsMarket) =>
		m.market === '1x2' ? 'Match result' : m.market === 'ou_total' ? `Over/Under ${m.line} goals` : `Asian handicap ${match.home} ${m.line! > 0 ? '+' : m.line! < 0 ? '−' : ''}${Math.abs(m.line!)}`;
	const points = (e: number) => `${e > 0 ? '+' : e < 0 ? '−' : ''}${Math.abs(e * 100).toFixed(1)}`;
	const ev = (v: number | null) => (v === null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v * 100).toFixed(1)}%`);
	const stamp = $derived(odds ? new Date(odds.fetched_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }) : '');

	// what happened in past matches when our probability sat well above the bookmakers' (pre-match prices, best price available)
	const past = $derived.by(() => {
		if (!bt) return null;
		const gap = bt.roi.find((r) => r.timing === 'opening' && r.group === 'all' && r.min_edge === 0.05 && r.price === 'best');
		const everything = bt.back_everything.find((r) => r.timing === 'opening' && r.price === 'best');
		return gap && everything ? { gap, everything } : null;
	});
	const ret = (r: number) => `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r * 100).toFixed(1)}%`;
</script>

<section class="odds" aria-label="Our numbers against the bookmakers">
	<h2 class="h3">Our numbers against the bookmakers</h2>
	{#if odds}
		<p class="muted small">
			Prices from {odds.source}, as of {stamp} UTC. “Bookmakers’ view” is the market average with its margin removed. “Gap” is our probability minus theirs, in points.
			“If we are right” is the return per unit staked at the best price listed, if our probability were exactly right.
		</p>
		{#each odds.markets as m (m.market + m.line)}
			<div class="market-block">
				<h3 class="team">{title(m)} <span class="muted small">· bookmaker margin {(m.margin * 100).toFixed(1)}%</span></h3>
				<div class="tbl-wrap">
					<table>
						<thead>
							<tr><th scope="col">Selection</th><th scope="col">Our probability</th><th scope="col">Bookmakers’ view</th><th scope="col">Gap</th><th scope="col">Best price</th><th scope="col">If we are right</th></tr>
						</thead>
						<tbody>
							{#each m.rows as r (r.selection)}
								<tr class:big-gap={Math.abs(r.edge) >= 0.05}>
									<th scope="row">{selectionLabel(m.market, m.line === null ? 'null' : String(m.line), r.selection, ctx)}</th>
									<td>{pct1(r.p)} <ConfBars tier={r.tier} /></td>
									<td>{pct1(r.fair)}</td>
									<td><strong>{points(r.edge)}</strong></td>
									<td>{r.best_odds.toFixed(2)}</td>
									<td>{ev(r.ev)}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if m.stake_can_be_returned}
					<p class="muted small">On this handicap line the stake can be returned or split, which our probabilities leave out, so no return is shown.</p>
				{/if}
			</div>
		{/each}
		<div class="caution">
			<p><strong>Read the gaps with care.</strong>
				{#if past}
					In {past.gap.bets.toLocaleString()} past bets where our probability was at least 5 points above the bookmakers’ (match result and over/under 2.5, pre-match prices), {pct0(past.gap.hit_rate)} won and
					the return was <strong>{ret(past.gap.roi)}</strong> per unit staked at the best price. Backing every selection returned {ret(past.everything.roi)}. When we disagree with the bookmakers, it has usually been our number that was wrong.
				{:else}
					The bookmakers’ prices have predicted results better than our probabilities, so a large gap is more often our error than theirs.
				{/if}
				This is information, not advice. <a href="/app/record#bookmakers">See the full test</a>.
			</p>
		</div>
	{:else}
		<p class="muted">Bookmaker prices for this match have not been published yet. They usually appear two to three days before kickoff, and this page picks them up on the next daily update. Prices cover the match result, over/under 2.5 goals and the main Asian handicap.</p>
	{/if}
</section>

<style>
	.odds { margin-top: 1.25rem; background: var(--surface); border-radius: var(--radius-lg); padding: 1.35rem 1.5rem; box-shadow: var(--shadow-card); display: grid; gap: .9rem; }
	.h3 { font-size: 1.25rem; line-height: 1.25; }
	.team { font: 600 1rem/1.3 var(--font-text); font-style: normal; }
	.market-block { display: grid; gap: .4rem; }
	table { width: 100%; border-collapse: collapse; font-size: .92rem; }
	th, td { padding: .55rem .6rem; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; font-weight: 400; color: var(--ink); }
	thead th { color: var(--ink-3); font-size: .8rem; font-weight: 500; }
	th:first-child, td:first-child { text-align: left; white-space: normal; min-width: 9rem; }
	tbody th { font-weight: 500; }
	tr.big-gap td strong { text-decoration: underline; text-underline-offset: .2em; text-decoration-thickness: 2px; }
	.caution { background: var(--panel); border-radius: var(--radius); padding: .9rem 1.1rem; color: var(--ink-2); font-size: .92rem; }
	.caution strong { color: var(--ink); }
	@media (max-width: 760px) {
		.odds { padding: 1.1rem; }
		th, td { padding: .5rem .4rem; }
	}
</style>
