"""Markdown -> HTML rendering, optionally linking a project stylesheet."""
import markdown

DEFAULT_PDF_MARGIN_MM = 5


def render_html(markdown_text: str, css_href: str | None = None, margin_mm: int = DEFAULT_PDF_MARGIN_MM) -> str:
    body = markdown.markdown(markdown_text, extensions=["extra", "sane_lists"])
    page_style = f"<style>@page {{ margin: {margin_mm}mm; }}</style>"
    css_link = f'<link rel="stylesheet" href="{css_href}">' if css_href else ""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">{page_style}{css_link}</head>
<body>
{body}
</body>
</html>"""
