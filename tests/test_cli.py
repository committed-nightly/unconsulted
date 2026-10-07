from __future__ import annotations

import pytest

from unconsulted.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_clean_config_exits_zero(repo, capsys):
    repo.write("[user]\n\temail = someone@example.invalid\n")
    code, out, _ = run(capsys, "check", "-C", str(repo.path))
    assert code == 0
    assert "Nothing unconsulted" in out


def test_findings_exit_one(repo, capsys):
    repo.write("[core]\n\tautocrfl = input\n")
    code, out, _ = run(capsys, "check", "-C", str(repo.path))
    assert code == 1
    assert "typo-key" in out
    assert "1 line git does not consult." in out


def test_quiet_is_one_line_per_finding(repo, capsys):
    repo.write("[core]\n\tautocrfl = input\n\tpagger = less\n")
    code, out, _ = run(capsys, "check", "-C", str(repo.path), "-q")
    assert code == 1
    lines = out.strip().split("\n")
    assert len(lines) == 2
    for line, expected in zip(lines, (":4", ":5")):
        # file:line: code: message -- the shape an editor can jump to.
        assert line.split(": ")[0].endswith(expected)
        assert ": typo-key: " in line


def test_explain_shows_every_value_and_marks_the_winner(repo, capsys):
    repo.write("[user]\n\temail = first@example.invalid\n\temail = second@example.invalid\n")
    code, out, _ = run(capsys, "explain", "user.email", "-C", str(repo.path))
    assert code == 0
    assert "first@example.invalid" in out
    assert "second@example.invalid" in out
    # Exactly one arrow, on the last value.
    assert out.count("->") == 1
    assert out.index("->") > out.index("first@example.invalid")


def test_explain_an_unset_key_exits_one(repo, capsys):
    repo.write("")
    code, out, _ = run(capsys, "explain", "user.email", "-C", str(repo.path))
    assert code == 1
    assert "not set anywhere" in out


def test_explain_is_case_insensitive_like_git(repo, capsys):
    repo.write("[core]\n\tautocrlf = input\n")
    code, out, _ = run(capsys, "explain", "CORE.AutoCRLF", "-C", str(repo.path))
    assert code == 0
    assert "input" in out


def test_explain_distinguishes_an_empty_value_from_no_value(repo, capsys):
    repo.write("[core]\n\tbare\n")
    _, out, _ = run(capsys, "explain", "core.bare", "-C", str(repo.path))
    assert "no value" in out
    repo.write("[core]\n\tbare = \n")
    _, out, _ = run(capsys, "explain", "core.bare", "-C", str(repo.path))
    assert "no value" not in out
    assert "''" in out


def test_multi_valued_subcommand_lists_the_table(capsys):
    code, out, _ = run(capsys, "multi-valued")
    assert code == 0
    assert "remote.<name>.fetch" in out
    assert "credential.helper" in out


def test_a_bad_directory_exits_two(capsys, tmp_path):
    code, _, err = run(capsys, "check", "-C", str(tmp_path / "nope"))
    assert code == 2
    assert "unconsulted:" in err


def test_outside_a_repository_it_still_works_and_says_what_it_skipped(capsys, tmp_path, monkeypatch):
    global_config = tmp_path / "global"
    global_config.write_text("[core]\n\tautocrfl = input\n")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    plain = tmp_path / "plain"
    plain.mkdir()

    code, out, _ = run(capsys, "check", "-C", str(plain))
    assert code == 1
    assert "typo-key" in out
    assert "not in a git repository" in out


def test_no_subcommand_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
