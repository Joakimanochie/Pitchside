---
name: Pitchside
description: A calm instrument for reading probabilities, pale and editorial with one blue data colour and one dark night screen.
colors:
  pale-ground: "#f5f7f7"
  white-card: "#ffffff"
  panel-grey: "#ebeef0"
  ink: "#222528"
  ink-soft: "#565d64"
  ink-muted: "#5f666d"
  hairline: "#e1e6e8"
  hairline-strong: "#cfd6d9"
  signal-blue: "#1f6bff"
  draw-slate: "#c7cfdd"
  night-navy: "#0c1022"
  navy-card: "#151a31"
  navy-line: "#272d4a"
  on-navy: "#eef1fb"
  on-navy-soft: "#aab3d0"
  blue-on-navy: "#7ea8ff"
  mark-orange: "#ff8a1f"
  mark-red: "#ee222e"
typography:
  display:
    fontFamily: "Lora, Georgia, serif"
    fontSize: "clamp(2.15rem, 4.6vw, 3.35rem)"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.012em"
  headline:
    fontFamily: "Lora, Georgia, serif"
    fontSize: "clamp(1.5rem, 2.6vw, 1.95rem)"
    fontWeight: 500
    lineHeight: 1.2
  title:
    fontFamily: "Lora, Georgia, serif"
    fontSize: "1.2rem"
    fontWeight: 500
    lineHeight: 1.25
  body:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "-0.005em"
  label:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.2
  data:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "0.8rem"
    fontWeight: 400
    lineHeight: 1.2
rounded:
  card: "16px"
  panel: "24px"
  pill: "999px"
spacing:
  xs: "0.5rem"
  sm: "0.75rem"
  md: "1.25rem"
  lg: "2.75rem"
  gutter: "clamp(1rem, 4vw, 2rem)"
components:
  pill-button:
    backgroundColor: "{colors.white-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.5rem 1rem"
  pill-button-active:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.white-card}"
    rounded: "{rounded.pill}"
    padding: "0.5rem 1rem"
  chip-muted:
    backgroundColor: "{colors.panel-grey}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.pill}"
    padding: "0.3rem 0.7rem"
  pick-tag:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.white-card}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.5rem"
  card:
    backgroundColor: "{colors.white-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "1.15rem 1.25rem"
  night-panel:
    backgroundColor: "{colors.navy-card}"
    textColor: "{colors.on-navy}"
    rounded: "{rounded.panel}"
  nav-pill:
    backgroundColor: "{colors.white-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.55rem 0.6rem 0.55rem 1.15rem"
---
# Design System: Pitchside

## Overview

**Creative North Star: "The Quiet Scoreboard"**

A tool for reading probabilities, built so the numbers never have to compete with the page. The ground is a pale cool grey, the ink is a soft black, and one serif italic voice
is raised for headings and the few large numerals. Betting-site noise (neon, flashing odds, banners that push action) is refused outright; the product is closer to a well-kept record than to a casino.

Two worlds meet by design. The ground, the type and the narrow reading column come from brimble.io; the components (a floating pill navigation, pill buttons, rounded white cards, one dark navy section)
come from practicegateway.com. Both were pinned by the product owner. Density is moderate and every probability sits next to its plain-words label, never alone.

**Key Characteristics:**
- Pale ground, soft black ink, one blue that means "data" and nothing else.
- Lora italic for display voice; IBM Plex Sans for everything read; IBM Plex Mono only for fair odds.
- Floating white pill navigation; pill buttons; 16px white cards; 24px night panels.
- One dark navy screen (the track record) set against the light ones.
- Motion is rare and once-only, and switches off with the browser's reduce-motion setting.

## Colors

Mostly neutral, with a single saturated blue. The orange-red of the logo mark never appears on data.

