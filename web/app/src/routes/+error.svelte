<script lang="ts">
	import { page } from '$app/state';
</script>

<svelte:head><title>{page.status === 404 ? 'Not found' : 'Something went wrong'} · Pitchside</title></svelte:head>

<main class="shell">
<div class="wrap stack">
	<h1 class="display">{page.status === 404 ? 'That page is not here' : 'Something went wrong'}</h1>
	<p class="lede">
		{page.status === 404
			? 'A match page disappears once the match is played and the next daily update runs. The upcoming matches are on the fixtures page.'
			: 'The page could not be shown. Try again in a moment.'}
	</p>
	<p><a class="back" href="/app" data-sveltekit-reload>Back to fixtures</a></p>
</div>
</main>
