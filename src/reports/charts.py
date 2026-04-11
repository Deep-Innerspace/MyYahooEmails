"""
Chart generation for reports using matplotlib.

All functions save a PNG to output_dir and return the Path.
Uses Agg backend (non-interactive).
"""
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Consistent style
_STYLE = {
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.labelsize": 10,
    "axes.titlesize": 12,
    "figure.figsize": (10, 5),
    "figure.dpi": 150,
    "axes.grid": True,
    "grid.alpha": 0.3,
}


def _apply_style():
    plt.rcParams.update(_STYLE)


# ─── Procedure overlay helpers ────────────────────────────────────────────

_INITIATOR_COLORS = {
    "party_a": "#3b82f6",   # blue  (you)
    "party_b": "#ef4444",   # red   (ex-wife)
    "both":    "#10b981",   # green (mutual)
}
_INITIATOR_DEFAULT = "#9ca3af"   # gray (unknown)


def _period_start_date(period: str) -> Optional[datetime]:
    """Convert a period string to its start datetime."""
    try:
        if "-Q" in period:
            year, q = period.split("-Q")
            return datetime(int(year), (int(q) - 1) * 3 + 1, 1)
        elif "-W" in period:
            return datetime.strptime(period + "-1", "%Y-W%W-%w")
        else:
            return datetime.strptime(period[:7], "%Y-%m")
    except Exception:
        return None


def _find_band_range(periods: List[str], date_start: Optional[str],
                     date_end: Optional[str]):
    """Return (x_start, x_end) floats for axvspan, given procedure date strings."""
    if not date_start:
        return None, None
    dated = [(i, _period_start_date(p)) for i, p in enumerate(periods)]
    dated = [(i, d) for i, d in dated if d is not None]
    if not dated:
        return None, None
    try:
        proc_start = datetime.strptime(date_start[:10], "%Y-%m-%d")
        proc_end = (datetime.strptime(date_end[:10], "%Y-%m-%d")
                    if date_end else datetime(2027, 12, 31))
    except Exception:
        return None, None

    # leftmost index whose period date >= proc_start
    x_start = dated[0][0] - 0.5
    for i, d in dated:
        if d >= proc_start:
            x_start = i - 0.5
            break

    # rightmost index whose period date <= proc_end
    x_end = dated[-1][0] + 0.5
    for i, d in reversed(dated):
        if d <= proc_end:
            x_end = i + 0.5
            break

    return x_start, x_end


def _add_procedure_bands(ax, procedures: List[Dict], periods: List[str]) -> None:
    """Overlay shaded vertical bands for each procedure's active period.

    Bands are drawn with alpha=0.07 so overlapping periods appear darker,
    visually showing "high legal activity" zones.  A rotated micro-label
    is placed at the left edge of each band.
    """
    if not procedures or not periods:
        return

    ylim = ax.get_ylim()
    label_y = ylim[0] + (ylim[1] - ylim[0]) * 0.04

    for proc in procedures:
        x0, x1 = _find_band_range(periods, proc.get("date_start"), proc.get("date_end"))
        if x0 is None or x0 >= x1:
            continue
        color = _INITIATOR_COLORS.get(proc.get("initiated_by"), _INITIATOR_DEFAULT)
        is_appeal = proc.get("procedure_type") == "appel"
        hatch = "///" if is_appeal else None
        ax.axvspan(x0, x1, alpha=0.07, color=color, hatch=hatch,
                   linewidth=0, zorder=0)
        short = proc.get("name", "")[:18]
        ax.text(x0 + 0.15, label_y, short,
                fontsize=5, color=color, alpha=0.85,
                rotation=90, va="bottom", ha="left", zorder=2)


# ─── Procedure Gantt chart ────────────────────────────────────────────────

_TODAY = "2026-04-06"


