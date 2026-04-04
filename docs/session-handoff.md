# Session Handoff

> This file is **replaced** each session. It captures the last session's work and the exact resume point.

---

**Last Updated: 2026-04-04**

## What Was Accomplished This Session

### Phase 6e — Procedure Document Upload + PDF Analysis (continued)

The session was entirely focused on populating procedure metadata by uploading court judgment PDFs and analysing them with pdfplumber. This is the "document-first" strategy: upload the PDF, Claude extracts text and auto-fills all metadata + creates procedure_events.

#### Procedures fully populated this session

| # | Name | RG | Status | Doc |
|---|---|---|---|---|
| 1 | Contestation Paternité | RG 17/10390 | closed | jugement_contestation_200225.pdf |
| 8 | Incident (JME) | RG 15/33553 | closed | ordonnance du JME du 20.02.2017.pdf (imported from Downloads) |
| 9 | Incident — Appel | RG 17/18289 | closed | Incident appel_5_139789124_DECISION.PDF |
| 10 | Acquiescements | Protocole 04/09/2020 | closed | Protocole d_accord signé GM 040920 rev-.pdf |
| 12 | Liquidation Financière | RG 23/06050 | open | MINUTE_75_.PDF (22 pages) |
| 13 | Révision de Pensions | RG 24/07044 | closed | MINUTE - 2025-07-02T095107.815.pdf |

#### Bug fixed: UPDATE not committed when INSERT fails in same script
When the first SQL script for procedure #1 errored on `NOT NULL constraint failed: procedure_events.notes` before reaching `conn.commit()`, the entire transaction was silently rolled back — including the already-executed UPDATE. Lesson: always use `notes=''` (not `None`) for NOT NULL columns, and use separate committed transactions.

#### Procedure #8 "Incident" — document imported from Downloads
The user shared `/Users/innerspace/Downloads/ordonnance du JME du 20.02.2017.pdf`. Claude identified it as belonging to procedure #8 (not #9) based on RG 15/33553 (TGI Paris JME, 20/02/2017). The file was copied with `shutil.copy2` to `data/documents/procedures/8/` and a DB record was inserted.

#### Key legal facts extracted

