/** Turn stored market codes into words, and decide where a market lives on the match page. Pure functions, no DOM. */
import type { Ctx, LinesMap, MarketMeta } from './types';

export const TABS = [
	{ id: 'main', label: 'Main' },
	{ id: 'goals', label: 'Goals' },
	{ id: 'halves', label: 'Halves' },
	{ id: 'flow', label: 'Game flow' },
	{ id: 'minutes', label: 'Minutes' },
	{ id: 'combos', label: 'Combos' },
	{ id: 'corners', label: 'Corners' },
	{ id: 'cards', label: 'Cards' },
	{ id: 'shots', label: 'Shots' },
	{ id: 'players', label: 'Players' }
] as const;
export type TabId = (typeof TABS)[number]['id'];

const MAIN_IDS = new Set(['1x2', 'double_chance', 'draw_no_bet', 'ou_total', 'btts', 'asian_handicap', 'handicap_3way']);
export const SORT_BY_PROBABILITY = new Set(['correct_score', 'multiscores', 'player_anytime_goal', 'player_assist', 'player_shots', 'player_sot', 'player_carded', 'player_fouls', 'player_fouled']);
export const COLLAPSED_ROWS = 6;

export const pct0 = (p: number) => `${Math.round(p * 100)}%`;
export const pct1 = (p: number) => (p > 0 && p < 0.0005 ? '<0.1%' : `${(p * 100).toFixed(1)}%`);
export const fair = (p: number) => (p <= 0 ? '—' : 1 / p >= 100 ? String(Math.round(1 / p)) : (1 / p).toFixed(2));
const signed = (n: number) => (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n);

function comboLine(mid: string): number | null {
	const m = mid.match(/_(\d)(\d)$/) || mid.match(/^ou_(\d)(\d)_/);
	return m ? parseFloat(`${m[1]}.${m[2]}`) : null;
}

function tokenLabel(tok: string, mid: string, ctx: Ctx): string {
	const { home, away } = ctx;
	// a plain GG/NG market reads "Both teams score"; "Home or GG" and "in both halves" markets are yes/no questions
	const isBtts = mid.includes('btts') && !mid.startsWith('or_') && mid !== 'btts_both_halves';
	const fixed: Record<string, string> = {
		home, away, draw: 'Draw', none: 'No goal', no_goal: 'No goal', odd: 'Odd', even: 'Even', '1st': '1st half', '2nd': '2nd half', equal: 'Equal',
		'1x': `${home} or Draw`, x2: `Draw or ${away}`, '12': `${home} or ${away}`, home_goal: `${home} scores first`, away_goal: `${away} scores first`,
		only_home: `Only ${home}`, only_away: `Only ${away}`, both: 'Both teams', other: 'Other', other_home: `Other ${home} win`, other_away: `Other ${away} win`,
		yes: isBtts ? 'Both teams score' : 'Yes', no: isBtts ? 'Not both teams' : 'No'
	};
	if (tok in fixed) return fixed[tok];
	if (tok === 'over' || tok === 'under') {
		const line = comboLine(mid);
		return (tok === 'over' ? 'Over' : 'Under') + (line != null ? ` ${line}` : '');
	}
	let m = tok.match(/^(home|away)_(\d)(\+?)$/);
	if (m) return `${m[1] === 'home' ? home : away} by ${m[2]}${m[3]}`;
	m = tok.match(/^(home|away)_([\d_-]+\+?)$/); // multiscores: home_3-2_4-2_4-3_5-1
	if (m) return `${m[1] === 'home' ? home : away} win: ${m[2].split('_').map((s) => s.replace('-', ':')).join(', ')}`;
	return tok.replace(/_/g, ' ');
}

function partLabel(part: string, mid: string, ctx: Ctx): string {
	if (!part.includes('/')) return tokenLabel(part, mid, ctx);
	const [a, b] = part.split('/').map((t) => tokenLabel(t, mid, ctx));
	return `HT ${a} / FT ${b}`;
}

