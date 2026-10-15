#!/usr/bin/env bash
# What the organisation's VM is asked for (#154): runner-vm.yml's decisions,
# out of the workflow so they can be tested.
#
#   runner-demand.sh scan              every job of a private repository still
#                                      queued for a `diluxone` runner, one per
#                                      line: repository, queued at (ISO 8601),
#                                      the job's link (tab-separated);
#                                      exit 3 when GitHub did not answer
#   runner-demand.sh decide <power> <waiting>
#                                      what `auto` does with the VM's power
#                                      state and the number of jobs waiting
#                                      (`unknown` when the scan failed):
#                                      start, stay, deallocate-if-idle, nothing
#   runner-demand.sh long <minutes> <now>
#                                      of the scan's lines on stdin, those
#                                      queued more than <minutes> before <now>
#                                      (epoch seconds)
#   runner-demand.sh report <file>     keeps the issue "Jobs waiting for the
#                                      organisation's VM" in step with <file>,
#                                      the output of `long`: opened or updated
#                                      while a job waits that long, closed
#                                      when none does
#   runner-demand.sh --test            self-test
#
# Environment: `scan` OWNER and GH_TOKEN (actions: read on the organisation's
# repositories); `report` GITHUB_REPOSITORY, GH_TOKEN (issues: write here),
# LONG_MINUTES (15), RUN_URL (the run that writes it), DEMAND_DRY=1 prints
# the plan and changes nothing.
#
# The issue is public and the repositories private: it names each repository
# (repos.yml, public, already does) and links each job, which only members
# can open, and says nothing a repository holds: no job's name, no branch, no
# title.
set -euo pipefail

TITLE="Jobs waiting for the organisation's VM"

scan() {
  local repos repo status runs id
  repos=$(gh api --paginate "orgs/$OWNER/repos?type=private&per_page=100" --jq '.[] | select(.archived | not) | .name') || return 3
  for repo in $repos; do
    for status in queued in_progress; do
      runs=$(gh api --paginate "repos/$OWNER/$repo/actions/runs?status=$status&per_page=100" --jq '.workflow_runs[].id') || return 3
      for id in $runs; do
        gh api --paginate "repos/$OWNER/$repo/actions/runs/$id/jobs?filter=latest&per_page=100" \
          --jq ".jobs[] | select(.status == \"queued\" and (.labels | index(\"diluxone\"))) | [\"$repo\", .created_at, .html_url] | @tsv" || return 3
      done
    done
  done | sort -u
}

# Unsure (an API error) starts a VM that is off, but does not keep one on: it
# goes off only when idle, and the next run starts it again.
decide() {
  local state=$1 waiting=$2
  if [ "$state" != PowerState/running ] && { [ "$waiting" = unknown ] || [ "${waiting:-0}" -gt 0 ]; }; then echo start
  elif [ "$state" = PowerState/running ] && [ "$waiting" != unknown ] && [ "${waiting:-0}" -gt 0 ]; then echo stay
  elif [ "$state" = PowerState/running ]; then echo deallocate-if-idle
  else echo nothing; fi
}

# ISO 8601 (GitHub's, always UTC with a Z) to epoch seconds, with GNU date or
# BSD date.
epoch() { date -u -d "$1" +%s 2>/dev/null || date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "$1" +%s; }

long() {
  local minutes=$1 now=$2 repo queued url
  while IFS=$'\t' read -r repo queued url; do
    [ -n "$repo" ] || continue
    [ $(( (now - $(epoch "$queued")) / 60 )) -gt "$minutes" ] && printf '%s\t%s\t%s\n' "$repo" "$queued" "$url"
  done
  return 0
}

# The issue's body for the lines of `long` in $1, as of $2 (epoch seconds).
body() {
  local file=$1 now=$2 repo queued url since
  # shellcheck disable=SC2016 # backticks are Markdown here, not commands.
  printf 'These jobs have waited more than %s minutes for a `diluxone` runner, the organisation'"'"'s VM (`runner-vm.yml`), as of %s UTC:\n\n' "${LONG_MINUTES:-15}" "$(date -u -d "@$now" '+%Y-%m-%d %H:%M' 2>/dev/null || date -u -r "$now" '+%Y-%m-%d %H:%M')"
  printf '| Repository | Job | Waiting |\n| --- | --- | --- |\n'
  while IFS=$'\t' read -r repo queued url; do
    [ -n "$repo" ] || continue
    since=$(( (now - $(epoch "$queued")) / 60 ))
    printf '| %s | [%s](%s) | %s min, since %s |\n' "$repo" "${url##*/}" "$url" "$since" "$queued"
  done < "$file"
  # shellcheck disable=SC2016 # backticks are Markdown here, not commands.
  printf '\nA job waits when the VM is off and nothing started it: the pull request pipeline starts it (`runner-wake.yml`), and `runner-vm.yml` every ten minutes, when GitHub runs its schedule. Start it by hand from [the workflow](%s/%s/actions/workflows/runner-vm.yml) (`start`) if it is off. This issue is kept up to date and closes itself once no job waits that long.\n' "${GITHUB_SERVER_URL:-https://github.com}" "$GITHUB_REPOSITORY"
  [ -z "${RUN_URL:-}" ] || printf '\n<sub>runner-vm.yml · [the run](%s)</sub>\n' "$RUN_URL"
}

