"""Markdown -> HTML rendering, optionally linking a project stylesheet."""
import re

import markdown

DEFAULT_PDF_MARGIN_MM = 5
PAGE_BREAK_MARKER = re.compile(r"^\s*<!--\s*md:page-break\s*-->\s*$", re.MULTILINE)


def render_body_html(markdown_text: str) -> str:
    markdown_text = PAGE_BREAK_MARKER.sub('<div class="page-break"></div>', markdown_text)
    return markdown.markdown(markdown_text, extensions=["extra", "sane_lists"])


def render_html(markdown_text: str, css_href: str | None = None, margin_mm: int = DEFAULT_PDF_MARGIN_MM) -> str:
    return _wrap_document(render_body_html(markdown_text), css_href=css_href, margin_mm=margin_mm)


def render_pages_html(
    markdown_texts: list[str],
    css_href: str | None = None,
    margin_mm: int = DEFAULT_PDF_MARGIN_MM,
) -> str:
    """Render multiple markdown documents, forcing each one onto its own PDF page."""
    pages = []
    for index, markdown_text in enumerate(markdown_texts):
        break_style = "" if index == 0 else " style=\"page-break-before: always;\""
        pages.append(f"<div{break_style}>{render_body_html(markdown_text)}</div>")
    return _wrap_document("\n".join(pages), css_href=css_href, margin_mm=margin_mm)


def render_shell_html(css_href: str | None = None, margin_mm: int = DEFAULT_PDF_MARGIN_MM) -> str:
    """A static page with an empty content placeholder, meant to be loaded once and then
    patched in place (via JS) as the user types, to avoid reload flicker in the live preview."""
    # A non-zero top padding stops the first heading's top margin from collapsing through
    # #md-content (which would otherwise clip its top when scrolled to the very top), and
    # padding-bottom adds breathing room at the end, since this is a screen preview, not print.
    spacer_style = "<style>#md-content { padding-top: 1em; padding-bottom: 8em; }</style>"
    return _wrap_document(
        f'<div id="md-content"></div>{spacer_style}', css_href=css_href, margin_mm=margin_mm
    )


def _wrap_document(body: str, css_href: str | None = None, margin_mm: int = DEFAULT_PDF_MARGIN_MM) -> str:
    page_style = f"<style>@page {{ margin: {margin_mm}mm; }}</style>"
    css_link = f'<link rel="stylesheet" href="{css_href}">' if css_href else ""
    image_style = "<style>img { max-width: 100%; height: auto; }</style>"
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">{page_style}{css_link}{image_style}</head>
<body>
{body}
</body>
</html>"""
