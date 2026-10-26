def edit(p, old, new):
    s=open(p).read(); assert s.count(old)==1,(p,old[:60]); open(p,'w').write(s.replace(old,new))

f='scripts/changelog-fragments.sh'
edit(f,'''    sed -e 's/\\r$//' -e '/^[[:space:]]*$/d' "$1/changelog.d/$f"''','''    # One line each, whether or not the file ends in a newline.
    awk '{ sub(/\\r$/, "") } NF' "$1/changelog.d/$f"''')
edit(f,'''#   changelog-fragments.sh hand-edit <base-readme> <head-readme>''','''#   changelog-fragments.sh pull-request <base-readme> <head-dir>
#       the check of a pull request, its `git diff --name-status` against
#       its base on stdin: the release (it removes fragments and leaves none)
#       may write readme.txt's changelog; any other pull request gets
#       `hand-edit`
#   changelog-fragments.sh hand-edit <base-readme> <head-readme>''')
edit(f,'''if [ "${1:-}" = "--test" ]; then''','''pull_request() { # <base-readme> <head-dir>, the name-status on stdin
  if grep -qE '^D[[:space:]]+changelog\\.d/[0-9]+\\.md$' && ! any "$2"; then
    echo "This pull request removes the changelog fragments and leaves none: the release, which writes them into readme.txt."
    return 0
  fi
  hand_edit "$1" "$2/readme.txt"
}

if [ "${1:-}" = "--test" ]; then''')
edit(f,'''  printf '* CRLF.\\r\\n' > "$t/p/changelog.d/15.md"
  ok    "CRLF bullets"                             check "$t/p"
''','''  printf '* CRLF.\\r\\n' > "$t/p/changelog.d/15.md"
  ok    "CRLF bullets"                             check "$t/p"
  rm -f "$t/p/changelog.d/"*.md; printf '* No newline' > "$t/p/changelog.d/1.md"; printf '* Next.\\n' > "$t/p/changelog.d/2.md"
  got=$(collect "$t/p" | tr '\\n' '|')
  if [ "$got" = "* No newline|* Next.|" ]; then echo "ok   collect: a file with no final newline stays its own line"; else echo "FAIL collect: $got"; fail=1; fi
''')
edit(f,'''  [ "$fail" -eq 0 ] && echo "all tests passed"''','''  mkdir -p "$t/h/changelog.d"
  sed 's/^\\* Old\\.$/* Old.\\n* Written by the release./' "$t/base.txt" > "$t/h/readme.txt"
  pr() { printf '%s\\n' "$2" | pull_request "$t/base.txt" "$t/h" "$1"; }
  ok    "pull-request: the release removes every fragment and writes them in" pr x $'D\\tchangelog.d/9.md\\nM\\treadme.txt'
  printf '* Left.\\n' > "$t/h/changelog.d/10.md"
  fails "pull-request: removing one fragment and leaving another is no release" pr x $'D\\tchangelog.d/9.md\\nM\\treadme.txt'
  rm "$t/h/changelog.d/10.md"
  fails "pull-request: no fragment removed, the changelog edited by hand" pr x $'M\\treadme.txt'
  fails "pull-request: a file that is not a fragment removed is no release" pr x $'D\\tchangelog.d/notes.txt\\nM\\treadme.txt'
  cp "$t/base.txt" "$t/h/readme.txt"
  ok    "pull-request: an ordinary one with a fragment"  pr x $'A\\tchangelog.d/11.md'
  [ "$fail" -eq 0 ] && echo "all tests passed"''')
edit(f,'''  hand-edit) shift;''','''  pull-request) shift; [ $# -eq 2 ] || { echo "usage: changelog-fragments.sh pull-request <base-readme> <head-dir> < name-status" >&2; exit 64; }; pull_request "$1" "$2" ;;
  hand-edit) shift;''')
