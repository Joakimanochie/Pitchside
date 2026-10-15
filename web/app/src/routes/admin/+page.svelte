<script lang="ts">
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const t = $derived(data.totals);
	const n = (v: unknown) => Number(v ?? 0);

	// fill in days with no visits so the bars are a true 30-day picture
	const days = $derived.by(() => {
		const by = new Map(data.daily.map((d) => [String(d.day), d]));
		const fresh = new Map(data.newPeople.map((d) => [String(d.day), n(d.n)]));
		const out: { day: string; views: number; people: number; fresh: number }[] = [];
		for (let i = 29; i >= 0; i--) {
			const day = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
			const d = by.get(day);
			out.push({ day, views: n(d?.views), people: n(d?.people), fresh: fresh.get(day) ?? 0 });
		}
		return out;
	});
	const maxViews = $derived(Math.max(1, ...days.map((d) => d.views)));
	const fb = $derived(data.feedbackSummary);
</script>

<svelte:head><title>Admin · Pitchside</title><meta name="robots" content="noindex" /></svelte:head>

<div class="wrap wide admin">
	<h1 class="display">Admin</h1>
	<p class="lede">Usage and feedback. Your own visits are left out. Times are UTC. “People” are distinct signed-in emails.</p>

	<section aria-label="Totals" class="stats">
		<div><span>People today</span><b>{n(t.people_today)}</b></div>
		<div><span>Views today</span><b>{n(t.views_today)}</b></div>
		<div><span>People, last 7 days</span><b>{n(t.people_7d)}</b></div>
		<div><span>Views, last 7 days</span><b>{n(t.views_7d)}</b></div>
		<div><span>People, all time</span><b>{n(t.people_all)}</b></div>
		<div><span>Views, all time</span><b>{n(t.views_all)}</b></div>
	</section>

	<h2>Last 30 days</h2>
	<div class="chart" role="img" aria-label="Page views per day for the last 30 days">
		{#each days as d (d.day)}
			<div class="col" title="{d.day}: {d.views} views, {d.people} people, {d.fresh} new">
				<i style="height:{(d.views / maxViews) * 100}%"></i>
			</div>
		{/each}
	</div>
	<div class="tbl-wrap">
		<table>
			<thead><tr><th>Day</th><th class="num">People</th><th class="num">New people</th><th class="num">Views</th></tr></thead>
			<tbody>
				{#each [...days].reverse().slice(0, 14) as d (d.day)}
					<tr><td>{d.day}</td><td class="num">{d.people}</td><td class="num">{d.fresh}</td><td class="num">{d.views}</td></tr>
				{/each}
			</tbody>
		</table>
	</div>

	<div class="two">
		<div>
			<h2>How people arrive</h2>
			<p class="small">The site asks visitors to sign in first, which hides where they came from. A link with <code>?ref=whatsapp</code> (or <code>utm_source</code>) on the end is counted under that name.</p>
			<div class="tbl-wrap"><table><thead><tr><th>Source</th><th class="num">Visits</th><th class="num">People</th></tr></thead><tbody>
				{#each data.referrers as r (r.source)}<tr><td>{r.source}</td><td class="num">{r.visits}</td><td class="num">{r.people}</td></tr>{/each}
			</tbody></table></div>
		</div>
		<div>
			<h2>Where from, on what</h2>
			<div class="tbl-wrap"><table><thead><tr><th>Country</th><th class="num">People</th><th class="num">Views</th></tr></thead><tbody>
				{#each data.countries as r (r.country)}<tr><td>{r.country}</td><td class="num">{r.people}</td><td class="num">{r.views}</td></tr>{/each}
			</tbody></table></div>
			<div class="tbl-wrap"><table><thead><tr><th>Device</th><th class="num">Views</th></tr></thead><tbody>
				{#each data.devices as r (r.device)}<tr><td>{r.device}</td><td class="num">{r.views}</td></tr>{/each}
			</tbody></table></div>
		</div>
	</div>

	<h2>Most viewed pages (30 days)</h2>
	<div class="tbl-wrap"><table><thead><tr><th>Page</th><th class="num">Views</th><th class="num">People</th></tr></thead><tbody>
		{#each data.pages as r (r.path)}<tr><td>{r.path}</td><td class="num">{r.views}</td><td class="num">{r.people}</td></tr>{/each}
	</tbody></table></div>

	<h2>People</h2>
	<div class="tbl-wrap"><table><thead><tr><th>Email</th><th>First seen</th><th>Last seen</th><th class="num">Days active</th><th class="num">Views</th></tr></thead><tbody>
		{#each data.people as r (r.email)}<tr><td>{r.email}</td><td>{r.first_seen}</td><td>{r.last_seen}</td><td class="num">{r.days}</td><td class="num">{r.views}</td></tr>{/each}
		{#if !data.people.length}<tr><td colspan="5">No visitors recorded yet.</td></tr>{/if}
	</tbody></table></div>

	<h2>Feedback</h2>
	<p class="small">{n(fb.total)} responses · {n(fb.yes)} found a page useful · {n(fb.no)} did not</p>
	<ul class="fb">
		{#each data.feedback as f (f.id)}
			<li>
				<div class="fb-top"><b>{f.useful === 1 ? 'Useful' : f.useful === 0 ? 'Not useful' : 'Comment'}</b><span>{f.created_at} UTC · {f.email ?? 'unknown'} · {f.page ?? ''}</span></div>
				{#if f.comment}<p>{f.comment}</p>{/if}
			</li>
		{/each}
		{#if !data.feedback.length}<li>No feedback yet.</li>{/if}
	</ul>
</div>

<style>
	.admin h2 { margin: 2rem 0 0.6rem; font-size: 1.25rem; }
	.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.6rem; margin-top: 1rem; }
	.stats div { padding: 0.8rem 1rem; border: 1px solid var(--line, #8883); border-radius: 12px; display: flex; flex-direction: column; gap: 0.2rem; }
	.stats span { font-size: 0.8rem; opacity: 0.75; }
	.stats b { font-size: 1.6rem; font-variant-numeric: tabular-nums; }
	.chart { display: flex; align-items: flex-end; gap: 3px; height: 120px; padding: 0.5rem 0; margin-bottom: 0.8rem; }
	.col { flex: 1; height: 100%; display: flex; align-items: flex-end; }
	.col i { display: block; width: 100%; min-height: 2px; background: linear-gradient(#ff8a1f, #ee222e); border-radius: 3px 3px 0 0; }
	.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
	.small { font-size: 0.85rem; opacity: 0.75; margin-bottom: 0.5rem; }
	.num { text-align: right; font-variant-numeric: tabular-nums; }
	table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
	th, td { padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--line, #8883); text-align: left; }
	th.num { text-align: right; }
	.fb { list-style: none; margin: 0.6rem 0 0; padding: 0; display: grid; gap: 0.6rem; }
	.fb li { padding: 0.7rem 0.9rem; border: 1px solid var(--line, #8883); border-radius: 10px; }
	.fb-top { display: flex; flex-wrap: wrap; gap: 0.2rem 0.8rem; justify-content: space-between; font-size: 0.85rem; }
	.fb-top span { opacity: 0.7; overflow-wrap: anywhere; }
	.fb p { margin-top: 0.4rem; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
