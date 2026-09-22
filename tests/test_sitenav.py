"""The bar every page carries, and where it points once there is a choice.

One map: the bar is the pair it has always been, and every page on the site
renders it identically. Several maps: a page that belongs to the SITE leads to
the choice between them and to the record across them; a page that belongs to
a MAP keeps that map's own links and gains a way back out.
"""
from __future__ import annotations

from chains import sitenav


def _hrefs(links):
    return {key: href for key, _label, href in links}


def test_one_map_is_the_bar_it_always_was():
    assert sitenav.links("semi") == [
        ("map", sitenav.MAP_LABEL, "/semi/"),
        ("track", sitenav.TRACK_RECORD, "/semi/track/")]


def test_site_wide_makes_no_difference_with_one_map():
    """The flag says what KIND of page this is; with one map there is no
    choice to point at, so it changes nothing."""
    assert sitenav.links("semi") == sitenav.links("semi", site_wide=True)
    assert sitenav.html("semi", "home") == \
        sitenav.html("semi", "home", site_wide=True)


def test_a_site_wide_page_with_several_maps_points_at_the_choice():
    h = _hrefs(sitenav.links("semi", several=True, site_wide=True))
    assert h["map"] == sitenav.MAPS_ANCHOR == "#maps"
    assert h["track"] == "/track/"
    assert "/semi/" not in h.values()


def test_a_maps_own_page_keeps_its_own_record_and_gains_a_way_out():
    """A reader inside a chain wants that chain's record. What they did not
    have was any way back to the site that holds both."""
    links = sitenav.links("energy", several=True)
    h = _hrefs(links)
    assert h["all"] == "/"
    assert h["map"] == "/energy/"
    assert h["track"] == "/energy/track/"
    assert [k for k, _l, _u in links][0] == "all", "the way out comes first"


def test_the_bar_renders_every_item_it_is_given():
    html = sitenav.html("energy", "map", several=True)
    assert 'href="/"' in html and sitenav.ALL_MAPS in html
    assert 'href="/energy/track/"' in html


def test_several_maps_is_read_from_the_data_directory():
    """Not from what is published: a page is built before anything is, and
    the answer must not depend on which step is running."""
    from chains import domains
    assert sitenav.several_maps() == (len(domains.discover()) > 1)
