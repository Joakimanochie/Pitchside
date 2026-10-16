<script lang="ts">
	const NAMES = ['High confidence', 'Medium confidence', 'Low confidence', 'Not yet rated'];
	let { tier }: { tier: number } = $props();
</script>

<span class="conf conf-{tier}" role="img" aria-label={NAMES[tier]} title={tier === 3 ? 'No confidence rating yet for this league' : `${NAMES[tier]} in this number`}><i></i><i></i><i></i></span>