edit(f,'''  *) echo "usage: changelog-fragments.sh check|collect|any|hand-edit … | --test" >&2; exit 64 ;;''','''  *) echo "usage: changelog-fragments.sh check|collect|any|pull-request|hand-edit … | --test" >&2; exit 64 ;;''')

w='.github/workflows/plugin-checks-wp.yml'
edit(w,'''          if git diff --name-status --no-renames HEAD^1 HEAD -- changelog.d | grep -q '^D'; then
            echo "This pull request removes changelog fragments: the release, which writes them into readme.txt."; exit 0
          fi
          git show HEAD^1:readme.txt > "$RUNNER_TEMP/base-readme.txt" 2>/dev/null || : > "$RUNNER_TEMP/base-readme.txt"
          bash .dx-central/scripts/changelog-fragments.sh hand-edit "$RUNNER_TEMP/base-readme.txt" readme.txt''','''          git show HEAD^1:readme.txt > "$RUNNER_TEMP/base-readme.txt" 2>/dev/null || : > "$RUNNER_TEMP/base-readme.txt"
          git diff --name-status --no-renames HEAD^1 HEAD -- changelog.d \\
            | bash .dx-central/scripts/changelog-fragments.sh pull-request "$RUNNER_TEMP/base-readme.txt" .''')

t='tests/workflows/test_changelog_fragments_wiring.py'
edit(t,'''    assert "changelog-fragments.sh hand-edit" in run
    # Only the pull request that removes fragments (the release) writes them in.
    assert "grep -q '^D'" in run and run.index("grep -q '^D'") < run.index("hand-edit")''','''    # The decision (only the release writes readme.txt's changelog) is the
    # script's, tested there: the workflow hands it the diff against the base.
    assert "git diff --name-status --no-renames HEAD^1 HEAD -- changelog.d" in run
    assert "changelog-fragments.sh pull-request" in run''')

r='scripts/release-markers.sh'
edit(r,'''  if bash "$here/changelog-fragments.sh" any "$dir"; then
    bash "$here/changelog-fragments.sh" check "$dir" >/dev/null || return 1''','''  if bash "$here/changelog-fragments.sh" any "$dir"; then
    bash "$here/changelog-fragments.sh" check "$dir" >/dev/null || return 1
    grep -qx '== Changelog ==' "$dir/readme.txt" || { echo "::error file=readme.txt::No '== Changelog ==' section to write the changelog fragments into; they are kept." >&2; return 1; }''')
edit(r,'''  fails "#452 prepare: refuses a fragment that is not bullets" prepare "$t/p" 2.1.0 my-plugin.php MY_VERSION
''','''  fails "#452 prepare: refuses a fragment that is not bullets" prepare "$t/p" 2.1.0 my-plugin.php MY_VERSION
  tree 2.0.0 2.1.0 "Unreleased."; mkdir -p "$t/p/changelog.d"; printf '* Kept.\\n' > "$t/p/changelog.d/42.md"; sed -i 's/^== Changelog ==$/== Notes ==/' "$t/p/readme.txt"
  fails "#452 prepare: no changelog section to write them into" prepare "$t/p" 2.1.0 my-plugin.php MY_VERSION
  ok    "#452 prepare: and the fragment is kept"         test -f "$t/p/changelog.d/42.md"
''')

sy='scripts/sync-repos.py'
edit(sy,'''    listing = gh("api", f"repos/{full}/contents/languages?ref={default}", "--jq", ".[] | select(.type == \\"file\\") | .name", check=False)
    names = listing.stdout.split() if listing.returncode == 0 else []''','''    listing = gh("api", f"repos/{full}/contents/languages?ref={default}", "--jq", ".[] | select(.type == \\"file\\") | .name", check=False)
    if listing.returncode != 0 and "404" not in listing.stderr and "Not Found" not in listing.stderr:
        # A rate limit or a server error is not an empty languages/.
        raise RuntimeError(f"could not list languages/: {listing.stderr.strip()[:200]}")
    names = listing.stdout.split() if listing.returncode == 0 else []''')
