"""
Report builder — assembles renderer-agnostic Report structures from aggregated data.

Each build_*() function queries the database via the aggregator, generates
charts, and returns a Report dataclass ready for rendering to DOCX or PDF.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.statistics.aggregator import (
    analysis_methodology,
    contact_summary,
    contradiction_summary,
    frequency_data,
    merged_timeline,
    overview_stats,
    tone_trends,
    top_aggressive_emails,
    topic_evolution,
    response_times,
)
from src.reports.charts import (
    frequency_chart,
    response_time_chart,
    tone_distribution_pie,
    tone_trend_chart,
    topic_evolution_chart,
)


# ─────────────────────────── DATA CLASSES ────────────────────────────────

@dataclass
class ReportSection:
    title: str
    level: int = 1
    paragraphs: List[str] = field(default_factory=list)
    table: Optional[Dict] = None  # {"headers": [...], "rows": [[...]]}
    chart_path: Optional[Path] = None
    subsections: List["ReportSection"] = field(default_factory=list)


@dataclass
class Report:
    title: str
    subtitle: str
    date: str
    sections: List[ReportSection] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ─────────────────────────── HELPERS ─────────────────────────────────────

def _has_analysis(conn: sqlite3.Connection, analysis_type: str) -> bool:
    """Check if any completed analysis of this type exists."""
    row = conn.execute(
        "SELECT COUNT(*) FROM analysis_runs WHERE analysis_type=? AND status IN ('complete','partial')",
        (analysis_type,),
    ).fetchone()
    return row[0] > 0


def _missing_section(title: str, analysis_type: str) -> ReportSection:
    """Placeholder section when analysis hasn't been run yet."""
    return ReportSection(
        title=title,
        paragraphs=[
            f"Analyse « {analysis_type} » non effectuée. "
            f"Exécutez 'python cli.py analyze {analysis_type}' au préalable."
        ],
    )


def _fmt_hours(h: float) -> str:
    if h == 0:
        return "—"
    if h < 1:
        return f"{h * 60:.0f} min"
    if h < 48:
        return f"{h:.1f} h"
    return f"{h / 24:.1f} j"


# ─────────────────────────── TIMELINE REPORT ─────────────────────────────

def build_timeline_report(conn: sqlite3.Connection, output_dir: Path,
                          since: Optional[str] = None,
                          until: Optional[str] = None) -> Report:
    """Build the master timeline report."""
    report = Report(
        title="Chronologie des événements",
        subtitle="Dossier de divorce — Événements extraits et audiences",
        date=date.today().isoformat(),
        metadata={"type": "timeline"},
    )

    events = merged_timeline(conn, since=since, until=until)

    if not events:
        report.sections.append(ReportSection(
            title="Chronologie",
            paragraphs=["Aucun événement trouvé. Exécutez 'analyze timeline' et/ou ajoutez des événements judiciaires."],
        ))
        return report

    # Summary
    court_count = sum(1 for e in events if e["source"] == "court")
    email_count = sum(1 for e in events if e["source"] == "email")
    high_count = sum(1 for e in events if e.get("significance") == "high")

    report.sections.append(ReportSection(
        title="Résumé",
        paragraphs=[
            f"Cette chronologie contient {len(events)} événements : "
            f"{court_count} événements judiciaires et {email_count} événements extraits des emails.",
            f"Dont {high_count} événements de haute importance.",
        ],
    ))

    # Frequency chart
    freq_data = frequency_data(conn, by="month")
    if freq_data:
        chart_path = frequency_chart(freq_data, output_dir, title="Volume d'emails par mois")
        report.sections.append(ReportSection(
            title="Volume de correspondance",
            chart_path=chart_path,
        ))

    # Timeline table
    headers = ["Date", "Source", "Type", "Description", "Importance", "Sujet"]
    rows = []
    for e in events:
        rows.append([
            str(e["date"] or "?")[:10],
            "⚖️ Tribunal" if e["source"] == "court" else "📧 Email",
            e.get("type", ""),
            (e.get("description", "") or "")[:80],
            e.get("significance", ""),
            e.get("topic", "") or "",
        ])

    report.sections.append(ReportSection(
        title="Chronologie détaillée",
        table={"headers": headers, "rows": rows},
    ))

    return report


# ─────────────────────────── TONE REPORT ─────────────────────────────────

