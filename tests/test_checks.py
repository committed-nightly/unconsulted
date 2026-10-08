"""One test per check, plus the cases each check must stay quiet about.

The quiet ones matter more. A tool that tells you a working line is dead gets
uninstalled, and for `shadowed` in particular the only thing standing between
us and that is multivalue.py.
"""

from __future__ import annotations

from unconsulted.analyse import Options, analyse

# repo.write() prepends a two-line [core] section, so a line number in the
# text a test passes in is HEADER + that line.
HEADER = 2


def codes(repo, **kwargs) -> list[str]:
    opts = Options(**kwargs)
    return [f.code for f in analyse(cwd=str(repo.path), options=opts).findings]


def find(repo, code, **kwargs):
    opts = Options(**kwargs)
    return [f for f in analyse(cwd=str(repo.path), options=opts).findings if f.code == code]


# --- shadowed -------------------------------------------------------------


def test_a_second_value_shadows_the_first(repo):
    repo.write("[user]\n\temail = old@example.invalid\n\temail = new@example.invalid\n")
    (finding,) = find(repo, "shadowed")
    assert finding.key == "user.email"
    # The finding sits on the loser; the message names the winner a line later.
    assert finding.line == HEADER + 2
    assert ".git/config:5" in finding.message
    assert "new@example.invalid" in finding.message
    assert repo.git("config", "user.email").strip() == "new@example.invalid"


