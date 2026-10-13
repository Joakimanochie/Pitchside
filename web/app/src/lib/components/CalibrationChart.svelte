<script lang="ts">
	import { pct1 } from '#lib/labels.js';

	let { points }: { points: { predicted: number; actual: number; n: number }[] } = $props();

	const W = 560, H = 380, L = 48, R = 18, T = 14, B = 42;
	const x = (p: number) => L + p * (W - L - R);
	const y = (p: number) => H - B - p * (H - T - B);
	const ticks = [0, 0.25, 0.5, 0.75, 1];
	const maxN = $derived(Math.max(...points.map((p) => p.n)));
</script>

<div class="chart">
	<svg viewBox="0 0 {W} {H}" role="img" aria-label="Calibration chart: predicted probability on the horizontal axis, actual frequency on the vertical axis. Points follow the diagonal closely.">
		{#each ticks as t (t)}
			<line class="grid" x1={x(0)} x2={x(1)} y1={y(t)} y2={y(t)} />
			<line class="grid" x1={x(t)} x2={x(t)} y1={y(0)} y2={y(1)} />
			<text x={x(t)} y={H - B + 20} text-anchor="middle">{t * 100}%</text>
			<text x={L - 10} y={y(t) + 4} text-anchor="end">{t * 100}%</text>
		{/each}
		<text x={(L + W - R) / 2} y={H - 6} text-anchor="middle">Predicted probability</text>
		<text x="14" y={(T + H - B) / 2} transform="rotate(-90 14 {(T + H - B) / 2})" text-anchor="middle">How often it happened</text>
		<line class="diag" x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} />
		<polyline class="line" points={points.map((p) => `${x(p.predicted)},${y(p.actual)}`).join(' ')} />
		{#each points as p (p.predicted)}
			<circle class="dot" cx={x(p.predicted)} cy={y(p.actual)} r={(3.5 + 5 * Math.sqrt(p.n / maxN)).toFixed(1)}>
				<title>Predicted {pct1(p.predicted)}, happened {pct1(p.actual)} ({p.n.toLocaleString()} predictions)</title>
			</circle>
		{/each}
	</svg>
</div>
