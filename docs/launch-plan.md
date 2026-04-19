# Business Launch Plan

Status: **Planning document — not committed.** Drafted 2026-04-19 as a
concrete 12-month blueprint for launching the B2B-to-avocats business
described in `B2B.md`. Assumes France as the founding jurisdiction and a solo
technical founder (the author).

## 1. Legal structure — where to incorporate

**Recommendation: SASU in France, domiciled in Paris or the founder's home
region.**

Rationale:
- Customers are French avocats buying B2B — any non-French entity creates
  trust friction with regulated professionals
- SASU = single-shareholder SAS, the standard French startup vehicle (no
  minimum capital, €1 symbolic)
- As president-SASU the founder gets *assimilé-salarié* status → full French
  health/pension coverage
- **Eligible for JEI + CIR** — these two regimes alone change the economics
  of the first 3 years

**Why not alternatives**:

| Option                | Verdict   | Reason                                                                  |
|-----------------------|-----------|-------------------------------------------------------------------------|
| Estonia e-Residency   | Reject    | Fatal trust signal when selling to regulated French professionals       |
| Delaware C-Corp       | Reject    | Only makes sense if raising US VC; brutal tax inefficiency otherwise    |
| Ireland Ltd           | Reject    | Only if relocating to Ireland                                           |
| Luxembourg SARL       | Reject    | Higher setup + maintenance, no tangible benefit for this use case       |
| SASU France           | **Adopt** | Aligned with market, optimal for JEI/CIR capture                        |

## 2. Two regimes to capture (non-negotiable)

### JEI — Jeune Entreprise Innovante

- **100% exoneration of employer social charges on R&D staff for 8 years**
- Partial corporate tax exoneration (year 1 + year 2)
- Eligibility: <250 employees, <€50M revenue, ≤11 years old, ≥15% of charges
  in R&D, majority held by physical persons

**Effect**: a €60k-gross developer costs ~€87k loaded normally → ~€62k under
JEI. Six-figure savings over the first two hires.

### CIR — Crédit d'Impôt Recherche

- **30% of R&D expenditure refunded** (cash if no IS due yet)
- Covers: R&D staff × 1.43 multiplier, approved subcontracting, patents
- AI work (manipulation detection, French-law taxonomy, prompt engineering
  framed as systematic research) qualifies with proper documentation

**Effect**: ~40% of first-year dev costs returned as cash.

**Action**: engineer both regimes into the company setup from Day 1. Find an
accountant specialized in JEI/CIR **before** signing anything else.

## 3. Month-0 setup checklist

| Item                                    | Provider / choice                                   | Cost           |
|-----------------------------------------|-----------------------------------------------------|----------------|
| Incorporation (SASU)                    | Legalstart, Captain Contrat, or direct Infogreffe   | €300–800       |
| Domiciliation address                   | SeDomicilier, Kandbaz (not home — privacy)          | ~€30/mo        |
| Business bank                           | Qonto (startup-friendly, API, fast KYC)             | ~€25/mo        |
| Accountant specialized in JEI/CIR       | Dougs, Keobiz, Numbr, or boutique cabinet           | €150–300/mo    |
| TVA intracommunautaire                  | Declared via accountant                             | €0             |
| RC Pro insurance (liability)            | Hiscox, Stello, Axa Pro                             | €600–1,500/yr  |
| Data processor DPA template             | RGPD specialist (one-off)                           | €1,500–3,000   |
| ToS + contract templates                | Legal-tech specialist lawyer                        | €2,000–4,000   |
| Trademark (brand name)                  | INPI deposit                                        | ~€250          |
| Domain + email + GSuite                 | Standard                                            | ~€15/mo        |

**Total setup**: ~€6–10k one-off + ~€500/mo recurring. Budget **€15k for
Month 0** for safety.

## 4. Capital plan

Three-stage funding, matched to product stage:

### Stage 1 — Bootstrap + subsidies (Month 0–6)

- Personal savings: €30–50k (setup, first 6 months living expenses, one
  freelance contractor)
