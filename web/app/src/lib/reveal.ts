/** Fade a block in the first time it scrolls into view. Blocks already on screen are left alone, and nothing happens for reduced motion. */
export function reveal(node: HTMLElement) {
	if (typeof matchMedia === 'undefined' || matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) return;
	if (node.getBoundingClientRect().top < window.innerHeight) return;
	node.classList.add('reveal');
	const io = new IntersectionObserver(
		(entries) => {
			for (const e of entries) {
				if (e.isIntersecting) {
					e.target.classList.add('is-in');
					io.unobserve(e.target);
				}
			}
		},
		{ threshold: 0.08, rootMargin: '0px 0px -4% 0px' }
	);
	io.observe(node);
	return { destroy: () => io.disconnect() };
}