def procedure_gantt_chart(procedures: List[Dict], output_dir: Path) -> Path:
    """Horizontal Gantt chart of all procedures coloured by initiator.

    Appeals are shown with hatching.  Ongoing procedures extend to TODAY
    with a semi-transparent tail.  Overlapping procedures are simply
    separate rows — overlap is immediately visible.
    """
    _apply_style()

    procs = [p for p in procedures if p.get("date_start")]
    procs.sort(key=lambda p: p["date_start"])

    if not procs:
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.text(0.5, 0.5, "No procedures with start dates", ha="center",
                va="center", transform=ax.transAxes, color="#999")
        path = output_dir / "procedure_gantt.png"
        fig.savefig(str(path))
        plt.close(fig)
        return path

    today = datetime.strptime(_TODAY, "%Y-%m-%d")
    fig_h = max(4, len(procs) * 0.7 + 2)
    fig, ax = plt.subplots(figsize=(14, fig_h))

    for idx, proc in enumerate(procs):
        try:
            start = datetime.strptime(proc["date_start"][:10], "%Y-%m-%d")
        except Exception:
            continue
        end_raw = proc.get("date_end")
        ongoing = end_raw is None
        try:
            end = (datetime.strptime(end_raw[:10], "%Y-%m-%d")
                   if end_raw else today)
        except Exception:
            end = today

        color = _INITIATOR_COLORS.get(proc.get("initiated_by"), _INITIATOR_DEFAULT)
        is_appeal = proc.get("procedure_type") == "appel"
        hatch = "///" if is_appeal else None

        # Main bar
        ax.barh(idx, (end - start).days, left=mdates.date2num(start),
                height=0.55, color=color, alpha=0.80,
                hatch=hatch, edgecolor="white", linewidth=0.5)

        # Ongoing ghost extension
        if ongoing:
            ghost_end = datetime(today.year + 1, today.month, 1)
            ax.barh(idx, (ghost_end - today).days,
                    left=mdates.date2num(today),
                    height=0.55, color=color, alpha=0.18,
                    edgecolor=color, linewidth=0.8, linestyle="dotted",
                    fill=True)

    # Today line
    ax.axvline(mdates.date2num(today), color="#374151", linewidth=1.2,
               linestyle="--", alpha=0.6, zorder=5)
    ax.text(mdates.date2num(today), len(procs) - 0.2, " Today",
            fontsize=7, color="#374151", va="top")

    ax.set_yticks(range(len(procs)))
    ax.set_yticklabels(
        [f"#{p['id']} {p['name']}" for p in procs],
        fontsize=8.5,
    )
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.grid(axis="x", alpha=0.3)
    ax.invert_yaxis()
    ax.set_title("Legal Procedures — Timeline & Overlap", fontsize=13,
                 fontweight="bold")

    # Legend
    from matplotlib.patches import Patch
    legend_handles = [
        Patch(color=_INITIATOR_COLORS["party_a"], alpha=0.8, label="Initiated by you (party A)"),
        Patch(color=_INITIATOR_COLORS["party_b"], alpha=0.8, label="Initiated by ex-wife (party B)"),
        Patch(color=_INITIATOR_COLORS["both"],    alpha=0.8, label="Mutual"),
        Patch(color=_INITIATOR_DEFAULT,            alpha=0.8, label="Unknown initiator"),
        Patch(color="#aaaaaa", hatch="///",        alpha=0.7, label="Appeal"),
    ]
    ax.legend(handles=legend_handles, loc="lower left", fontsize=8,
              framealpha=0.9)

    fig.tight_layout()
    path = output_dir / "procedure_gantt.png"
    fig.savefig(str(path), dpi=150)
    plt.close(fig)
    return path


