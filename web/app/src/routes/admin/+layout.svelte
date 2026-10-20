<script lang="ts">
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<div class="shell">
	<main id="main" tabindex="-1">
		<p class="small"><a href="/app" data-sveltekit-reload>Back to the app</a></p>
		{@render children()}
	</main>
</div>
