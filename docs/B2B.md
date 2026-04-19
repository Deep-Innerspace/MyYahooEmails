# B2B-to-Avocats — Product Strategy

Status: **Strategy sketch — not committed to the roadmap.** Drafted 2026-04-19
as an alternative to the B2C SaaS direction in `productization.md`. Keep for
reference when deciding the commercial wedge.

## Core thesis

Sell the platform **to French family-law solo & small practices** as a
client-facing tool, not to end-users in conflictual divorces directly. The
avocat onboards their own clients. The platform becomes the firm's modern case
management + client collaboration layer, powered by the existing AI stack.

Advantages over B2C:
- No CNB / démarchage compliance minefield
- No direct liability — the avocat remains the client's legal representative
- One sale = 8–60 seats (low CAC per end-user)
- The end-client *wants* their avocat to have this (unlike typical enterprise
  tools where end-users resent admin)
- Firms that migrate their case history don't churn easily

## Target customer

**Not** big firms. Target profile:
- **Size**: solo avocat or boutique of 2–5 avocats
- **Specialization**: *droit de la famille contentieux* — divorce, garde
  d'enfants, pensions, violences conjugales
- **Geography**: France, start with one regional bar (Paris or Lyon)
- **TAM estimate**: ~3–5k firms nationally

### The pain being solved for the avocat

- Clients email daily in emotional panic asking *"should I reply this way?"*
- Avocat bills 30 min for what's 5 min of legal work + 25 min of hand-holding
- No visibility into what the client is actually writing to the other party
  (which can tank a case)
- Timeline reconstruction for hearings is still done manually in Word
- Small firms can't out-brand big ones — tech is their only viable
  differentiator

## Product shape

### Firm workspace (the avocat logs in)

- **Cross-client dashboard** across all active cases
- **Review queue**: pending draft reviews from clients, sortable by AI risk
  score (reuses existing manipulation/tone analysis)
- **Red-flag alerts**: e.g. "Client A just drafted a reply admitting to X",
  "Custody-sensitive draft awaiting review"
- **Per-client timeline** auto-generated for hearing prep (already built)
- **Procedures + invoices + court events** modules (already built) → become
  the firm's case file

### Client workspace (invited by their avocat)

- Connects IMAP; analysis runs in isolated tenant
- **"Request avocat review"** button on any draft reply → lands in the firm
  dashboard
- Sees which emails the avocat has flagged as key evidence
- Reply Command Center + Memory features: unchanged, pure value-add

### The review loop (the defining product moment)

1. Client drafts a reply to the other party
2. AI pre-screens for legal risk (reusing existing manipulation/tone/topic
   analysis)
3. **Low-risk** → client sends directly (majority of messages)
4. **High-risk** → auto-queued to avocat's review dashboard with a structured
   checklist:
   - `legal_risk`: low / med / high
   - `tone_concern`: yes / no
   - `inline_edits`: tracked diff
   - `green_light`: yes / no / request revision
5. Avocat's 5-min structured review replaces their 30-min free-text email back
6. **Bonus**: structured review decisions become training signal for future
   prompt refinement

## Evidence workflow

The dossier-building loop is the second defensible piece of the B2B product
(the first being the reply review loop above). Full spec:
`docs/evidence-feature.md`. B2B-specific summary below.

### Three-feature split (why the design looks like it does)

The naïve feature is "let the client mark emails as proof and auto-share
with the lawyer." Three separable concerns are hiding in there:

(a) **Tagging** — marking emails as candidates for a procedure. Valuable
    standalone, even with no sharing. Shipped in v0 (2026-04-19).
(b) **Sharing** — pushing tagged pieces to a lawyer's review queue. Only
    meaningful when lawyers are in the system. **This is the B2B feature.**
(c) **Context bundle** — a pure function (email set → structured package)
    that is reused by personal PDF export, B2B submission, and the
    Phase 6 reply review flow. Build once, consume everywhere.

