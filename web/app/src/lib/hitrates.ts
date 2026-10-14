/**
 * How often each thing has happened in a team's last N matches, set beside the model's probability for the same thing in the upcoming match.
 * Shown for context only: tests found recent hit rates on their own predict worse than the model (docs/goals-model-report.md).
 */
import type { FormResult, LinesMap } from './types';

export const WINDOWS = [5, 10, 15] as const;
export type Window = (typeof WINDOWS)[number];

type Side = 'home' | 'away';
type Preds = Record<string, LinesMap>;

export interface FormEvent {
	id: string;
	label: string;
	group: 'Result' | 'Goals' | 'Halves';
	/** did it happen in this game (from the team's own point of view)? null when the game lacks the data (no half-time score) */
	test: (g: FormResult) => boolean | null;
	/** the model's probability of the same thing in the upcoming match for the team playing on this side */
	model: (preds: Preds, side: Side) => number | null;
}

const pick = (preds: Preds, market: string, line: string, selection: string): number | null => {
	const row = preds[market]?.[line]?.find((r) => r[0] === selection);
	return row ? row[1] : null;
};
const ht = (g: FormResult) => (g.hf == null || g.ha == null ? null : { f: g.hf, a: g.ha });

export const EVENTS: FormEvent[] = [
	{ id: 'win', label: 'Won', group: 'Result', test: (g) => g.gf > g.ga, model: (p, s) => pick(p, '1x2', 'null', s) },
	{ id: 'draw', label: 'Drew', group: 'Result', test: (g) => g.gf === g.ga, model: (p) => pick(p, '1x2', 'null', 'draw') },
	{ id: 'loss', label: 'Lost', group: 'Result', test: (g) => g.gf < g.ga, model: (p, s) => pick(p, '1x2', 'null', s === 'home' ? 'away' : 'home') },
	{ id: 'o15', label: 'Over 1.5 goals', group: 'Goals', test: (g) => g.gf + g.ga > 1.5, model: (p) => pick(p, 'ou_total', '1.5', 'over') },
	{ id: 'o25', label: 'Over 2.5 goals', group: 'Goals', test: (g) => g.gf + g.ga > 2.5, model: (p) => pick(p, 'ou_total', '2.5', 'over') },
	{ id: 'o35', label: 'Over 3.5 goals', group: 'Goals', test: (g) => g.gf + g.ga > 3.5, model: (p) => pick(p, 'ou_total', '3.5', 'over') },
	{ id: 'btts', label: 'Both teams scored', group: 'Goals', test: (g) => g.gf > 0 && g.ga > 0, model: (p) => pick(p, 'btts', 'null', 'yes') },
	{ id: 'cs', label: 'Clean sheet', group: 'Goals', test: (g) => g.ga === 0, model: (p, s) => pick(p, `clean_sheet_${s}`, 'null', 'yes') },
	{ id: 'fts', label: 'Failed to score', group: 'Goals', test: (g) => g.gf === 0, model: (p, s) => pick(p, `goals_${s}`, 'null', '0') },
	{ id: 's2', label: 'Scored 2 or more', group: 'Goals', test: (g) => g.gf >= 2, model: (p, s) => pick(p, `ou_${s}`, '1.5', 'over') },
	{ id: 'h1goal', label: 'Scored in the 1st half', group: 'Halves', test: (g) => (ht(g) ? ht(g)!.f > 0 : null), model: (p, s) => pick(p, `ou_${s}_h1`, '0.5', 'over') },
	{ id: 'h1lead', label: 'Led at half-time', group: 'Halves', test: (g) => (ht(g) ? ht(g)!.f > ht(g)!.a : null), model: (p, s) => pick(p, '1x2_h1', 'null', s) },
	{ id: 'h1o05', label: '1st half over 0.5 goals', group: 'Halves', test: (g) => (ht(g) ? ht(g)!.f + ht(g)!.a > 0.5 : null), model: (p) => pick(p, 'ou_total_h1', '0.5', 'over') },
	{ id: 'both', label: 'Scored in both halves', group: 'Halves', test: (g) => (ht(g) ? ht(g)!.f > 0 && g.gf - ht(g)!.f > 0 : null), model: (p, s) => pick(p, `${s}_scores_both_halves`, 'null', 'yes') }
];

export interface Rate {
	hits: number;
	games: number;
}

/** Hits among the team's last `n` games that carry the data the event needs. `games` is newest first. */
export function hitRate(games: FormResult[], event: FormEvent, n: number): Rate {
	let hits = 0;
	let seen = 0;
	for (const g of games.slice(0, n)) {
		const r = event.test(g);
		if (r === null) continue;
		seen += 1;
		if (r) hits += 1;
	}
	return { hits, games: seen };
}
