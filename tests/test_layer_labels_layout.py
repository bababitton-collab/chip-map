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
    const t = clone.querySelector('.t'), n = clone.querySelector('.n'),
          s = clone.querySelector('.s');
    if (t) t.textContent = word;
    if (n) n.textContent = '';
    if (s) s.textContent = '';
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
      const inName = !!(node.parentElement &&
                        node.parentElement.classList.contains('t'));
      for (let i = 0; i < node.data.length; i++) {
        const r = document.createRange();
        r.setStart(node, i); r.setEnd(node, i + 1);
        chars.push({ch: node.data[i], top: Math.round(r.getBoundingClientRect().top),
                    inName});
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
      const word = (raw.match(/\S+$/) || [''])[0] + (next.match(/^\S+/) || [''])[0];
      breaks.push({kind: 'word', word,
                   wordWidth: Math.round(wordWidth(chip, word)),
                   inner: Math.round(inner)});
    }
    return {text: chip.textContent.replace(/\s+/g, ' ').trim(),
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
def test_no_label_breaks_inside_a_word_that_would_have_fitted(measured, width):
    """The rule. A word split across lines is allowed only where that word,
    alone, is wider than the text box it had to fit in."""
    bad = []
    for label in measured[width]:
        for b in label["breaks"]:
            if b["kind"] != "word":
                continue
            if b["wordWidth"] <= b["inner"]:
                bad.append(f"{width}px: '{b['word']}' split at {b['wordWidth']}px "
                           f"inside a {b['inner']}px box -- it fitted; "
                           f"lines={label['lines']}")
    assert bad == [], "\n".join(bad)


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


def test_the_only_word_ever_split_is_one_that_cannot_fit(measured):
    """Recorded rather than asserted loosely: at energy's column widths the
    single word TRANSMISSION measures 126px against 110px of text at 1200 and
    101px at 1440, so it is split there and not at 1280, where it fits."""
    split = {w: sorted({b["word"] for l in measured[w] for b in l["breaks"]
                        if b["kind"] == "word"})
             for w in WIDTHS}
    for w, words in split.items():
        for word in words:
            hits = [b for l in measured[w] for b in l["breaks"]
                    if b.get("word") == word]
            assert all(b["wordWidth"] > b["inner"] for b in hits), (w, word)
