"""The site's primary navigation, defined once for every page that carries it.

The landing page, the map and the track record all draw this bar, so the label
and the one-line promise under "Track Record" cannot drift apart between them.
The promise is a claim, and it is checked: tests/test_landing.py holds every
registered forecast to a commitment made before its answer date.
"""
from __future__ import annotations

import html as _html

BRAND = "Linchpin Signal"
MAP_LABEL = "Map"
TRACK_RECORD = "Track Record"
TRACK_RECORD_DESCRIPTOR = "Every forecast recorded before the answer."
SUBSCRIBE_LABEL = "Get the key: subscribe to the weekly mail (free)"


def links(dom: str) -> list[tuple[str, str, str]]:
    """``(key, label, href)`` for each item, in the order they are drawn."""
    return [("map", MAP_LABEL, f"/{dom}/"),
            ("track", TRACK_RECORD, f"/{dom}/track/")]


def html(dom: str, current: str | None = None) -> str:
    """The bar. ``current`` is "home", "map" or "track"."""
    home = ' aria-current="page"' if current == "home" else ""
    parts = [f'<nav class="sitenav" aria-label="Site">'
             f'<a class="home" href="/"{home}>{_html.escape(BRAND)}</a>']
    for key, label, href in links(dom):
        cur = ' aria-current="page"' if key == current else ""
        cls = ' class="rec"' if key == "track" else ""
        parts.append(f'<a{cls} href="{href}"{cur}>{_html.escape(label)}</a>')
        if key == "track":
            parts.append('<span class="navdesc">'
                         f'{_html.escape(TRACK_RECORD_DESCRIPTOR)}</span>')
    parts.append("</nav>")
    return "".join(parts)


def subscribe_html(url: str | None) -> str:
    """The mail service's subscribe form under its one-line label, or nothing.

    Drawn on the landing and beside the track page's key field. With no URL it
    is the empty string -- not a placeholder, not a disabled form -- so a page
    built before the mail service exists makes no claim about a signup. Styled
    inline so an unconfigured page carries no trace of it, not even a class.
    """
    if not url:
        return ""
    label = _html.escape(SUBSCRIBE_LABEL, quote=True)
    return ('<div id="mailkey" style="margin:18px 0 0;max-width:480px">'
            '<p style="margin:0 0 8px;font-size:.95rem;color:#b3bccb">'
            f'{label}</p>'
            f'<iframe src="{_html.escape(url, quote=True)}" title="{label}" '
            'width="480" height="150" loading="lazy" frameborder="0" '
            'scrolling="no" style="display:block;width:100%;max-width:480px;'
            'border:1px solid #222a36;border-radius:8px;background:#fff">'
            '</iframe></div>')


CSS = (".sitenav{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 18px;"
       "padding:12px 0;margin:0 0 14px;border-bottom:1px solid #222a36;"
       "font-family:'IBM Plex Mono',monospace;font-size:.72rem;"
       "letter-spacing:.1em;text-transform:uppercase}"
       ".sitenav a{color:#b3bccb;text-decoration:none}"
       ".sitenav a:hover{color:#e8ecf2}"
       ".sitenav a.home{color:#e8ecf2;font-weight:500;margin-inline-end:auto}"
       ".sitenav a[aria-current=page]{color:#e8ecf2}"
       ".sitenav a.rec{color:#f2b632;border:1px solid #3a3320;"
       "border-radius:5px;padding:3px 9px}"
       ".sitenav a.rec:hover{border-color:#f2b632}"
       ".sitenav .navdesc{text-transform:none;letter-spacing:0;"
       "font-family:Inter,system-ui,sans-serif;font-size:.8rem;color:#7d8797}")


__all__ = ["BRAND", "MAP_LABEL", "TRACK_RECORD", "TRACK_RECORD_DESCRIPTOR",
           "SUBSCRIBE_LABEL", "links", "html", "subscribe_html", "CSS"]
