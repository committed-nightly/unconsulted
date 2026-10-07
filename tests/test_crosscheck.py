"""Prove the locator against git, not against itself.

A unit test for the scanner only says the scanner does what I thought. These
take awkward config files, ask git what it read from them, ask the scanner
where each of those came from, and then read the line back out of the file to
check it really does assign that key. If the scanner has drifted from git's
parser, the line it points at will be the wrong one or there will be no line,
and both show up here.
"""

from __future__ import annotations

import re

import pytest

from unconsulted import oracle
from unconsulted.locate import Lines

AWKWARD = [
    pytest.param("[core] autocrlf = true\n", id="key-on-section-line"),
    pytest.param("[core]\n\tautocrlf = input\n[core]\n\tautocrlf = false\n", id="reopened"),
    pytest.param('[remote "Origin"]\n\turl = a\n[remote "origin"]\n\turl = b\n', id="case-split"),
    pytest.param("[remote.beta]\n\turl = b\n", id="dotted-subsection"),
    pytest.param('[core]\n\texcludesfile = "/a \\\n/b"\n', id="continued-value"),
    pytest.param("[core]\n\tautocrlf = false ; why\n", id="trailing-comment"),
    pytest.param("[CORE]\n\tAutoCRLF = TRUE\n", id="upper-case"),
    pytest.param("[alias]\n\trequest-pull = !x\n", id="hyphen"),
    pytest.param('[credential "https://example.com"]\n\thelper = \n', id="url-subsection"),
    pytest.param("[user]\n\tname = a\n\tname = b\n\tname = c\n", id="three-of-a-kind"),
    pytest.param('[core]\n\tbare\n', id="no-value"),
    pytest.param("[user]\n\tname = has = equals\n", id="equals-in-value"),
]


@pytest.mark.parametrize("text", AWKWARD)
def test_every_entry_git_read_gets_a_line_that_assigns_it(repo, text):
    repo.write(text)
    entries = oracle.config_entries(cwd=str(repo.path))
    assert entries, "git read nothing; the fixture is wrong, not the code"

    source = repo.config.read_text().splitlines()
    lines = Lines(str(repo.path))

    counts: dict[str, int] = {}
    for entry in entries:
        assert entry.file is not None
        total = sum(1 for o in entries if o.file == entry.file and o.key == entry.key)
        seen = counts.get(entry.key, 0)
        counts[entry.key] = seen + 1

        line = lines.resolve(entry.file, entry.key, seen, total)
        assert line is not None, f"no line found for {entry.key}"

        # The line we point at must actually assign the variable git named.
        variable = entry.key.rsplit(".", 1)[-1]
        text_at = source[line - 1]
        assert re.search(rf"\b{re.escape(variable)}\b", text_at, re.IGNORECASE), (
            f"{entry.key} attributed to line {line}, which is {text_at!r}"
        )


@pytest.mark.parametrize("text", AWKWARD)
def test_scanner_finds_exactly_as_many_assignments_as_git_read(repo, text):
    """The count check is what makes a wrong line impossible rather than rare.

    If these two ever disagree the tool reports no line number, which is the
    designed behaviour -- so this test is the one that tells us the designed
    behaviour is not silently the normal one.
    """
    repo.write(text)
    entries = oracle.config_entries(cwd=str(repo.path))
    from unconsulted.locate import scan

    found = scan(repo.config.read_text())
    for key in {e.key for e in entries}:
        git_count = sum(1 for e in entries if e.key == key)
        assert len(found.get(key, [])) == git_count, f"{key}: scanner disagrees with git"


def test_order_within_a_file_matches_gits_order(repo):
    repo.write("[user]\n\tname = first\n\tname = second\n\tname = third\n")
    entries = [e for e in oracle.config_entries(cwd=str(repo.path)) if e.key == "user.name"]
    assert [e.value for e in entries] == ["first", "second", "third"]

    lines = Lines(str(repo.path))
    located = [
        lines.resolve(e.file, e.key, i, len(entries)) for i, e in enumerate(entries)
    ]
    # 4, 5, 6 because the fixture prepends a two-line [core] section.
    assert located == [4, 5, 6]
    # And git returns the last one, which is the premise of the whole tool.
    assert repo.git("config", "user.name").strip() == "third"
