<script lang="ts">
	import MatchCard from '#lib/components/MatchCard.svelte';
	import { reveal } from '#lib/reveal.js';
	import { ui } from '#lib/ui.svelte.js';
	import { clock, dayKey, dayLabel, tzLabel } from '#lib/time.svelte.js';
	import type { FixtureSummary } from '#lib/types.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const index = $derived(data.index);

	const shown = $derived(index.fixtures.filter((f) => ui.league === 'ALL' || f.league === ui.league));
	const days = $derived.by(() => {
		void clock.local;
		const groups = new Map<string, FixtureSummary[]>();
		for (const f of shown) {
			const k = dayKey(f.kickoff);
			groups.set(k, [...(groups.get(k) ?? []), f]);
		}
		return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
	});
	const counts = $derived(Object.fromEntries(Object.keys(index.leagues).map((id) => [id, index.fixtures.filter((f) => f.league === id).length])));
	const generated = $derived(new Date(index.generated_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' }));
</script>

<div class="wrap">
	<div class="intro">
		<h1 class="display">This week across Europe’s top five leagues</h1>
		<p class="lede">Every upcoming match, with a probability for every market a betting site offers. Open a match to read all of them, and the numbers behind them.</p>
		<div class="pills" role="group" aria-label="League">
			<button class="pill" aria-pressed={ui.league === 'ALL'} onclick={() => (ui.league = 'ALL')}>All leagues <span class="count">{index.fixtures.length}</span></button>
			{#each Object.entries(index.leagues) as [id, name] (id)}
				<button class="pill" aria-pressed={ui.league === id} onclick={() => (ui.league = id)}>{name} <span class="count">{counts[id]}</span></button>
			{/each}
		</div>
		<div class="notice">
			<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4" /><circle cx="8" cy="4.8" r=".6" fill="currentColor" /></svg>
			<p>
				<strong>Private preview.</strong> The {index.fixtures.length} matches predicted up to {generated}, refreshed every morning. Predictions use results only: no lineups, injuries or suspensions.
				The bars show how far each number can be trusted. Times are in your time zone ({tzLabel()}).
			</p>
		</div>
	</div>

	{#each days as [k, list], gi (k)}
		<section use:reveal style="--i:{Math.min(gi, 3)}">
			<h2 class="day">{dayLabel(list[0].kickoff)}</h2>
			<ol class="match-list">
				{#each list as f (f.id)}
					<MatchCard fixture={f} leagueName={index.leagues[f.league]} />
				{/each}
			</ol>
		</section>
	{/each}
	{#if !shown.length}
		<p class="empty">No matches in this league right now.</p>
	{/if}
</div>
