#!/usr/bin/env bash
# A plugin's translations in a form two pull requests merge (#452).
#
# `languages/*.pot` and `*.po` are written with no source references (the
# `#: file.php:123` lines, which move with any code), sorted by message and
# with no header a tool rewrites on every run (POT-Creation-Date and
# PO-Revision-Date hold one fixed date, X-Generator goes), so a pull request
# that adds strings changes only their lines; the
# compiled `*.mo` are never committed (a binary always conflicts): they are
# built when the plugin is packaged and before its suites start.
#
#   plugin-i18n.sh form
#       a .pot or .po on stdin, in that form on stdout (scripts/sync-repos.py
#       migrates a plugin with it, so the form is written once)
#   plugin-i18n.sh normalise <dir>
#       rewrite <dir>/languages/*.pot and *.po in that form (msgcat), in place
#   plugin-i18n.sh check <dir>
#       exit 1, naming each, when a .pot or .po is not in that form or a .mo
#       is committed (git ls-files, when <dir> is a checkout)
#   plugin-i18n.sh compile <dir>
#       write languages/<name>.mo from every languages/<name>.po (msgfmt)
#   plugin-i18n.sh --test
#
# A plugin regenerates its template with `wp i18n make-pot . languages/<slug>.pot
# --slug=<slug> --domain=<slug> --location=false` and its catalogues with
# `msgmerge --update --no-location --sort-output --no-wrap <po> <pot>`, then
# runs `normalise`. Needs gettext (msgcat, msgfmt).
set -euo pipefail

self=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")

STILL="1970-01-01 00:00+0000"

form() { # <file> (- for stdin): the file in the merging form, on stdout
  msgcat --no-location --sort-output --no-wrap "$1" | sed -E \
    -e "s/^\"(POT-Creation-Date|PO-Revision-Date): .*\\\\n\"\$/\"\\1: $STILL\\\\n\"/" \
    -e '/^"X-Generator: .*\\n"$/d'
}

catalogues() { # <dir>
  find "$1/languages" -maxdepth 1 -type f \( -name '*.po' -o -name '*.pot' \) 2>/dev/null | sort
}

normalise() {
  local f tmp
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    tmp=$(mktemp)
    form "$f" > "$tmp" && mv "$tmp" "$f"
    echo "normalised ${f#"$1"/}"
  done < <(catalogues "$1")
}

check() {
  local dir=$1 f fail=0 n=0 mo
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    n=$((n + 1))
    if ! diff -q <(form "$f") "$f" >/dev/null 2>&1; then
      echo "::error file=${f#"$dir"/}::Not in the form that merges (#452): no source references (#: lines), sorted by message, the header's dates fixed and no X-Generator. Run scripts/plugin-i18n.sh normalise from a checkout of DiluxOne/.github." >&2
      fail=1
    fi
  done < <(catalogues "$dir")
  if git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    while IFS= read -r mo; do
      [ -n "$mo" ] || continue
      echo "::error file=$mo::A compiled translation is committed: .mo files are built when the plugin is packaged (#452). Remove it and list languages/*.mo in .gitignore." >&2
      fail=1
    done < <(git -C "$dir" ls-files -- 'languages/*.mo')
  fi
  [ "$fail" -eq 0 ] && echo "Translations in the form that merges ($n file(s)), no .mo committed."
  return "$fail"
}