def build_tone_report(conn: sqlite3.Connection, output_dir: Path) -> Report:
    """Build the tone analysis report with charts and tables."""
    report = Report(
        title="Analyse du ton",
        subtitle="Dossier de divorce — Agressivité, manipulation et posture juridique",
        date=date.today().isoformat(),
        metadata={"type": "tone"},
    )

    if not _has_analysis(conn, "tone"):
        report.sections.append(_missing_section("Analyse du ton", "tone"))
        return report

    # Tone trends chart
    trends = tone_trends(conn, by="month")
    if trends:
        chart_path = tone_trend_chart(trends, output_dir)
        report.sections.append(ReportSection(
            title="Évolution du ton dans le temps",
            paragraphs=[
                "Ce graphique montre l'évolution de l'agressivité et de la manipulation "
                "dans les emails envoyés et reçus, mois par mois."
            ],
            chart_path=chart_path,
        ))

    # Tone distribution pie
    tone_counts: Dict[str, int] = {}
    rows = conn.execute(
        """SELECT json_extract(ar.result_json, '$.tone') AS tone, COUNT(*) AS cnt
           FROM analysis_results ar
           JOIN analysis_runs r ON r.id = ar.run_id
           WHERE r.analysis_type = 'tone'
           GROUP BY tone ORDER BY cnt DESC"""
    ).fetchall()
    for r in rows:
        if r["tone"]:
            tone_counts[r["tone"]] = r["cnt"]
    if tone_counts:
        pie_path = tone_distribution_pie(tone_counts, output_dir)
        report.sections.append(ReportSection(
            title="Distribution des catégories de ton",
            chart_path=pie_path,
        ))

    # Top aggressive emails
    top_emails = top_aggressive_emails(conn, limit=10)
    if top_emails:
        headers = ["#", "Date", "Direction", "Sujet", "Agressivité", "Manipulation", "Ton"]
        tbl_rows = []
        for e in top_emails:
            tbl_rows.append([
                str(e["id"]),
                e["date"],
                "↑ envoyé" if e["direction"] == "sent" else "↓ reçu",
                e["subject"][:40],
                f"{e['aggression']:.2f}",
                f"{e['manipulation']:.2f}",
                e["tone"],
            ])
        report.sections.append(ReportSection(
            title="Top 10 des emails les plus agressifs",
            table={"headers": headers, "rows": tbl_rows},
        ))

    return report


# ─────────────────────────── CONTRADICTION REPORT ────────────────────────

def build_contradiction_report(conn: sqlite3.Connection, output_dir: Path) -> Report:
    """Build the contradiction report grouped by severity."""
    report = Report(
        title="Rapport de contradictions",
        subtitle="Dossier de divorce — Contradictions détectées dans la correspondance",
        date=date.today().isoformat(),
        metadata={"type": "contradictions"},
    )

    summary = contradiction_summary(conn)

    if summary["total"] == 0:
        report.sections.append(ReportSection(
            title="Contradictions",
            paragraphs=["Aucune contradiction détectée. Exécutez 'analyze contradictions' au préalable."],
        ))
        return report

    # Summary
    report.sections.append(ReportSection(
        title="Résumé",
        paragraphs=[
            f"Total de contradictions détectées : {summary['total']}",
            f"Par sévérité : {summary['by_severity']['high']} haute, "
            f"{summary['by_severity']['medium']} moyenne, {summary['by_severity']['low']} basse.",
            f"Par portée : {summary['by_scope'].get('intra-sender', 0)} intra-expéditeur, "
            f"{summary['by_scope'].get('cross-sender', 0)} inter-expéditeur.",
        ],
    ))

    # Detailed table
    for sev in ("high", "medium", "low"):
        sev_items = [i for i in summary["items"] if i["severity"] == sev]
        if not sev_items:
            continue

        sev_labels = {"high": "Haute", "medium": "Moyenne", "low": "Basse"}
        headers = ["Email A", "Email B", "Portée", "Sujet", "Explication"]
        rows = []
        for item in sev_items:
            rows.append([
                f"#{item['email_id_a']} ({str(item['date_a'])[:10]})",
                f"#{item['email_id_b']} ({str(item['date_b'])[:10]})",
                item["scope"],
                item.get("topic") or "—",
                (item["explanation"] or "")[:120],
            ])

        report.sections.append(ReportSection(
            title=f"Sévérité {sev_labels[sev]} ({len(sev_items)})",
            level=2,
            table={"headers": headers, "rows": rows},
        ))

    return report


# ─────────────────────────── FULL DOSSIER ────────────────────────────────