- **Prêt d'honneur** (BPI France / Réseau Entreprendre / Initiative France):
  €15–50k zero-interest personal loan
- **BPI Bourse French Tech Émergence**: up to €30k grant for pre-market
  startups
- CIR first refund arrives Year 2 — do not count on it early

### Stage 2 — Seed (Month 6–12, triggered by €5k+ MRR)

- Angel round: €300–500k at €2–3M valuation
- Target angels who know legal tech or family-law sector (ex-avocats turned
  investors, legal-tech exits)
- Avoid generalist VCs at this stage — they push scale narratives that don't
  fit the B2B avocat market

### Stage 3 — Series A (Year 2–3, only if expansion justifies)

- €2–5M from a European B2B SaaS fund (Elaia, Serena, Partech seed)
- Only raise if launching Belgium + Switzerland + harcèlement moral vertical
  simultaneously
- Otherwise stay bootstrapped — this market is solo-founder-scale profitable

## 5. Hiring sequence (phased by MRR, not by calendar)

### Phase 0 — alone, until €5k MRR

Founder does everything. Supplement with **3 freelancers**, not employees:
- UX/UI designer (~20 days for firm dashboard rework, €400/day)
- RGPD/legal consultant (one-off compliance audit, €3–5k)
- Part-time marketing/content contractor (€1–2k/mo)

### Phase 1 — €5–10k MRR: first hire = Sales/CS with legal background

- **Role**: demo to firms, onboard them, feed customer insights to product
- **Profile**: ex-avocat, juriste d'entreprise, or legal-tech CS veteran,
  3–5 years experience
- **Why legal background is non-negotiable**: avocats won't take a demo call
  from a generic SaaS rep
- **Comp**: €50–55k base + €10–20k variable + 0.5–2% equity (BSPCE)
- Under JEI if R&D-adjacent responsibilities documented

### Phase 2 — €20–30k MRR: senior full-stack developer

- **Role**: ship product faster, take over frontend, free founder for
  prompts/AI/strategy
- **Profile**: 5+ years Python + TypeScript, mission-driven (coming out of
  banking, corporate, or consulting burn-out)
- **Comp**: €60–75k + BSPCE
- **Full JEI benefit** — employer charges near zero

### Phase 3 — €40–50k MRR: AI/ML engineer + Sales #2

- AI/ML engineer owns prompt/fine-tuning pipeline and structured-review →
  training-data flywheel
- Sales #2 covers southern/regional France
- Begin scoping part-time Head of Customer Success

### Phase 4 — €80k+ MRR: operational team

- Customer Success lead (separate from sales)
- Content / marketing hire
- Finance/ops part-time → full-time at €150k MRR

**Golden rule**: do not hire a second developer before hiring the
legal-savvy salesperson. Engineering past product-market-fit instead of
selling through it is the #1 technical-founder failure mode.

## 6. Advisors (pre-hires, equity-compensated)

Lock in **before** starting to sell:

1. **Senior family-law avocat** — 0.5–1% equity, 4-yr vesting — product
   validation, first referrals, credibility
2. **Legal-tech founder who's exited or scaled** — 0.25–0.5% — pricing,
   sales process, avoiding known mistakes
3. **SaaS operator with €1M+ ARR track record** — 0.25–0.5% — metrics,
   hiring, fundraising timing
4. **Specialized accountant for JEI/CIR** — fee-based, not equity — monthly
   conversations

Advisor board meets quarterly, 90 min. Worth every basis point.

## 7. 12-month launch roadmap

### Month 0 — Legal foundation

- SASU incorporated, JEI file prepared, bank + accountant + insurance in place
- RC Pro, DPA, ToS templates signed off
- Brand registered at INPI
- **Budget burn**: €15k setup + €4k/mo living

### Month 1–3 — Design partner recruitment

