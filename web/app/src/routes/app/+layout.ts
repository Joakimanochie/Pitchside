import type { Index } from '#lib/types.js';
import type { LayoutLoad } from './$types';

// The pages under /app are built ahead of time from the data files the daily pipeline writes (see scripts/export_app_data.py).
export const load: LayoutLoad = async ({ fetch }) => {
	const res = await fetch('/data/index.json');
	if (!res.ok) throw new Error(`index.json: HTTP ${res.status}`);
	return { index: (await res.json()) as Index };
};
