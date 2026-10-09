# Design reference: practicegateway.com

Looked at on 2026-10-09 (screenshots `pg-*.png` in this folder). It is a software company's marketing site, so only its **visual style** is
useful for Pitchside; its content, logo, illustrations and copy are not to be copied.

## What the style is

- **Page:** very light off-white background (`#fafafa` / white), generous whitespace, centred layouts, big section breaks.
- **Type:** Montserrat throughout. Headlines are heavy (weight 700), tight (52px on 52px line height at the top, 40px for section headings),
  near-black (`#27272a`). Body text is calm grey (`#52525b`), 16px. Small orange-to-red eyebrow line above the main headline.
- **Navigation:** a white pill-shaped bar floating at the top with a soft shadow, a small dark pill button on the right.
- **Buttons:** fully rounded pills (radius 9999px), dark navy to black gradient, white 600-weight text, soft shadow.
- **Cards and panels:** large rounded corners (about 12 to 16px), light grey panels (`#ededef`, `#f4f4f4`) holding white rounded "chips" with a
  small tick; thin 1px borders on dark cards.
- **Dark sections:** deep navy (`#020219` page, `#111120` cards) with subtle borders, white text. They alternate with light sections.
- **Accent:** a bright red (`#ee222e`) running into orange, used for icons, ribbons, the eyebrow text and highlights. Used sparingly on a mostly neutral page.
- **Feel:** clean, confident, modern SaaS. Calm, with one strong accent colour.

## How it could map to Pitchside (suggestions, not decisions)

- Confidence tiers as small rounded **chips** (High / Medium / Low), the way the site uses white chips with ticks.
- The match board as light rounded cards on a light grey panel; the **track record** screen as a dark navy section with dark cards.
- Pill buttons and the floating pill navigation bar for league and game-week switching.
- A single accent colour. One caution: red usually means "danger" or "loss" to people looking at betting figures, so using this red for
  confidence or probability would send the wrong signal. A neutral accent for data, and the red/orange only for brand moments, would avoid that.
- Probability, confidence and edge must stay visually equal and side by side (BUILD.md rule), never ranked by probability alone.

---

# Design reference 2: brimble.io

Looked at on 2026-10-09 (screenshots `brimble-*.png`). Again a developer-platform marketing site; only the visual style is used.

## What the style is

- **Page:** a very pale, cool grey-white background (about `#f4f7f6`), calm and almost monochrome. Lots of space, a narrow centred column (about 720px).
- **Type:** large **italic serif** headlines (a Lora / Source Serif style) in near-black, with a clean grey **sans** (IBM Plex Sans style) for body text and a small
  **monospace** for tiny uppercase labels such as "COMMUNITY". The contrast between serif headings and plain sans text is what makes it feel editorial.
- **Art:** hand-drawn **pencil sketches** (a bee, a street scene) in black on the pale page. This is the site's personality.
- **Navigation:** slim, transparent bar: logo, small grey text links, a small green status dot, "Sign in" on the right. Nothing heavy.
- **Components:** tab pills where the active one is solid dark; a big dark charcoal rounded card (about 24px radius) with a white title and grey text;
  light cards with a thin border and soft shadow; small pill chips for links; a dark gradient button with an arrow.
- **Accent:** one saturated blue, used for a single large block and the chat bubble. Everything else stays grey and black.
- **Motion:** the hero headline types itself with a blinking cursor; sections and images appear as you scroll; small logo badges float over the sketch.

# Pairing the two: a direction for Pitchside (a proposal, to be confirmed)

What each site contributes:

| From practicegateway.com | From brimble.io |
|---|---|
| Floating white **pill navigation bar** with a soft shadow | Calm **pale grey** page, near-monochrome |
| **Pill buttons** (dark navy-to-black, rounded) and white **chips** | **Italic serif** display headings; mono micro-labels |
| Large rounded **cards**; alternating light and dark navy sections | Narrow readable column; **dark charcoal card** for the key panel |
| The **animations** you liked: soft reveals, depth, smooth hovers | A **single** saturated accent, used sparingly |

Proposed Pitchside look:

- **Base:** Brimble's pale background and serif italic headings for page titles and the big numbers' captions; a clean sans with tabular figures for all data.
- **Structure:** Practice Gateway's floating pill navigation (league, game week), pill buttons, white rounded cards, and a **dark navy section for the track record**.
- **Colour:** neutral greys and ink, one **blue** for interactive and data elements (it carries no win/lose meaning), and the **orange-red** from Practice Gateway only for small brand moments.
  Confidence tiers use tints of the blue, not red/green, so they do not read as "good/bad bet". Settled results (won / lost) get their own quiet pair of colours.
- **Art:** an optional hand-drawn pencil style for the home and empty states. Original sketches only, nothing copied.

## Motion rules (restrained, as requested)

Allowed:
1. The hero headline types in **once** when the page opens.
2. Sections and cards fade and rise **once** as they scroll into view (about 300 to 400 ms, small distance).
3. Key numbers count up **once** on the home and track-record screens.
4. Buttons and cards lift slightly on hover; filters change with a short cross-fade.

Not allowed: looping or autoplay animation, parallax, scroll-jacking, anything that moves while someone is reading probabilities, and any animation on the
match board's numbers themselves. Everything respects the browser's **reduce motion** setting (all of the above turn off).
