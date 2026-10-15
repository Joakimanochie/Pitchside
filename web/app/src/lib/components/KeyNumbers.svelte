<script lang="ts">
	import ConfBars from './ConfBars.svelte';
	import { marketTitle, pct0, selectionLabel } from '#lib/labels.js';
	import type { Ctx, Index, LinesMap } from '#lib/types.js';

	let { preds, index, ctx }: { preds: Record<string, LinesMap>; index: Index; ctx: Ctx } = $props();

	// The questions most people open a match to answer, then the numbers the model is most reliable about.
	const KEY: [string, string][] = [['ou_total', '2.5'], ['btts', 'null'], ['double_chance', 'null']];

	type Row = { title: string; label: string; p: number; tier: number };
	const rowFor = (mid: string, line: string, sel: [string, number, number, number]): Row => ({
		title: marketTitle(index.markets[mid].name, ctx) + (line === 'null' ? '' : ` ${line}`),
		label: selectionLabel(mid, line, sel[0], ctx),
		p: sel[1],
		tier: sel[3]
	});

	const key = $derived(
		KEY.flatMap(([mid, line]) => {
			const sels = preds[mid]?.[line];
			if (!sels || !index.markets[mid]) return [];
			const best = [...sels].sort((a, b) => b[1] - a[1])[0];
			return [rowFor(mid, line, best as [string, number, number, number])];
		})
	);

	// Most trusted: High-confidence selections that are neither near-certain nor coin flips, one per market.
	const trusted = $derived.by(() => {
		const out: Row[] = [];
		for (const [mid, lines] of Object.entries(preds)) {
			const meta = index.markets[mid];
			if (!meta || meta.family === 'I' || KEY.some(([k]) => k === mid) || mid === '1x2' || /handicap|_ah$|_ah_|from_behind|win_to_nil/.test(mid)) continue;
			let best: [Row, string] | null = null;
			for (const [line, sels] of Object.entries(lines)) {
				for (const s of sels) {
					if (s[3] !== 0 || s[1] < 0.6 || s[1] > 0.85 || Number.isInteger(Number(line)) && line !== 'null') continue;
					if (!best || s[1] > best[0].p) best = [rowFor(mid, line, s as [string, number, number, number]), line];
				}
			}
			if (best) out.push(best[0]);
		}
		return out.sort((a, b) => b.p - a.p).slice(0, 5);
	});
</script>

{#if key.length || trusted.length}
	<section class="keynums" aria-label="Key numbers">
		<h2 class="kn-h">At a glance</h2>
		<div class="kn-grid">
			{#each key as r (r.title)}
				<div class="kn"><span class="kn-t">{r.title}</span><span class="kn-l">{r.label}</span><span class="kn-p">{pct0(r.p)}<ConfBars tier={r.tier} /></span></div>
			{/each}
		</div>
		{#if trusted.length}
			<h3 class="kn-sub">Where the model is most reliable</h3>
			<ul class="kn-list">
				{#each trusted as r (r.title + r.label)}
					<li><span>{r.title}: <strong>{r.label}</strong></span><span class="kn-p">{pct0(r.p)}<ConfBars tier={r.tier} /></span></li>
				{/each}
			</ul>
		{/if}
	</section>
{/if}

<style>
	.keynums { margin-top: 1rem; }
	.kn-h { font-size: 1.1rem; margin: 0 0 0.6rem; }
	.kn-sub { font-size: 0.95rem; margin: 1rem 0 0.4rem; color: var(--muted, inherit); font-weight: 600; }
	.kn-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.6rem; }
	.kn { display: flex; flex-direction: column; gap: 0.15rem; padding: 0.75rem 0.9rem; border: 1px solid var(--line, #8883); border-radius: 12px; }
	.kn-t { font-size: 0.8rem; opacity: 0.75; }
	.kn-l { font-weight: 600; }
	.kn-p { display: inline-flex; align-items: center; gap: 0.5rem; font-variant-numeric: tabular-nums; font-weight: 600; }
	.kn-list { list-style: none; margin: 0; padding: 0; }
	.kn-list li { display: flex; justify-content: space-between; gap: 1rem; padding: 0.45rem 0; border-bottom: 1px solid var(--line, #8883); }
</style>
