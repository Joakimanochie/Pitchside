import { error } from '@sveltejs/kit';
import type { ResultDetail } from '#lib/types.js';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
	const res = await fetch(`/data/result/${params.id}.json`);
	if (!res.ok) error(404, 'That result is no longer listed.');
	return { result: (await res.json()) as ResultDetail };
};
