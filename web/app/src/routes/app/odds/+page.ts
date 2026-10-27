import type { OddsFile } from '#lib/types.js';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const res = await fetch('/data/odds.json');
	if (!res.ok) throw new Error(`odds.json: HTTP ${res.status}`);
	return { odds: (await res.json()) as OddsFile };
};
