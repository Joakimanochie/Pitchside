import { getDb } from '#lib/server/db.js';
import type { RequestHandler } from './$types';

// First-party usage counting: one row per page view, no cookies, no third party. See the privacy notice.
export const prerender = false;

const host = (v: unknown) => {
	if (typeof v !== 'string' || !v) return null;
	try {
		return new URL(v).hostname.replace(/^www\./, '').slice(0, 100);
	} catch {
		return null;
	}
};

export const POST: RequestHandler = async ({ request }) => {
	const db = await getDb();
	if (!db) return new Response(null, { status: 204 });
	let b: { path?: unknown; referrer?: unknown; utm?: unknown; device?: unknown };
	try {
		b = await request.json();
	} catch {
		return new Response(null, { status: 400 });
	}
	const path = typeof b.path === 'string' && b.path.startsWith('/') ? b.path.slice(0, 200) : null;
	if (!path || path.startsWith('/admin') || path.startsWith('/api')) return new Response(null, { status: 204 });
	const email = request.headers.get('cf-access-authenticated-user-email');
	const country = request.headers.get('cf-ipcountry');
	const utm = typeof b.utm === 'string' ? b.utm.slice(0, 80) : null;
	const device = b.device === 'mobile' || b.device === 'desktop' ? b.device : null;
	await db.prepare('INSERT INTO events (email, path, ref_host, utm, country, device) VALUES (?, ?, ?, ?, ?, ?)').bind(email, path, host(b.referrer), utm, country, device).run();
	return new Response(null, { status: 204 });
};