### What B2B adds on top of the B2C tagging feature

- **Status lifecycle** on `evidence_tags`:
  `candidate → submitted → under_review → approved | flagged | rejected`
- **Lawyer dashboard queue** (`/firm/review`): tagged bundles arrive from
  clients; filter by client, procedure, submission date, status
- **Version pinning**: a `submitted_bundle_id` snapshot on each submission —
  the client can't edit an email mid-review without creating a new
  submission (avoids "the thing I reviewed changed under me" complaints)
- **Lawyer notes** populated during review (`evidence_tags.lawyer_notes`)
- **Piece numbering** assigned on approval — matches French legal
  convention ("Pièce 1, Pièce 2…") so the output drops straight into the
  avocat's bordereau de pièces

### Product-shape implications

- The client-facing Cabinet Starter tier can include the full tagging UI
  but caps **submitted** bundles per month (say 3) — natural upgrade lever
  to Plus
- Cabinet Plus unlocks unlimited submissions and the version-pinning +
  lawyer-note returns
- Cabinet Pro adds redaction tooling for zones of emails the client wants
  hidden before transmission (e.g. third-party mentions), plus shared
  evidence libraries across a firm's clients for boilerplate procedures

### AI suggester as training-data flywheel

When an AI-suggested tag (`tagged_by='ai_suggested'`) is either confirmed
or dismissed by the client, and then approved/flagged by the lawyer, that
double-human-signal is exactly the labelled data the fine-tuning pipeline
in the LLM infrastructure strategy section needs. Evidence workflow and
training-data collection are the same pipeline — don't treat them
separately in the roadmap.

### Build sequence

Already shipped (B2C-usable): v0 tagging.
Near-term (B2C, still useful solo): v1 bulk tag + Evidence tab on
procedure, v2 bundle builder + PDF/ZIP export + redaction.
B2B-gated: v3 submission + lawyer dashboard + status lifecycle —
triggered by the first paying firm, not earlier.

## Pricing

| Tier            | Price/mo | Capacity                                  |
|-----------------|----------|-------------------------------------------|
| Cabinet Starter | €149     | Solo avocat, up to 8 active clients       |
| Cabinet Plus    | €349     | 2–5 avocats, up to 25 active clients      |
| Cabinet Pro     | €699     | Up to 60 clients, priority, white-label   |

- Annual plan: -20%
- Per-extra-client overage: €15/mo
- Payment: Stripe, SEPA Direct Debit for annual

### Revenue math

At 200 firms on Cabinet Plus: **~€70k MRR / €840k ARR** — a meaningful
solo-founder business without needing venture scale.

## What needs to change in the codebase

- **Multi-tenancy**: PostgreSQL with schema-per-tenant (already in
  `productization.md`)
- **Three roles**: `firm_admin`, `avocat`, `client` — client data accessible
  only to assigned avocats
- **New UI**: firm dashboard (cross-client), review queue, structured-review
  form
- **Billing**: per-active-client metering via Stripe
- **White-label option** (Pro tier): firm logo, custom domain
- **DPA (Data Processing Agreement)** boilerplate: firm = controller,
  platform = processor
- **Audit log**: every review decision recorded with avocat ID + timestamp
  (needed for liability defense and disciplinary proceedings)

## Compliance checklist (France)

- **RGPD**: standard DPA with each firm; firm is controller, platform is
  processor. Client consent captured at onboarding by the firm, not the
  platform.
- **Secret professionnel**: enterprise-grade encryption at rest and in transit;
  platform operators never read content; strict access logs.
- **CNB / démarchage**: no marketing to end-clients directly. Platform is a
  neutral tool sold to licensed avocats.
- **Hébergement**: French or EU-hosted infrastructure (OVH, Scaleway, Hetzner
  Nuremberg). No US cloud for client data without SCCs + TIA.
