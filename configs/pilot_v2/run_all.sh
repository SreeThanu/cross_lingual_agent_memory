#!/usr/bin/env bash
# Pilot v2 driver: 12 configs (3 frameworks x 4 directions), 3 seeds each.
# Run from the repo root inside tmux:   tmux new -s pilot 'bash configs/pilot_v2/run_all.sh'
# Needs Ollama, the Letta server and its Postgres running (OPEN_ISSUES §1.2).
#
# Writes runs/pilot_v2/manifest/ first (git SHA, config hashes, package versions),
# because the runner itself does not record them yet (AGENTS.md §12).
set -u
cd "$(dirname "$0")/../.."
PY=~/miniforge3/envs/xlmem/bin/python
OUT=runs/pilot_v2
mkdir -p "$OUT/manifest" "$OUT/logs"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ANONYMIZED_TELEMETRY=False MEM0_TELEMETRY=False PYTHONDONTWRITEBYTECODE=1

if [ -n "$(git status --porcelain -- xlmem configs data)" ]; then
  echo "Refusing to start: uncommitted changes in xlmem/, configs/ or data/." >&2
  exit 1
fi
git rev-parse HEAD > "$OUT/manifest/git_sha.txt"
sha256sum configs/pilot_v2/*.yaml data/facts_v1.yaml > "$OUT/manifest/inputs.sha256"
"$PY" -m pip freeze > "$OUT/manifest/pip_freeze.txt" 2>/dev/null
curl -s localhost:11434/api/tags > "$OUT/manifest/ollama_models.json"
curl -s localhost:8283/v1/health/ > "$OUT/manifest/letta_health.json"
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv > "$OUT/manifest/gpu_start.csv"
date -Is > "$OUT/manifest/started_at.txt"

: > "$OUT/logs/summary.txt"
for fw in mem0 letta amem; do
  for d in enen enhi hihi hien; do
    cfg="configs/pilot_v2/${fw}_${d}.yaml"
    start=$(date +%s)
    "$PY" -m xlmem.scripts.run --config "$cfg" > "$OUT/logs/${fw}_${d}.log" 2>&1
    status=$?
    echo "$(date -Is) ${fw}_${d} exit=${status} seconds=$(( $(date +%s) - start ))" | tee -a "$OUT/logs/summary.txt"
  done
done
date -Is > "$OUT/manifest/finished_at.txt"
echo "Pilot v2 finished. Summary: $OUT/logs/summary.txt"