### Primary
- **Signal Blue** (#1f6bff): probability bars, links, the home share of a three-part bar. It is the only data colour and carries no win/lose meaning.
- **Night Blue** (#7ea8ff): the same role on the night screen, where Signal Blue would be too dark.

### Secondary
- **Draw Slate** (#c7cfdd): the draw share of a three-part bar.

### Tertiary
- **Mark Orange** (#ff8a1f) and **Mark Red** (#ee222e): the logo mark only.

### Neutral
- **Pale Ground** (#f5f7f7): page background. **White Card** (#ffffff): cards, navigation, inputs. **Panel Grey** (#ebeef0): quiet panels, bar tracks, muted chips.
- **Ink** (#222528): headings, body, the active pill, the Pick tag. **Soft Ink** (#565d64) and **Muted Ink** (#5f666d): secondary and tertiary text (both pass 4.5:1 on the ground).
- **Hairline** (#e1e6e8) and **Strong Hairline** (#cfd6d9): card and control borders.
- **Night Navy** (#0c1022), **Navy Card** (#151a31), **Navy Line** (#272d4a), **Cool White** (#eef1fb), **Dusk Grey** (#aab3d0): the night screen.

### Named Rules
**The Blue Is Data Rule.** Blue marks data and interactive things only. Never use it, or red or green, to say a prediction is good or bad; meaning is carried by words.

**The Logo-Only Warm Rule.** Orange and red appear in the logo mark and nowhere else.

## Typography

**Display Font:** Lora, italic, weight 500 (Georgia fallback)
**Body Font:** IBM Plex Sans (system sans fallback)
**Label/Mono Font:** IBM Plex Mono, for fair odds only

**Character:** An editorial serif italic over a plain, even sans: the headline sounds like a person, the numbers read like a ledger.

### Hierarchy
- **Display** (500, clamp 2.15rem to 3.35rem, 1.1, -0.012em): the page title and the match name; the large probability numerals use the same face.
- **Headline** (500, clamp 1.5rem to 1.95rem, 1.2): section titles on the record screen and day headings.
- **Title** (500, 1.2rem, 1.25): the name of each market card.
- **Body** (400, 1rem, 1.55): running text, capped near 62ch; selection names at 450.
- **Label** (500, 0.875rem): pills, tabs, table headings, captions. Figures use tabular numerals throughout.
- **Data** (Plex Mono 400, 0.8rem): fair odds.

### Named Rules
**The One Voice Rule.** Serif italic is for headings and the large probability numerals only. Never for body text, buttons or table cells.

## Layout

A single reading column: 960px for fixtures, 1120px for the match board, 1040px for the floating navigation, with a fluid gutter (clamp 1rem to 2rem). Spacing is generous between groups (2.75rem above a day heading, 1rem
between cards) and tight inside them (0.3 to 0.8rem). Market cards flow in an auto-fill grid with a 25rem minimum, so two columns on a desktop and one on a phone. On screens under 760px the
match row stacks, the headline probabilities become rows, and the navigation note and fair odds are dropped. Tabs scroll sideways rather than wrap.

## Elevation & Depth

Soft, offset shadows on a pale page: cards rest with a hairline border and a diffuse shadow, and lift on hover. The floating navigation is solid white with a larger shadow so nothing shows through it. The night screen
uses tonal layering instead (Navy Card on Night Navy with a Navy Line border) and no shadow.

### Shadow Vocabulary
- **Card** (`0 1px 2px rgba(34,37,40,.05), 0 12px 28px -18px rgba(34,37,40,.28)`): resting cards.
- **Lift** (`0 2px 4px rgba(34,37,40,.06), 0 18px 34px -16px rgba(34,37,40,.34)`): a hovered match card.
- **Navigation** (`0 1px 0 rgba(34,37,40,.04), 0 14px 32px -14px rgba(34,37,40,.3)`): the floating pill.

### Named Rules
**The Solid Float Rule.** The floating navigation is opaque white. No glass, no blur.

## Shapes

Round and soft. Controls, chips, tags and bars are fully rounded pills (999px). Cards are 16px; large panels and the headline card are 24px. Borders are one pixel in a hairline tone; there are no coloured side borders.
Bars are 5 to 10px tall pills inside a Panel Grey track.

## Components

### Buttons and tabs (pills)
- **Shape:** fully rounded (999px), one-pixel Strong Hairline border, white fill, 0.5rem by 1rem padding.
- **Active:** a charcoal-to-ink gradient fill with white text, no border.
- **Hover / Focus:** lifts 1px with a soft shadow; focus shows a 2px Signal Blue ring with a 3px offset.

### Chips and the Pick tag
- **Chip:** Panel Grey fill, Soft Ink text, 0.8rem. **Pick tag:** Ink fill, white text, 0.68rem; marks the most likely outcome of a market whose outcomes are mutually exclusive, and is always paired with the word "Pick".

### Cards
- **Corner Style:** 16px. **Background:** White Card on Pale Ground. **Border:** one-pixel Hairline. **Shadow:** Card; Lift on hover for the clickable match card. **Padding:** 1.15 to 1.25rem.
- **Selection row:** name, percentage (600), fair odds (mono), and a 5px bar underneath; the pick is bold with a full-strength bar, the others at 55% strength.

### Probability bar (three-part)
- A 10px pill: home in Signal Blue, draw in Draw Slate, away in Ink, with 2px gaps. Percentages and plain-word captions always sit below it; the bar itself is decorative.

### Inputs
- **Style:** one-pixel Strong Hairline, white, fully rounded, leading search icon. **Focus:** Signal Blue ring.

### Navigation
- A floating white pill (max 1040px): wordmark in Lora italic 600 with the logo mark, two text links, and an "18+" note that is hidden on phones. The current page is a solid Ink pill.

### Night panel (signature)
- Navy Card on Night Navy, 24px corners, Navy Line border, Cool White text. It holds the calibration chart (Night Blue line and points, a dashed Dusk Grey diagonal) and the tables with Navy Line rules.

## Do's and Don'ts

### Do:
- **Do** put a plain-words label next to every bar, number and tag; colour never carries meaning alone.
- **Do** keep Signal Blue for data and interactive elements only.
- **Do** keep motion once-only: one typed title per session, one fade-and-rise per card, one count-up on the record screen (about 350 to 900 ms, exponential ease-out), and turn all of it off for reduce-motion.
- **Do** keep text at 4.5:1 or better (Muted Ink on Pale Ground is 4.9:1).

### Don't:
- **Don't** use red or green, or the logo's warm colours, to signal good or bad predictions.
- **Don't** animate probabilities while they are being read; the match board's numbers never move.
- **Don't** make the floating navigation translucent.
- **Don't** set body text, buttons or table cells in the serif italic.
- **Don't** add small uppercase labels above headings.

*Not canonized: none; the build ships no quality-floor violations.*
