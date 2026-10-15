import { json } from '@sveltejs/kit';
import { getDb } from '#lib/server/db.js';
import type { RequestHandler } from './$types';

// The one dynamic route in an otherwise prerendered site: stores "was this useful?" feedback in Cloudflare D1.
export const prerender = false;

export const POST: RequestHandler = async ({ request }) => {
	const db = await getDb();
	if (!db) return json({ ok: false, error: 'Feedback is not available here.' }, { status: 503 });

	let body: { match_id?: unknown; page?: unknown; useful?: unknown; comment?: unknown };
	try {
		body = await request.json();
	} catch {
		return json({ ok: false, error: 'Bad request.' }, { status: 400 });
	}
	const useful = body.useful === true ? 1 : body.useful === false ? 0 : null;
	const comment = typeof body.comment === 'string' ? body.comment.trim().slice(0, 2000) : '';
	if (useful === null && !comment) return json({ ok: false, error: 'Nothing to save.' }, { status: 400 });
	const matchId = Number.isInteger(body.match_id) ? (body.match_id as number) : null;
	const page = typeof body.page === 'string' ? body.page.slice(0, 200) : null;
	// Cloudflare Access adds the signed-in email; it tells us who said what during the invited preview.
	const email = request.headers.get('cf-access-authenticated-user-email');

	await db.prepare('INSERT INTO feedback (match_id, page, useful, comment, email) VALUES (?, ?, ?, ?, ?)').bind(matchId, page, useful, comment || null, email).run();
	return json({ ok: true });
};
