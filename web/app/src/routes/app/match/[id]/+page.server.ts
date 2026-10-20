import { readdirSync } from 'node:fs';
import type { EntryGenerator } from './$types';

// One page per upcoming match, enumerated from the data files written by scripts/export_app_data.py.
export const entries: EntryGenerator = () =>
	readdirSync('static/data/match')
		.filter((f) => f.endsWith('.json'))
		.map((f) => ({ id: f.replace('.json', '') }));
