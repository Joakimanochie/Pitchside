// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		interface Platform {
			env?: { DB?: { prepare(sql: string): { bind(...v: unknown[]): { run(): Promise<unknown> } } } };
		}
	}
}

export {};
