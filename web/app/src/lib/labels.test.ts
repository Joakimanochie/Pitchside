import { describe, expect, it } from 'vitest';
import { defaultLine, fair, lineChipLabel, marketTitle, matchesQuery, pct1, selectionLabel, sortedLineKeys, tabOf } from './labels';

const ctx = { home: 'Arsenal', away: 'Leeds United' };

describe('selectionLabel', () => {
	it('names the teams in handicaps', () => {
		expect(selectionLabel('asian_handicap', '-1.5', 'home', ctx)).toBe('Arsenal −1.5');
		expect(selectionLabel('asian_handicap', '-1.5', 'away', ctx)).toBe('Leeds United +1.5');
		expect(selectionLabel('handicap_3way', '-1', 'draw', ctx)).toBe('Draw (0:1)');
	});
	it('reads over/under, double chance and both-teams-to-score in words', () => {
		expect(selectionLabel('ou_total', '2.5', 'over', ctx)).toBe('Over 2.5');
		expect(selectionLabel('double_chance', 'null', '1x', ctx)).toBe('Arsenal or Draw');
		expect(selectionLabel('btts', 'null', 'yes', ctx)).toBe('Both teams score');
	});
	it('labels half-time / full-time and combination selections', () => {
		expect(selectionLabel('ht_ft', 'null', 'home/home', ctx)).toBe('HT Arsenal / FT Arsenal');
		expect(selectionLabel('1x2_ou_25', 'null', 'home&over', ctx)).toContain('Arsenal & Over');
	});
});

describe('yes/no questions and combos', () => {
	it('keeps Yes/No for markets that only mention both teams to score', () => {
		expect(selectionLabel('or_home_btts', 'null', 'yes', ctx)).toBe('Yes');
		expect(selectionLabel('btts_both_halves', 'null', 'no', ctx)).toBe('No');
		expect(selectionLabel('btts', 'null', 'yes', ctx)).toBe('Both teams score');
	});
	it('says who won in first goal & 1X2', () => {
		expect(selectionLabel('first_goal_x12', 'null', 'home_goal&away', ctx)).toBe('Arsenal scores first & Leeds United win');
	});
	it('pluralises minute windows', () => {
		expect(marketTitle('1X2 from 1 to 5 minute', ctx)).toBe('1X2 from 1 to 5 minutes');
	});
});

describe('corners, cards and shots', () => {
	it('labels handicaps and who-has-more selections with the team names', () => {
		expect(selectionLabel('corners_ah', '-1.5', 'home', ctx)).toBe('Arsenal −1.5');
		expect(selectionLabel('cards_ah', '0.5', 'away', ctx)).toBe('Leeds United −0.5');
		expect(selectionLabel('corners_x12', 'null', 'draw', ctx)).toBe('Draw');
		expect(lineChipLabel('shots_ah', '-2.5')).toBe('−2.5');
		expect(selectionLabel('corners_ou_total', '9.5', 'over', ctx)).toBe('Over 9.5');
	});
	it('files them under their own tabs', () => {
		expect(tabOf('corners_ou_total', { name: 'Corners Over/Under', family: 'F', exclusive: true, order: 1 })).toBe('corners');
		expect(tabOf('cards_ou_total', { name: 'Cards Over/Under', family: 'G', exclusive: true, order: 2 })).toBe('cards');
		expect(tabOf('sot_ou_total', { name: 'Shots on Target Over/Under', family: 'H', exclusive: true, order: 3 })).toBe('shots');
	});
});

describe('search', () => {
	it('finds "1st Goal" when someone types "first goal"', () => {
		expect(matchesQuery('1st Goal', 'first goal')).toBe(true);
		expect(matchesQuery('1st Goal', '1st goal')).toBe(true);
		expect(matchesQuery('Corners', 'first goal')).toBe(false);
		expect(matchesQuery('Corners Over/Under', 'corners')).toBe(true);
	});
	it('knows btts and half time/full time', () => {
		expect(matchesQuery('GG/NG', 'btts')).toBe(true);
		expect(matchesQuery('Half Time/Full Time', 'half time full time')).toBe(true);
	});
	it('does not make "goal" match every over/under market', () => {
		expect(matchesQuery('Over/Under', 'goal')).toBe(false);
	});
});

describe('layout helpers', () => {
	it('files markets under the right tab', () => {
		expect(tabOf('1x2', { name: '1X2', family: 'A', exclusive: true, order: 0 })).toBe('main');
		expect(tabOf('exact_goals', { name: 'Exact', family: 'A', exclusive: true, order: 1 })).toBe('goals');
		expect(tabOf('ht_ft', { name: 'HT/FT', family: 'B', exclusive: true, order: 2 })).toBe('halves');
	});
	it('opens a card on a half line near a coin flip', () => {
		const lines = { '1.0': [['over', 0.8, 0, 1]], '2.5': [['over', 0.52, 0, 1]], '3.5': [['over', 0.3, 0, 1]] } as never;
		expect(defaultLine(lines)).toBe('2.5');
		expect(sortedLineKeys({ '3.5': [], null: [], '1.5': [] } as never)).toEqual(['null', '1.5', '3.5']);
	});
	it('formats probabilities, fair odds and line chips', () => {
		expect(pct1(0.5763)).toBe('57.6%');
		expect(pct1(0.0001)).toBe('<0.1%');
		expect(fair(0.5)).toBe('2.00');
		expect(fair(0.004)).toBe('250');
		expect(lineChipLabel('asian_handicap', '-0.5')).toBe('−0.5');
	});
});
