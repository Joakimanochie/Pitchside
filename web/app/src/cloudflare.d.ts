// Worker bindings (see src/lib/server/db.ts)
declare module 'cloudflare:workers' {
	export const env: Record<string, unknown>;
}
