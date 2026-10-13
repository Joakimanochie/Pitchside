<script lang="ts">
	const NAMES = ['High', 'Medium', 'Low'];
	let { tier }: { tier: number } = $props();
</script>

<span class="conf conf-{tier}" role="img" aria-label="{NAMES[tier]} confidence" title="{NAMES[tier]} confidence in this number"><i></i><i></i><i></i></span>
