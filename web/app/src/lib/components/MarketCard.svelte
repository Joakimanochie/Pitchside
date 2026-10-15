<script lang="ts">
	import ConfBars from './ConfBars.svelte';
	import { COLLAPSED_ROWS, SORT_BY_PROBABILITY, defaultLine, fair, lineChipLabel, marketTitle, pct1, selectionLabel, sortedLineKeys } from '#lib/labels.js';
	import { reveal } from '#lib/reveal.js';
	import type { Ctx, LinesMap, MarketMeta, Sel } from '#lib/types.js';

	let { mid, meta, lines, ctx, highOnly, outcome = 'all', showResults = false }: { mid: string; meta: MarketMeta; lines: LinesMap; ctx: Ctx; highOnly: boolean; outcome?: 'all' | 'won' | 'lost'; showResults?: boolean } = $props();

	const keep = (r: Sel) => (!highOnly || r[3] === 0) && (outcome === 'all' || (outcome === 'won' ? r[4] === 1 : r[4] === 0));

	let chosen = $state<string | null>(null);
	let open = $state(false);

	const lineKeys = $derived(sortedLineKeys(lines).filter((lk) => lines[lk].some(keep)));
	const current = $derived(
		chosen !== null && lineKeys.includes(chosen) ? chosen : lineKeys.length ? defaultLine(Object.fromEntries(lineKeys.map((lk) => [lk, lines[lk]]))) : null
	);
	const allRows = $derived.by(() => {
		if (current === null) return [];
		const rows = lines[current].filter(keep);
		return SORT_BY_PROBABILITY.has(mid) ? [...rows].sort((a, b) => b[1] - a[1]) : rows;
	});
	const collapsible = $derived(allRows.length > COLLAPSED_ROWS + 2);
	const rows = $derived(collapsible && !open ? allRows.slice(0, COLLAPSED_ROWS) : allRows);
	const refund = $derived(current !== null && current !== 'null' && Number.isInteger(Number(current)) && /^(ou_|asian_handicap)/.test(mid));
</script>

{#if current !== null}
	<article class="market" data-market={mid} use:reveal>
		<h3>{marketTitle(meta.name, ctx)}</h3>
		{#if lineKeys.length > 1}
			<div class="lines" role="group" aria-label="Line">
				{#each lineKeys as lk (lk)}
					<button class="pill sm" aria-pressed={lk === current} onclick={() => (chosen = lk)}>{lineChipLabel(mid, lk)}</button>
				{/each}
			</div>
		{/if}
		{#if refund}
			<p class="refund">On a whole-number line, the stake is returned if the result lands exactly on it. Probabilities here exclude that case.</p>
		{/if}
		<ul class="sels">
			{#each rows as [sel, p, pick, tier, res] (sel)}
				<li class="sel" class:is-pick={pick}>
					<div class="sel-top">
						<span class="sel-name">{selectionLabel(mid, current, sel, ctx)}{#if meta.family === 'I' && ctx.players?.[sel]}<span class="team-tag">{ctx.players[sel] === 'home' ? ctx.home : ctx.away}</span>{/if}{#if pick}<span class="pick-tag">Pick</span>{/if}{#if showResults && (res === 0 || res === 1)}<span class="res-tag" class:won={res === 1}>{res === 1 ? 'Won' : 'Lost'}</span>{:else if showResults && res === 2}<span class="res-tag returned">Stake returned</span>{/if}<ConfBars {tier} /></span>
						<span class="sel-p">{pct1(p)}</span>
						<span class="sel-fair" title="Fair odds: 1 divided by the probability">{fair(p)}</span>
					</div>
					<div class="sel-bar" aria-hidden="true"><i style="width:{(p * 100).toFixed(1)}%"></i></div>
				</li>
			{/each}
		</ul>
		{#if collapsible}
			<div class="more">
				<button onclick={() => (open = !open)}>{open ? 'Show fewer' : `Show all ${allRows.length}${SORT_BY_PROBABILITY.has(mid) ? ' (most likely first)' : ''}`}</button>
			</div>
		{/if}
	</article>
{/if}