**Proc #1 — Contestation Paternité:**
- Iannÿs Müller (ex-Maison) — non-paternité confirmée par 18 exclusions ADN (rapport 07/01/2019)
- Père biologique: Frédéric BAREYRE (reconnu 30/12/2017 à Ville-d'Avray)
- Admin ad hoc: Me Laurence JARRET (SCP LC2J, Hauts-de-Seine, vestiaire 752)
- Gaël connaissait sa non-paternité depuis juillet 2014 (test privé) → rejet partiel remboursement

**Proc #8 — Incident JME TGI Paris:**
- Gaël demandait cessation du devoir de secours + modification contribution enfants
- Maud demandait augmentation (700-900 €/enfant), provision ad litem 15k€, avance liquidation 95k€
- → Toutes demandes rejetées (aucun élément nouveau depuis l'ONC du 26/11/2015)

**Proc #9 — Incident appel (art. 526 CPC):**
- Maud obtient radiation du rôle (02/10/2018) pour défaut d'exécution par Gaël des frais de scolarité internationale (Ecole internationale de la Celle Saint-Cloud)
- Gaël condamné aux dépens + 1 500 € art. 700
- L'appel a été réinscrit et jugé sur le fond (procédure #6)

**Proc #10 — Acquiescements (Protocole 04/09/2020):**
- Compensation croisée: 35 132,49 € (Maud → Gaël) vs 35 762,65 € (Gaël → Maud)
- Solde net: 600 € + arrièrés 12 181,58 € dus par Gaël
- Prestation compensatoire 30k€ incluse dans la compensation
- Devoir de secours éteint au 01/09/2020
- Gaël prend 100% frais transport Iannÿs
- Engagement de procéder à la liquidation (→ procédure #12 ouverte en 2023)

**Proc #12 — Liquidation Financière (jugement 04/11/2025):**
- Partage judiciaire ordonné, notaire Me Hélène Boidin désignée
- Indemnité d'occupation 37 512 € (Gaël a bloqué la vente Sèvres 3 ans)
- Récompense 230 000 AED (loyers 2014 remboursés par employeur, non restitués)
- Gaël: avocat postulant Me Guillaume BOULAN (SCP CRTD, vestiaire 713, Hauts-de-Seine)
- Maud: avocat postulant Me Florence BERNARD-FERTIER (JRF & TEYTAUD SALEH, vestiaire PN 81)
- Procédure toujours OPEN (opérations notariales en cours)

**Proc #13 — Révision de Pensions (jugement 01/07/2025):**
- Pension augmentée de 568,78 → **800 €/enfant/mois** (2 400 € total)
- Maud comparante en PERSONNE (sans avocat)
- Revenus Gaël 2024: 23 160 €/mois net (ESRI, Dubai)
- Appel devant Cour d'Appel de VERSAILLES (pas Paris — TJ Nanterre)
- Gaël autorisé à inscrire Matheÿs au Club de Boxe Jaguar

---

## Current Procedure State

| # | Name | RG | Status | Docs | Events |
|---|---|---|---|---|---|
| 1 | Contestation Paternité | RG 17/10390 | closed ✅ | 1 | 5 |
| 2 | Première Instance (ONC) | RG 15/33553 | active ✅ | 1 | 4 |
| 3 | Appel Première Instance | RG 15/13023 | closed ✅ | 1 | 3 |
| 4 | Référé | RG 15/42684 | closed ✅ | 1 | 3 |
| 5 | Divorce pour Faute | RG 15/33553 | closed ✅ | 1 | 4 |
| 6 | Divorce pour Faute — Appel | RG 19/07859 | closed ✅ | 1 | 5 |
| 7 | Négociation Amiable | — | unknown ⚠️ | 0 | 0 |
| 8 | Incident (JME) | RG 15/33553 | closed ✅ | 1 | 4 |
| 9 | Incident — Appel | RG 17/18289 | closed ✅ | 1 | 3 |
| 10 | Acquiescements | Protocole 04/09/2020 | closed ✅ | 1 | 3 |
| 11 | Plainte pour Maltraitance | — | unknown ⚠️ | 0 | 0 |
| 12 | Liquidation Financière | RG 23/06050 | open 🔄 | 1 | 3 |
| 13 | Révision de Pensions | RG 24/07044 | closed ✅ | 1 | 4 |
| 14 | Révision de Pensions — Appel | — | unknown ⚠️ | 0 | 0 |
| 15 | Procédure Lounys vivre à Dubai | — | unknown ⚠️ | 0 | 0 |

**Total: 11 procedure_documents, 41 procedure_events**

---

## Resume Point for Next Session

### Current branch: `feature/corpus-filter-ui`

### Procedures awaiting documents / analysis
- **#7 Négociation Amiable** — no document yet; may be undocumented (informal)
- **#11 Plainte pour Maltraitance** — no document yet
- **#14 Révision de Pensions — Appel** — no document uploaded yet (may not exist if no appeal was filed)
- **#15 Procédure Lounys vivre à Dubai** — no document uploaded yet

### Next tasks (Phase 6 remaining)

**Phase 6e — Procedures Web UI (not started)**
- Web UI for viewing/editing procedures and procedure_events at `/procedures/`
- Display document list per procedure (upload already works in detail page)
- Link procedure_events to emails and attachments via UI

**Phase 6h — Unified Timeline (not started)**
- Merge personal + legal corpora + procedure events + cost events
- Color-coded by source type

**Phase 6i — Judgment PDF Analysis (partially done)**
- pdfplumber installed and used ad-hoc this session
- Formal structured extraction (parties, amounts, outcome) not yet a CLI command
- New dependency: `pdfplumber` (already installed in .venv)

### Quick Start
```bash
git checkout feature/corpus-filter-ui
.venv/bin/python cli.py web --reload    # http://127.0.0.1:8000
# Navigate to Legal Strategy → Procedures
```