- Target: 3 avocats committed, free-forever + testimonial agreement
- Refactor current MVP into multi-tenant-ready shape (schema-per-tenant, roles)
- Build firm dashboard v1 (review queue, cross-client overview)
- Attend 2 family-law events (Congrès ACE, rentrée solennelle du Barreau)
- **Budget**: €10–15k (travel, tooling, freelance UX)

### Month 4–6 — First paid conversions

- Convert 2 of 3 design partners to paid (heavy discount year 1)
- Recruit 3–5 additional firms at Cabinet Starter/Plus (€149–349/mo)
- Write case studies with design partners
- Apply for BPI grants, prêt d'honneur
- **Revenue target**: €1.5–3k MRR

### Month 7–9 — First hire + content engine

- Hire Sales/CS with legal background (€55k + variable)
- Launch content series "IA et droit de la famille" (LinkedIn, Village de
  la Justice)
- Speak at one regional Barreau event
- **Revenue target**: €8–15k MRR

### Month 10–12 — Growth + second hire

- Hire senior developer (€65k + BSPCE)
- Partnership with practice-management tool (Jarvis Legal or Secib)
- Close angel round (€300–500k) if growth trajectory justifies
- Sponsor one flagship event (Congrès du Barreau de Paris)
- **Revenue target**: €25–40k MRR

## 8. Risk register + mitigations

| Risk                                                        | Probability    | Mitigation                                                                                                     |
|-------------------------------------------------------------|----------------|----------------------------------------------------------------------------------------------------------------|
| Avocats find the tool too complex, drop off                 | High           | Design partners must be failure-tolerant. Measure adoption weekly.                                             |
| CNB issues restrictive guidance on AI in legal practice     | Medium         | Position as "tool used by the avocat", not "tool replacing the avocat". Stay engaged with CNB commissions.     |
| Data breach at any scale                                    | Medium-High    | SOC 2 Type I in Year 2, pen tests annually, mandatory MFA, encryption at rest, audit logs from Day 1           |
| Founder burnout doing sales + product alone                 | High           | Do not delay the first sales hire past €10k MRR.                                                               |
| Mistral / OpenAI change pricing or ToS                      | Medium         | Provider abstraction in `src/llm/` — never violate. Add Ollama/self-host fallback before Year 2.               |
| Copycat from larger legal-tech player (Doctrine, Predictice)| Medium         | Moat is the avocat-client workflow and review loop, not the AI. Ship faster than they can reprioritize.        |
| Design partner drops out early                              | High           | Recruit **4** partners, expect 1 to attrit. Structure a 4-week pilot with explicit exit, not open-ended.       |

## 9. What to do this week

1. Talk to **three specialized accountants** offering JEI/CIR expertise. Pick
   one.
2. Draft a one-pager describing the product in avocat terms (not developer
   terms).
3. Identify **5 family-law avocats** in your personal network or 2nd-degree
   connections. Book intro coffees.
4. Decide on the legal name (confirm availability on Infogreffe + INPI).
5. Open a Qonto account (takes 48h).
6. Sign up to *Village de la Justice* and read what avocats actually publish.
7. Do **not** start coding new features this week. Everything built before
   talking to 3 avocats is waste.

## 10. Non-obvious calls

- **Incorporate before acquiring any paying customer.** Invoicing as a
  physical person or micro-entreprise to avocats tanks credibility on first
  sale.
- **Do not take on a technical co-founder at this stage.** The tech already
  exists. Equity is expensive. A strong advisor-avocat is more useful.
- **Do not build a mobile app in Year 1.** Tempting, low ROI until web
  product is validated.
- **Differentiated language is "second opinion avocat", not "AI".** Avocats
  are AI-skeptical; they respect peer review. Lead every conversation with
  the review loop, not the LLM.
- **Plan for one failed hire in the first three.** Budget it. The learning
  is worth the cost.

## Cross-references

- `docs/B2B.md` — product strategy, pricing tiers, expansion roadmap, LLM
  infrastructure strategy
- `productization.md` (repo root) — original B2C SaaS plan (alternative
  direction)
- `docs/telemetry-spec.md` — telemetry spec for prompt/product iteration
  (works for either direction)
