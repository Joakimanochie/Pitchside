import adapter from '@sveltejs/adapter-cloudflare';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Scrollable table wrappers are focusable on purpose (role=region, so the keyboard can scroll them); the lint rule does not know that pattern.
				warningFilter: (warning) => warning.code !== 'a11y_no_noninteractive_tabindex',
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter()
		})
	],
	test: { include: ['src/**/*.test.ts'] }
});
