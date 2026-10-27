<script lang="ts">
	// markup-only page: the script tag turns on TypeScript for the snippet below
</script>

<svelte:head>
	<title>Pitchside · match probabilities you can check afterwards</title>
	<meta name="description" content="A probability for every market on every match in Europe's top leagues, stored before kickoff, never edited, and scored after the match. Sign in with Google." />
</svelte:head>

{#snippet google(label: string)}
	<!-- Cloudflare Access signs the visitor in with Google and sends them to the fixtures. A full page load, because the app is behind the sign-in. -->
	<a class="google" href="/app" data-sveltekit-reload>
		<svg viewBox="0 0 48 48" width="20" height="20" aria-hidden="true">
			<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
			<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
			<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
			<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
		</svg>
		<span>{label}</span>
	</a>
{/snippet}

<div class="land">
	<!-- hero -->
	<section class="hero">
		<div class="hero-copy">
			<p class="eyebrow">Private preview</p>
			<h1 class="display">Football probabilities you can check afterwards</h1>
			<p class="lede">
				A probability for every market a betting site offers, on every match in Europe’s top leagues. Each one is stored before kickoff, never edited, and scored once the match is played.
			</p>
			<div class="cta">
				{@render google('Continue with Google')}
				<a class="ghost" href="#how">How it works</a>
			</div>
			<p class="fine">
				Free during the preview. New here? Continuing creates your account: we receive your email address and name from Google, and nothing else. By continuing you confirm you are 18 or
				over and accept the <a href="/terms">Terms</a> and <a href="/privacy">Privacy notice</a>.
			</p>
		</div>

		<figure class="sample" aria-label="Example of a match page, not a real prediction">
			<figcaption><span class="tag">Example</span> Not a real match or prediction</figcaption>
			<div class="s-head">
				<span class="s-league">League · Saturday 15:00</span>
				<h2 class="s-title">Home FC v Away FC</h2>
			</div>
			<div class="s-bars">
				<div class="s-row"><span>Home win</span><b>52%</b><i style="--w:52%"></i></div>
				<div class="s-row"><span>Draw</span><b>26%</b><i style="--w:26%"></i></div>
				<div class="s-row"><span>Away win</span><b>22%</b><i style="--w:22%"></i></div>
			</div>
			<ul class="s-list">
				<li><span>Over 2.5 goals</span><span class="s-p">56% <span class="conf conf-1" aria-hidden="true"><i></i><i></i><i></i></span></span></li>
				<li><span>Both teams to score</span><span class="s-p">61% <span class="conf conf-2" aria-hidden="true"><i></i><i></i><i></i></span></span></li>
				<li><span>Home team corners over 4.5</span><span class="s-p">54% <span class="conf conf-0" aria-hidden="true"><i></i><i></i><i></i></span></span></li>
			</ul>
			<p class="s-note">Three small bars rate how far a number can be trusted, from past predictions of the same kind.</p>
		</figure>
	</section>

	<!-- facts -->
	<section class="facts" aria-label="At a glance">
		<div><b>8</b><span>competitions</span></div>
		<div><b>200+</b><span>markets per match</span></div>
		<div><b>Before</b><span>kickoff, never edited</span></div>
		<div><b>After</b><span>every match, scored</span></div>
	</section>

	<!-- how it works -->
	<section id="how" class="block">
		<h2 class="h2">How it works</h2>
		<ol class="steps">
			<li>
				<span class="n">1</span>
				<h3>Stored before kickoff</h3>
				<p>Each match gets its predictions days ahead. They are written once, time-stamped, and the database refuses any change afterwards.</p>
			</li>
			<li>
				<span class="n">2</span>
				<h3>Scored after the match</h3>
				<p>When the match ends, every prediction is settled by the same rules that priced it, and the Results page shows the misses as well as the hits.</p>
			</li>
			<li>
				<span class="n">3</span>
				<h3>Rated by its record</h3>
				<p>A High, Medium or Low rating on each number comes from thousands of past predictions of the same kind, checked on matches the rating never saw.</p>
			</li>
		</ol>
	</section>

	<!-- coverage -->
	<section id="covered" class="block">
		<h2 class="h2">What is covered</h2>
		<p class="lede">Every upcoming match in these competitions, refreshed every morning, with team lineups used once they are announced.</p>
		<ul class="chips" aria-label="Competitions">
			<li>Premier League</li>
			<li>La Liga</li>
			<li>Bundesliga</li>
			<li>Serie A</li>
			<li>Ligue 1</li>
			<li>Championship</li>
			<li>Champions League <em>new</em></li>
			<li>Europa League <em>new</em></li>
		</ul>
		<ul class="chips soft" aria-label="Markets">
			<li>Result and double chance</li>
			<li>Over/under and handicaps</li>
			<li>Both teams to score</li>
			<li>Correct score</li>
			<li>Halves</li>
			<li>Goal minutes</li>
			<li>Corners</li>
			<li>Cards and card timing</li>
			<li>Shots</li>
			<li>Player markets</li>
		</ul>
	</section>

	<!-- honesty -->
	<section class="honest">
		<h2 class="h2">We would rather tell you where it is weak</h2>
		<ul>
			<li><b>Bookmakers predict results better than we do.</b> In our own tests, and following our numbers against their prices lost money.</li>
			<li><b>It does not know injuries or suspensions.</b> Lineups are not used yet: the numbers come from past results only.</li>
			<li><b>The European cups are new and experimental.</b> The result markets beat the usual frequencies in tests; goals totals did not.</li>
			<li><b>It is not advice and it takes no bets.</b> For people aged 18 and over. <a href="/responsible-gambling">Responsible gambling</a></li>
		</ul>
	</section>

	<!-- final call -->
	<section class="final">
		<h2 class="h2">See this week’s matches</h2>
		<p class="lede">Sign in with Google and you land on the fixtures.</p>
		<div class="cta">{@render google('Continue with Google')}</div>
	</section>
</div>

<style>
	.land { max-width: 1120px; margin: 0 auto; }
	.eyebrow { font-size: 0.85rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-3); margin: 0 0 0.8rem; }
	.block { margin-top: clamp(3.5rem, 8vw, 6rem); }
	.block .lede { margin-top: 0.6rem; }

	/* hero */
	.hero { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr); gap: clamp(2rem, 5vw, 4rem); align-items: center; }
	.hero .lede { margin-top: 1.1rem; }
	.cta { display: flex; flex-wrap: wrap; align-items: center; gap: 0.9rem; margin-top: 1.75rem; }
	.google {
		display: inline-flex; align-items: center; gap: 0.75rem; min-height: 52px; padding: 0.65rem 1.4rem; border-radius: 999px;
		background: #fff; color: #1f1f1f; border: 1px solid #dadce0; font-weight: 500; font-size: 1rem; text-decoration: none;
		box-shadow: var(--shadow-card); transition: box-shadow 0.2s var(--ease), transform 0.2s var(--ease);
	}
	.google:hover { box-shadow: var(--shadow-lift); transform: translateY(-1px); }
	.ghost { font-weight: 500; padding: 0.7rem 0.4rem; text-decoration: none; border-bottom: 1px solid var(--line-strong); }
	.ghost:hover { border-color: var(--ink); }
	.fine { margin-top: 1.1rem; font-size: 0.85rem; color: var(--ink-3); max-width: 36rem; }
	.fine a, .honest a { text-decoration: underline; }

	/* example card */
	.sample {
		margin: 0; background: var(--navy); color: var(--on-navy); border-radius: var(--radius-lg); padding: 1.4rem 1.4rem 1.2rem;
		box-shadow: 0 30px 60px -30px rgba(12, 16, 34, 0.7); transform: rotate(-1.2deg);
	}
	.sample figcaption { font-size: 0.78rem; color: var(--on-navy-2); display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; }
	.tag { background: var(--blue); color: #fff; border-radius: 999px; padding: 0.1rem 0.6rem; font-weight: 600; letter-spacing: 0.03em; }
	.s-league { font-size: 0.82rem; color: var(--on-navy-2); }
	.s-title { font-size: 1.5rem; margin-top: 0.15rem; }
	.s-bars { margin-top: 1.1rem; display: grid; gap: 0.7rem; }
	.s-row { display: grid; grid-template-columns: 1fr auto; align-items: baseline; gap: 0 0.75rem; font-size: 0.95rem; }
	.s-row b { font: italic 600 1.5rem/1 var(--font-display); }
	.s-row i { grid-column: 1 / -1; height: 6px; border-radius: 3px; background: var(--navy-line); position: relative; overflow: hidden; margin-top: 0.3rem; }
	.s-row i::after { content: ''; position: absolute; inset: 0 auto 0 0; width: var(--w); background: var(--blue-on-navy); border-radius: 3px; }
	.s-list { margin-top: 1.3rem; border-top: 1px solid var(--navy-line); }
	.s-list li { display: flex; justify-content: space-between; align-items: center; padding: 0.65rem 0; border-bottom: 1px solid var(--navy-line); font-size: 0.92rem; }
	.s-p { display: inline-flex; align-items: center; font-weight: 600; font-variant-numeric: tabular-nums; }
	.sample :global(.conf i) { background: #4a5278; }
	.sample :global(.conf-0 i) { background: var(--on-navy); }
	.sample :global(.conf-1 i:nth-child(-n + 2)) { background: var(--on-navy-2); }
	.sample :global(.conf-2 i:nth-child(1)) { background: #7f89ad; }
	.s-note { margin-top: 0.9rem; font-size: 0.8rem; color: var(--on-navy-2); }

	/* facts strip */
	.facts { display: grid; grid-template-columns: repeat(4, 1fr); margin-top: clamp(2.5rem, 6vw, 4rem); border-block: 1px solid var(--line-strong); }
	.facts div { padding: 1.2rem 1rem; display: flex; flex-direction: column; gap: 0.15rem; border-inline-start: 1px solid var(--line); }
	.facts div:first-child { border-inline-start: 0; padding-inline-start: 0; }
	.facts b { font: italic 500 clamp(1.5rem, 3vw, 2.1rem)/1.1 var(--font-display); }
	.facts span { font-size: 0.9rem; color: var(--ink-2); }

	/* steps */
	.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1.25rem; margin-top: 1.5rem; }
	.steps li { background: var(--surface); border-radius: var(--radius); padding: 1.4rem; box-shadow: var(--shadow-card); }
	.n { display: inline-grid; place-items: center; width: 2rem; height: 2rem; border-radius: 50%; background: var(--ink); color: #fff; font-weight: 600; font-size: 0.9rem; margin-bottom: 0.9rem; }
	.steps h3 { font-size: 1.25rem; margin-bottom: 0.4rem; }
	.steps p { color: var(--ink-2); font-size: 0.95rem; }

	/* coverage chips */
	.chips { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1.25rem; }
	.chips li { background: var(--surface); border: 1px solid var(--line-strong); border-radius: 999px; padding: 0.45rem 1rem; font-weight: 500; font-size: 0.95rem; }
	.chips em { font-style: normal; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase; background: var(--blue-soft); color: #1448b8; border-radius: 999px; padding: 0.1rem 0.5rem; margin-left: 0.3rem; }
	.chips.soft li { background: transparent; border-color: var(--line); color: var(--ink-2); font-weight: 400; }

	/* honesty */
	.honest { margin-top: clamp(3.5rem, 8vw, 6rem); background: var(--navy); color: var(--on-navy); border-radius: var(--radius-lg); padding: 2rem; }
	.honest ul { display: grid; gap: 0.9rem; margin-top: 1.3rem; max-width: 46rem; }
	.honest li { color: var(--on-navy-2); padding-inline-start: 1.1rem; position: relative; }
	.honest li::before { content: ''; position: absolute; inset-inline-start: 0; top: 0.65em; width: 6px; height: 6px; border-radius: 50%; background: var(--blue-on-navy); }
	.honest b { color: var(--on-navy); font-weight: 600; }
	.honest a { color: var(--on-navy); }

	/* final call */
	.final { text-align: center; margin: clamp(3.5rem, 8vw, 6rem) auto 1rem; max-width: 36rem; }
	.final .lede { margin: 0.6rem auto 0; }
	.final .cta { justify-content: center; }

	@media (min-width: 901px) {
		.honest { padding: 3rem; }
	}
	@media (max-width: 900px) {
		.hero { grid-template-columns: 1fr; }
		.sample { transform: none; max-width: 28rem; }
		.steps { grid-template-columns: 1fr; }
		.facts { grid-template-columns: repeat(2, 1fr); }
		.facts div:nth-child(3) { border-inline-start: 0; padding-inline-start: 0; }
		.facts div:nth-child(n + 3) { border-top: 1px solid var(--line); }
	}
	@media (prefers-reduced-motion: reduce) {
		.google:hover { transform: none; }
	}
</style>
