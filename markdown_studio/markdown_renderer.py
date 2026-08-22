"""Markdown -> HTML rendering, optionally linking a project stylesheet."""
import markdown

DEFAULT_PDF_MARGIN_MM = 5


def render_html(markdown_text: str, css_href: str | None = None, margin_mm: int = DEFAULT_PDF_MARGIN_MM) -> str:
    body = markdown.markdown(markdown_text, extensions=["extra", "sane_lists"])
    page_style = f"<style>@page {{ margin: {margin_mm}mm; }}</style>"
    css_link = f'<link rel="stylesheet" href="{css_href}">' if css_href else ""
    image_style = "<style>img { max-width: 100%; height: auto; }</style>"
    scroll_state_script = """
<script>
(function () {
    const key = "markdown_studio_preview_scroll";

    function getMaxX() {
        return Math.max(0, document.documentElement.scrollWidth - window.innerWidth);
    }

    function getMaxY() {
        return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    }

    function clamp(value, min, max) {
        return Math.min(max, Math.max(min, value));
    }

    function restoreScroll() {
        try {
            const saved = sessionStorage.getItem(key);
            if (!saved) return;
            const state = JSON.parse(saved);
            requestAnimationFrame(() => requestAnimationFrame(() => {
                const maxX = getMaxX();
                const maxY = getMaxY();

                const hasRelative = Number.isFinite(state.xr) || Number.isFinite(state.yr);
                if (hasRelative) {
                    const xr = Number.isFinite(state.xr) ? clamp(state.xr, 0, 1) : 0;
                    const yr = Number.isFinite(state.yr) ? clamp(state.yr, 0, 1) : 0;
                    window.scrollTo(xr * maxX, yr * maxY);
                    return;
                }

                // Backward-compatible fallback for older absolute snapshots.
                const x = Number.isFinite(state.x) ? clamp(state.x, 0, maxX) : 0;
                const y = Number.isFinite(state.y) ? clamp(state.y, 0, maxY) : 0;
                window.scrollTo(x, y);
            }));
        } catch (_err) {
            // Ignore malformed state and continue rendering.
        }
    }

    function saveScroll() {
        try {
            const maxX = getMaxX();
            const maxY = getMaxY();
            const xr = maxX > 0 ? window.scrollX / maxX : 0;
            const yr = maxY > 0 ? window.scrollY / maxY : 0;
            sessionStorage.setItem(
                key,
                JSON.stringify({
                    xr: clamp(xr, 0, 1),
                    yr: clamp(yr, 0, 1),
                    // Keep absolute values too in case relative data is unavailable.
                    x: window.scrollX,
                    y: window.scrollY,
                })
            );
        } catch (_err) {
            // Ignore storage errors and continue rendering.
        }
    }

    window.addEventListener("beforeunload", saveScroll);
    window.addEventListener("DOMContentLoaded", restoreScroll);
})();
</script>
"""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">{page_style}{css_link}{image_style}{scroll_state_script}</head>
<body>
{body}
</body>
</html>"""
