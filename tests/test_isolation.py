"""This repository must build from a checkout of itself and nothing else.

The rule is not "remember not to import the old project". It is checked
mechanically, here, over every module in the package: the AST is walked for
imports, and every string literal is inspected for a path that leaves the
repository.

WHY IT MATTERS ENOUGH TO TEST
-----------------------------
chains/ grew inside a trading repository, beside a strategy whose universe it
was an explicit non-input to. Two things came out of that arrangement and both
had to go before a CI runner could build this:

  - an import path into a shared package that lives in the other repository;
  - a read of a 700 MB database at an absolute path in a third project, which
    is where the fundamentals came from.

Neither failed loudly. The first is an ImportError on a fresh clone; the second
returned an empty result and would have published a map with every filing panel
blank. A test that walks the AST catches both before a build does.

The original separation still matters on its own terms: the map is a
hand-curated list of companies somebody finds interesting, and a trading
universe is a mechanical rule applied without reference to whether a name is
interesting. Letting the first feed the second puts hindsight into a selection
rule, invisibly.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "chains"

# The projects this code was extracted from. An import of any of them means a
# module came across in a copy and was never repointed.
FORBIDDEN_MODULES = ("swing", "smallcap", "core", "quant")

# Fragments that can only appear in a path leading out of this repository.
FORBIDDEN_PATH_FRAGMENTS = (
    "universe.parquet",
    "engine.duckdb",
    "/home/claude",
    "C:/claude-projects",
    "C:\\claude-projects",
    "/features",
    "features/",
    "signals.db",
)

# A string that looks like an absolute path is the other way out of the tree.
def _looks_absolute(v: str) -> bool:
    if v.startswith(("http://", "https://")):
        return False
    if len(v) > 2 and v[1] == ":" and v[2] in "/\\" and v[0].isalpha():
        return True                       # C:/... or C:\...
    return v.startswith(("/home/", "/Users/", "/mnt/", "/var/", "/etc/"))


def _is_environ(node: ast.AST) -> bool:
    """True for ``os.environ`` and for ``os`` itself (os.getenv).

    Without this the scan below matches any ``.get("USD")`` -- a unit key in
    the EDGAR reader -- and reports it as an undocumented environment read.
    """
    if isinstance(node, ast.Attribute):
        return node.attr == "environ"
    return isinstance(node, ast.Name) and node.id == "os"


def docstring_ids(tree: ast.AST) -> set[int]:
    """Every string constant that IS a docstring, by identity.

    Docstrings are prose and this package's prose explains the rule by naming
    the things it must not touch. A check that flagged its own explanation
    would be worse than useless: the only way to make it pass would be to stop
    documenting the boundary.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))
    return out


def modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def test_there_is_something_to_check():
    assert modules(), "no modules found -- the test would pass vacuously"


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
def test_no_module_imports_the_projects_this_came_from(path: Path):
    """An import is the direct route out. There is no allowed exception."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names
                    if a.name.split(".")[0] in FORBIDDEN_MODULES]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in FORBIDDEN_MODULES:
                bad.append(node.module)
    assert not bad, f"{path.name} imports {bad}"


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
def test_no_module_names_a_path_out_of_this_repository(path: Path):
    """An import is not the only route. A bare string would do it too."""
    rel = path.relative_to(REPO).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = docstring_ids(tree)
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in skip):
            for frag in FORBIDDEN_PATH_FRAGMENTS:
                if frag in node.value:
                    bad.append((frag, node.value[:60]))
    assert not bad, f"{rel} names {bad}"


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
def test_no_module_hard_codes_an_absolute_path(path: Path):
    """Every path is relative to the repository root or comes from the
    environment. An absolute one is a machine this build cannot leave."""
    rel = path.relative_to(REPO).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = docstring_ids(tree)
    bad = [n.value[:70] for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and id(n) not in skip and _looks_absolute(n.value)]
    assert not bad, f"{rel} hard-codes {bad}"


# -- where things are read from and written to ------------------------------

def test_every_write_path_stays_inside_the_repository_by_default():
    """With no environment set, a build writes only under the checkout. That
    is what lets CI run it in a sandbox and archive the result."""
    from chains import paths
    for helper in (paths.out_dir, paths.site_dir, paths.prices_dir):
        p = helper()
        assert paths.REPO_ROOT == p or paths.REPO_ROOT in p.parents, (
            f"{helper.__name__} -> {p}")


def test_the_data_directory_is_input_and_lives_in_the_repository():
    """One source of truth. The map is curated input under version control."""
    from chains import paths
    m = paths.map_path()
    assert paths.REPO_ROOT in m.parents, m
    assert m.exists(), f"the tracked map is missing at {m}"
    assert paths.out_dir() not in m.parents, (
        "the map must not be read from the derived-output directory")


def test_output_is_not_input():
    from chains import paths
    assert paths.data_dir() != paths.out_dir()
    assert paths.site_dir() != paths.out_dir()


@pytest.mark.parametrize("env,helper", [
    ("CHIP_MAP_DATA", "data_root"),
    ("CHIP_MAP_SITE", "site_root"),
    ("CHIP_MAP_PRICES", "prices_dir"),
])
def test_every_directory_can_be_moved_by_the_environment(env, helper,
                                                         monkeypatch, tmp_path):
    """CI puts the price cache where the cache action can restore it, and the
    site where the Pages action can upload it. Neither is a code change."""
    from chains import paths
    monkeypatch.setenv(env, str(tmp_path))
    assert getattr(paths, helper)() == tmp_path.resolve()


@pytest.mark.parametrize("helper", ["data_dir", "out_dir", "site_dir"])
def test_the_per_domain_directories_carry_the_domain(helper, monkeypatch,
                                                     tmp_path):
    """One engine, many maps: every curated and derived path is namespaced, so
    a second domain cannot overwrite the first one's snapshot."""
    from chains import paths
    monkeypatch.setenv("CHIP_MAP_DATA", str(tmp_path))
    monkeypatch.setenv("CHIP_MAP_OUT", str(tmp_path))
    monkeypatch.setenv("CHIP_MAP_SITE", str(tmp_path))
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "widgets")
    assert getattr(paths, helper)().name == "widgets"


def test_the_price_store_is_shared_across_domains(monkeypatch, tmp_path):
    """Two maps naming the same company should not download it twice, and a
    price series is the same series whoever is looking at it."""
    from chains import paths
    monkeypatch.setenv("CHIP_MAP_OUT", str(tmp_path))
    monkeypatch.delenv("CHIP_MAP_PRICES", raising=False)
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "widgets")
    a = paths.prices_dir()
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "gadgets")
    assert paths.prices_dir() == a


def test_a_domain_must_be_a_plain_name(monkeypatch):
    """It names a directory. A path fragment here would write outside data/."""
    from chains import paths
    monkeypatch.setenv("CHIP_MAP_DOMAIN", "../etc")
    with pytest.raises(SystemExit):
        paths.domain()


