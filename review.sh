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
#   ./review.sh /projeto/dbt --only sqlfluff --keyfile ~/keys/projeto-xxx.json
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

if [[ "${1:-}" == -* ]]; then
    TARGET_INPUT=".."
else
    TARGET_INPUT="${1:-..}"
    if [[ $# -gt 0 ]]; then shift; fi
fi

TARGET="$(cd "$TARGET_INPUT" && pwd)"
export TARGET

# --keyfile: só a etapa sqlfluff usa (credencial de BigQuery pro templater
# dbt). Nunca é repassado pro Python dentro do container — vira volume
# montado num path fixo (ver docker-compose.yml), o container não sabe o
# caminho original no host.
KEYFILE_INPUT=""
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --keyfile)
            KEYFILE_INPUT="${2:-}"
            shift 2
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done
set -- "${ARGS[@]}"
if [[ -n "$KEYFILE_INPUT" ]]; then
    [[ -f "$KEYFILE_INPUT" ]] || { echo "Keyfile não encontrado: $KEYFILE_INPUT" >&2; exit 1; }
    export KEYFILE="$(cd "$(dirname "$KEYFILE_INPUT")" && pwd)/$(basename "$KEYFILE_INPUT")"
fi

docker compose build -q review

set +e
docker compose run --rm review --project "$(basename "$TARGET")" "$@"
CODE=$?
set -e

dashboard_up
exit $CODE