compile() {
  local po n=0
  shopt -s nullglob
  for po in "$1"/languages/*.po; do
    msgfmt --check -o "${po%.po}.mo" "$po"
    n=$((n + 1))
  done
  echo "Compiled $n catalogue(s)."
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  command -v msgcat >/dev/null || { echo "FAIL gettext (msgcat) is not installed"; exit 1; }
  t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
  ok()    { if "${@:2}" >/dev/null 2>&1; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
  fails() { if "${@:2}" >/dev/null 2>&1; then echo "FAIL $1"; fail=1; else echo "ok   $1"; fi; }
  mkdir -p "$t/p/languages"
  po() { # <file> <msgid> <msgstr> <msgid> <msgstr>
    printf 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n#: zeta.php:10\nmsgid "%s"\nmsgstr "%s"\n\n#: alpha.php:3\nmsgid "%s"\nmsgstr "%s"\n' "$2" "$3" "$4" "$5" > "$1"
  }
  po "$t/p/languages/my-es_ES.po" "Zebra" "Cebra" "Apple" "Manzana"
  fails "a .po with references and unsorted is refused" check "$t/p"
  ok    "normalise"                                   normalise "$t/p"
  ok    "then it passes"                              check "$t/p"
  ok    "no reference is left"                        bash -c "! grep -q '^#:' '$t/p/languages/my-es_ES.po'"
  got=$(grep '^msgid "[^"]' "$t/p/languages/my-es_ES.po" | tr '\n' '|')
  if [ "$got" = 'msgid "Apple"|msgid "Zebra"|' ]; then echo "ok   sorted by message"; else echo "FAIL sorted: $got"; fail=1; fi
  # Two branches that each add a string to the normalised file, where the
  # sorting puts them apart, merge with no conflict (strings that land in
  # the same place still meet, as any two edits of one line do).
  g() { git -c commit.gpgsign=false -c core.hooksPath=/dev/null -c user.name=t -c user.email=t@t "$@"; }
  (cd "$t/p" && g init -q -b base . && g add -A && g commit -qm base) >/dev/null 2>&1
  (cd "$t/p" && g checkout -qb one && printf '\nmsgid "Banana"\nmsgstr "Banana"\n' >> languages/my-es_ES.po && bash "$self" normalise . && g commit -qam one) >/dev/null 2>&1
  (cd "$t/p" && g checkout -q base && g checkout -qb two && printf '\nmsgid "Zulu"\nmsgstr "Zulú"\n' >> languages/my-es_ES.po && bash "$self" normalise . && g commit -qam two) >/dev/null 2>&1
  if (cd "$t/p" && g merge -q --no-edit one) >/dev/null 2>&1; then echo "ok   two pull requests adding strings merge with no conflict"; else echo "FAIL two pull requests adding strings conflict"; fail=1; fi
  # A tool rewrites the header's dates (and its own name) on every run: two
  # pull requests that regenerate the catalogue on different days still merge.
  mkdir -p "$t/q/languages"
  hpo() { # <date> <generator> <msgid> <msgstr>
    printf 'msgid ""\nmsgstr ""\n"POT-Creation-Date: %s\\n"\n"PO-Revision-Date: %s\\n"\n"X-Generator: %s\\n"\n"Content-Type: text/plain; charset=UTF-8\\n"\n\nmsgid "Apple"\nmsgstr "Manzana"\n\nmsgid "%s"\nmsgstr "%s"\n' "$1" "$1" "$2" "$3" "$4" > languages/my-es_ES.po
  }
  (cd "$t/q" && hpo "2026-10-01 09:00+0000" "Poedit 3.3" "Mango" "Mango" && bash "$self" normalise . && g init -q -b base . && g add -A && g commit -qm base) >/dev/null 2>&1
  (cd "$t/q" && g checkout -qb three && hpo "2026-10-25 10:00+0000" "Poedit 3.4" "Banana" "Banana" && printf '\nmsgid "Mango"\nmsgstr "Mango"\n' >> languages/my-es_ES.po && bash "$self" normalise . && g commit -qam three) >/dev/null 2>&1
  (cd "$t/q" && g checkout -q base && g checkout -qb four && hpo "2026-10-26 11:30+0000" "Loco" "Zulu" "Zulú" && printf '\nmsgid "Mango"\nmsgstr "Mango"\n' >> languages/my-es_ES.po && bash "$self" normalise . && g commit -qam four) >/dev/null 2>&1
  if (cd "$t/q" && g merge -q --no-edit three) >/dev/null 2>&1; then echo "ok   regenerated on different days, they still merge"; else echo "FAIL the header's dates conflict"; fail=1; fi
  ok    "the dates are the fixed one"                 grep -q "^\"PO-Revision-Date: $STILL" "$t/q/languages/my-es_ES.po"
  ok    "no X-Generator is left"                      bash -c "! grep -q '^\"X-Generator' '$t/q/languages/my-es_ES.po'"
  ok    "and that merge is in form"                   check "$t/q"
  ok    "form on stdin is the file's form"            bash -c "diff <(bash '$self' form < '$t/q/languages/my-es_ES.po') '$t/q/languages/my-es_ES.po'"
  ok    "and the merge is still in form"              check "$t/p"
  ok    "compile writes the .mo"                      compile "$t/p"
  ok    "the .mo is there"                            test -s "$t/p/languages/my-es_ES.mo"
  (cd "$t/p" && g add -f languages/my-es_ES.mo && g commit -qm mo) >/dev/null 2>&1
  fails "a committed .mo is refused"                  check "$t/p"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  form)      shift; [ $# -eq 0 ] || { echo "usage: plugin-i18n.sh form < file" >&2; exit 64; }; form - ;;
  normalise) shift; [ $# -eq 1 ] || { echo "usage: plugin-i18n.sh normalise <dir>" >&2; exit 64; }; normalise "$1" ;;
  check)     shift; [ $# -eq 1 ] || { echo "usage: plugin-i18n.sh check <dir>" >&2; exit 64; }; check "$1" ;;
  compile)   shift; [ $# -eq 1 ] || { echo "usage: plugin-i18n.sh compile <dir>" >&2; exit 64; }; compile "$1" ;;
  *) echo "usage: plugin-i18n.sh form | normalise|check|compile <dir> | --test" >&2; exit 64 ;;
esac
