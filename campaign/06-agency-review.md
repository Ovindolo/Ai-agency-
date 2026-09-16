# Phase 6 — The Agency Review

Every asset audited against ten axes before handoff. Findings are reported **Problem → Why it matters → Exact repair**, and each repair below has been **applied to the files in this package**, not merely recommended.

---

## Audit summary

| Axis | Verdict | Notes |
|---|---|---|
| Audience fit | **Pass** | Every asset speaks to the considered-wardrobe buyer. Nothing drifts to the mass laundry shopper. |
| Message clarity | **Pass** | One message, seven expressions. A stranger can restate it after one view. |
| Brand consistency | **Repaired** | See F-02, F-06 |
| Product accuracy | **Repaired** | See F-11 — the Brand Lock specified the object it separately forbade |
| Visual continuity | **Repaired** | See F-12 — a transition that contradicted the shot it introduced |
| Platform fit | **Repaired** | See F-07, F-13 — captions had no safe-area bounds and were unreadable on their own grounds |
| Claim accuracy | **Repaired** | See F-01, F-03, F-04, F-08, F-09 — the most serious cluster in the audit |
| CTA clarity | **Repaired** | See F-02 |
| AI artifacts | **Pass** | Negative constraints on every prompt cover hands, duplication, warped geometry, melted text. |
| Unnecessary complexity | **Repaired** | See F-05, F-10 |

---

## F-01 · Unregistered figures in a UGC script — SEVERE

**Problem.** UGC-01's script and on-screen text carried *"This was a hundred and twenty dollars. Four months."* and the burned-in card `4 months. $120.` A synthetic creator was stating a specific price and a specific timeframe as lived personal fact.

**Why it matters.** It breaks two rules at once. It is an invented customer experience presented as real, and it is a number with no registered source — both explicitly Forbidden in the Brand Lock. It is also the exact failure that ends a brand built on not faking proof: the moment someone asks *"which $120 sweater, whose, when?"* there is no answer.

**Repair applied.** Script line rewritten to *"This is good merino. It has not had a hard life. Look at the shoulder."* On-screen card changed to *"this is abrasion, not age."* The claim is now about the mechanism, which is registrable, rather than about a person's history, which is not. The labeling requirement was also strengthened: a persistent in-frame `AI-generated · concept demonstration` label for the full duration, not just an end card, plus an explicit prohibition on prices, wear counts and timeframes presented as lived results.

## F-02 · Two CTAs in circulation — HIGH

**Problem.** The Brand Lock locks one CTA: `Get the Starter Kit — $34`. UGC-01's end card read `AIRING — Get the Starter Kit, $34` — brand name prepended, em dash swapped for a comma.

**Why it matters.** A locked element that varies is not locked. Small drift in a CTA is how a system dies: the next person copies the variant, and within a month there are five. It also breaks click-through measurement consistency across placements.

**Repair applied.** Normalized to `Get the Starter Kit — $34`. All eleven instances across the package are now byte-identical.

## F-03 · UGC scripts had no claim governance — SEVERE

**Problem.** The advertising and landing-page files carried `[RTB-n]` markers on every factual claim. The UGC file carried **zero**, while its scripts made the same claims — agitation damage, enzyme mechanism, no softeners.

**Why it matters.** UGC is the highest-volume, lowest-supervision asset class in the campaign and the most likely to be handed to a production partner without the brief attached. Leaving it ungoverned means the least-reviewed assets carry the most exposed claims. This is precisely backwards.

**Repair applied.** Five `[RTB-n]` markers inserted directly into the spoken scripts at the sentences that carry the claims, so the marker travels with the line even if the file is excerpted.

## F-04 · An unpublishable number baked into an image prompt — HIGH

**Problem.** PS-03 "The Evidence" specified a Caution Orange annotation reading `40 washes`. It was flagged as a placeholder in prose, but the number sat in the spec where an artworker would read it as a design instruction.

