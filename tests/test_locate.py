"""The locator is the only part that reads config syntax, so it gets the most
hostile tests. Each case is also crosschecked against git in
test_crosscheck.py, which is what actually proves the line is the right one.
"""

from __future__ import annotations

from unconsulted.locate import Lines, scan


def test_plain_file():
    assert scan("[core]\n\tautocrlf = true\n") == {"core.autocrlf": [2]}


def test_key_on_the_section_line():
    assert scan("[core] autocrlf = true\n") == {"core.autocrlf": [1]}


def test_section_reopened_keeps_both_lines_in_order():
    text = "[core]\n\tautocrlf = input\n[user]\n\tname = x\n[core]\n\tautocrlf = false\n"
    assert scan(text)["core.autocrlf"] == [2, 6]


def test_quoted_subsection_keeps_its_case():
    found = scan('[remote "Origin"]\n\turl = x\n')
    assert found == {"remote.Origin.url": [1 + 1]}


def test_dotted_subsection_is_lowercased_like_git_does():
    # [remote.Origin] and [remote.origin] are the same remote; the quoted form
    # of the same two are not. git lowercases only the dotted one.
    assert scan("[remote.Origin]\n\turl = x\n") == {"remote.origin.url": [2]}


def test_section_and_variable_case_folds():
    assert scan("[CORE]\n\tAutoCRLF = true\n") == {"core.autocrlf": [2]}


def test_comments_are_not_keys():
    text = "[core]\n\t# autocrlf = true\n\t; autocrlf = true\n\tautocrlf = false\n"
    assert scan(text) == {"core.autocrlf": [4]}


def test_trailing_comment_on_a_real_key():
    assert scan("[core]\n\tautocrlf = false ; and why\n") == {"core.autocrlf": [2]}


def test_continued_value_does_not_leak_a_key():
    # Line 3 looks like `name = ...` but is the tail of line 2's value.
    text = '[core]\n\texcludesfile = "/a \\\n\tname = not-a-key"\n'
    found = scan(text)
    assert found == {"core.excludesfile": [2]}


def test_value_with_no_equals_is_still_an_assignment():
    assert scan("[core]\n\tbare\n") == {"core.bare": [2]}


def test_keys_before_any_section_are_ignored():
    # git rejects such a file outright; not crashing is the whole requirement.
    assert scan("autocrlf = true\n[core]\n\tbare = false\n") == {"core.bare": [3]}


def test_hyphenated_key():
    assert scan("[alias]\n\trequest-pull = !x\n") == {"alias.request-pull": [2]}


def test_resolve_refuses_to_guess_when_the_count_disagrees(tmp_path):
    path = tmp_path / "config"
    # One assignment in the file, but git is said to have read two: something
    # about this file is beyond the scanner, so it declines to answer.
    path.write_text("[core]\n\tautocrlf = true\n")
    lines = Lines()
    assert lines.resolve(str(path), "core.autocrlf", 0, expected=1) == 2
    assert lines.resolve(str(path), "core.autocrlf", 0, expected=2) is None


def test_resolve_on_an_unreadable_file_is_quiet(tmp_path):
    assert Lines().resolve(str(tmp_path / "nope"), "core.autocrlf", 0, 1) is None


def test_relative_paths_resolve_against_the_given_base(tmp_path):
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "config").write_text("[core]\n\n\tautocrlf = true\n")
    assert Lines(str(tmp_path)).resolve("sub/config", "core.autocrlf", 0, 1) == 3
    # Without the base, the same relative path means something else entirely,
    # and answering would mean reading a different file.
    assert Lines().resolve("sub/config", "core.autocrlf", 0, 1) is None
