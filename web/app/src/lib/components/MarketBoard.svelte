<script lang="ts">
	import ConfBars from './ConfBars.svelte';
	import MarketCard from './MarketCard.svelte';
	import { TABS, marketTitle, matchesQuery, pct1, tabOf, type TabId } from '#lib/labels.js';
	import { ui } from '#lib/ui.svelte.js';
	import type { Ctx, Index, LinesMap } from '#lib/types.js';

	/** Every market of a match with search, tabs and the confidence filter. With `results`, finished-match outcomes are shown and can be filtered. */
	let { preds, index, ctx, results = false }: { preds: Record<string, LinesMap>; index: Index; ctx: Ctx; results?: boolean } = $props();

	let tab = $state<TabId>('main');
	let query = $state('');
	let outcome = $state<'all' | 'won' | 'lost'>('all');

	const markets = $derived(
		Object.entries(preds)
			.filter(([mid]) => index.markets[mid])
			.sort((a, b) => index.markets[a[0]].order - index.markets[b[0]].order)
	);
	const counts = $derived(Object.fromEntries(TABS.map((t) => [t.id, markets.filter(([mid]) => tabOf(mid, index.markets[mid]) === t.id).length])) as Record<TabId, number>);
	const q = $derived(query.trim());
	const visible = $derived(
		markets.filter(([mid]) => (q ? matchesQuery(marketTitle(index.markets[mid].name, ctx), q) : tabOf(mid, index.markets[mid]) === tab))
	);
	const anyShown = $derived(
		visible.some(([, lines]) =>
			Object.values(lines).some((rows) =>
				rows.some((r) => (!ui.highOnly || r[3] === 0) && (outcome === 'all' || (outcome === 'won' ? r[4] === 1 : r[4] === 0)))
			)
		)
	);
	const v = $derived(index.confidence.validation);
	const showsPlayers = $derived(visible.some(([mid]) => index.markets[mid].family === 'I'));
</script>

<h2 class="sr-only">Markets</h2>
<div class="toolbar">
	<div class="conf-note">
		<button class="pill sm" aria-pressed={ui.highOnly} onclick={() => (ui.highOnly = !ui.highOnly)}>High confidence only</button>
		{#if results}
			<div class="outcome" role="group" aria-label="Show">
				{#each [['all', 'All'], ['won', 'Won'], ['lost', 'Lost']] as [id, label] (id)}
					<button class="pill sm" aria-pressed={outcome === id} onclick={() => (outcome = id as 'all' | 'won' | 'lost')}>{label}</button>
				{/each}
			</div>
		{/if}
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

{#if showsPlayers}
	<div class="notice experimental">
		<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4" /><circle cx="8" cy="4.8" r=".6" fill="currentColor" /></svg>
		<p>
			<strong>Experimental.</strong> Player markets use each player’s recent share of his club’s goals, shots and assists. Lineups, injuries and suspensions are not known, so a player who does not play still counts as a loss
			when the match is scored. Treat these as rough guides.
		</p>
	</div>
{/if}

<div class="markets">
	{#each visible as [mid, lines] (mid)}
		<MarketCard {mid} meta={index.markets[mid]} {lines} {ctx} highOnly={ui.highOnly} {outcome} showResults={results} />
	{/each}
</div>
{#if !visible.length}
	<p class="empty">{q ? 'No market matches that search.' : 'Nothing in this group.'}</p>
{:else if !anyShown}
	<p class="empty">Nothing here matches the filters.</p>
{/if}

<style>
	.outcome { display: inline-flex; gap: .35rem; }
</style>
