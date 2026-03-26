"""
Chart generation for reports using matplotlib.

All functions save a PNG to output_dir and return the Path.
Uses Agg backend (non-interactive).
"""
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List

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


def frequency_chart(data: List[Dict], output_dir: Path,
                    title: str = "Email Volume by Quarter") -> Path:
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
                     title: str = "Tone Evolution") -> Path:
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
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(axis="y", alpha=0.3)
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
