import { describe, expect, it } from 'vitest';
import { EVENTS, hitRate } from './hitrates';
import type { FormResult } from './types';

const game = (gf: number, ga: number, hf: number | null = null, ha: number | null = null): FormResult => ({
	date: '2026-01-01', opponent: 'X', home: true, gf, ga, hf, ha, result: gf > ga ? 'W' : gf === ga ? 'D' : 'L'
});
const ev = (id: string) => EVENTS.find((e) => e.id === id)!;

describe('hit rates', () => {
	const games = [game(2, 1, 1, 0), game(0, 0, 0, 0), game(1, 3, 0, 2), game(3, 0, 2, 0), game(1, 1, 1, 1), game(0, 2, 0, 1)];

	it('counts wins, draws and losses over the last N games only', () => {
		expect(hitRate(games, ev('win'), 5)).toEqual({ hits: 2, games: 5 });
		expect(hitRate(games, ev('draw'), 5)).toEqual({ hits: 2, games: 5 });
		expect(hitRate(games, ev('loss'), 6)).toEqual({ hits: 2, games: 6 });
	});

	it('uses a shorter window when fewer games exist', () => {
		expect(hitRate(games.slice(0, 3), ev('win'), 15)).toEqual({ hits: 1, games: 3 });
		expect(hitRate([], ev('win'), 5)).toEqual({ hits: 0, games: 0 });
	});

	it('counts goals markets from full-time scores', () => {
		expect(hitRate(games, ev('o25'), 6).hits).toBe(3);   // 2-1, 1-3, 3-0 ... totals 3, 0, 4, 3, 2, 2
		expect(hitRate(games, ev('btts'), 6).hits).toBe(3);  // 2-1, 1-3, 1-1
		expect(hitRate(games, ev('cs'), 6).hits).toBe(2);    // 0-0 and 3-0
		expect(hitRate(games, ev('fts'), 6).hits).toBe(2);   // 0-0 and 0-2
	});

	it('skips games without a half-time score instead of counting them as misses', () => {
		const mixed = [game(1, 0, 1, 0), game(2, 2), game(0, 1, 0, 1)];
		expect(hitRate(mixed, ev('h1goal'), 3)).toEqual({ hits: 1, games: 2 });
		expect(hitRate(mixed, ev('h1lead'), 3)).toEqual({ hits: 1, games: 2 });
	});

	it('counts scoring in both halves from the half-time split', () => {
		expect(hitRate([game(2, 0, 1, 0), game(2, 0, 2, 0), game(1, 1, 0, 1)], ev('both'), 3)).toEqual({ hits: 1, games: 3 });
	});
});

describe('model probability for the same event', () => {
	const preds = {
		'1x2': { null: [['home', 0.5, 0, 1], ['draw', 0.3, 0, 1], ['away', 0.2, 0, 1]] },
		ou_total: { '2.5': [['over', 0.55, 0, 1], ['under', 0.45, 0, 1]] },
		clean_sheet_away: { null: [['yes', 0.2, 0, 1], ['no', 0.8, 0, 1]] }
	} as never;

	it('reads win, loss and draw from the match result for the right side', () => {
		expect(ev('win').model(preds, 'home')).toBe(0.5);
		expect(ev('win').model(preds, 'away')).toBe(0.2);
		expect(ev('loss').model(preds, 'home')).toBe(0.2);
		expect(ev('draw').model(preds, 'away')).toBe(0.3);
	});

	it('reads match-level and side-specific markets, and gives null when a market is missing', () => {
		expect(ev('o25').model(preds, 'home')).toBe(0.55);
		expect(ev('cs').model(preds, 'away')).toBe(0.2);
		expect(ev('cs').model(preds, 'home')).toBeNull();
	});
});
