# Session Handoff

> This file is **replaced** each session. It captures the last session's work and the exact resume point.

---

**Last Updated: 2026-04-04**

## What Was Accomplished This Session

### Phase 6e — Procedure Document Upload + PDF Analysis (continued)

This session completed procedure #11 "Plainte pour Maltraitance", which had been blocked by a CID/Type 3 font-encoded PDF that neither pdfplumber nor pypdf could decode.

#### Procedure #11 — Plainte pour Maltraitance (PV n° 00962/2023/001368)

**Problem**: The PDF (`12_2023-1368 MAISON GAEL VIOLENCES SUR MINEURS.pdf`, 89 KB, 4 pages) uses proprietary CID/Type 3 font encoding — pdfplumber outputs `(cid:0)(cid:1)...`, pypdf outputs `/0 /1 /2...`. Standard OCR tools (tesseract, ocrmypdf, pytesseract) not installed.

**Solution**: macOS Vision framework via Swift 6.2.4. Compiled a Swift script (`/tmp/ocr_pdf.swift`) that renders each PDF page to a CGImage at 2× scale then runs `VNRecognizeTextRequest` with `recognitionLevel = .accurate` and `recognitionLanguages = ["fr-FR", "en-US"]`. Full 4-page text extracted successfully (~95% accuracy).

**Key legal facts extracted:**
- **Plaignant**: Gaël MAISON, architecte, résidant à Abu Dhabi (The Arc Tower C 2016)
- **Victimes**: Matheys (né 19/09/2008) et Lounys (né 30/07/2011)
- **Mis en cause**: MULLER Maud + BAREYRE Frédéric (compagnon)
- **Rédactrice PV**: Laurine TRENEC, Gardienne de la Paix, APJ, CSP Sèvres
- **Faits depuis 2021**: Bareyre ceinturerait régulièrement Matheys au sol ; insults récurrentes ("vous êtes stupides") ; comportements d'intimidation
- **25/03/2023**: Bareyre tient fortement la mâchoire de Lounys (photos WhatsApp remises)
- **26/03/2023**: Maud mord la main de Matheys + casse sa montre ; Bareyre le plaque au sol et le ceinture (photo de morsure remise ~5h après)
- **29/03/2023**: Email de Gaël à Maud → Maud nie les faits par écrit
- **07/04/2023**: Dépôt de plainte au CSP Sèvres, 14h11 ; annexes : photos, WhatsApp, email
- **Suites**: Inconnues (renvoi possible au Parquet de Nanterre)
- **Maylis**: Citée pour un fait isolé ~2017 (Frédéric lui aurait mis un coup de portefeuille dans le visage) mais non retenue comme victime dans la plainte

**Metadata populated:**
- `jurisdiction`: CSP de Sèvres (Police Judiciaire)
- `case_number`: PV n° 00962/2023/001368
- `filing_date`: 2023-04-07, `date_start`: 2023-04-07
- `status`: unknown (suites inconnues)
- 4 procedure_events: incident 25/03, incident 26/03, correspondence 29/03, filing 07/04

**OCR transcript saved**: `data/documents/procedures/11/ocr_PV_2023-1368.txt` (11 KB) registered as `procedure_document id=13` with `content_type: text/plain` and a note explaining the CID encoding issue.

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
| 11 | Plainte pour Maltraitance | PV 2023/001368 | unknown ⚠️ | 2 | 4 |
| 12 | Liquidation Financière | RG 23/06050 | open 🔄 | 1 | 3 |
| 13 | Révision de Pensions | RG 24/07044 | closed ✅ | 1 | 4 |
| 14 | Révision de Pensions — Appel | — | unknown ⚠️ | 0 | 0 |
| 15 | Procédure Lounys vivre à Dubai | — | unknown ⚠️ | 0 | 0 |

**Total: 13 procedure_documents, 45 procedure_events**

---

## Resume Point for Next Session

### Current branch: `feature/corpus-filter-ui`

### Procedures awaiting documents
- **#7 Négociation Amiable** — no document; likely informal/undocumented
- **#14 Révision de Pensions — Appel** — no document uploaded (may not exist if appeal not yet filed / CA Versailles)
- **#15 Procédure Lounys vivre à Dubai** — no document uploaded

### OCR approach for future CID-encoded PDFs
```bash
# Compile once per session
swiftc /tmp/ocr_pdf.swift -o /tmp/ocr_pdf

# Run on any PDF
/tmp/ocr_pdf "path/to/document.pdf"
```
The Swift source is at `/tmp/ocr_pdf.swift` (not committed — regenerate from session summary if needed).

### Next tasks (Phase 6 remaining)

**Phase 6e — Procedures Web UI (not started)**
- Web UI for viewing/editing procedures and procedure_events at `/procedures/`
- Display document list per procedure (upload already works in detail page)
- Link procedure_events to emails and attachments via UI

**Phase 6h — Unified Timeline (not started)**
- Merge personal + legal corpora + procedure events + cost events
- Color-coded by source type

**Phase 6i — Judgment PDF Analysis (partially done)**
- pdfplumber installed and used ad-hoc
- Vision framework OCR now proven for CID-encoded PDFs
- Formal structured extraction CLI command not yet built

### Quick Start
```bash
git checkout feature/corpus-filter-ui
.venv/bin/python cli.py web --reload    # http://127.0.0.1:8000
# Navigate to Legal Strategy → Procedures
```