- **Avocat liability**: platform terms make explicit that legal responsibility
  remains with the avocat; platform is a tool, not a legal advisor.

## LLM infrastructure strategy

Two separate decisions, different cost/benefit profiles, must be sequenced
carefully: **specialized model training** and **dedicated LLM instances per
firm**.

### Specialized model training

| Option                                | Cost                             | When to do it                                                  |
|---------------------------------------|----------------------------------|----------------------------------------------------------------|
| Prompt engineering (current)          | €0                               | Until 10k+ labeled examples from real customer use exist       |
| LoRA / QLoRA on open base (Mistral, Llama, Qwen) | €5–50k + retraining cycles | After ~12 months of B2B customers generating structured reviews |
| Full fine-tuning                      | €50–500k                         | Probably never — ROI doesn't beat LoRA for this domain         |
| From-scratch training                 | €10M+                            | Never                                                          |

**Why it's premature now**: the current corpus is effectively one user's
divorce — fine-tuning on it overfits. Prompt engineering on Llama 3.3 70B or
Mistral Large already hits ~90% of the achievable ceiling for
classify/tone/manipulation tasks.

**Why the B2B review loop is the training flywheel**: the structured reviews
avocats submit (legal_risk, tone_concern, inline_edits, green_light) are
*exactly* the labeled data a future fine-tune needs. The B2B product generates
its own training dataset as a side effect of normal use — do not short-circuit
this.

**Advantages of eventual fine-tuning** (not before Year 2):
- Fewer JSON parse failures — the biggest practical quality-of-life win
- Strict taxonomy compliance — model always outputs exact manipulation/tone
  categories defined by the product
- Cheaper inference on 7–13B models → per-firm hosting cost drops ~10×
- Narrative: *"our model, trained on French family-law data, not a US
  corporation's generic LLM"*

### Dedicated LLM instance per firm

**Real advantages**:
- Data sovereignty — strongest enterprise sales argument in France post-Cloud
  Act
- Avocat can truthfully tell clients *"your data never leaves EU-controlled
  infrastructure"*
- Defense against future API provider terms changes (e.g. training on API data)
- Cleaner posture for *secret professionnel* defense

