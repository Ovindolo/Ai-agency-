# Claims Substantiation Register

Every factual assertion in this package, its evidence status, and what must exist before it can be published. **No claim leaves this register as "cleared" without a named document and a named approver.**

Status key — `BLOCKED` (no evidence, cannot publish) · `PENDING` (evidence commissioned) · `CLEARED` (evidenced and legally approved) · `SAFE` (verifiable fact about our own product) · `PROHIBITED` (never publish under any circumstance)

---

## Registered claims

| ID | Claim as written | Status | Evidence required | Appears in |
|---|---|---|---|---|
| **RTB-1** | Mechanical agitation, heat and repeated wet cycling drive pilling, shrinkage and fiber loss in knitwear | **BLOCKED** | Cited peer-reviewed textile-science literature on abrasion-induced pilling and dimensional change; counsel review of the specific wording; a defensible position on "forty minutes, twice a week" as illustrative rather than measured | Brief · Directions · S-01 · S-02 · V-01 · LP problem + benefits · UGC-01 · Posts 1, 2 |
| **RTB-2** | Removes odor compounds via enzyme action plus molecular capture, rather than masking with fragrance | **BLOCKED** | Formulation documentation from the chemist; independent sensory odor-panel test under a stated protocol; counsel review of "removes" vs. "reduces" | S-01 · S-02 · S-03 · V-01 · V-02 · LP mechanism + objections · all three UGC · Posts 4, 5, 6 |
| **RTB-3** | No softeners, no quats, no residue. Safe on merino, cashmere, raw denim and elastane | **BLOCKED** | Locked formula with formulator sign-off; fabric compatibility testing on all four named fibers; counsel review of the word "safe" | S-02 · LP mechanism + benefits + objections · UGC-03 · Post 6 |
| **RTB-4** | Refillable aluminum bottle with concentrate refills; buy the bottle once | **SAFE** | Verifiable from the shipped product. Lowest-risk claim in the package — **lean on it hardest in launch creative while the others clear** | LP benefits + FAQ |
| **RTB-5** | Made without [exclusion list] | **BLOCKED** | Locked formula; exclusion list verified line by line; counsel review | LP FAQ |
| **RTB-6** | *Cold Air* contains no added fragrance | **PENDING** | Formula confirmation. Trivial to clear and disproportionately useful — it answers the single most common objection | LP objections + FAQ · Post 7 |
| **RTB-7** | 30-day money-back guarantee, bottle empty, full refund | **PENDING** | Business approval of the terms; published returns policy; margin modeling on expected return rate | LP offer + objections · Posts 5, 7 |
| **RTB-8** | Starter Kit $34 · Refill 3-pack $27 · Subscribe and save 15% · Free shipping over $30 | **PENDING** | Final pricing approval; margin check on the shipping threshold | Everywhere |

---

## Prohibited — never publish, in any form

| Claim type | Why |
|---|---|
| Antimicrobial, antibacterial, sanitizing, disinfecting, "kills 99.9%" | Pesticidal claim territory. Triggers a regulatory regime this product is not registered for. There is no version of this sentence that is worth it. |
| "Chemical-free," "non-toxic," "natural," "eco-friendly" as bare adjectives | Unsubstantiable by construction, and actively enforced against in advertising |
| Any customer testimonial, star rating, review count or customer photo | **None exist.** Not one. |
| Any performance statistic — wears saved, water saved, loads avoided, dollars saved, garment lifespan extension | **None have been measured.** |
| Press logos, "as seen in," awards, certifications, partnerships | None exist |
| Named comparative claims against Febreze, Downy, Day Two, Steamery or The Laundress | Requires head-to-head substantiation the brand does not have |
| "Replaces washing" without the limiting clause | Legally and factually false. The limiting clause is mandatory in every instance |

---

## Launch gate

A claim moves to `CLEARED` only when all four are recorded:

1. The evidence document exists and is filed.
2. The exact published wording is attached to it — not a paraphrase.
3. Legal counsel has signed that wording.
4. The `[RTB-n]` string has been removed from the asset file.

**Roughly 70% of the copy in this package is currently unpublishable.** That is the correct state for a pre-launch brand with no testing behind it, and it is the number to hand the client on day one — because the alternative to knowing it is discovering it in a regulatory letter.

**Build enforcement:** an unresolved `[RTB-n]` string anywhere in the site source fails the build. The proof section is a component that returns null on empty data. Integrity is wired in, not remembered.