def test_shadowed_across_scopes(repo, tmp_path, monkeypatch):
    global_config = tmp_path / "global"
    global_config.write_text("[user]\n\temail = global@example.invalid\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    repo.write("[user]\n\temail = local@example.invalid\n")

    (finding,) = find(repo, "shadowed")
    assert finding.scope == "global"
    assert finding.file == str(global_config)
    assert finding.line == 2  # the global file has no prepended header


def test_identical_values_say_so(repo):
    repo.write("[user]\n\temail = same@example.invalid\n\temail = same@example.invalid\n")
    (finding,) = find(repo, "shadowed")
    assert "to the same value" in finding.message


def test_multi_valued_keys_are_not_shadowed(repo):
    # Two fetch refspecs is the normal shape of a remote, not a mistake.
    repo.write(
        '[remote "origin"]\n'
        "\turl = https://example.invalid/a.git\n"
        "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
        "\tfetch = +refs/tags/*:refs/tags/*\n"
    )
    assert "shadowed" not in codes(repo)


def test_the_credential_helper_reset_idiom_is_not_shadowed(repo):
    # Setting a helper to the empty string clears the list, then the real one
    # is added. Both lines are read. This is what `gh auth setup-git` writes,
    # so getting it wrong would make the tool noisy on a great many machines.
    repo.write(
        '[credential "https://github.com"]\n'
        "\thelper = \n"
        "\thelper = !/usr/bin/gh auth git-credential\n"
    )
    assert "shadowed" not in codes(repo)


def test_user_supplied_multi_valued_pattern_silences_it(repo):
    repo.write("[mytool]\n\tpath = a\n\tpath = b\n")
    assert "shadowed" in codes(repo)
    assert "shadowed" not in codes(repo, multi_valued=("mytool.path",))


# --- typo-key / undocumented-key ------------------------------------------


def test_a_one_character_typo_is_found_with_a_suggestion(repo):
    repo.write("[core]\n\tautocrfl = input\n")
    (finding,) = find(repo, "typo-key")
    assert "core.autocrlf" in finding.message
    assert finding.line == HEADER + 2


def test_a_key_git_does_not_document_but_does_read_is_not_a_typo(repo):
    # filter.<driver>.process and .required are documented in gitattributes(5)
    # and are absent from `git help --config`. Calling them typos would be
    # telling someone to delete a working git-lfs setup.
    repo.write(
        '[filter "lfs"]\n'
        "\tclean = git-lfs clean -- %f\n"
        "\tprocess = git-lfs filter-process\n"
        "\trequired = true\n"
    )
    assert codes(repo) == []


def test_undocumented_is_opt_in_and_then_finds_them(repo):
    repo.write('[filter "lfs"]\n\tprocess = git-lfs filter-process\n')
    assert codes(repo) == []
    assert codes(repo, include_undocumented=True) == ["undocumented-key"]


def test_another_tools_section_is_not_a_typo(repo):
    repo.write("[lfs]\n\turl = https://example.invalid/lfs\n[delta]\n\tnavigate = true\n")
    assert codes(repo) == []


def test_a_well_known_key_is_quiet(repo):
    repo.write("[core]\n\tautocrlf = input\n[init]\n\tdefaultBranch = main\n")
    assert codes(repo) == []


# --- dead-alias -----------------------------------------------------------


def test_an_alias_named_after_a_builtin_never_runs(repo):
    repo.write("[alias]\n\tcommit = !echo mine\n")
    (finding,) = find(repo, "dead-alias")
    assert "built into git" in finding.message


def test_an_alias_named_after_a_non_builtin_git_command_never_runs(repo):
    # git-request-pull is a script in git's exec path, not a builtin, and it
    # still wins. This is the case a builtins-only check would miss.
    repo.write("[alias]\n\trequest-pull = !echo mine\n")
    (finding,) = find(repo, "dead-alias")
    assert "shipped with git" in finding.message


def test_a_normal_alias_is_quiet(repo):
    repo.write("[alias]\n\tst = status -sb\n\tlg = log --oneline\n")
    assert codes(repo) == []


# --- includes -------------------------------------------------------------


def test_a_missing_include_is_found(repo):
    repo.write("[include]\n\tpath = ./nowhere.config\n")
    (finding,) = find(repo, "include-missing")
    assert finding.line == HEADER + 2
    # git itself says nothing and exits zero, which is the point.
    assert repo.git("config", "--list") != ""


def test_an_include_with_nothing_in_it_is_found(repo):
    (repo.path / ".git" / "empty.config").write_text("# just a comment\n")
    repo.write("[include]\n\tpath = ./empty.config\n")
    assert [f.code for f in find(repo, "include-empty")] == ["include-empty"]


def test_a_working_include_is_quiet(repo):
    (repo.path / ".git" / "work.config").write_text("[user]\n\temail = w@example.invalid\n")
    repo.write("[include]\n\tpath = ./work.config\n")
    assert codes(repo) == []
    assert repo.git("config", "user.email").strip() == "w@example.invalid"


def test_a_relative_include_resolves_from_the_including_file(repo):
    # Beside .git/config, not in the work tree. Proven by the work-tree copy
    # being ignored: if we resolved from the wrong base this would be quiet.
    (repo.path / "work.config").write_text("[user]\n\temail = wrong@example.invalid\n")
    repo.write("[include]\n\tpath = ./work.config\n")
    assert [f.code for f in find(repo, "include-missing")] == ["include-missing"]


def test_a_gitdir_condition_pointing_nowhere_is_found(repo, tmp_path):
    (repo.path / ".git" / "work.config").write_text("[user]\n\temail = w@example.invalid\n")
    repo.append(
        f'[includeIf "gitdir:{tmp_path}/not-a-directory/"]\n\tpath = ./work.config\n'
    )
    assert [f.code for f in find(repo, "includeif-no-such-dir")] == ["includeif-no-such-dir"]


def test_a_gitdir_condition_that_simply_does_not_match_here_is_quiet(repo, tmp_path):
    """Not matching the current repository is what conditional includes are for.

    The directory exists and holds other repositories; this one is not under
    it. Reporting that would make the tool unusable for anyone who separates
    work and personal identities, which is most people who use includeIf.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo.path / ".git" / "work.config").write_text("[user]\n\temail = w@example.invalid\n")
    repo.append(f'[includeIf "gitdir:{elsewhere}/"]\n\tpath = ./work.config\n')
    assert codes(repo) == []


def test_a_gitdir_condition_that_matches_is_quiet(repo):
    (repo.path / ".git" / "work.config").write_text("[user]\n\temail = w@example.invalid\n")
    repo.append(f'[includeIf "gitdir:{repo.path}/"]\n\tpath = ./work.config\n')
    assert codes(repo) == []
    assert repo.git("config", "user.email").strip() == "w@example.invalid"


# --- branches and remotes -------------------------------------------------


def test_a_branch_section_with_no_branch_is_found(repo):
    repo.commit()
    repo.append('[branch "gone"]\n\tmerge = refs/heads/main\n')
    (finding,) = find(repo, "stale-branch")
    assert "gone" in finding.message


def test_a_live_branch_section_is_quiet(repo):
    repo.commit()
    branch = repo.git("symbolic-ref", "--short", "HEAD").strip()
    repo.append(f'[branch "{branch}"]\n\tmerge = refs/heads/{branch}\n')
    assert "stale-branch" not in codes(repo)


def test_a_repository_with_no_branches_yet_is_not_accused(repo):
    # Nothing is checked out, so every branch section is technically
    # unconsulted and reporting it would be useless.
    repo.append('[branch "main"]\n\tmerge = refs/heads/main\n')
    result = analyse(cwd=str(repo.path))
    assert "stale-branch" not in [f.code for f in result.findings]
    assert any("no branches yet" in note for note in result.skipped)


def test_a_misspelled_remote_name_is_found(repo):
    repo.commit()
    repo.git("remote", "add", "origin", "https://example.invalid/a.git")
    branch = repo.git("symbolic-ref", "--short", "HEAD").strip()
    repo.append(f'[branch "{branch}"]\n\tremote = orgin\n')
    (finding,) = find(repo, "no-such-remote")
    assert "orgin" in finding.message


def test_a_remote_of_dot_or_a_url_is_quiet(repo):
    repo.commit()
    branch = repo.git("symbolic-ref", "--short", "HEAD").strip()
    repo.append(f'[branch "{branch}"]\n\tremote = .\n')
    assert "no-such-remote" not in codes(repo)
    repo.write(f'[branch "{branch}"]\n\tremote = https://example.invalid/a.git\n')
    assert "no-such-remote" not in codes(repo)
    repo.write(f'[branch "{branch}"]\n\tremote = git@example.invalid:a/b.git\n')
    assert "no-such-remote" not in codes(repo)


# --- case-split -----------------------------------------------------------


def test_two_remotes_differing_only_in_case(repo):
    repo.write(
        '[remote "Origin"]\n\turl = https://example.invalid/a.git\n'
        '[remote "origin"]\n\turl = https://example.invalid/b.git\n'
    )
    found = find(repo, "case-split")
    assert len(found) == 2
    assert {f.line for f in found} == {HEADER + 2, HEADER + 4}
    # git agrees these are two remotes, which is the proof.
    assert sorted(repo.git("remote").split()) == ["Origin", "origin"]


def test_the_dotted_form_is_one_remote_not_two(repo):
    # git lowercases a dotted subsection, so these merge rather than split.
    repo.write("[remote.Origin]\n\turl = a\n[remote.origin]\n\tfetch = +x:y\n")
    assert "case-split" not in codes(repo)
    assert repo.git("remote").split() == ["origin"]


def test_url_subsections_are_left_alone(repo):
    # git normalises credential URLs itself before matching, so two spellings
    # there are not two settings.
    repo.write(
        '[credential "https://Example.com"]\n\tusername = a\n'
        '[credential "https://example.com"]\n\tusername = b\n'
    )
    assert "case-split" not in codes(repo)


# --- whole-run behaviour --------------------------------------------------


def test_a_clean_config_finds_nothing(repo):
    repo.commit()
    repo.write(
        "[user]\n\tname = Someone\n\temail = someone@example.invalid\n"
        "[init]\n\tdefaultBranch = main\n[alias]\n\tst = status -sb\n"
    )
    assert analyse(cwd=str(repo.path)).findings == []


def test_scope_filter(repo, tmp_path, monkeypatch):
    global_config = tmp_path / "global"
    global_config.write_text("[core]\n\tautocrfl = input\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    repo.write("[core]\n\tpagger = less\n")

    assert len(codes(repo)) == 2
    assert codes(repo, scopes=("local",)) == ["typo-key"]
    assert [f.scope for f in find(repo, "typo-key", scopes=("global",))] == ["global"]