**Real disadvantages**:
- GPU 24/7 per firm → meaningful infra cost
- Operational complexity multiplied by firm count
- Slower iteration (can't hot-patch across all firms simultaneously)
- Quality ceiling of self-hosted open models
- Only economically viable at Cabinet Pro tier or higher

### Recommended sequencing

**Phase 1 — France launch (Q1 post-decision)**: use **Mistral AI's hosted API**
as default LLM.
- French company, French servers, no US transfer
- Quality competitive with GPT-4 for classification tasks
- Alone, this is 80% of the data-control pitch with 0% of the ops cost
- Market positioning: *"IA souveraine française"*

**Phase 2 — after ~€50k MRR**: add a **Sovereign tier**.
- Dedicated Mistral instance (via Mistral's enterprise offering) OR self-hosted
  Llama 3.3 70B on a firm-dedicated Hetzner GPU box
- New pricing line: **Cabinet Sovereign — €1,499/mo**
- Target: firms handling high-profile cases (célébrités, politiques, HNW)
- This is a pure upsell on existing tiers, not a separate product line

**Phase 3 — after ~10k+ structured avocat reviews collected**: evaluate
fine-tuning.
- LoRA on Mistral Small (7B) using accumulated review data
- Blind eval against hosted Mistral on internal benchmark
- If fewer parse failures + comparable quality → ship as Sovereign-tier
  default model
- Narrative shift: *"model benchmarked to beat GPT-4 on our French
  family-law taxonomy"*

### Positioning tiers externally

Avocats do not care about model architecture. Position the options as:

- **Standard tier**: "French-hosted AI, your client data stays in the EU"
- **Sovereign tier**: "Dedicated instance, your firm's data never touches a
  shared system"
- **Custom tier** (Year 2+): "Model trained specifically on French family-law
  manipulation patterns"

### Architectural consequence today

- LLM calls must continue to route exclusively through `src/llm/` provider
  abstraction (already the case — keep it that way)
- **Never bake provider-specific assumptions into analysis code** — the
  Sovereign tier depends on swapping providers transparently
- Add a `tenant.llm_provider` setting when multi-tenancy lands, so per-firm
  routing works from day one

## Go-to-market

### Phase 1 — design partners (Q1 post-decision)

- Recruit **3 design-partner firms** in one city (Paris preferred)
- Free forever in exchange for:
  - Weekly feedback sessions
  - Video testimonial once the product clicks
  - Introductions to 2–3 peer firms each
- **Do not build multi-tenancy yet** — run each firm on a dedicated instance.
  Prove the review loop works first, then invest in the platform rebuild.

### Phase 2 — inbound only (6–12 months)

- **Content engine**: "Le droit de la famille à l'ère de l'IA" — position the
  founder as a thought leader in the space
- **Channels**:
  - *Village de la Justice* (articles, sponsored content)
  - LinkedIn family-law groups
  - *Barreau de Paris* commission famille
  - JAF (Juge aux Affaires Familiales) networking events
  - Regional conferences (Congrès de l'ACE, Salon du Barreau)
- **Avoid cold email** — regulated under démarchage rules and ineffective
  with this audience
- **Referral mechanic**: 2 months free for each firm a customer refers

### Phase 3 — scale (12–24 months)

- Channel partnerships with legal-tech distributors (Lamy, Dalloz)
- Expand to other specialized family-law segments (successions, filiation)
- Consider adjacent jurisdictions: Belgium, Switzerland (Romandie), Quebec

## Expansion roadmap

Expansion is sequenced to minimize compounding risk: **never add a new
geography and a new vertical in the same quarter**. Every new geography is a
new sales motion; every new vertical is new prompts, taxonomies, and domain
expertise.

### Geographic expansion

**Tier 1 — near-zero adaptation cost (same language, similar civil law)**

| Market                        | Why                                                                                   | Caveats                                                |
|-------------------------------|---------------------------------------------------------------------------------------|--------------------------------------------------------|
| Belgium (Wallonie, Bruxelles) | French-speaking, civil-law, adversarial family culture, tech-curious bar              | Separate OBFG compliance                               |
| Switzerland (Romandie)        | French-speaking, wealthy clientele, high legal-tech spend per capita                  | Cantonal differences (Genève ≠ Vaud), smaller TAM      |
| Québec                        | French-speaking, civil-law (Code civil du Québec close to French model)               | Different court structure, Barreau du Québec rules     |
| Luxembourg                    | French-speaking bar, high-income, civil law                                           | Tiny TAM                                               |

Estimated effort: **4–8 weeks per market** — procedure-dictionary tweaks only,
no re-prompting or retraining.

**Tier 2 — meaningful adaptation (Romance languages, civil law)**

- **Italy** — very high family litigation rate, codice civile close to French
  model; new language + tone/manipulation taxonomy
- **Spain** — high divorce rate, high-conflict custody culture
- **Portugal** — smaller but underserved legal-tech market

Estimated effort: **2–3 months per language** (prompts + taxonomy + validation
corpus).

**Tier 3 — expensive, high reward**

- **UK / Ireland / Australia / Anglo-Canada**: common-law systems. English is
  easy for LLMs but the legal ontology is fundamentally different.
- **USA**: largest market on the planet, but 50 state bars + entrenched legal
  tech incumbents (Relativity, Logikcull, MyCase). Only viable with a local
  partner.

**Don't pursue**:
- **Germany / Nordics**: mediation-first culture dampens the adversarial use
  case
- **Russia / Ukraine / Belarus**: high divorce rate but geopolitical instability

### Vertical expansion

The core capability is *"intelligence platform for relationship-deterioration
email evidence"*. Three adjacent verticals reuse the stack cleanly:

**Strong fit — same emotional and evidential pattern**

1. **Workplace harassment (harcèlement moral / sexuel)** — best adjacency.
   Same lawyer archetype (*avocats droit du travail contentieux*), same
   email-as-evidence pattern, manipulation/tone analysis applies almost
   unchanged. Target court: *Conseil des Prud'hommes*.
2. **Inheritance / succession disputes** — family conflict, decade-long email
   trails, emotional escalation, distinct legal vocabulary but same core
   capability.
3. **Small-business co-founder / shareholder disputes** — two people who
   worked closely, relationship deteriorated, evidence is email. Buyer is
   *avocat droit des sociétés*.

**Weak fit — avoid**

- Commercial M&A litigation (entrenched incumbents, commoditized discovery)
- Medical malpractice (unrelated domain)
- IP / patent (specialized, small buyer pool)
- Criminal defense (different workflow)

### Recommended sequence

1. **Prove the B2B-to-avocats model in France first** (design partners + first
   paying firms)
2. **Horizontal — Belgium + Switzerland Romandie** (near-zero cost,
   validates the multi-jurisdiction operating model)
3. **Vertical — harcèlement moral in France** (same country, same regulatory
   environment, different avocat segment — the cheapest revenue multiplier
   available)
4. **Horizontal — Québec**, then **Italy or Spain**
5. **Vertical — inheritance disputes in France** alongside the Romance-language
   expansion
6. Only then evaluate Anglo / US with a local partner

**Rationale**: step 3 is the highest-ROI move after France works, because
*harcèlement moral* reuses the same lawyer audience, the same compliance
framework, and nearly the same prompts — but doubles addressable demand.

## Competitive landscape

| Competitor      | What they do               | Why we're different                       |
|-----------------|----------------------------|-------------------------------------------|
| Legalstart      | Transactional legal docs   | We're relational, for ongoing cases       |
| Captain Contrat | B2B contracts              | Not family-law                            |
| Doctrine        | Legal research for lawyers | Research tool, not client collaboration   |
| Jarvis Legal    | Practice management        | No AI, no client-facing layer             |
| Secib           | Billing + calendar         | No AI, no email intelligence              |
| Harvey          | AI for big-firm corporate  | Wrong segment, wrong language, wrong $$$  |
| Spellbook       | AI contract review         | Not family-law, not French                |

The uncontested space: **AI-native client collaboration for French family-law
solo practitioners**. No serious incumbent.

## Risks

- **Avocats are notoriously tech-averse** → long sales cycles (6–12 months)
- **Small French TAM** → may need EU expansion to reach venture scale (if ever
  needed); comfortable solo-founder scale without it
- **Regulatory drift** if CNB issues new restrictions on AI tools
- **Design partners quit** if the review loop doesn't actually save them time
  → Phase 1 must rigorously measure avocat time-per-review before scaling

## The sharpest bet

**This quarter:**
1. Pick one avocat as design partner
2. Run a 4-week pilot on their 3–5 highest-conflict clients
3. Measure: time-to-review per draft, client satisfaction, avocat satisfaction
4. Get one testimonial on video

**Only then** invest in multi-tenancy, billing, and the platform rebuild.

The existing B2C product becomes the demo:
*"Here's what your clients already do manually — now imagine you're in the
loop."*

## Open questions for future decisions

- **White-label vs. branded**: do firms want to present the tool as their
  own, or is Northline branding acceptable?
- **Mobile app**: clients in emotional crisis reach for phone first. Web-only
  may be insufficient.
- **Integration with existing practice management** (Jarvis, Secib): essential
  or distraction?
- **Multi-language**: Belgian avocats speak French but use Dutch-language
  clients too. When does i18n become blocking?
- **Insurance**: does the platform carry a complementary RCP umbrella, or is
  the firm's own RCP sufficient? Speak to an insurance broker before Phase 2.
