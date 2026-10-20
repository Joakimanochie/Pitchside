import { existsSync, readdirSync } from 'node:fs';
import type { EntryGenerator } from './$types';

// One page per recently finished match, enumerated from the data files written by scripts/export_app_data.py.
export const entries: EntryGenerator = () =>
	existsSync('static/data/result')
		? readdirSync('static/data/result')
				.filter((f) => f.endsWith('.json'))
				.map((f) => ({ id: f.replace('.json', '') }))
		: [];
