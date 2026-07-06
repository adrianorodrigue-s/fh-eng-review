#!/bin/bash
# Revisão de código para engenharias de dados (Ruff + Semgrep + Trivy).
#
# Uso:
#   ./review.sh                          # revisa a engenharia onde a lib está (pasta acima)
#                                        # e sobe o dashboard automaticamente
#   ./review.sh /caminho/da/engenharia   # revisa qualquer outra engenharia
#   ./review.sh dashboard                # sobe só o dashboard
#   ./review.sh down                     # derruba tudo (dashboard e containers)
#
# Flags extras vão direto para o runner:
#   ./review.sh . --only ruff semgrep
#   ./review.sh /outro/projeto --fail-fast
set -euo pipefail
cd "$(dirname "$0")"

PORT="${DASHBOARD_PORT:-3000}"

dashboard_up() {
    mkdir -p reports
    docker compose up -d dashboard >/dev/null 2>&1
    echo ""
    echo "📊 Dashboard no ar:  http://localhost:${PORT}"
    echo "   Quando terminar a análise:  ./review.sh down"
}

case "${1:-}" in
    down)
        docker compose down --remove-orphans
        echo "🛑 Ambiente de revisão encerrado."
        exit 0
        ;;
    dashboard)
        docker compose build -q dashboard
        dashboard_up
        exit 0
        ;;
esac

TARGET_INPUT="${1:-..}"
if [[ $# -gt 0 ]]; then shift; fi

TARGET="$(cd "$TARGET_INPUT" && pwd)"
export TARGET

docker compose build -q review

set +e
docker compose run --rm review --project "$(basename "$TARGET")" "$@"
CODE=$?
set -e

dashboard_up
exit $CODE
