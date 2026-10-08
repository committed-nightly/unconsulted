"""Tests for the things the tool has to get right about its lists.

`known.py` builds a matcher out of `git help --config`; if the matcher is too
strict the typo check accuses working keys, and if it is too loose it finds
nothing. `multivalue.py` is the one hand-maintained table of git's behaviour
in the tool, so the test here is that every entry in it is a key this git
recognises -- which catches a typo in the table, the failure mode that would
silently switch off a check.

`report.py` carries a third list: which finding codes let the closing summary
say "git does not consult" outright. A code missing from it would be counted
into nothing and go unmentioned; a code in the wrong half of it would have the
summary overclaim, which is the bug this list was added to fix.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from unconsulted import analyse, oracle
from unconsulted.known import KeyIndex
from unconsulted.multivalue import MULTI_VALUED, reason
from unconsulted.report import _HEDGED, _UNCONSULTED, summary


@pytest.fixture(scope="module")
def index():
    return KeyIndex(oracle.known_config_keys())


# Keys that must be recognised. Anything here being reported as a typo would
# be the tool telling someone to break a working config.
@pytest.mark.parametrize(
    "key",
    [
        "core.autocrlf",
        "CORE.AUTOCRLF",  # git folds section and variable case
        "user.email",
        "init.defaultBranch",
        "init.defaultbranch",
        "alias.st",
        "alias.request-pull",
        "branch.main.remote",
        "branch.feature/long-name.merge",  # a slash in the subsection
        "remote.origin.url",
        "remote.origin.fetch",
        "submodule.libs.url",
        "credential.helper",
        "credential.https://github.com.helper",  # dots and colons in a URL
        "credential.https://github.com.useHttpPath",
        "url.git@github.com:.insteadOf",
        "http.https://example.com/.sslVerify",
        "diff.psd.textconv",
        "filter.lfs.clean",
        "merge.ours.driver",
        "safe.directory",
        "includeIf.gitdir:~/work/.path",
        "include.path",
    ],
)
def test_known_keys_are_recognised(index, key):
    assert index.knows_key(key), f"{key} should be recognised"


@pytest.mark.parametrize(
    "key",
    ["core.autocrfl", "user.emial", "init.defaultBrunch", "pull.rebse", "core.excludefile"],
)
def test_typos_are_not_recognised_and_get_a_suggestion(index, key):
    assert not index.knows_key(key)
    assert index.suggest(key) is not None


@pytest.mark.parametrize("key", ["lfs.url", "delta.navigate", "difftool.meld.cmd"])
def test_other_tools_sections(index, key):
    # The section is either not git's at all, or it is and the key is real.
    section = key.split(".", 1)[0]
    assert index.knows_section(section) == (section == "difftool")


def test_a_key_with_no_near_miss_gets_no_suggestion(index):
    assert index.suggest("core.wibbleflange") is None


def test_suggestions_stay_inside_the_section(index):
    # user.nmae should suggest user.name, never branch.<name>.
    assert index.suggest("user.nmae") == "user.name"


def test_every_multi_valued_entry_is_a_key_git_knows(index):
    """A typo in the table switches a check off silently. This catches it.

    Each pattern is turned into a concrete key first -- `remote.<name>.fetch`
    becomes `remote.anything.fetch` -- so it is tested the way a real key
    would be. A misspelled variable then matches nothing in git's list.
    """
    concrete = {key: re.sub(r"<[^>]+>", "anything", key) for key in MULTI_VALUED}
    unknown = [key for key, probe in concrete.items() if not index.knows_key(probe)]
    assert unknown == []


def test_multi_valued_matching_handles_placeholders():
    assert reason("remote.origin.fetch")
    assert reason("remote.my-fork.push")
    assert reason("credential.https://github.com.helper")
    assert reason("includeIf.gitdir:~/work/.path")
    assert reason("core.autocrlf") is None
    assert reason("user.email") is None


def test_user_patterns_are_reported_as_theirs():
    assert reason("mytool.path", extra=("mytool.path",)) == "--multi-valued mytool.path"
    assert reason("mytool.a.path", extra=("mytool.<n>.path",)).startswith("--multi-valued")


def test_the_table_cites_a_source_for_every_entry():
    for key, why in MULTI_VALUED.items():
        assert why.strip(), f"{key} has no provenance"


# --- the summary's claim table --------------------------------------------


def _codes_in_source() -> set[str]:
    """Every finding code analyse.py can emit, read out of its own source.

    Every Finding is built through the local `at()` helper, which takes the
    code as its second positional argument, always as a literal. Reading them
    from the AST rather than listing them here means a new check cannot be
    added without the table below being told about it -- a hand-written list
    would just be one more thing to forget.
    """
    tree = ast.parse(Path(analyse.__file__).read_text())
    return {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "at"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
    }


def test_every_finding_code_has_a_decided_claim():
    codes = _codes_in_source()
    assert codes, "found no at(e, <code>) calls in analyse.py -- has the helper moved?"
    classified = set(_UNCONSULTED) | set(_HEDGED)
    assert codes - classified == set(), "new check, nobody decided what the summary may claim"
    assert classified - codes == set(), "claim table names a code no check emits"


def test_a_code_in_neither_half_is_counted_but_not_described():
    """The unreachable branch, kept honest.

    If the test above ever fails, this is what the user gets in the meantime:
    counted, and no claim made about it.
    """
    unclassified = analyse.Finding(code="brand-new", message="m", key="k", scope="local")
    assert summary([unclassified]) == ["1 further finding above."]


def test_the_summary_agrees_with_itself_about_one_versus_many():
    one = analyse.Finding(code="typo-key", message="m", key="k", scope="local")
    assert summary([one]) == ["1 line git does not consult."]
    assert summary([one, one]) == ["2 lines git does not consult."]
    assert summary([]) == ["Nothing unconsulted. Every line in your git config is read."]
