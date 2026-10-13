import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { lineChipLabel, marketTitle, selectionLabel, tabOf } from './labels';
import type { Index, MatchDetail } from './types';

// Reads the real exported data (not committed; the pipeline writes it before the build). Skipped when it is absent.
const dir = 'static/data';
const have = existsSync(`${dir}/index.json`) && existsSync(`${dir}/match`);

describe.skipIf(!have)('every label on every upcoming match reads as words', () => {
	const index: Index = have ? JSON.parse(readFileSync(`${dir}/index.json`, 'utf8')) : ({} as Index);
	const matches: MatchDetail[] = have ? readdirSync(`${dir}/match`).filter((f) => f.endsWith('.json')).map((f) => JSON.parse(readFileSync(`${dir}/match/${f}`, 'utf8'))) : [];

	it('has matches to check', () => {
		expect(matches.length).toBeGreaterThan(0);
	});

	it('gives every market a title, a tab and every selection a readable label', () => {
		const bad: string[] = [];
		for (const m of matches) {
			const ctx = { home: m.home, away: m.away };
			for (const [mid, lines] of Object.entries(m.preds)) {
				const meta = index.markets[mid];
				if (!meta) { bad.push(`${mid}: no market metadata`); continue; }
				if (!marketTitle(meta.name, ctx).trim()) bad.push(`${mid}: empty title`);
				if (!tabOf(mid, meta)) bad.push(`${mid}: no tab`);
				for (const [lk, rows] of Object.entries(lines)) {
					if (lk !== 'null' && !lineChipLabel(mid, lk).trim()) bad.push(`${mid} ${lk}: empty line chip`);
					for (const [sel] of rows) {
						const label = selectionLabel(mid, lk, sel, ctx);
						if (!label.trim() || /undefined|NaN|\[object/.test(label) || /_/.test(label)) bad.push(`${mid} ${lk} ${sel} -> "${label}"`);
					}
				}
			}
		}
		expect([...new Set(bad)].slice(0, 40)).toEqual([]);
	});

	it('labels the two sides of one market differently', () => {
		const m = matches[0];
		const ctx = { home: m.home, away: m.away };
		for (const [mid, lines] of Object.entries(m.preds)) {
			for (const [lk, rows] of Object.entries(lines)) {
				const labels = rows.map(([sel]) => selectionLabel(mid, lk, sel, ctx));
				expect(new Set(labels).size, `${mid} ${lk}`).toBe(labels.length);
			}
		}
	});
});
