# Phase 4 — The Brand Lock

Direction A approved. This document governs every asset. Anything that contradicts it is rejected, regardless of how good it looks.

---

## LOCKED — identical across every asset, forever

**Brand name.** `AIRING` — always uppercase, always this spelling. Never "Airing," never "AIR-ING," never possessive.

**Logo / wordmark.** `AIRING` set in the primary grotesk, Medium weight, letterspaced +8%, all caps, on a single line. No icon, no symbol, no lockup variant, no tagline attached to the mark. Reproduces in one color only: Graphite on light, Paper on dark. Minimum width 18mm print / 72px screen.

**Product appearance.** 250ml cylindrical bottle, matte anodized aluminum in Paper White, **flat shoulder with a hard 90° transition** to the neck. Black matte fine-mist trigger, black collar. Wordmark screen-printed in Graphite on a single horizontal line at the bottle's vertical midpoint. Scent name in mono, small caps, 24mm below the wordmark. **No illustrations, no botanicals, no gradients, no back-label copy visible in any hero image.** Refill concentrate: 30ml clear glass vial, black screw cap, single mono label.

**Core promise.** Removes odor so clothes can be worn again — without the wash cycle that wears them out.

**Primary colors.**

| Token | Hex | Role | Max share of frame |
|---|---|---|---|
| Paper | `#F4F2ED` | Ground. Wardrobe, fabric, product body | 60–80% |
| Graphite | `#1A1A18` | Type, the machine, shadow | 15–30% |
| Line-Dry Blue | `#2E4A7D` | Denim, depth, the one saturated note | ≤ 20% |
| Caution Orange | `#E8541F` | Evidence marks, damage callouts, CTA only | **≤ 5%** |

Caution Orange is a scalpel. If it is decorating, it is wrong.

**Typography direction.** One neo-grotesk for everything (ABC Diatype or Söhne; open fallback Inter Tight), Regular and Medium only. One mono for annotations, measurements and evidence labels (ABC Diatype Mono; fallback JetBrains Mono). **No serif anywhere, ever** — the category's default is a soft serif and the entire visual position depends on refusing it. No third typeface. No italics. Headlines set tight (-2% tracking), body set loose (1.5 line height).

**Tone of voice.** Direct, informed, unhurried. Short declaratives. Specific nouns. It knows more than it says. It never exclaims, never puns on laundry, never says "we get it," never apologizes for selling something. Closest reference: a very good product manual written by someone who is quietly angry about a widespread mistake.

**Key message.** *It's not the wearing that wears your clothes out. It's the washing.*

**Tagline.** *Wear it again.* — always lowercase after the first word, always with the full stop.

**Call to action.** *Get the Starter Kit — $34.* One CTA everywhere. No variants, no "Shop now," no "Learn more."

---

## FLEXIBLE — free to vary asset to asset

Creator (age, gender, ethnicity, body, voice) · location and room · time of day within a cool-to-neutral range · camera angle and distance · supporting props from the approved set (wooden hangers, wire hangers, wool combs, gym bags, suitcases, dresser tops, laundry baskets, the washing machine itself as antagonist) · hook wording · content format and length · caption and secondary copy · garment type and color · scent variant shown · which fabric is the subject.

---

## FORBIDDEN — never appears, in any asset, under any circumstance

**Product errors.** Altered bottle shape or a rounded shoulder · any color but Paper White body / black trigger · wordmark moved, scaled disproportionately, curved or duplicated · invented label copy, ingredients lists, icons or certification badges · a spray cloud that reads as aerosol mist rather than a fine pump fan · the bottle shown with a pistol-grip trigger or a squeeze head.

**Claim errors.** Any statement not in `claims-substantiation-register.md` · "kills 99.9% of bacteria" or any antimicrobial, sanitizing or disinfecting claim · "eco," "clean," "non-toxic," "chemical-free," "natural" as bare adjectives · any number — wears, percentages, days, dollars saved — without a registered source · comparative claims naming a competitor · anything implying the product cleans, launders or replaces washing entirely. **It replaces *some* washes. That distinction is legal, not stylistic.**

**Proof errors.** Fabricated testimonials, star ratings, review counts, customer photos, press logos, "as seen in," award marks, founder credentials, sales figures, waitlist numbers, sustainability statistics.