def frequency_chart(data: List[Dict], output_dir: Path,
                    title: str = "Email Volume by Quarter",
                    procedures: Optional[List[Dict]] = None) -> Path:
    """Stacked bar chart: sent vs received by quarter, with year separators."""
    _apply_style()
    periods = [d["period"] for d in data]
    sent     = [d["sent"]     for d in data]
    received = [d["received"] for d in data]

    fig, ax = plt.subplots(figsize=(14, 5))
    x = range(len(periods))
    ax.bar(x, sent,     label="Sent",     color="#3b82f6", alpha=0.85)
    ax.bar(x, received, bottom=sent,      label="Received", color="#ef4444", alpha=0.85)

    # Year separator lines + labels
    current_year = None
    for i, period in enumerate(periods):
        year = period[:4]
        if year != current_year:
            if i > 0:
                ax.axvline(i - 0.5, color="#999", linewidth=0.6, linestyle="--", alpha=0.5)
            ax.text(i, ax.get_ylim()[1] * 0.02, year,
                    fontsize=7, color="#555", ha="left", va="bottom")
            current_year = year

    ax.set_xticks(x)
    ax.set_xticklabels(
        [p.replace("-Q", "\nQ") if "Q" in p else p for p in periods],
        rotation=0, ha="center", fontsize=6
    )
    ax.set_ylabel("Emails")
    ax.set_title(title)

    # Procedure period overlay (drawn before legend so bands are behind bars)
    if procedures:
        _add_procedure_bands(ax, procedures, periods)
        from matplotlib.patches import Patch
        proc_handles = [
            Patch(color=_INITIATOR_COLORS["party_a"], alpha=0.5, label="Proc. party A"),
            Patch(color=_INITIATOR_COLORS["party_b"], alpha=0.5, label="Proc. party B"),
        ]
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles=handles + proc_handles, loc="upper right", fontsize=8)
    else:
        ax.legend(loc="upper right")

    fig.tight_layout()

    path = output_dir / "frequency_chart.png"
    fig.savefig(str(path))
    plt.close(fig)
    return path


def daily_avg_chart(data: List[Dict], output_dir: Path,
                    title: str = "Daily Communication Intensity by Year") -> Path:
    """Grouped bars (sent/received avg per day) + ratio line overlay per year."""
    _apply_style()
    if not data:
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.text(0.5, 0.5, "No data", ha="center", va="center",
                transform=ax.transAxes, fontsize=12, color="#999")
        path = output_dir / "daily_avg_chart.png"
        fig.savefig(str(path))
        plt.close(fig)
        return path

    import numpy as np

    years      = [d["year"]           for d in data]
    sent_pd    = [d["sent_per_day"]   for d in data]
    recv_pd    = [d["received_per_day"] for d in data]
    ratios     = [d["ratio"] if d["ratio"] is not None else 0 for d in data]

    x      = np.arange(len(years))
    width  = 0.35

    fig, ax1 = plt.subplots(figsize=(13, 5))
    ax2 = ax1.twinx()

    bars_s = ax1.bar(x - width/2, sent_pd, width, label="Sent / day",
                     color="#3b82f6", alpha=0.85)
    bars_r = ax1.bar(x + width/2, recv_pd, width, label="Received / day",
                     color="#ef4444", alpha=0.85)

    # Ratio line (sent ÷ received) — >1 means you sent more, <1 means she sent more
    ax2.plot(x, ratios, color="#f59e0b", linewidth=2, marker="o",
             markersize=5, label="Sent/Received ratio", zorder=5)
    ax2.axhline(1.0, color="#f59e0b", linewidth=0.8, linestyle="--", alpha=0.4)
    ax2.set_ylabel("Sent / Received ratio", color="#f59e0b", fontsize=9)
    ax2.tick_params(axis="y", labelcolor="#f59e0b")
    ax2.set_ylim(0, max(ratios) * 1.4 + 0.1)

    ax1.set_xticks(x)
    ax1.set_xticklabels(years, rotation=45, ha="right")
    ax1.set_ylabel("Avg emails / day")
    ax1.set_title(title)

    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)

    fig.tight_layout()
    path = output_dir / "daily_avg_chart.png"
    fig.savefig(str(path))
    plt.close(fig)
    return path


