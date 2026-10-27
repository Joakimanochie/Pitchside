<script lang="ts">
	import MatchCard from '#lib/components/MatchCard.svelte';
	import { reveal } from '#lib/reveal.js';
	import { ui } from '#lib/ui.svelte.js';
	import { clock, dayKey, dayLabel, tzLabel } from '#lib/time.svelte.js';
	import type { FixtureSummary } from '#lib/types.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const index = $derived(data.index);

	// A match stays here from the listing until it is over (people watch it with the numbers open) and moves to Results once scored. The results job removes it within the hour of the final whistle;
	// this cutoff (kickoff plus 2 h 15 min) only stops a match lingering if that update is late. Before the browser takes over (clock.now is 0) every match is listed.
	const PLAYING_MS = 135 * 60_000;
	const upcoming = $derived(index.fixtures.filter((f) => clock.now === 0 || new Date(f.kickoff).getTime() + PLAYING_MS > clock.now));
	let query = $state('');
	const shown = $derived(upcoming.filter((f) => (ui.league === 'ALL' || f.league === ui.league) && (!query.trim() || `${f.home} ${f.away}`.toLowerCase().includes(query.trim().toLowerCase()))));
	const days = $derived.by(() => {
		void clock.local;
		const groups = new Map<string, FixtureSummary[]>();
		for (const f of shown) {
			const k = dayKey(f.kickoff);
			groups.set(k, [...(groups.get(k) ?? []), f]);
		}
		return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
	});
	const counts = $derived(Object.fromEntries(Object.keys(index.leagues).map((id) => [id, upcoming.filter((f) => f.league === id).length])));
	const generated = $derived(new Date(index.generated_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', timeZone: 'UTC' }));
</script>

<div class="wrap">
	<div class="intro">
		<h1 class="display">This week across Europe’s top leagues</h1>
		<p class="lede">Every upcoming match, with a probability for every market a betting site offers. Open a match to read all of them, and the numbers behind them.</p>
		<div class="pills" role="group" aria-label="League">
			<button class="pill" aria-pressed={ui.league === 'ALL'} onclick={() => (ui.league = 'ALL')}>All leagues <span class="count">{upcoming.length}</span></button>
			{#each Object.entries(index.leagues) as [id, name] (id)}
				<button class="pill" aria-pressed={ui.league === id} disabled={!counts[id]} onclick={() => (ui.league = id)}>{name} <span class="count">{counts[id]}</span></button>
			{/each}
		</div>
		<label class="sr-only" for="team-search">Find a club</label>
		<input id="team-search" class="search" type="search" placeholder="Find a club" bind:value={query} />
		<div class="notice">
			<svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5" /><path d="M8 7.2v4" /><circle cx="8" cy="4.8" r=".6" fill="currentColor" /></svg>
			<p>
				<strong>Private preview.</strong> The {upcoming.length} matches to be played or in play, predicted up to {generated}, refreshed every morning. Predictions use results only: no lineups, injuries or suspensions.
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
		<p class="empty">
			{upcoming.length ? 'No matches still to be played in this league.' : 'Every match in the window has kicked off.'}
			Matches already played are in <a href="/app/results">Results</a>; new fixtures arrive each morning.
		</p>
	{/if}
</div>
