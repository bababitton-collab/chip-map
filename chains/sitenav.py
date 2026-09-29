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
# What the same item is called, and where it goes, once there is more than one
# map: the choice between them rather than one of them.
MAPS_LABEL = "Maps"
MAPS_ANCHOR = "#maps"
# The way back out of a map, to the site that holds them all.
ALL_MAPS = "All maps"
TRACK_RECORD = "Track record"
# The bar carries the short claim; the rule itself carries conditions and
# belongs where they can be read -- the measurement method. It used to say
# "Only contracts committed before the answer count as preregistered", which
# is the rule, in a nav bar, on every page.
#
# Still not "every forecast recorded before the answer": one was not. orcl_q1
# was committed three days after its answer date and is labelled late wherever
# it appears. Neither line claims otherwise.
TRACK_RECORD_DESCRIPTOR = "Public contracts · Forward scored"
# The rule in full, stated once per page that explains the method, and never
# in the navigation.
PREREGISTRATION_RULE = (
    "A contract counts as preregistered only when it was committed before "
    "the answer date. Late commitments remain public and are excluded from "
    "preregistered results.")
SUBSCRIBE_LABEL = "Unlock upcoming questions"
# One vocabulary, used wherever the key is offered.
SUBSCRIBE_BODY = ("The maps and all resolved questions are public. A free "
                  "weekly key unlocks upcoming questions and their "
                  "registered baskets.")
# The embed is double opt-in: the mail service sends a confirmation first, and
# only a confirmed reader gets the welcome email that carries the key.
SUBSCRIBE_CONFIRM = ("Confirm your email. The key arrives in the welcome "
                     "message.")
# The signup is a link out, not an embedded frame. Substack serves its embed as
# its own white page inside the iframe, and a cross-origin frame cannot be
# restyled from here, so on a dark page it landed as a white rectangle. A link
# carries the reader to the same form on Substack's own page, where the white
# belongs, and leaves this page dark all the way down.
#
# The label says what the reader gets, not where the form lives. The
# destination is still that service; the button is not the place to name it.
SUBSCRIBE_CTA = "Get the free key"
# The footer's third clause used to read "Sources attached to every published
# measure". It is not true: 44 of semi's 136 subnode share rows carry no
# source, and energy's six carry none at all. What IS true is the rule the map
# already follows -- a figure with a source shows it, and one without is
# labelled an estimate.
FOOTER_NOTE = ("Supply-chain research, not investment advice · Sources shown "
               "where recorded; estimates labelled")

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


def links(dom: str, *, several: bool = False,
          site_wide: bool = False) -> list[tuple[str, str, str]]:
    """``(key, label, href)`` for each item, in the order they are drawn.

    ``several`` says the site serves more than one map; ``site_wide`` says
    this page belongs to the site rather than to one of them -- the front
    door and the pooled record.

    The two together are what stop the bar pointing at the first map as if it
    were the only one. On a site-wide page with several maps, "Map" leads to
    the choice between them and "Track Record" to the record across them;
    pointing either at /<first>/ would send a reader who arrived at the site
    into one industry without ever showing them there was another. On a map's
    own page the two stay that map's -- a reader inside a chain wants that
    chain's record -- and "All maps" is added as the way back out.

    With a single map every branch below collapses to the pair it always
    returned, so a one-map site is byte-for-byte the site it was.
    """
    if not several:
        return [("map", MAP_LABEL, f"/{dom}/"),
                ("track", TRACK_RECORD, f"/{dom}/track/")]
    if site_wide:
        return [("map", MAPS_LABEL, MAPS_ANCHOR),
                ("track", TRACK_RECORD, "/track/")]
    return [("all", ALL_MAPS, "/"),
            ("map", MAP_LABEL, f"/{dom}/"),
            ("track", TRACK_RECORD, f"/{dom}/track/")]


def several_maps() -> bool:
    """Does this site serve more than one map?

    Read from data/, which is the definition of a domain -- so a page built
    before anything is published still knows, and the answer cannot disagree
    with what the publish walk is about to do.
    """
    from chains import domains
    return len(domains.discover()) > 1


def html(dom: str, current: str | None = None, *,
         several: bool = False, site_wide: bool = False) -> str:
    """The bar. ``current`` is "home", "map" or "track"."""
    home = ' aria-current="page"' if current == "home" else ""
    parts = [f'<nav class="sitenav" aria-label="Site">'
             f'<a class="home" href="/"{home}>{_html.escape(BRAND)}</a>']
    for key, label, href in links(dom, several=several,
                                  site_wide=site_wide):
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
            '<p style="margin:0 0 4px;font-size:1rem;color:#e8ecf2;'
            'font-weight:500">'
            f'{label}</p>'
            '<p style="margin:0 0 6px;font-size:.92rem;color:#b3bccb;'
            'line-height:1.5">'
            f'{_html.escape(SUBSCRIBE_BODY)}</p>'
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
       "font-family:'IBM Plex Mono',monospace;font-size:.82rem;"
       "letter-spacing:.1em;text-transform:uppercase}"
       ".sitenav a{color:#b3bccb;text-decoration:none}"
       ".sitenav a:hover{color:#e8ecf2}"
       ".sitenav a.home{color:#e8ecf2;font-weight:500;margin-inline-end:auto}"
       ".sitenav a[aria-current=page]{color:#e8ecf2}"
       ".sitenav a.rec{color:#f2b632;border:1px solid #3a3320;"
       "border-radius:5px;padding:3px 9px}"
       ".sitenav a.rec:hover{border-color:#f2b632}"
       ".sitenav .navdesc{color:#7d8797;font-size:.72rem;letter-spacing:.14em}"
       # On a phone the four items competed for one row and the brand ended up
       # against the viewport edge. The trust line takes its own full-width
       # row, and the three that are links keep theirs.
       "@media (max-width:640px){"
       ".sitenav{gap:4px 14px;font-size:.74rem}"
       ".sitenav a.home{margin-inline-end:auto}"
       ".sitenav .navdesc{flex:0 0 100%;order:9;padding-top:6px;"
       "border-top:1px solid #222a36;margin-top:2px}"
       # 44px of target, without making the bar taller than it reads.
       ".sitenav a{display:inline-flex;align-items:center;min-height:44px}"
       "}")


__all__ = ["BRAND", "MAP_LABEL", "TRACK_RECORD", "TRACK_RECORD_DESCRIPTOR",
           "PREREGISTRATION_RULE", "FOOTER_NOTE",
           "SUBSCRIBE_LABEL", "SUBSCRIBE_BODY", "SUBSCRIBE_CONFIRM",
           "SUBSCRIBE_CTA", "ANALYTICS",
           "ANALYTICS_ORIGIN", "EVENTS", "event_js", "links", "html",
           "subscribe_html", "CSS"]
