#!/usr/bin/env bash
# Corrida programada del pipeline de intake. Uso: run_intake_cron.sh test|production
#
# - Un log por día y ambiente en cache/cron/ (se borran los de más de 30 días).
# - Código 75 = otra corrida tiene el candado: no es error, sale con 0.
# - Cualquier otro código distinto de 0 se devuelve tal cual, para que el
#   programador (cron u OpenClaw) lo marque como fallo.
set -u
ENV="${1:-}"
case "$ENV" in test|production) ;; *) echo "uso: $0 test|production" >&2; exit 2 ;; esac

SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
LOGDIR="$SCRIPTS/../cache/cron"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/intake-$ENV-$(date -u +%Y%m%d).log"
find "$LOGDIR" -name "intake-*.log" -mtime +30 -delete 2>/dev/null

{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) start ($ENV)"
  cd "$SCRIPTS" && python3 intake_pipeline.py --run-all --environment "$ENV" \
      --trigger-type cron --triggered-by cron
  rc=$?
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) exit $rc"
} >> "$LOG" 2>&1
rc=$(tail -1 "$LOG" | sed -n 's/.* exit \([0-9]*\)$/\1/p')
[ "$rc" = "75" ] && exit 0
exit "${rc:-1}"