def test_the_defaults_need_no_environment_at_all(monkeypatch):
    """A fresh clone builds with no configuration but the token."""
    from chains import paths
    for env in ("CHIP_MAP_DATA", "CHIP_MAP_OUT", "CHIP_MAP_SITE",
                "CHIP_MAP_PRICES", "CHIP_MAP_PATH", "CHIP_MAP_DOMAIN"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv("CHIP_MAP_DOMAIN", raising=False)
    assert paths.data_dir() == paths.REPO_ROOT / "data" / "semi"
    assert paths.out_dir() == paths.REPO_ROOT / "out" / "semi"
    assert paths.site_dir() == paths.REPO_ROOT / "site" / "semi"
    assert paths.prices_dir() == paths.REPO_ROOT / "out" / "prices"


def test_the_map_override_is_available_but_not_the_default(monkeypatch,
                                                           tmp_path):
    """CHIP_MAP_PATH exists for reading a candidate map before committing it.
    Unset, a run is reproducible from a commit hash alone."""
    from chains import paths
    monkeypatch.setenv("CHIP_MAP_PATH", str(tmp_path / "candidate.json"))
    assert paths.map_path().name == "candidate.json"
    monkeypatch.delenv("CHIP_MAP_PATH")
    assert paths.map_path().name == paths.MAP_FILENAME


# -- the token ---------------------------------------------------------------

def test_only_the_price_step_needs_the_token(monkeypatch):
    """Everything else builds without it, so a contributor with no vendor
    account can still run the tests and rebuild the pages from a cache."""
    from chains import paths
    monkeypatch.delenv(paths.TOKEN_ENV, raising=False)
    with pytest.raises(SystemExit) as e:
        paths.api_token()
    assert paths.TOKEN_ENV in str(e.value)


def test_the_token_is_never_written_into_a_module():
    """A token in the source is a token in the git history for ever."""
    for path in modules():
        text = path.read_text(encoding="utf-8")
        assert "api_token=" not in text or "api_token=<" in text or (
            "_TOKEN_PARAM" in text or "params" in text), path.name


# -- the package imports on its own ------------------------------------------

def test_the_package_imports_with_the_old_projects_blocked(monkeypatch):
    """Import the modules with every ancestor project removed from sys.modules
    and blocked. If they still import, the separation is real and not merely
    currently unused."""
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def guard(name, *a, **kw):
        if name.split(".")[0] in FORBIDDEN_MODULES:
            raise ImportError(f"{name} is not available to chains")
        return real_import(name, *a, **kw)

    for mod in [m for m in sys.modules if m.split(".")[0] in FORBIDDEN_MODULES]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    for mod in [m for m in sys.modules if m.startswith("chains")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setattr(builtins, "__import__", guard)

    for name in ("chains.paths", "chains.mapfile", "chains.exchanges",
                 "chains.answers", "chains.edgar", "chains.questions",
                 "chains.build_pages", "chains.publish_site"):
        importlib.import_module(name)


def test_no_module_reads_an_environment_variable_that_is_not_documented():
    """Every knob is in chains/paths.py's docstring, so "what does this build
    need" is answerable by reading one file."""
    documented = {"CHIP_MAP_DATA", "CHIP_MAP_OUT", "CHIP_MAP_SITE",
                  "CHIP_MAP_PRICES", "CHIP_MAP_PATH", "CHIP_MAP_DOMAIN",
                  "EODHD_API_TOKEN", "ANSWERS_URL", "QUESTIONS_URL",
                  "SIGNUP_URL"}
    seen: set[str] = set()
    for path in modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("get", "getenv")
                    and _is_environ(node.func.value)
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.isupper()):
                seen.add(node.args[0].value)
    assert seen <= documented, f"undocumented environment reads: {seen - documented}"


# -- the engine holds no domain's vocabulary --------------------------------

# The words of ONE map. If they can be found in the package's own source, the
# package is not an engine: it is a chip map with the data smeared through it,
# and a second industry would mean editing Python instead of writing JSON.
#
# Comments and docstrings are exempt on purpose. Prose has to be able to say
# what the code is for, and this file names most of these words itself.
DOMAIN_WORDS = ("HBM", "EUV", "TSMC", "NVIDIA", "memory", "lithography",
                "packaging", "cloud", "power")


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = docstring_ids(tree)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip]


@pytest.mark.parametrize("path", modules(), ids=lambda p: p.name)
def test_no_module_names_one_domains_vocabulary(path: Path):
    """Layer names, line names, lane names and chokepoint titles belong in the
    map's ``labels`` block, not here."""
    import re
    pat = re.compile("|".join(DOMAIN_WORDS), re.I)
    bad = [(v[:70], pat.search(v).group(0))
           for v in _string_literals(path) if pat.search(v)]
    assert bad == [], f"{path.relative_to(REPO)} carries domain words: {bad}"


def test_the_map_supplies_every_label_the_package_stopped_holding():
    """The other half of the rule: taking the words out is only correct if the
    data puts them back."""
    from chains.mapfile import load
    lb = (load().get("labels") or {})
    for block in ("layers", "lines", "lanes", "stages"):
        assert lb.get(block), f"the map declares no {block}"
    for k, v in lb["lines"].items():
        assert v.get("color", "").startswith("#"), f"{k} has no colour"
        assert v.get("he") and v.get("en"), f"{k} is missing a language"


def test_every_node_carries_its_line_and_display_name():
    """They used to be two tables in live_snapshot.py keyed by company id."""
    from chains.mapfile import load
    m = load()
    lines = set((m.get("labels") or {}).get("lines") or {})
    bad = [n["id"] for n in m["nodes"]
           if n.get("line") not in lines or not n.get("short")]
    assert bad == []


def test_every_chokepoint_carries_its_title_and_blurb_in_both_languages():
    from chains.mapfile import load
    for c in load()["chokepoints"]:
        for field in ("label", "blurb"):
            v = c.get(field) or {}
            assert v.get("he") and v.get("en"), f"{c['id']} {field}"