**Why it matters.** Flags in prose get skipped; values in specs get set. This is how an invented statistic reaches a paid impression — nobody decides to publish it, they just render what the file said.

**Repair applied.** The spec now carries `[RTB-1 — figure pending]` as the literal annotation string, plus a defined fallback: if RTB-1 clears qualitatively but not numerically, the halves are labeled `machine-washed` / `not machine-washed`. The argument survives without a figure the brand cannot defend.

## F-05 · The offer contradicted itself at the point of sale — HIGH

**Problem.** The hero CTA read `Get the Starter Kit — $34` with micro-copy directly beneath it reading *Free shipping over $40.*

**Why it matters.** The entry product could not qualify for the shipping offer sitting next to it. Every first-time buyer would hit the gap at checkout, and the brand's single most important promise — that it does not play games — would break on the first transaction, over shipping.

**Repair applied.** Threshold moved to $30 across all four occurrences. The Starter Kit now qualifies; refills alone do not, which turns an own-goal into a functioning basket incentive.

## F-06 · Mixed orthography against a US launch — MEDIUM

**Problem.** 122 instances of British spelling — *odour, colour, aluminium, fibre, centre, behaviour, anodised, labelled, grey, travelling* — throughout copy, prompts and specs, against assumption A-09 (US launch, US English).

**Why it matters.** In customer-facing copy it is an immediate credibility tell for a US audience. In *generation prompts* it is worse than cosmetic: spelling steers the model's style prior, and "aluminium" pulls toward a different visual register than "aluminum." Inconsistent orthography inside a prompt library produces inconsistent output.

**Repair applied.** All 122 instances converted to US English across every file including the README.

## F-07 · A voiceover that did not fit its slot — MEDIUM

**Problem.** V-01's 0:04–0:08 slot carried *"Same sweater. Same age. The difference is forty minutes of agitation, twice a week"* — roughly six seconds of natural speech in a four-second window.

**Why it matters.** In a 15-second unit, one overrun compresses everything after it. The casualty is always the last beat, which here is the CTA. An ad that clips its own CTA is a media buy that pays for nothing.

**Repair applied.** Line cut to *"Same sweater. The difference is the machine."* and the slot rebalanced to 0:04–0:07 / 0:07–0:12. The shorter line is also better — the audit found a copy improvement hiding inside a timing bug.

## F-08 · A carousel primed to grow invented statistics — MEDIUM

**Problem.** Social Post 3 described slides giving "the honest answer" for each fabric while a footnote separately instructed qualitative publishing. Two instructions, one slide.

**Why it matters.** Ambiguity at artwork stage resolves toward whatever looks better in a layout, and *"merino: 7 wears"* looks better than *"merino: several wears."* This was the single most likely place in the package for a fabricated statistic to enter production.

**Repair applied.** Slide content rewritten to carry qualitative language explicitly, and the note rewritten to name the risk directly and instruct designers not to add figures at artwork stage.

## F-09 · A miscount inside a production instruction — LOW

**Problem.** The UGC casting note referred to "the four creator personas above." There are three.

**Why it matters.** Small, but it is a production document. A partner reading it looks for a fourth persona, does not find it, and either asks — costing a day — or invents one — costing the brand system.

**Repair applied.** Corrected to three.

## F-13 · The caption spec was invisible on most of its own frames — HIGH

**Problem.** The caption spec called for Graphite text on a Paper pad at 82% opacity. Four of V-01's five shots sit on a Paper ground. A Paper pad on a Paper frame is not a caption, it is a rumour.

**Why it matters.** Captions are the entire sound-off layer, and sound-off is how most of this media will be consumed. A caption spec that fails on 80% of the unit's own frames means the unit does not work muted — which is not a styling problem, it is the media plan failing.

**Repair applied.** Inverted and locked: **Paper text on a solid Graphite pad, always**, on every frame in the campaign. One rule, legible on any ground, and it reads as a technical annotation — which is the brand's voice regardless. Applied in the animatic and written into the caption spec in `06-storyboards.md`, along with the platform safe-area bounds that were missing entirely.