**Visual errors.** Off-brand color, especially sage, lavender, terracotta or cream — the category's palette · any serif · script or handwriting type · gradients, drop shadows on type, outlined type, text over busy areas · lens flare, bokeh hearts, sparkles, "freshness" swooshes, animated wind lines · steam, bubbles, water droplets, suds · florals, botanicals, leaves, eucalyptus · stock-photo laughing-with-laundry · symmetrical centered flat-lays on pure white · anything that reads as generic AI: plastic skin, over-sharpened micro-contrast, impossible reflections, six-fingered hands, melted text, uncanny symmetry.

**System errors.** More than one CTA in a single asset · two competing messages in one frame · type smaller than 14px on mobile or set over a photo without a contrast pad · clutter. **If an element is not carrying meaning, remove it.**

---

# Reusable Visual Generation Specification

Use this as the backbone of every image and video prompt. Swap only the *Subject* and *Scene* lines; everything else is constant.

## Standing block — paste into every prompt

```
COMPOSITION — Single clear subject. Off-center, weighted left or right third, never
dead center. Generous negative space reserved top-left or top-right for type. One
depth relationship only: subject sharp, ground falling away. Horizon or surface line
kept level. Frame edges clean — nothing clipped ambiguously.

LIGHTING — One dominant hard source, raking across the subject at 30–45°, from the
left unless specified. Deliberate directional shadow with a defined edge; shadow
treated as a compositional element, not spill. Single soft bounce on the shadow side
at roughly 1/8 power. Cool-neutral white balance, ~5200K. No second key, no rim
light, no colored gels, no practicals in frame.

LENS — Full-frame, 50mm or 85mm for product, 35mm for people, 100mm macro for
fiber. Shot at f/4–f/8 for product (deep enough to hold the whole bottle sharp),
f/2 for people, f/8 with focus stacking for macro. Eye-level to slightly above.
No wide-angle distortion, no tilt-shift, no fisheye.

TEXTURE — Real fiber structure visible: knit loops, twill lines, denim slub, raised
pills. Matte aluminum with fine brushed grain and a soft specular roll-off, never a
mirror finish. Paper-grade surfaces. Fine natural film grain. Skin with visible pores
and texture. NOT plastic, NOT airbrushed, NOT over-sharpened.

COLOR — Paper #F4F2ED ground, Graphite #1A1A18 type and shadow, Line-Dry Blue
#2E4A7D as the single saturated note, Caution Orange #E8541F on evidence marks only
and under 5% of frame. Desaturated overall. No sage, no lavender, no terracotta,
no cream.

TYPOGRAPHY (when type is in frame) — Neo-grotesk, Medium, all caps, +8% tracking for
the wordmark; mono small caps for annotations. Graphite on Paper or Paper on
Graphite. Flush left. No serif, no script, no outline, no shadow, no gradient.

PROTECTED — PRODUCT REF governs the bottle absolutely: 250ml matte Paper White
aluminum cylinder, hard 90° flat shoulder, black matte fine-mist trigger and collar,
AIRING wordmark in Graphite on one horizontal line at the vertical midpoint, mono
scent name below. Do not restyle, recolor, reshape, re-letter, add labels, add
badges, or add back-label copy.

NEGATIVE — no serif type, no script, no sage or lavender or cream, no florals or
botanicals or eucalyptus, no steam, no bubbles, no suds, no water droplets, no spray
sparkles, no lens flare, no bokeh, no gradients, no drop shadows, no centered
symmetrical flat-lay, no pure white seamless, no stock-photo smiling, no plastic
skin, no extra fingers, no duplicated or warped bottle, no invented label text, no
readable text other than the wordmark, no watermark, no logo other than AIRING.
```

## Reference role assignment — mandatory on every generation

| Slot | Controls | Contributes nothing to |
|---|---|---|
| `BRAND REF` | typography, color, layout logic | subject, scene |
| `PRODUCT REF` | bottle identity — shape, finish, wordmark position | light, environment |
| `SCENE REF` | light direction and quality, palette, composition | product detail |
| `UGC REF` | framing, camera behavior, performance energy | product detail, type |

A generation that blends two roles is rejected on sight. This is the most common failure mode in AI campaign work and the easiest to prevent.
