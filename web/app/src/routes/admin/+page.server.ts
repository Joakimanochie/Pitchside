import { error } from '@sveltejs/kit';
import { getDb } from '#lib/server/db.js';
import type { PageServerLoad } from './$types';

// The operator's dashboard. Cloudflare Access guards /admin as well; this check is the second lock.
export const prerender = false;
export const ssr = true;

const ADMIN = 'anochietobe@gmail.com';

type Row = Record<string, string | number | null>;

export const load: PageServerLoad = async ({ request }) => {
	const email = request.headers.get('cf-access-authenticated-user-email');
	if (email?.toLowerCase() !== ADMIN) error(404, 'Not found');
	const db = await getDb();
	if (!db) error(503, 'The database is not available here.');
	const q = async (sql: string, ...args: unknown[]): Promise<Row[]> => (await db.prepare(sql).bind(...args).all<Row>()).results;
	// the operator's own visits are left out of every visitor number
	const me = ADMIN;

	const [totals, daily, newPeople, pages, referrers, countries, devices, people, feedback, feedbackSummary] = await Promise.all([
		q(`SELECT
			(SELECT count(*) FROM events WHERE day = date('now') AND coalesce(email,'') <> ?) AS views_today,
			(SELECT count(DISTINCT email) FROM events WHERE day = date('now') AND coalesce(email,'') <> ?) AS people_today,
			(SELECT count(*) FROM events WHERE day >= date('now','-6 day') AND coalesce(email,'') <> ?) AS views_7d,
			(SELECT count(DISTINCT email) FROM events WHERE day >= date('now','-6 day') AND coalesce(email,'') <> ?) AS people_7d,
			(SELECT count(DISTINCT email) FROM events WHERE coalesce(email,'') <> ?) AS people_all,
			(SELECT count(*) FROM events WHERE coalesce(email,'') <> ?) AS views_all`, me, me, me, me, me, me),
		q(`SELECT day, count(*) AS views, count(DISTINCT email) AS people FROM events WHERE day >= date('now','-29 day') AND coalesce(email,'') <> ? GROUP BY day ORDER BY day`, me),
		q(`SELECT first AS day, count(*) AS n FROM (SELECT email, min(day) AS first FROM events WHERE email IS NOT NULL AND email <> ? GROUP BY email) WHERE first >= date('now','-29 day') GROUP BY first ORDER BY first`, me),
		q(`SELECT path, count(*) AS views, count(DISTINCT email) AS people FROM events WHERE day >= date('now','-29 day') AND coalesce(email,'') <> ? GROUP BY path ORDER BY views DESC LIMIT 15`, me),
		q(`SELECT coalesce(utm, ref_host, 'direct / unknown') AS source, count(*) AS visits, count(DISTINCT email) AS people FROM events WHERE day >= date('now','-29 day') AND coalesce(email,'') <> ? GROUP BY 1 ORDER BY visits DESC LIMIT 15`, me),
		q(`SELECT coalesce(country,'?') AS country, count(DISTINCT email) AS people, count(*) AS views FROM events WHERE day >= date('now','-29 day') AND coalesce(email,'') <> ? GROUP BY 1 ORDER BY people DESC LIMIT 10`, me),
		q(`SELECT coalesce(device,'?') AS device, count(*) AS views FROM events WHERE day >= date('now','-29 day') AND coalesce(email,'') <> ? GROUP BY 1 ORDER BY views DESC`, me),
		q(`SELECT email, min(day) AS first_seen, max(day) AS last_seen, count(*) AS views, count(DISTINCT day) AS days FROM events WHERE email IS NOT NULL AND email <> ? GROUP BY email ORDER BY max(ts) DESC LIMIT 100`, me),
		q(`SELECT id, created_at, page, useful, comment, email FROM feedback ORDER BY id DESC LIMIT 200`),
		q(`SELECT sum(useful = 1) AS yes, sum(useful = 0) AS no, count(*) AS total FROM feedback`)
	]);
	return { totals: totals[0], daily, newPeople, pages, referrers, countries, devices, people, feedback, feedbackSummary: feedbackSummary[0] };
};