## F-12 · The transition destroyed the comparison it set up — HIGH

**Problem.** V-01's board specified a *whip cut* from shot 1 to shot 2, in the same table row that required the two frames be "identical light, identical scale."

**Why it matters.** The ad's entire argument is *these two frames differ in one variable only.* A whip tells the eye the camera moved between them. The viewer cannot articulate the objection, but they stop believing the comparison — and an evidence ad that isn't believed is worse than no ad, because it spends the budget teaching people to distrust the claim.

**Repair applied.** Changed to a **hard match cut** — identical framing, identical scale, identical push curve across both shots, no transition and no sound on the cut. Visible in the animatic: shots 1 and 2 run the same motion, so the only thing that changes at 0:02 is the fabric.

## F-11 · The Brand Lock specified the object it forbade — SEVERE

**Problem.** LOCKED described the closure as a *"fine-mist trigger."* FORBIDDEN listed *"the bottle shown with a pistol-grip trigger or a squeeze head."* The same document both mandated and prohibited a trigger. Found while drawing the product spec — the word had to resolve to a shape, and it resolved to two.

**Why it matters.** The most dangerous kind of defect: invisible in prose, fatal in production. "Trigger" in a generation prompt reliably produces a pistol-grip trigger sprayer, because that is what the word means to an image model. Every one of the four PROTECTED blocks carried it, so the first render of every prompt would have produced the explicitly forbidden object — and it would have looked correct enough to approve, because the prompt said what the render showed.

It also propagated into direction. UGC-01 and UGC-03 staged *"trigger pulls,"* which is a whole-hand gesture; V-03's sound design was built on *"two trigger pulls,"* which is a mechanical click, not a pump's hiss. The wrong noun had already produced wrong performance and wrong audio.

**Repair applied.** Resolved in favor of the product the brand actually needs — a **flat fine-mist pump actuator, pressed with one finger**, which is what a fabric mist uses and what the forbidden list was protecting. Corrected in eleven places across six files: the LOCKED clause now names the actuator and explicitly excludes a pistol-grip trigger sprayer in the same sentence, all four generation prompts updated, both UGC product-interaction notes rewritten as pump presses, V-03's sound design corrected, and the commissioned shot list renamed to "pump detail."

## F-10 · A structural risk left as a checklist item — MEDIUM

**Problem.** The landing page listed "every `[RTB-n]` is a build-blocker" as a written instruction.

**Why it matters.** The entire integrity position of this brand rests on no unsubstantiated claim reaching a customer. Protecting that with a line in a document protects it with someone's memory on a launch day.

**Repair applied.** Rewritten as an engineering requirement: an unresolved `[RTB-n]` string fails the build, and the proof section is specified as a component that returns null on empty data — so shipping a fabricated proof block is structurally impossible rather than merely discouraged.

---

## What was checked and deliberately not changed

- **Direction A's dependence on RTB-1.** Flagged in Phase 3 as the campaign's central risk. Not repaired, because it is not a defect — it is the correct risk to carry, and the fallback is already specified.
- **The empty proof section.** Reads as a hole on a launch page. Left as a hole. For this audience it is an asset.
- **The "it doesn't replace washing" boundary appearing in five places.** Redundant by normal standards. Kept everywhere, because it is the sentence that keeps the campaign legal.
- **Three UGC concepts rather than five.** Three fully-specified concepts across three casting variants each produce nine assets — sufficient for Test 2. More concepts would have been volume, not coverage.

## Residual risks going into handoff

1. **A-10 — the AIRING name is unverified for trademark and domain.** Unresolvable here; blocks everything downstream. Escalated.
2. **RTB-1, RTB-2, RTB-3 are all unevidenced.** Roughly 70% of the copy in this package is unpublishable until they clear.
3. **Formulation feasibility (A-04)** has not been tested with a chemist. If the enzyme mechanism is not achievable at this price, Direction A loses its mechanism and the campaign reverts to the B-led fallback.
