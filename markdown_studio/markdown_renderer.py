"""Markdown -> HTML rendering, optionally linking a project stylesheet."""
import markdown

DEFAULT_PAGE_STYLE = "<style>@page { margin: 5mm; }</style>"


def render_html(markdown_text: str, css_href: str | None = None) -> str:
    body = markdown.markdown(markdown_text, extensions=["extra", "sane_lists"])
    css_link = f'<link rel="stylesheet" href="{css_href}">' if css_href else ""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">{DEFAULT_PAGE_STYLE}{css_link}</head>
<body>
{body}
</body>
</html>"""
