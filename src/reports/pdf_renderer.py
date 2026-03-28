"""
PDF renderer using weasyprint + Jinja2 HTML template.

Renders a Report structure to PDF via an HTML intermediate.

Requires system libraries (Pango, GObject, Cairo). Install on macOS:
    brew install pango
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from src.reports.builder import Report, ReportSection

_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Severity CSS class mapping
_SEV_CLASSES = {
    "high": "severity-high", "haute": "severity-high",
    "medium": "severity-medium", "moyenne": "severity-medium",
    "low": "severity-low", "basse": "severity-low",
}


def _render_section_html(section: ReportSection) -> str:
    """Recursively render a section to HTML string."""
    level = min(section.level + 1, 4)  # h2-h4 (h1 reserved for title)
    parts = [f"<h{level}>{_esc(section.title)}</h{level}>"]

    for para in section.paragraphs:
        parts.append(f"<p>{_esc(para)}</p>")

    if section.chart_path and section.chart_path.exists():
        # Use absolute file:// path for weasyprint
        abs_path = section.chart_path.resolve()
        parts.append(f'<img class="chart" src="file://{abs_path}" />')

    if section.table:
        parts.append("<table>")
        parts.append("<thead><tr>")
        for header in section.table["headers"]:
            parts.append(f"<th>{_esc(header)}</th>")
        parts.append("</tr></thead>")
        parts.append("<tbody>")
        for row in section.table["rows"]:
            parts.append("<tr>")
            for cell in row:
                cell_str = str(cell)
                css_class = _SEV_CLASSES.get(cell_str.lower().strip(), "")
                cls_attr = f' class="{css_class}"' if css_class else ""
                parts.append(f"<td{cls_attr}>{_esc(cell_str)}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")

    for sub in section.subsections:
        parts.append(_render_section_html(sub))

    return "\n".join(parts)


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_pdf(report: Report, output_path: Path) -> Path:
    """Render a Report structure to a PDF file.

    Raises OSError if weasyprint system dependencies are missing.
    """
    try:
        from weasyprint import HTML
    except OSError as e:
        raise OSError(
            "WeasyPrint requires system libraries (Pango, Cairo, GObject). "
            "Install on macOS with: brew install pango\n"
            f"Original error: {e}"
        ) from e

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=False,
    )

    # Register the recursive section renderer as a Jinja2 callable
    def render_section(section):
        return Markup(_render_section_html(section))

    env.globals["render_section"] = render_section

    template = env.get_template("report.html")
    html_content = template.render(report=report)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_content).write_pdf(str(output_path))
    return output_path
