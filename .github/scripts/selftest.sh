#!/bin/bash
# selftest.sh -- build the toy pipeline, sign off, change upstream code, and
# check that provenance moves passages ok -> pending -> changed. Runs in CI
# for the template repository; runs locally too (it restores what it edits).
#
# Usage (from the repository root): bash .github/scripts/selftest.sh
set -euo pipefail

prov() { python3 code/provenance/prov.py "$@"; }
state() { prov status --json | python3 -c "import json,sys; print({r['id']: r['state'] for r in json.load(sys.stdin)['passages']}['$1'])"; }
expect() {
  local got; got=$(state "$1")
  if [ "$got" != "$2" ]; then echo "FAIL: $1 is $got, expected $2"; prov status; exit 1; fi
  echo "ok: $1 is $2"
}

LOCK=products/paper/provenance.lock
SCRIPT=code/data/simulate_example.R
cp "$SCRIPT" /tmp/selftest_script.R
[ -f "$LOCK" ] && cp "$LOCK" /tmp/selftest_lock.json
restore() {
  cp /tmp/selftest_script.R "$SCRIPT"
  if [ -f /tmp/selftest_lock.json ]; then cp /tmp/selftest_lock.json "$LOCK"; else rm -f "$LOCK"; fi
  scons -k -Q > /dev/null || true
}
trap restore EXIT
rm -f "$LOCK"

bash setup.sh > /dev/null
scons -k -Q
prov lint
prov signoff --clean > /dev/null
expect sec:results-main ok
expect sec:strategy ok

# Change the data-generating step: nothing rebuilt yet, so downstream passages
# are pending, and the passage that declares the script is changed.
sed -i.bak 's/0.25 \* d\$treated/0.15 * d$treated/' "$SCRIPT" && rm -f "$SCRIPT.bak"
expect sec:results-main pending
expect sec:data changed
expect sec:strategy ok

# Rebuild: values and exhibits move, so their passages are changed.
scons -k -Q > /dev/null
expect sec:results-main changed
expect results-magnitude changed
prov status --all
prov tree sec:results-main
prov impact "$SCRIPT"
echo "self-test passed"