export function selectionLabel(mid: string, lineKey: string, sel: string, ctx: Ctx): string {
	const line = lineKey === 'null' ? null : Number(lineKey);
	const { home, away } = ctx;
	if ((mid.startsWith('asian_handicap') || mid.endsWith('_ah')) && line != null) return sel === 'home' ? `${home} ${signed(line)}` : `${away} ${signed(-line)}`;
	if (mid.startsWith('handicap_3way') && line != null) return `${tokenLabel(sel, mid, ctx)} (${line < 0 ? `0:${-line}` : `${line}:0`})`;
	if ((sel === 'over' || sel === 'under') && line != null) return `${sel === 'over' ? 'Over' : 'Under'} ${line}`;
	if (mid === 'first_card_team') return sel === 'none' ? 'No card' : `${sel === 'home' ? home : away} first`;
	if (mid === 'first_card_by') return sel === 'yes' ? 'Yes' : 'No';
	if (mid === 'cards_half_most') return sel === 'equal' ? 'Equal' : `${sel} half`;
	if (mid === 'first_goal_10' || mid === 'first_goal_15') return sel === 'none' ? 'No goal' : `${sel} min`;
	if (mid === 'gg_ng_each_half') {
		const [a, b] = sel.split('/');
		return `1st half: ${a === 'yes' ? 'Yes' : 'No'} · 2nd half: ${b === 'yes' ? 'Yes' : 'No'}`;
	}
	if (mid === 'first_goal_x12' && sel.includes('&')) {
		const [first, result] = sel.split('&');
		const r = result === 'home' ? `${home} win` : result === 'away' ? `${away} win` : tokenLabel(result, mid, ctx);
		return `${partLabel(first, mid, ctx)} & ${r}`;
	}
	if (sel.includes('&')) return sel.split('&').map((part) => partLabel(part, mid, ctx)).join(' & ');
	if (mid === 'ht_ft') return partLabel(sel, mid, ctx);
	if (mid.includes('multigoals') && sel === 'no_goal') return 'No goal';
	return tokenLabel(sel, mid, ctx);
}

export function lineChipLabel(mid: string, lineKey: string): string {
	const n = Number(lineKey);
	if (mid.startsWith('handicap_3way')) return n < 0 ? `0:${-n}` : `${n}:0`;
	if (mid.startsWith('asian_handicap') || mid.endsWith('_ah')) return signed(n);
	if (mid === 'first_card_by') return `by ${n}'`;
	if (mid.startsWith('lead_by')) return `${n}+ goal${n > 1 ? 's' : ''}`;
	if (mid.startsWith('goals_in_a_row')) return `${n}+ in a row`;
	return String(n);
}

export const marketTitle = (name: string, ctx: Ctx) =>
	name.replace(/Home Team/g, ctx.home).replace(/Away Team/g, ctx.away).replace(/ minute$/, ' minutes');

// Search: people type "first goal", the market is called "1st Goal"; "btts" is "GG/NG".
const ALIASES: [RegExp, string][] = [
	[/gg\/ng/i, 'both teams to score btts'],
	[/half time\/full time|halftime\/fulltime/i, 'half time full time ht ft'],
	[/1x2/i, 'match result win draw'],
	[/clean sheet/i, 'shutout']
];
const normalise = (t: string) => t.toLowerCase().replace(/\bfirst\b/g, '1st').replace(/\bsecond\b/g, '2nd').replace(/[^a-z0-9/& ]+/g, ' ');

export function matchesQuery(title: string, query: string): boolean {
	const text = normalise(`${title} ${ALIASES.filter(([re]) => re.test(title)).map(([, w]) => w).join(' ')}`);
	return normalise(query).split(/\s+/).filter(Boolean).every((word) => text.includes(word));
}

export function tabOf(mid: string, meta: MarketMeta): TabId {
	if (meta.family === 'A') return MAIN_IDS.has(mid) ? 'main' : 'goals';
	return ({ B: 'halves', C: 'flow', D: 'minutes', E: 'combos', F: 'corners', G: 'cards', H: 'shots', I: 'players' } as const)[meta.family];
}

/** The line a card opens on: prefer a half line, then the one closest to a coin flip. */
export function defaultLine(lines: LinesMap): string {
	const keys = Object.keys(lines);
	const half = keys.filter((k) => k === 'null' || !Number.isInteger(Number(k)));
	let best: { lk: string; gap: number } | null = null;
	for (const lk of half.length ? half : keys) {
		const gap = Math.abs((lines[lk][0] ? lines[lk][0][1] : 0) - 0.5);
		if (best === null || gap < best.gap) best = { lk, gap };
	}
	return best!.lk;
}

export const sortedLineKeys = (lines: LinesMap) =>
	Object.keys(lines).sort((a, b) => (a === 'null' ? -1 : b === 'null' ? 1 : Number(a) - Number(b)));