def tone_trend_chart(data: List[Dict], output_dir: Path,
                     title: str = "Tone Evolution",
                     procedures: Optional[List[Dict]] = None) -> Path:
    """Line chart: aggression + manipulation over time, split by direction."""
    _apply_style()

    sent_data = [d for d in data if d["direction"] == "sent"]
    recv_data = [d for d in data if d["direction"] == "received"]

    # Build a unified sorted period index so both series share the same x-axis
    all_periods = sorted({d["period"] for d in data})
    if not all_periods:
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.text(0.5, 0.5, "No tone data available", ha="center", va="center",
                transform=ax.transAxes, fontsize=12, color="#999")
        path = output_dir / "tone_trend_chart.png"
        fig.savefig(str(path))
        plt.close(fig)
        return path

    p_idx = {p: i for i, p in enumerate(all_periods)}

    fig, ax = plt.subplots(figsize=(13, 5))

    if recv_data:
        x = [p_idx[d["period"]] for d in recv_data]
        ax.plot(x, [d["avg_aggression"] for d in recv_data],
                marker="o", markersize=4, label="Aggression (received)",
                color="#ef4444", linewidth=2)
        ax.plot(x, [d["avg_manipulation"] for d in recv_data],
                marker="s", markersize=3, label="Manipulation (received)",
                color="#f97316", linestyle="--", linewidth=1.5)

    if sent_data:
        x = [p_idx[d["period"]] for d in sent_data]
        ax.plot(x, [d["avg_aggression"] for d in sent_data],
                marker="o", markersize=4, label="Aggression (sent)",
                color="#3b82f6", linewidth=2)
        ax.plot(x, [d["avg_manipulation"] for d in sent_data],
                marker="s", markersize=3, label="Manipulation (sent)",
                color="#6366f1", linestyle="--", linewidth=1.5)

    # Thin x-axis ticks: show at most 20 labels regardless of granularity
    n = len(all_periods)
    step = max(1, n // 20)
    tick_pos = list(range(0, n, step))
    ax.set_xticks(tick_pos)
    ax.set_xticklabels([all_periods[i] for i in tick_pos], rotation=45, ha="right", fontsize=9)

    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Score (0–1)", fontsize=10)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.grid(axis="y", alpha=0.3)

    # Procedure period overlay
    if procedures:
        _add_procedure_bands(ax, procedures, all_periods)
        from matplotlib.patches import Patch
        proc_handles = [
            Patch(color=_INITIATOR_COLORS["party_a"], alpha=0.5, label="Proc. party A"),
            Patch(color=_INITIATOR_COLORS["party_b"], alpha=0.5, label="Proc. party B"),
        ]
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles=handles + proc_handles, fontsize=8, loc="upper left")
    else:
        ax.legend(fontsize=9, loc="upper left")

    fig.tight_layout()

    path = output_dir / "tone_trend_chart.png"
    fig.savefig(str(path), dpi=150)
    plt.close(fig)
    return path


def topic_evolution_chart(data: List[Dict], output_dir: Path,
                          top_n: int = 8,
                          title: str = "Évolution des sujets") -> Path:
    """Stacked area chart for top N topics over time."""
    _apply_style()

    # Aggregate total per topic to find top N
    topic_totals: Dict[str, int] = {}
    for d in data:
        topic_totals[d["topic"]] = topic_totals.get(d["topic"], 0) + d["email_count"]
    top_topics = sorted(topic_totals, key=topic_totals.get, reverse=True)[:top_n]

    # Build period -> topic -> count
    periods_set: OrderedDict = OrderedDict()
    for d in data:
        if d["topic"] in top_topics:
            if d["period"] not in periods_set:
                periods_set[d["period"]] = {}
            periods_set[d["period"]][d["topic"]] = d["email_count"]

    periods = list(periods_set.keys())
    series = {}
    for t in top_topics:
        series[t] = [periods_set.get(p, {}).get(t, 0) for p in periods]

    fig, ax = plt.subplots()
    colors = plt.cm.Set3.colors[:top_n]
    bottom = [0] * len(periods)
    for i, t in enumerate(top_topics):
        ax.bar(range(len(periods)), series[t], bottom=bottom,
               label=t, color=colors[i % len(colors)], alpha=0.85)
        bottom = [b + s for b, s in zip(bottom, series[t])]

    ax.set_xticks(range(len(periods)))
    ax.set_xticklabels(periods, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Nombre d'emails")
    ax.set_title(title)
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()

    path = output_dir / "topic_evolution_chart.png"
    fig.savefig(str(path))
    plt.close(fig)
    return path


def tone_distribution_pie(tone_counts: Dict[str, int], output_dir: Path,
                          title: str = "Distribution des tons") -> Path:
    """Pie chart of tone category distribution."""
    _apply_style()

    labels = list(tone_counts.keys())
    sizes = list(tone_counts.values())

    fig, ax = plt.subplots(figsize=(7, 7))
    colors = plt.cm.Set2.colors[:len(labels)]
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.0f%%", startangle=90,
        colors=colors, pctdistance=0.85,
    )
    for t in autotexts:
        t.set_fontsize(8)
    ax.set_title(title)
    fig.tight_layout()

    path = output_dir / "tone_distribution_pie.png"
    fig.savefig(str(path))
    plt.close(fig)
    return path