def build_full_report(conn: sqlite3.Connection, output_dir: Path) -> Report:
    """Build the comprehensive dossier combining all sections."""
    report = Report(
        title="Dossier d'analyse de correspondance",
        subtitle="Analyse complète des échanges d'emails — Procédure de divorce",
        date=date.today().isoformat(),
        metadata={"type": "full"},
    )

    # ── 1. Synthèse ─────────────────────────────────────────────────────
    stats = overview_stats(conn)
    report.sections.append(ReportSection(
        title="Synthèse",
        paragraphs=[
            f"Ce dossier couvre {stats['total']} emails ({stats['sent']} envoyés, "
            f"{stats['received']} reçus) échangés entre le {stats['first_date'] or '?'} "
            f"et le {stats['last_date'] or '?'}.",
            f"Les emails sont regroupés en {stats['threads']} fils de conversation, "
            f"couvrant {stats['topics_count']} sujets thématiques.",
            f"Langue dominante : français ({stats['french']} emails), "
            f"anglais ({stats['english']} emails).",
            f"Analyses effectuées : {stats['classify_count']} classifiés, "
            f"{stats['tone_count']} analysés en ton, "
            f"{stats['manipulation_count']} analysés en manipulation, "
            f"{stats['contradiction_count']} contradictions détectées.",
        ],
    ))

    # ── 2. Chronologie ──────────────────────────────────────────────────
    timeline_report = build_timeline_report(conn, output_dir)
    for s in timeline_report.sections:
        s.level = 2
    report.sections.append(ReportSection(
        title="Chronologie",
        subsections=timeline_report.sections,
    ))

    # ── 3. Analyse du ton ───────────────────────────────────────────────
    tone_report = build_tone_report(conn, output_dir)
    for s in tone_report.sections:
        s.level = 2
    report.sections.append(ReportSection(
        title="Analyse du ton",
        subsections=tone_report.sections,
    ))

    # ── 4. Contradictions ───────────────────────────────────────────────
    contradiction_report = build_contradiction_report(conn, output_dir)
    for s in contradiction_report.sections:
        s.level = 2
    report.sections.append(ReportSection(
        title="Contradictions",
        subsections=contradiction_report.sections,
    ))

    # ── 5. Évolution des sujets ─────────────────────────────────────────
    topic_data = topic_evolution(conn, by="quarter")
    if topic_data:
        chart_path = topic_evolution_chart(topic_data, output_dir)
        report.sections.append(ReportSection(
            title="Évolution des sujets",
            paragraphs=[
                "Ce graphique montre l'évolution de la prévalence des principaux "
                "sujets de discussion au fil du temps."
            ],
            chart_path=chart_path,
        ))

    # ── 6. Temps de réponse ─────────────────────────────────────────────
    rt_data = response_times(conn, by="quarter")
    if rt_data["your_response"]["count"] > 0 or rt_data["their_response"]["count"] > 0:
        rt_chart = response_time_chart(rt_data, output_dir)
        yr = rt_data["your_response"]
        tr = rt_data["their_response"]
        report.sections.append(ReportSection(
            title="Temps de réponse",
            paragraphs=[
                f"Votre temps de réponse moyen : {_fmt_hours(yr['avg_hours'])} "
                f"(médiane : {_fmt_hours(yr['median_hours'])}, sur {yr['count']} échanges).",
                f"Temps de réponse de l'ex-conjoint(e) : {_fmt_hours(tr['avg_hours'])} "
                f"(médiane : {_fmt_hours(tr['median_hours'])}, sur {tr['count']} échanges).",
            ],
            chart_path=rt_chart,
        ))

    # ── 7. Activité par contact ─────────────────────────────────────────
    contacts = contact_summary(conn)
    if contacts:
        headers = ["Nom", "Rôle", "Envoyés", "Reçus", "Total", "Période"]
        rows = []
        for c in contacts:
            rows.append([
                c["name"], c["role"],
                str(c["sent"]), str(c["received"]), str(c["total"]),
                f"{c['first_email'] or '?'} → {c['last_email'] or '?'}",
            ])
        report.sections.append(ReportSection(
            title="Activité par contact",
            table={"headers": headers, "rows": rows},
        ))

    # ── 8. Méthodologie ─────────────────────────────────────────────────
    runs = analysis_methodology(conn)
    if runs:
        headers = ["Type", "Fournisseur", "Modèle", "Date", "Emails", "Statut"]
        rows = []
        for r in runs:
            rows.append([
                r["analysis_type"],
                r["provider_name"],
                r["model_id"][:20],
                str(r["run_date"])[:16],
                str(r["email_count"] or "—"),
                r["status"],
            ])
        report.sections.append(ReportSection(
            title="Méthodologie",
            paragraphs=[
                "Ce tableau détaille les analyses effectuées, les modèles d'IA utilisés, "
                "et la couverture de chaque analyse."
            ],
            table={"headers": headers, "rows": rows},
        ))

    return report
