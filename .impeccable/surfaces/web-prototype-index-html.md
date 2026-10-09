---
version: 1
slug: "web-prototype-index-html"
primary_target: "web/prototype/index.html"
related_targets: []
---

# Surface brief: Pitchside prototype (fixtures, match board, track record)

Scope and visitor mode: Operate. A private, clickable prototype with three screens (fixtures, match board, track record), reading a real JSON snapshot of 48 matches across the five leagues.
Audience: HEO now (testing how predictions fare against real results), paying subscribers later. Job: open a match, see every market's probability and the numbers behind it.
Constraints: HEO pinned two visual references (practicegateway.com, brimble.io), restrained animation, and a responsible-gambling notice. No odds, no bet placement, no live results yet.
Unresolved: production framework; confidence tiers (not calibrated, so the slot says "not rated yet"); logo and any hand-drawn art.

## Direction contract

THESIS: A calm instrument for reading probabilities. The page refuses the betting-site default (neon, flashing odds, "BET NOW") and the SaaS hero with a metric strip; the
numbers sit on a quiet pale page where the serif italic headline is the only voice raised. Honesty is the signature: every probability shows its pick status and its not-yet-rated confidence.

OWN-WORLD: Brimble's world carries the ground and the type, Practice Gateway's carries the components. Pale cool ground #f5f7f7, ink #222528, Lora italic 500 for display headings, IBM Plex Sans for text,
IBM Plex Mono only for fair odds and figures. A floating white pill navigation bar with a soft offset shadow, pill buttons in charcoal-to-ink, white rounded cards (16px) on a pale grey panel,
and one dark navy section (#0c1022 ground, #151a31 cards) for the track record. One saturated blue (#1f6bff) is the only data colour; orange-red appears only in the logo mark.

STORY: Visitor understands this is a prediction tool that shows its working and its limits, believes the numbers because the calibration and the model's weakness are stated, and acts by opening a match and reading its markets.

FIRST VIEWPORT: Floating pill nav top centre (wordmark left, Fixtures and Track record, an 18+ note right). Beneath it, left-aligned in a 960px column, a typed serif italic title about this week's matches, one plain sentence,
and the league pills. Directly below, the match list begins within the fold: kickoff time, the two teams, a three-part probability bar with the three percentages, and a small "results only" data-quality note. Primary action: open a match.

FORM: User-pinned combination of the two reference sites (no concept roll; a user-pinned direction beats the roll). Seed key: none, pinned by HEO on 2026-10-09.

MOTION: typed headline once per session; cards and sections rise and fade in once on first scroll (about 350 ms, exponential ease-out); key numbers count up once on the record screen; buttons and cards lift 2px on hover.
Nothing loops, nothing moves while probabilities are being read, and reduce-motion turns all of it off.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