def response_time_chart(data: Dict, output_dir: Path,
                        title: str = "Temps de réponse par période") -> Path:
    """Grouped bar chart: your vs their response times by period."""
    _apply_style()

    by_period = data.get("by_period", [])
    if not by_period:
        # Fallback: just show the summary
        fig, ax = plt.subplots(figsize=(6, 4))
        labels = ["Vous", "Ex-conjoint(e)"]
        avgs = [data["your_response"]["avg_hours"], data["their_response"]["avg_hours"]]
        ax.bar(labels, avgs, color=["#3b82f6", "#ef4444"], alpha=0.85)
        ax.set_ylabel("Heures (moyenne)")
        ax.set_title(title)
        fig.tight_layout()
        path = output_dir / "response_time_chart.png"
        fig.savefig(str(path))
        plt.close(fig)
        return path

    periods = [p["period"] for p in by_period]
    your_avgs = [p["your_avg"] for p in by_period]
    their_avgs = [p["their_avg"] for p in by_period]

    fig, ax = plt.subplots()
    x = range(len(periods))
    width = 0.35
    ax.bar([i - width / 2 for i in x], your_avgs, width,
           label="Vous", color="#3b82f6", alpha=0.85)
    ax.bar([i + width / 2 for i in x], their_avgs, width,
           label="Ex-conjoint(e)", color="#ef4444", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(periods, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Heures (moyenne)")
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()

    path = output_dir / "response_time_chart.png"
    fig.savefig(str(path))
    plt.close(fig)
    return path


# ───────────────────────── MANIPULATION CHARTS ───────────────────────────

_MANIP_SENT     = "#3b82f6"   # blue
_MANIP_RECEIVED = "#ef4444"   # red


def _thin_labels(labels: list, max_shown: int = 20) -> list:
    """Return labels with every Nth replaced by '' to avoid crowding."""
    n = len(labels)
    if n <= max_shown:
        return labels
    step = n // max_shown + 1
    return [lbl if i % step == 0 else "" for i, lbl in enumerate(labels)]


def manipulation_timeline_chart(data: list, output_dir: Path) -> Path:
    """Dual-line chart: avg manipulation score per period (sent vs received)."""
    _apply_style()

    sent_map:     dict = {}
    received_map: dict = {}
    for d in data:
        if d["direction"] == "sent":
            sent_map[d["period"]] = d["avg_score"]
        else:
            received_map[d["period"]] = d["avg_score"]

    all_periods = sorted(set(sent_map) | set(received_map))
    if not all_periods:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "Pas de données", ha="center", va="center",
                transform=ax.transAxes, color="gray")
        ax.set_title("Évolution du score de manipulation")
        path = output_dir / "manip_timeline.png"
        fig.savefig(str(path))
        plt.close(fig)
        return path

    x             = range(len(all_periods))
    sent_vals     = [sent_map.get(p, None) for p in all_periods]
    received_vals = [received_map.get(p, None) for p in all_periods]

    fig, ax = plt.subplots(figsize=(13, 5))

    if any(v is not None for v in sent_vals):
        xs = [i for i, v in zip(x, sent_vals) if v is not None]
        ys = [v for v in sent_vals if v is not None]
        ax.plot(xs, ys, color=_MANIP_SENT, linewidth=2.2, marker="o",
                markersize=4, label="Envoyés", zorder=3)
        ax.fill_between(xs, ys, alpha=0.08, color=_MANIP_SENT)

    if any(v is not None for v in received_vals):
        xs = [i for i, v in zip(x, received_vals) if v is not None]
        ys = [v for v in received_vals if v is not None]
        ax.plot(xs, ys, color=_MANIP_RECEIVED, linewidth=2.2, marker="o",
                markersize=4, label="Reçus", zorder=3)
        ax.fill_between(xs, ys, alpha=0.08, color=_MANIP_RECEIVED)

    ax.set_xticks(list(x))
    ax.set_xticklabels(_thin_labels(all_periods), rotation=45, ha="right", fontsize=8)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Score moyen de manipulation")
    ax.set_title("Évolution du score de manipulation dans le temps")
    ax.legend(loc="upper left")

    current_year = None
    for i, p in enumerate(all_periods):
        year = p[:4]
        if year != current_year and i > 0:
            ax.axvline(x=i - 0.5, color="#cccccc", linewidth=0.8, zorder=1)
        current_year = year

    fig.tight_layout()
    path = output_dir / "manip_timeline.png"
    fig.savefig(str(path))
    plt.close(fig)
    return path


def manipulation_pattern_freq_chart(data: list, output_dir: Path) -> Path:
    """Horizontal stacked bar: pattern frequency (sent vs received)."""
    _apply_style()

    if not data:
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.text(0.5, 0.5, "Pas de données", ha="center", va="center",
                transform=ax.transAxes, color="gray")
        ax.set_title("Fréquence des patterns de manipulation")
        path = output_dir / "manip_pattern_freq.png"
        fig.savefig(str(path))
        plt.close(fig)
        return path

    patterns    = [d["pattern"].replace("_", " ").title() for d in data]
    sent_counts = [d.get("sent", 0) for d in data]
    recv_counts = [d.get("received", 0) for d in data]

    fig, ax = plt.subplots(figsize=(10, max(4, len(patterns) * 0.55 + 1)))
    y = range(len(patterns))
    ax.barh(list(y), sent_counts, color=_MANIP_SENT, alpha=0.85, label="Envoyés")
    ax.barh(list(y), recv_counts, left=sent_counts, color=_MANIP_RECEIVED,
            alpha=0.85, label="Reçus")
    ax.set_yticks(list(y))
    ax.set_yticklabels(patterns, fontsize=9)
    ax.set_xlabel("Nombre d'emails")
    ax.set_title("Fréquence des patterns de manipulation détectés")
    ax.legend(loc="lower right")
    ax.invert_yaxis()
    fig.tight_layout()

    path = output_dir / "manip_pattern_freq.png"
    fig.savefig(str(path))
    plt.close(fig)
    return path


def manipulation_score_dist_chart(data: list, output_dir: Path) -> Path:
    """Stacked bar histogram: email count per score bucket (sent vs received)."""
    _apply_style()

    buckets     = [d["bucket"] for d in data]
    sent_counts = [d.get("sent", 0) for d in data]
    recv_counts = [d.get("received", 0) for d in data]

    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(buckets))
    ax.bar(list(x), sent_counts, color=_MANIP_SENT, alpha=0.85, label="Envoyés")
    ax.bar(list(x), recv_counts, bottom=sent_counts, color=_MANIP_RECEIVED,
           alpha=0.85, label="Reçus")
    ax.set_xticks(list(x))
    ax.set_xticklabels(buckets, rotation=30, ha="right", fontsize=9)
    ax.set_xlabel("Score de manipulation")
    ax.set_ylabel("Nombre d'emails")
    ax.set_title("Distribution des scores de manipulation")
    ax.legend()
    fig.tight_layout()

    path = output_dir / "manip_score_dist.png"
    fig.savefig(str(path))
    plt.close(fig)
    return path