# What to do with the issue: $1 jobs waiting that long (yes or no), $2 the
# open issue's number, empty when there is none.
plan_report() {
  if [ "$1" = yes ] && [ -n "$2" ]; then echo update
  elif [ "$1" = yes ]; then echo open
  elif [ -n "$2" ]; then echo close
  else echo nothing; fi
}

report() {
  local file=$1 open waiting=no action out now
  [ -s "$file" ] && waiting=yes
  # Not --search: its index lags, and two runs close together would each
  # open one.
  open=$(gh issue list --repo "$GITHUB_REPOSITORY" --state open --limit 500 --json number,title --jq "[.[] | select(.title == \"$TITLE\")] | min_by(.number) | .number // empty")
  action=$(plan_report "$waiting" "$open")
  if [ "${DEMAND_DRY:-}" = 1 ]; then echo "would $action${open:+ #$open}"; return 0; fi
  now=${NOW:-$(date +%s)}
  out=$(mktemp)
  case "$action" in
    open)
      body "$file" "$now" > "$out"
      echo "Opened $(gh issue create --repo "$GITHUB_REPOSITORY" --title "$TITLE" --body-file "$out")." ;;
    update)
      body "$file" "$now" > "$out"
      gh issue edit "$open" --repo "$GITHUB_REPOSITORY" --body-file "$out" >/dev/null
      echo "Updated #$open." ;;
    close)
      gh issue close "$open" --repo "$GITHUB_REPOSITORY" --comment "No job waits more than ${LONG_MINUTES:-15} minutes for the VM now${RUN_URL:+ ([the run]($RUN_URL))}." >/dev/null
      echo "Closed #$open." ;;
    nothing) echo "No job waits more than ${LONG_MINUTES:-15} minutes." ;;
  esac
  rm -f "$out"
}

