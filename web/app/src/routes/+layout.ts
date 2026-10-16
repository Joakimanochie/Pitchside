import type { Index } from '#lib/types.js';
import type { LayoutLoad } from './$types';

// Every page is built ahead of time from the data files the daily pipeline writes (see scripts/export_app_data.py).
export const prerender = true;

export const load: LayoutLoad = async ({ fetch, url }) => {
	const res = await fetch('/data/index.json');
	if (!res.ok) {
		// /admin is rendered live, where the Worker cannot fetch its own static files; it needs only the page frame, not the predictions.
		if (url.pathname.startsWith('/admin')) return { index: { generated_at: new Date().toISOString(), model_version: '' } as Index };
		throw new Error(`index.json: HTTP ${res.status}`);
	}
	return { index: (await res.json()) as Index };
};