def manipulation_patterns_time_chart(data: dict, output_dir: Path,
                                     direction: str = "") -> Path:
    """Stacked area chart: top-N pattern counts over time, optionally split by direction."""
    _apply_style()

    periods  = data.get("periods", [])
    patterns = data.get("patterns", [])
    rows     = data.get("data", [])

    dir_label = {"sent": "Envoyés", "received": "Reçus"}.get(direction, "Tous")
    title     = f"Patterns de manipulation — {dir_label} — % des emails scorés (top 5)"
    fname     = f"manip_patterns_time_{direction or 'all'}.png"

    if not periods or not patterns:
        fig, ax = plt.subplots(figsize=(13, 5))
        ax.text(0.5, 0.5, "Pas de données", ha="center", va="center",
                transform=ax.transAxes, color="gray")
        ax.set_title(title)
        path = output_dir / fname
        fig.savefig(str(path))
        plt.close(fig)
        return path

    palette = ["#ef4444", "#f59e0b", "#3b82f6", "#10b981",
               "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"]

    x       = range(len(periods))
    bottoms = [0.0] * len(periods)

    fig, ax = plt.subplots(figsize=(13, 5))
    for i, ptype in enumerate(patterns):
        counts = [float(row.get(ptype, 0)) for row in rows]
        label  = ptype.replace("_", " ").title()
        color  = palette[i % len(palette)]
        tops   = [b + c for b, c in zip(bottoms, counts)]
        ax.fill_between(list(x), bottoms, tops, alpha=0.72, color=color, label=label)
        ax.plot(list(x), tops, color=color, linewidth=0.6, alpha=0.5)
        bottoms = tops

    ax.set_xticks(list(x))
    ax.set_xticklabels(_thin_labels(periods), rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_ylabel("% des emails scorés")
    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=8, ncol=2)

    current_year = None
    for i, p in enumerate(periods):
        year = p[:4]
        if year != current_year and i > 0:
            ax.axvline(x=i - 0.5, color="#cccccc", linewidth=0.8, zorder=1)
        current_year = year

    fig.tight_layout()
    path = output_dir / fname
    fig.savefig(str(path))
    plt.close(fig)
    return path



