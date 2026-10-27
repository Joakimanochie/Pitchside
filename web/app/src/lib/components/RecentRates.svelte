<script lang="ts">
	import { EVENTS, WINDOWS, hitRate, type Window } from '#lib/hitrates.js';
	import { pct0 } from '#lib/labels.js';
	import type { MatchDetail } from '#lib/types.js';

	let { match }: { match: MatchDetail } = $props();

	let n = $state<Window>(10);

	const groups = ['Result', 'Goals', 'Halves'] as const;
	const rows = $derived(
		EVENTS.map((e) => ({
			e,
			home: hitRate(match.form.home, e, n),
			away: hitRate(match.form.away, e, n),
			modelHome: e.model(match.preds, 'home'),
			modelAway: e.model(match.preds, 'away')
		}))
	);
	const share = (r: { hits: number; games: number }) => (r.games ? (r.hits / r.games) * 100 : 0);
	const enough = $derived(match.form.home.length > 0 && match.form.away.length > 0);
</script>

<section class="rates" aria-label="How often it has happened lately">
	<div class="head">
		<h2 class="h3">How often it has happened lately</h2>
		<div class="windows" role="group" aria-label="Number of matches">
			{#each WINDOWS as w (w)}
				<button class="pill sm" aria-pressed={n === w} onclick={() => (n = w)}>Last {w}</button>
			{/each}
		</div>
	</div>
	<p class="muted small">
		How many of each team’s last {n} matches (any venue) it happened in, beside what the model gives for this match. Shown for context: the model already counts these matches, and in tests recent
		hit rates on their own predicted worse than the model (over 2.5 goals in the last 5 matches did worse than a coin flip). Read them as a description of recent matches, not a prediction.
	</p>
	{#if enough}
		<div class="tbl-wrap" tabindex="0" role="region" aria-label="Table, scrolls sideways">
			<table>
				<thead>
					<tr>
						<th scope="col">Happened</th>
						<th scope="col">{match.home}</th>
						<th scope="col">Model</th>
						<th scope="col">{match.away}</th>
						<th scope="col">Model</th>
					</tr>
				</thead>
				<tbody>
					{#each groups as g (g)}
						<tr class="group"><th scope="rowgroup" colspan="5">{g}</th></tr>
						{#each rows.filter((r) => r.e.group === g) as r (r.e.id)}
							<tr>
								<th scope="row">{r.e.label}</th>
								<td><span class="count">{r.home.hits}/{r.home.games}</span><span class="bar" aria-hidden="true"><i style="width:{share(r.home)}%"></i></span></td>
								<td class="model">{r.modelHome === null ? '—' : pct0(r.modelHome)}</td>
								<td><span class="count">{r.away.hits}/{r.away.games}</span><span class="bar away" aria-hidden="true"><i style="width:{share(r.away)}%"></i></span></td>
								<td class="model">{r.modelAway === null ? '—' : pct0(r.modelAway)}</td>
							</tr>
						{/each}
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<p class="muted">Not enough earlier results in the database for one of the teams.</p>
	{/if}
</section>

<style>
	.rates { background: var(--surface); border-radius: var(--radius-lg); padding: 1.35rem 1.5rem; box-shadow: var(--shadow-card); display: grid; gap: .75rem; min-width: 0; grid-column: 1 / -1; }
	.head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: .6rem 1rem; }
	.h3 { font-size: 1.25rem; line-height: 1.25; }
	.windows { display: flex; gap: .4rem; }
	table { width: 100%; border-collapse: collapse; font-size: .92rem; }
	th, td { padding: .5rem .6rem; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; font-weight: 400; color: var(--ink); }
	thead th { color: var(--ink-3); font-size: .8rem; font-weight: 500; white-space: normal; }
	tbody th[scope='row'] { font-weight: 500; white-space: normal; min-width: 10rem; }
	tr.group th { color: var(--ink-3); font-size: .75rem; font-weight: 500; padding-top: 1rem; border-bottom: 0; text-transform: none; }
	td { white-space: nowrap; }
	.count { display: inline-block; min-width: 3.1rem; font-weight: 600; }
	.bar { display: inline-block; vertical-align: middle; width: 3.5rem; height: 6px; border-radius: 999px; background: var(--panel); overflow: hidden; margin-left: .4rem; }
	.bar i { display: block; height: 100%; background: var(--blue); border-radius: 999px; }
	.bar.away i { background: var(--ink); }
	td.model { color: var(--ink-2); }
	@media (max-width: 760px) {
		.rates { padding: 1.1rem; }
		th, td { padding: .5rem .35rem; }
		.bar { display: none; }
	}
</style>
