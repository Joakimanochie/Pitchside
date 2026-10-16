<svelte:head><title>How it works · Pitchside</title></svelte:head>

<div class="wrap">
	<article class="prose">
		<h1 class="display">How Pitchside works</h1>
		<p class="lede">Pitchside puts a probability on every market a betting site offers for every match in Europe’s top five leagues and the English Championship. It does not take bets, give tips or promise a result.</p>

		<h2>What you are looking at</h2>
		<p>
			Each number is the model’s estimate of how likely something is: “Over 2.5 goals 54%” means that in matches like this one it would happen about 54 times in 100. The small odds beside it (“fair odds”) are simply 1 divided by
			the probability. They are not bookmaker prices, and a bookmaker’s price always includes a margin.
		</p>
		<p><strong>Every prediction is stored before kickoff and never edited.</strong> After the match it is scored against what happened. The <a href="/results">Results</a> page shows each prediction’s outcome, and the <a href="/record">Track record</a> page scores them properly.</p>

		<h2>Where the numbers come from</h2>
		<ul>
			<li><strong>Goals markets</strong> (result, over/under, both teams to score, handicaps, correct score and so on): each club gets an attack and a defence rating from its past results, with recent matches counting more, and matches are turned into scoreline probabilities. Halves, game flow, goal timing and combination markets come from simulating many matches from those probabilities.</li>
			<li><strong>Corners, cards, shots and shots on target</strong>: the same idea with counts of those things instead of goals.</li>
			<li><strong>Player markets</strong> (experimental): each player’s recent share of his club’s goals, shots and assists, combined with the club’s expected goals in the match. Lineups are not known, so these are rough guides.</li>
			<li><strong>The Championship</strong> uses the same models, but is newer here: its confidence bars are not rated yet and it has no player markets, because the shot data those need does not cover it.</li>
			<li><strong>Bookmaker prices</strong> are shown for comparison only. They are never used to make a prediction.</li>
		</ul>
		<p>Results and team statistics come from football-data.co.uk, shot and expected-goals data from Understat, and fixtures from a public scoreboard feed.</p>

		<h2>The confidence bars</h2>
		<p>
			Three small bars beside a number rate how far it can be trusted, not how likely the thing is. We looked at thousands of past predictions of each kind: High means that when the model gave numbers like this one it was reliably better than simply using
			how often that thing usually happens, and its numbers matched reality. Low means the model adds little there, for example on odd/even markets. The ratings were checked on matches they were not built from, and the check is on the Track record page.
		</p>

		<h2>What it cannot do</h2>
		<ul>
			<li><strong>It does not know lineups, injuries or suspensions.</strong> Bookmakers do, which is a large part of why their prices predict results better than we do.</li>
			<li><strong>It does not find winning bets.</strong> We tested this on thousands of matches: backing every selection where our number was well above the bookmakers’ lost money, and the bigger the gap the more it lost. Where we disagree with the bookmakers it has usually been our number that was wrong. The Track record page has the full test.</li>
			<li><strong>The live record is short.</strong> Only matches since October 2026 are scored live. The tests on past matches are not the same as live results.</li>
			<li>Football is uncertain. A 70% chance fails three times in ten.</li>
		</ul>

		<h2>Gambling</h2>
		<p>Pitchside is for people aged 18 and over and is not advice. Please read the <a href="/responsible-gambling">responsible gambling</a> page.</p>
	</article>
</div>