if [ "${1:-}" = "--test" ]; then
  fail=0
  export GITHUB_REPOSITORY=DiluxOne/.github
  is() { if [ "$2" = "$3" ]; then echo "ok   $1"; else printf 'FAIL %s\n  want: %s\n  got:  %s\n' "$1" "$3" "$2"; fail=1; fi; }
  # decide: what `auto` does.
  is "C1: off, a job waits: start" "$(decide PowerState/deallocated 1)" start
  is "C1: off, the scan failed: start" "$(decide PowerState/deallocated unknown)" start
  is "deallocating, a job waits: start (it waits the deallocation out)" "$(decide PowerState/deallocating 2)" start
  is "off, nothing waits: nothing" "$(decide PowerState/deallocated 0)" nothing
  is "on, a job waits: it stays on" "$(decide PowerState/running 3)" stay
  is "C3: on and nothing waits: off when idle, as before" "$(decide PowerState/running 0)" deallocate-if-idle
  is "C3: on, the scan failed: still off when idle" "$(decide PowerState/running unknown)" deallocate-if-idle
  # long: only what waited more than the minutes.
  now=$(epoch 2026-10-15T01:00:00Z)
  lines=$(printf 'alpha\t2026-10-15T00:07:00Z\thttps://github.com/DiluxOne/alpha/actions/runs/1/job/11\nbeta\t2026-10-15T00:50:00Z\thttps://github.com/DiluxOne/beta/actions/runs/2/job/22\ngamma\t2026-10-15T00:45:00Z\thttps://github.com/DiluxOne/gamma/actions/runs/3/job/33\n')
  is "C2: a job queued 53 minutes ago is listed, one of 10 is not" "$(long 15 "$now" <<<"$lines" | cut -f1 | tr '\n' ' ')" "alpha "
  is "C2: a job queued 15 minutes ago is more than 14, not more than 15" "$(long 14 "$now" <<<"$lines" | cut -f1 | tr '\n' ' ')" "alpha gamma "
  is "nothing waiting, nothing listed" "$(long 15 "$now" </dev/null)" ""
  # body: the run link, the repository, how long; nothing the repository holds.
  f=$(mktemp)
  printf 'alpha\t2026-10-15T00:07:00Z\thttps://github.com/DiluxOne/alpha/actions/runs/1/job/11\n' > "$f"
  b=$(RUN_URL=https://github.com/DiluxOne/.github/actions/runs/9 body "$f" "$now")
  is "C2: the body links the job" "$(grep -c '| \[11\](https://github.com/DiluxOne/alpha/actions/runs/1/job/11) |' <<<"$b")" 1
  is "C2: and says how long it waited" "$(grep -c '| alpha | .* | 53 min, since 2026-10-15T00:07:00Z |' <<<"$b")" 1
  is "the run that wrote it is linked" "$(grep -c 'runner-vm.yml · \[the run\](https://github.com/DiluxOne/.github/actions/runs/9)' <<<"$b")" 1
  is "the time is UTC" "$(grep -c 'as of 2026-10-15 01:00 UTC' <<<"$b")" 1
  # plan_report: one issue, kept up to date.
  is "C2: a long wait and no issue: open one" "$(plan_report yes "")" open
  is "C2: a long wait and an issue: update it" "$(plan_report yes 12)" update
  is "no long wait and an issue: close it" "$(plan_report no 12)" close
  is "no long wait and no issue: nothing" "$(plan_report no "")" nothing
  # report, against a stand-in for gh that answers the open issue and logs the rest.
  log=$(mktemp)
  gh() { if [ "$1 $2" = "issue list" ]; then jq -r "${12}" <<<"${GH_ISSUES:-[]}"; else echo "$1 $2 ${3:-}" >> "$log"; echo https://github.com/x/y/issues/7; fi; }
  mine='[{"number":3,"title":"Runner image"},{"number":14,"title":"Jobs waiting for the organisation'"'"'s VM"},{"number":12,"title":"Jobs waiting for the organisation'"'"'s VM"}]'
  : > "$log"; GH_ISSUES='[{"number":3,"title":"Runner image"}]' NOW=$now report "$f" >/dev/null
  is "report: opens the issue" "$(cut -d' ' -f1,2 "$log")" "issue create"
  : > "$log"; GH_ISSUES=$mine NOW=$now report "$f" >/dev/null
  is "report: edits the open one (the oldest), never a second" "$(cut -d' ' -f1-3 "$log")" "issue edit 12"
  : > "$f"; : > "$log"; GH_ISSUES=$mine report "$f" >/dev/null
  is "report: closes it when nothing waits that long" "$(cut -d' ' -f1-3 "$log")" "issue close 12"
  : > "$log"; report "$f" >/dev/null
  is "report: nothing to say, nothing written" "$(cat "$log")" ""
  is "report, dry: says the plan" "$(GH_ISSUES=$mine DEMAND_DRY=1 report "$f")" "would close #12"
  # scan, against a stand-in for gh: only queued jobs asking for `diluxone`, once each.
  gh() {
    case "$3" in
      orgs/*) printf 'alpha\n' ;;
      */runs\?status=queued*) printf '1\n' ;;
      */runs\?status=in_progress*) printf '1\n' ;; # moved between the two reads
      */jobs*) jq -r "$5" <<<'{"jobs":[
        {"status":"queued","labels":["self-hosted","linux","x64","diluxone"],"created_at":"2026-10-15T00:07:00Z","html_url":"https://github.com/DiluxOne/alpha/actions/runs/1/job/11","name":"Conventions"},
        {"status":"queued","labels":["ubuntu-latest"],"created_at":"2026-10-15T00:07:00Z","html_url":"u2","name":"Release"},
        {"status":"in_progress","labels":["diluxone"],"created_at":"2026-10-15T00:07:00Z","html_url":"u3","name":"Running"}]}' ;;
    esac
  }
  is "scan: the queued diluxone job, once" "$(OWNER=DiluxOne scan | cut -f1,3 | tr '\t' ' ')" "alpha https://github.com/DiluxOne/alpha/actions/runs/1/job/11"
  gh() { case "$3" in */jobs*) return 1 ;; orgs/*) echo alpha ;; *) echo 1 ;; esac; }
  is "scan: a jobs read that fails, inside the loop, is exit 3" "$(OWNER=DiluxOne scan >/dev/null; echo $?)" 3
  gh() { return 1; }
  is "scan: GitHub not answering is exit 3" "$(OWNER=DiluxOne scan >/dev/null; echo $?)" 3
  unset -f gh; rm -f "$f" "$log"
  [ "$fail" -eq 0 ] && echo "all tests passed"
  exit "$fail"
fi

case "${1:-}" in
  scan) scan ;;
  decide) decide "$2" "$3" ;;
  long) long "$2" "$3" ;;
  report) report "$2" ;;
  *) echo "usage: runner-demand.sh scan|decide|long|report|--test" >&2; exit 2 ;;
esac
