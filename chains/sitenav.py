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
SUBSCRIBE_LABEL = "Get the key — subscribe to the weekly mail (free)"
# The embed is double opt-in: Substack sends a confirmation first, and only a
# confirmed reader gets the welcome email that carries the key.
SUBSCRIBE_CONFIRM = ("Confirm in the first email — the key arrives in the "
                     "welcome email right after.")
# The signup is a link out, not an embedded frame. Substack serves its embed as
# its own white page inside the iframe, and a cross-origin frame cannot be
# restyled from here, so on a dark page it landed as a white rectangle. A link
# carries the reader to the same form on Substack's own page, where the white
# belongs, and leaves this page dark all the way down.
SUBSCRIBE_CTA = "Subscribe on Substack →"

# Plausible: cookie-less page analytics, in the <head> of every public page and
# of nothing private. Site-specific but public -- it is in every page's source
# -- so it is defined once, here, and each public page's head takes it from
# here: the landing (chains/landing.py), both maps (build_pages.public_page)
# and the track page (chains/track.py). Kept verbatim.
ANALYTICS_ORIGIN = "https://plausible.io"
ANALYTICS = """<!-- Privacy-friendly analytics by Plausible -->
<script async src="https://plausible.io/js/pa-pY3vdi9LyMCXS_gJTVNhu.js"></script>
<script>
  window.plausible=window.plausible||function(){(plausible.q=plausible.q||[]).push(arguments)},plausible.init=plausible.init||function(i){plausible.o=i||{}};
  plausible.init()
</script>"""

# The only custom events. A name and nothing else: no props, so nothing about
# the reader, their email or their key can travel with one.
EVENTS = ("unlock_success", "subscribe_form_view")


def event_js(name: str) -> str:
    """The call for one event, safe on a page that does not carry Plausible."""
    if name not in EVENTS:
        raise ValueError(f"{name!r} is not one of the site's events {EVENTS}")
    return f"window.plausible&&plausible('{name}')"


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


def subscribe_link(url: str) -> str:
    """The publication's own page, from the embed URL the site is configured
    with. Only a trailing ``/embed`` is dropped -- no path is invented."""
    return url[: -len("/embed")] if url.endswith("/embed") else url


def subscribe_html(url: str | None) -> str:
    """The mail service's subscribe call under its one-line label, or nothing.

    Drawn on the landing and beside the track page's key field. With no URL it
    is the empty string -- not a placeholder, not a disabled link -- so a page
    built before the mail service exists makes no claim about a signup. Styled
    inline so an unconfigured page carries no trace of it, not even a class.
    """
    if not url:
        return ""
    label = _html.escape(SUBSCRIBE_LABEL, quote=True)
    return ('<div id="mailkey" style="margin:18px 0 0;max-width:480px">'
            '<p style="margin:0 0 2px;font-size:.95rem;color:#b3bccb">'
            f'{label}</p>'
            '<p style="margin:0 0 8px;font-size:.85rem;color:#7d8797">'
            f'{_html.escape(SUBSCRIBE_CONFIRM)}</p>'
            f'<a href="{_html.escape(subscribe_link(url), quote=True)}" '
            f'title="{label}" target="_blank" rel="noopener" '
            'style="display:block;box-sizing:border-box;width:100%;'
            'max-width:480px;padding:12px 16px;text-align:center;'
            'text-decoration:none;font-family:\'IBM Plex Mono\',monospace;'
            'font-size:.85rem;letter-spacing:.04em;border:1px solid #2d3a4d;'
            'border-radius:8px;background:#141a24;color:#e6ebf2">'
            f'{_html.escape(SUBSCRIBE_CTA)}</a>'
            # Once, when the call is drawn.
            f'<script>{event_js("subscribe_form_view")}</script></div>')


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
           "SUBSCRIBE_LABEL", "SUBSCRIBE_CONFIRM", "ANALYTICS",
           "ANALYTICS_ORIGIN", "EVENTS", "event_js", "links", "html",
           "subscribe_html", "CSS"]
