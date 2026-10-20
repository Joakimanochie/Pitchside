<script lang="ts">
	import '../app.css';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
</script>

<svelte:head>
	<title>Pitchside · match predictions</title>
	<meta name="description" content="A probability for every market on every match in Europe's top leagues, stored before kickoff and scored after." />
</svelte:head>

{@render children()}
