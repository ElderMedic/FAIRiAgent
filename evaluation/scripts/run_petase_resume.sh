#!/usr/bin/env bash
# Run a PETase batch to completion across service outages.
#
# Each round waits until the services named in the env file answer, then
# calls run_petase_parallel.py with --skip-done, so finished papers are
# never redone. The script stops when every selected paper has succeeded,
# or when a round completes no new paper (MAX_STALL rounds in a row) so a
# paper that always fails is reported instead of retried forever.
#
#   evaluation/scripts/run_petase_resume.sh --env path/to/ollama.env \
#       --overlay evaluation/config/production/qwen3.8-27b.overlay.env \
#       --out evaluation/runs/petase_batch_X/ollama --workers 2
#
# All arguments are passed to run_petase_parallel.py unchanged. Service
# URLs come from the env file (FAIRIFIER_LLM_BASE_URL, FAIR_DS_API_URL,
# MINERU_SERVER_URL); no port is assumed here.
set -u
cd "$(dirname "$0")/../.."
PYTHON="${PYTHON:-python}"
MAX_STALL="${MAX_STALL:-3}"
POLL_SECONDS="${POLL_SECONDS:-60}"

env_file="" out=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[i]}" in
    --env) env_file="${args[i+1]}" ;;
    --out) out="${args[i+1]}" ;;
  esac
done
[[ -n "$env_file" && -n "$out" ]] || { echo "usage: $0 --env FILE --out DIR [run_petase_parallel.py args]" >&2; exit 2; }

env_value() { grep -E "^$1=" "$env_file" | tail -1 | cut -d= -f2- | tr -d '"'"'"; }
endpoints=()
llm="$(env_value FAIRIFIER_LLM_BASE_URL)"; [[ -n "$llm" ]] && endpoints+=("${llm%/}/api/tags")
fairds="$(env_value FAIR_DS_API_URL)"; [[ -n "$fairds" ]] && endpoints+=("${fairds%/}/")
mineru="$(env_value MINERU_SERVER_URL)"; [[ -n "$mineru" ]] && endpoints+=("${mineru%/}/health")

services_up() {
  local url
  for url in "${endpoints[@]}"; do
    curl -s -m 5 -o /dev/null "$url" || return 1
  done
}

succeeded() {
  [[ -f "$out/run_status.jsonl" ]] || { echo 0; return; }
  "$PYTHON" -c 'import json,sys; print(len({json.loads(l)["instance_id"] for l in open(sys.argv[1]) if l.strip() and json.loads(l)["exit"] in (0, "skipped")}))' "$out/run_status.jsonl"
}

stall=0
while true; do
  until services_up; do
    echo "$(date '+%F %T') waiting for services: ${endpoints[*]}"
    sleep "$POLL_SECONDS"
  done
  before="$(succeeded)"
  echo "$(date '+%F %T') round start: $before papers done"
  "$PYTHON" evaluation/scripts/run_petase_parallel.py "$@" --skip-done
  after="$(succeeded)"
  remaining="$("$PYTHON" evaluation/scripts/run_petase_parallel.py "$@" --skip-done --dry-run 2>/dev/null | head -1 | grep -oE '^[0-9]+' || echo "?")"
  echo "$(date '+%F %T') round end: $after papers done, $remaining left"
  [[ "$remaining" == "0" ]] && { echo "all papers done"; exit 0; }
  # A round that ended because a service went down says nothing about the papers:
  # only a round that finished with the services up and no new paper counts as a stall.
  if ! services_up; then :
  elif (( after > before )); then stall=0
  else stall=$((stall + 1)); fi
  if (( stall >= MAX_STALL )); then
    echo "no paper completed in $MAX_STALL rounds; stopping (see $out/run_status.jsonl)" >&2
    exit 1
  fi
done
