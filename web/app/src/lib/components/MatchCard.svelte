<script lang="ts">
	import { pct0 } from '#lib/labels.js';
	import { timeLabel } from '#lib/time.svelte.js';
	import type { FixtureSummary } from '#lib/types.js';

	let { fixture, leagueName }: { fixture: FixtureSummary; leagueName: string } = $props();
	const p = $derived(fixture.p);
</script>

<li>
	<a class="match-card" href="/match/{fixture.id}">
		<div class="kick"><span class="kick-time">{timeLabel(fixture.kickoff)}</span><span class="kick-league">{leagueName}</span></div>
		<div class="teams"><span>{fixture.home}</span><span><span class="vs">v </span>{fixture.away}</span></div>
		<div class="probs">
			<div class="bar3" aria-hidden="true">
				<i class="h" style="width:{(p.home * 100).toFixed(1)}%"></i><i class="d" style="width:{(p.draw * 100).toFixed(1)}%"></i><i class="a" style="width:{(p.away * 100).toFixed(1)}%"></i>
			</div>
			<div class="pnums">
				<span><b>{pct0(p.home)}</b><small>Home win</small></span>
				<span><b>{pct0(p.draw)}</b><small>Draw</small></span>
				<span><b>{pct0(p.away)}</b><small>Away win</small></span>
			</div>
		</div>
	</a>
</li>
