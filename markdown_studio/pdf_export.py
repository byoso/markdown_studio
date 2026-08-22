"""HTML -> PDF export via WeasyPrint, single file or whole-project modes."""
from __future__ import annotations

from pathlib import Path

from weasyprint import HTML

from .markdown_renderer import render_html
from .project import Project


def export_single(project: Project, md_path: str | Path, pdf_path: str | Path | None = None) -> Path:
    md_path = Path(md_path)
    pdf_path = Path(pdf_path) if pdf_path is not None else md_path.with_suffix(".pdf")

    html = render_html(md_path.read_text(encoding="utf-8"), css_href=project.get_css_relative_path())
    HTML(string=html, base_url=str(project.path)).write_pdf(str(pdf_path))
    return pdf_path


def export_project(project: Project, pdf_path: str | Path) -> Path:
    pdf_path = Path(pdf_path)
    combined_markdown = "\n\n".join(
        path.read_text(encoding="utf-8") for path in project.list_markdown_files()
    )

    html = render_html(combined_markdown, css_href=project.get_css_relative_path())
    HTML(string=html, base_url=str(project.path)).write_pdf(str(pdf_path))
    return pdf_path
