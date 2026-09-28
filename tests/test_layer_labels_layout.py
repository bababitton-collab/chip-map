"""No layer label breaks inside a word, at the widths the map is read at.

Item 6 allows two lines, a third if a name needs it, and the "E1 ·" prefix on
its own line -- but never a name cut through the middle of a word, and never a
smaller font to avoid one. The single exception it names is a word that is
wider than the line box by itself, which cannot be honoured any other way once
truncating and shrinking are both ruled out.

This is checked against a real layout because it is a fact about a real line
breaker: which break opportunities exist in "E6 · TRANSMISSION & HVDC", and
which of them the browser takes at 110px of text. The first version of this
code set overflow-wrap:anywhere, which is a break opportunity between every
pair of characters; that also collapses min-content to one character, so the
inline-block shrank to nothing and every label broke mid-word -- "E1 · FU/EL",
"GE/NERATIO/N". No string comparison would have noticed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.browser import Browser, Served, require

SITE = Path(__file__).resolve().parents[1] / "site"
WIDTHS = (1200, 1280, 1440)

# Per label: the characters of each line box, and every break classified.
SCRIPT = r"""
(() => {
  const chips = [...document.querySelectorAll('#layerbar .lchip, #l9bar .lchip')];
  function wordWidth(chip, word) {
    const clone = chip.cloneNode(true);
    clone.style.position = 'absolute';
    clone.style.visibility = 'hidden';
    clone.style.width = 'auto';
    clone.style.maxWidth = 'none';
    clone.style.whiteSpace = 'nowrap';
    const t = clone.querySelector('.t');
    if (t) t.textContent = word;
    // Removed rather than emptied: .s keeps margin:0 6px when it is empty,
    // which silently added 12px to every measurement.
    ['.n', '.s', '.vh'].forEach(sel => {
      const e = clone.querySelector(sel); if (e) e.remove();
    });
    clone.querySelectorAll('wbr').forEach(e => e.remove());
    document.body.appendChild(clone);
    const cs = getComputedStyle(chip);
    const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight)
              + parseFloat(cs.borderLeftWidth) + parseFloat(cs.borderRightWidth);
    const w = clone.getBoundingClientRect().width - pad;
    clone.remove();
    return w;
  }
  const out = chips.map(chip => {
    const walker = document.createTreeWalker(chip, NodeFilter.SHOW_TEXT);
    const chars = [];
    let node;
    while ((node = walker.nextNode())) {
      // The visually-hidden copy carries the plain word for assistive tech;
      // it is out of flow and is not part of the rendered line boxes.
      if (node.parentElement && node.parentElement.closest('.vh')) continue;
      const inName = !!(node.parentElement &&
                        node.parentElement.classList.contains('t'));
      for (let i = 0; i < node.data.length; i++) {
        const r = document.createRange();
        r.setStart(node, i); r.setEnd(node, i + 1);
        const box = r.getBoundingClientRect();
        chars.push({ch: node.data[i], top: Math.round(box.top),
                    width: box.width, inName});
      }
    }
    // Repair one degenerate rect before grouping. A soft hyphen that was USED
    // for a break renders as a hyphen and so has a width; an unused one is
    // zero-width. The single-character Range on the letter right AFTER a used
    // one reports the previous line's top with the new line's left and a
    // width spanning the rest of it -- so that letter looked like the last of
    // the old line instead of the first of the new one. It belongs to the
    // line its neighbours are on.
    for (let i = 1; i < chars.length; i++) {
      if (chars[i - 1].ch === '­' && chars[i - 1].width > 0
          && i + 1 < chars.length) {
        chars[i].top = chars[i + 1].top;
      }
    }
    const lines = [];
    chars.forEach(c => {
      const last = lines[lines.length - 1];
      if (!last || last.top !== c.top)
        lines.push({top: c.top, text: c.ch, firstInName: c.inName});
      else last.text += c.ch;
    });
    const cs = getComputedStyle(chip);
    const inner = parseFloat(cs.width) - parseFloat(cs.paddingLeft)
                - parseFloat(cs.paddingRight) - parseFloat(cs.borderLeftWidth)
                - parseFloat(cs.borderRightWidth);
    const breaks = [];
    for (let i = 1; i < lines.length; i++) {
      const raw = lines[i - 1].text, next = lines[i].text;
      if (/\s$/.test(raw) || /^\s/.test(next)) { breaks.push({kind: 'space'}); continue; }
      if (/[·]\s*$/.test(raw) && lines[i].firstInName) {
        breaks.push({kind: 'prefix'}); continue;
      }
      // A soft hyphen ends the line it was used on: the break is the one the
      // renderer put there on purpose, and the reader sees a hyphen.
      // The "E1 ·" prefix runs into the name with no space, so \S+ would take
      // it along. The word is what follows the separator.
      const drop = t => t.replace(/^.*·/, '').replace(/­/g, '');
      if (/­$/.test(raw)) {
        const before = drop((raw.replace(/­$/, '').match(/\S+$/) || [''])[0]);
        const after = (next.match(/^\S+/) || [''])[0];
        breaks.push({kind: 'shy', at: before + '|' + after,
                     word: before + after});
        continue;
      }
      const word = drop((raw.match(/\S+$/) || [''])[0])
                   + (next.match(/^\S+/) || [''])[0].replace(/­/g, '');
      breaks.push({kind: 'word', word,
                   wordWidth: Math.round(wordWidth(chip, word)),
                   inner: Math.round(inner)});
    }
    return {text: chip.textContent.replace(/\s+/g, ' ').trim(),
            plain: [...chip.querySelectorAll('.vh')].map(e => e.textContent),
            lines: lines.map(l => l.text), breaks};
  });
  return JSON.stringify(out);
})()
"""


@pytest.fixture(scope="module")
def measured():
    require()
    if not (SITE / "energy" / "index.html").is_file():
        pytest.skip("no build in site/ to measure")
    served = Served(SITE)
    browser = Browser()
    try:
        yield {w: json.loads(browser.measure(served.url("energy/"), w, 950,
                                             SCRIPT))
               for w in WIDTHS}
    finally:
        browser.close()
        served.close()


@pytest.mark.parametrize("width", WIDTHS)
def test_a_word_is_only_ever_broken_at_a_hyphen_the_renderer_chose(measured,
                                                                   width):
    """The rule. A break inside a word is allowed at a soft-hyphen position --
    where the reader sees a hyphen and the split lands between syllables --
    and nowhere else. A bare mid-word cut is a defect even when the word does
    not fit, because a soft hyphen is what the renderer is supposed to give it.
    """
    bad = []
    for label in measured[width]:
        for b in label["breaks"]:
            if b["kind"] != "word":
                continue
            bad.append(f"{width}px: '{b['word']}' cut with no hyphen "
                       f"({b['wordWidth']}px in a {b['inner']}px box); "
                       f"lines={label['lines']}")
    assert bad == [], "\n".join(bad)


@pytest.mark.parametrize("width", WIDTHS)
def test_transmission_breaks_only_between_its_two_halves(measured, width):
    """TRANSMISSION is the one name on these maps that cannot fit its column.
    Where it breaks, it breaks at TRANS|MISSION and nowhere else."""
    seen = [b for label in measured[width] for b in label["breaks"]
            if b["kind"] == "shy" and b["word"].upper() == "TRANSMISSION"]
    for b in seen:
        assert b["at"].upper() == "TRANS|MISSION", b
    if width in (1200, 1440):
        assert seen, f"TRANSMISSION does not fit at {width}px and should hyphenate"


def test_the_plain_word_is_what_assistive_tech_and_search_get(measured):
    """The soft hyphen is for the eye. Everything else -- the accessible name,
    find-in-page, the rail's search -- reads the word with no U+00AD in it."""
    for width in WIDTHS:
        for label in measured[width]:
            for plain in label["plain"]:
                assert "­" not in plain, (width, plain)
            if label["plain"]:
                assert any("TRANSMISSION" in p.upper() for p in label["plain"])


@pytest.mark.parametrize("width", WIDTHS)
def test_every_label_renders_something(measured, width):
    labels = measured[width]
    assert labels, f"no layer chips at {width}px"
    assert all(l["text"] for l in labels)


@pytest.mark.parametrize("width", WIDTHS)
def test_a_label_takes_at_most_three_lines(measured, width):
    """Two where possible, a third where a name needs it -- and no further:
    a fourth line means the column budget stopped being readable."""
    over = [(l["text"], l["lines"]) for l in measured[width]
            if len(l["lines"]) > 3]
    assert over == [], over


def test_a_name_that_fits_is_never_hyphenated(measured):
    """The soft hyphen is invisible until it is needed. At 1280 the column is
    wide enough for TRANSMISSION, and the label reads straight through."""
    shy = {w: [b["word"] for l in measured[w] for b in l["breaks"]
               if b["kind"] == "shy"]
           for w in WIDTHS}
    assert shy[1280] == [], f"1280 has room and should not hyphenate: {shy[1280]}"
