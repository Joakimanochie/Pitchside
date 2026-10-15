// The Worker's D1 binding (feedback and usage). In the Cloudflare adapter v8 bindings come from `cloudflare:workers`, not from event.platform.
// Returns undefined where there is no Worker runtime (plain `vite dev`), so callers can say "not available here".
export interface D1Statement {
	bind(...v: unknown[]): D1Statement;
	run(): Promise<unknown>;
	all<T = Record<string, unknown>>(): Promise<{ results: T[] }>;
}
export interface D1 {
	prepare(sql: string): D1Statement;
}

export async function getDb(): Promise<D1 | undefined> {
	try {
		const mod = (await import(/* @vite-ignore */ 'cloudflare:workers')) as { env: { DB?: D1 } };
		return mod.env.DB;
	} catch {
		return undefined;
	}
}
