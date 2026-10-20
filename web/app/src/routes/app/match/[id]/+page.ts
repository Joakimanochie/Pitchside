import { error } from '@sveltejs/kit';
import type { MatchDetail } from '#lib/types.js';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
	const res = await fetch(`/data/match/${params.id}.json`);
	if (!res.ok) error(404, 'That match is not in the latest data.');
	return { match: (await res.json()) as MatchDetail };
};