# ─── Event type colours for procedure event markers ────────────────────────
_EVENT_MARKER_COLORS = {
    "conclusions_received": "#ef4444",   # red   — adverse conclusions
    "judgment":             "#7c3aed",   # purple
    "ordonnance":           "#f59e0b",   # amber
    "hearing":              "#3b82f6",   # blue
    "depot_conclusions":    "#10b981",   # green — own conclusions filed
    "assignation":          "#6366f1",   # indigo
}


def aggression_events_chart(
    tone_rows: List[Dict],
    procedure_events: List[Dict],
    output_dir: Path,
    date_from: Optional[str] = None,
    date_to:   Optional[str] = None,
) -> Path:
    """Monthly aggression/manipulation lines with procedure event markers.

    Args:
        tone_rows: output of tone_trends(conn, by='month'), may contain multiple
                   rows per period (one per direction). Aggregated here by period.
        procedure_events: list of dicts with event_date, event_type, procedure_name.
        date_from / date_to: if provided, zoom the x-axis to this range (YYYY-MM-DD).
    """
    _apply_style()

    # Aggregate tone_rows by period (combine sent + received)
    from collections import defaultdict
    agg: Dict[str, Dict] = defaultdict(lambda: {"agg_sum": 0.0, "manip_sum": 0.0, "cnt": 0})
    for r in tone_rows:
        period = r.get("period", "")
        if not period:
            continue
        cnt = r.get("count") or 0
        agg_val = r.get("avg_aggression") or 0.0
        manip_val = r.get("avg_manipulation") or 0.0
        agg[period]["agg_sum"]   += agg_val * cnt
        agg[period]["manip_sum"] += manip_val * cnt
        agg[period]["cnt"]       += cnt

    dates, agg_vals, manip_vals = [], [], []
    for period in sorted(agg.keys()):
        d = agg[period]
        if d["cnt"] == 0:
            continue
        try:
            dt = datetime.strptime(period + "-01", "%Y-%m-%d")
        except Exception:
            continue
        dates.append(dt)
        agg_vals.append(d["agg_sum"] / d["cnt"])
        manip_vals.append(d["manip_sum"] / d["cnt"])

    if not dates:
        fig, ax = plt.subplots(figsize=(14, 5))
        ax.text(0.5, 0.5, "No tone data available", ha="center", va="center",
                transform=ax.transAxes, color="#999")
        path = output_dir / "aggression_events.png"
        fig.savefig(str(path))
        plt.close(fig)
        return path

    fig, ax = plt.subplots(figsize=(14, 5))

    ax.plot(dates, agg_vals,   color="#ef4444", linewidth=1.8, label="Aggression",   alpha=0.9)
    ax.plot(dates, manip_vals, color="#f59e0b", linewidth=1.5, label="Manipulation", alpha=0.75,
            linestyle="--")
    ax.fill_between(dates, agg_vals, alpha=0.07, color="#ef4444")

    # Draw notable procedure event markers
    SHOW_TYPES = {"conclusions_received", "judgment", "ordonnance", "hearing"}
    seen_types: set = set()
    for ev in procedure_events:
        etype = ev.get("event_type", "")
        if etype not in SHOW_TYPES:
            continue
        try:
            dt = datetime.strptime(ev["event_date"][:10], "%Y-%m-%d")
        except Exception:
            continue
        color = _EVENT_MARKER_COLORS.get(etype, "#9ca3af")
        ax.axvline(mdates.date2num(dt), color=color, linewidth=0.8, alpha=0.45, zorder=2)
        seen_types.add(etype)

    # Build legend
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], color="#ef4444", linewidth=1.8, label="Aggression"),
        Line2D([0], [0], color="#f59e0b", linewidth=1.5, linestyle="--", label="Manipulation"),
    ]
    for etype in sorted(seen_types):
        color = _EVENT_MARKER_COLORS.get(etype, "#9ca3af")
        label = etype.replace("_", " ").title()
        handles.append(Line2D([0], [0], color=color, linewidth=1.2, alpha=0.7, label=label))
    ax.legend(handles=handles, loc="upper left", fontsize=7.5, ncol=2)

    ymax = max(max(agg_vals), max(manip_vals)) if agg_vals else 1.0
    ax.set_ylim(0, min(1.0, ymax * 1.3))
    ax.xaxis_date()

    # Zoom x-axis to requested date range
    if date_from or date_to:
        try:
            x_min = datetime.strptime(date_from, "%Y-%m-%d") if date_from else dates[0]
            x_max = datetime.strptime(date_to,   "%Y-%m-%d") if date_to   else dates[-1]
            ax.set_xlim(mdates.date2num(x_min), mdates.date2num(x_max))
            # Use monthly ticks when zoomed to ≤ 3 years
            span_years = (x_max - x_min).days / 365
            if span_years <= 3:
                ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
                ax.xaxis.set_minor_locator(mdates.MonthLocator())
                plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
            else:
                ax.xaxis.set_major_locator(mdates.YearLocator())
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
                ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
        except Exception:
            ax.xaxis.set_major_locator(mdates.YearLocator())
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
            ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    else:
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))

    ax.set_ylabel("Score (0–1)")
    title = "Aggression & Manipulation Over Time — with Legal Event Markers"
    if date_from or date_to:
        title += f"\n{date_from or '…'} → {date_to or 'now'}"
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="y", alpha=0.25)

    plt.tight_layout()
    path = output_dir / "aggression_events.png"
    fig.savefig(str(path), bbox_inches="tight")
    plt.close(fig)
    return path
