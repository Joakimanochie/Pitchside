/**
 * Kickoff times. Pages are built ahead of time, so before the browser takes over everything is shown in UTC;
 * once mounted the same values switch to the visitor's own time zone (and every label updates).
 */
export const clock = $state({ local: false });

const zone = () => (clock.local ? undefined : 'UTC');

export const tzLabel = () => (clock.local ? Intl.DateTimeFormat().resolvedOptions().timeZone : 'UTC');
export const dayKey = (iso: string) => new Date(iso).toLocaleDateString('en-CA', { timeZone: zone() });
export const dayLabel = (iso: string) =>
	new Date(iso).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', timeZone: zone() });
export const timeLabel = (iso: string) =>
	new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: zone() });
export const kickoffLong = (iso: string) =>
	new Date(iso).toLocaleString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: zone() });
export const shortDate = (isoDate: string) =>
	new Date(`${isoDate}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
export const longDate = (isoDate: string) =>
	new Date(`${isoDate}T12:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
