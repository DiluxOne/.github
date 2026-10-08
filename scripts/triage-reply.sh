#!/usr/bin/env bash
# The fixed replies of the triage when it read a paid add-on's private
# roadmap. An answer that could come from that roadmap (a paid, planned, new
# or by-design request) is never written by a model: it is this fixed text,
# in the issue's language. Any other answer is written by a second model run
# that never saw the roadmap; when that run fails, the plain text here is
# posted instead.
#
#   triage-reply.sh <category> <language>
#       prints the fixed reply; exit 0 when the category always gets it,
#       exit 1 (still printing the plain reply, the fallback) when it is
#       written without the roadmap
#   triage-reply.sh --test
set -euo pipefail

fixed() {
  case "$1:$2" in
    pro_feature:es) echo "¡Gracias por la sugerencia! Esto no está planeado para el plugin gratuito.";;
    pro_feature:pt) echo "Obrigado pela sugestão! Isso não está planejado para o plugin gratuito.";;
    pro_feature:*) echo "Thanks for the suggestion! This is not planned for the free plugin.";;
    planned:es) echo "¡Gracias por la sugerencia! Esto ya está planificado.";;
    planned:pt) echo "Obrigado pela sugestão! Isso já está planejado.";;
    planned:*) echo "Thanks for the suggestion! This is already planned.";;
    *:es) echo "¡Gracias! Un maintainer lo va a revisar.";;
    *:pt) echo "Obrigado! Um maintainer vai dar uma olhada.";;
    *) echo "Thanks! A maintainer will take a look.";;
  esac
}

reply() {
  fixed "$1" "$2"
  case "$1" in pro_feature|planned|enhancement|by_design) return 0 ;; *) return 1 ;; esac
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  t() {
    local name=$1 category=$2 language=$3 want=$4 wantcode=$5 got code
    got=$(reply "$category" "$language") && code=0 || code=1
    if [ "$got" = "$want" ] && [ "$code" = "$wantcode" ]; then echo "ok   $name"; else echo "FAIL $name: got \"$got\" ($code)"; fail=1; fi
  }
  t "a paid request gets the fixed text"        pro_feature en "Thanks for the suggestion! This is not planned for the free plugin." 0
  t "in Spanish when the issue is"              pro_feature es "¡Gracias por la sugerencia! Esto no está planeado para el plugin gratuito." 0
  t "a planned request, in Portuguese"          planned pt "Obrigado pela sugestão! Isso já está planejado." 0
  t "a new idea gets the plain text"            enhancement en "Thanks! A maintainer will take a look." 0
  t "an unknown language falls back to English" by_design other "Thanks! A maintainer will take a look." 0
  t "a bug report is written without the roadmap, with a fallback" needs_info es "¡Gracias! Un maintainer lo va a revisar." 1
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

[ $# -eq 2 ] || { sed -n '2,13p' "$0"; exit 64; }
reply "$1" "$2"
