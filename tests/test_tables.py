"""Tests for the two things the tool has to get right about git's own lists.

`known.py` builds a matcher out of `git help --config`; if the matcher is too
strict the typo check accuses working keys, and if it is too loose it finds
nothing. `multivalue.py` is the one hand-maintained table in the tool, so the
test here is that every entry in it is a key this git recognises -- which
catches a typo in the table, the failure mode that would silently switch off
a check.
"""

from __future__ import annotations

import re

import pytest

from unconsulted import oracle
from unconsulted.known import KeyIndex
from unconsulted.multivalue import MULTI_VALUED, reason


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
