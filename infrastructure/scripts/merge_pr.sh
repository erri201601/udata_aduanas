#!/usr/bin/env bash
# Mergea un PR sólo si los seis jobs del CI pasaron.
#
# Existe porque `develop` no se puede proteger: la protección de ramas en
# repositorios privados exige plan de pago, y este vive en una cuenta personal
# gratuita. Mientras eso no cambie, el botón de GitHub deja mergear en rojo.
#
# El 8 de septiembre pasó dos veces el mismo día:
#
#   · el #44 se mergeó con «Lint y formato» en FAILURE
#   · el #46 se mergeó con las seis comprobaciones sin arrancar siquiera
#
# En los dos casos el coste lo pagó quien abrió el siguiente PR, no quien lo
# introdujo: Persona 3 perdió una tarde persiguiendo un fallo que no era suyo.
#
# La idea es la de Persona 3 en el RAG: que el camino cómodo sea el seguro.
#
#   ./infrastructure/scripts/merge_pr.sh 47
#   make merge PR=47
set -euo pipefail

PR="${1:-}"
[ -n "$PR" ] || { echo "uso: $0 <número de PR>" >&2; exit 2; }

# Los seis jobs de .github/workflows/ci.yml. Si añades uno al workflow,
# añádelo aquí: un job que el CI corre y esta lista no conoce se mergearía sin
# mirarse, que es justo el agujero que este script tapa.
ESPERADOS=(
  "Lint y formato"
  "Tipos (mypy)"
  "Tests (Python 3.12)"
  "Migraciones reversibles"
  "Frontend"
  "Higiene del repositorio"
)

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
mal()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; }

echo "PR #$PR — $(gh pr view "$PR" --json title -q .title)"
echo

estado=$(gh pr view "$PR" --json statusCheckRollup \
  -q '.statusCheckRollup[] | "\(.name)\t\(.conclusion // "SIN-TERMINAR")"' 2>/dev/null || true)

fallos=0
for job in "${ESPERADOS[@]}"; do
  linea=$(printf '%s\n' "$estado" | awk -F'\t' -v j="$job" '$1==j {print $2; exit}')
  if [ -z "$linea" ]; then
    # Una comprobación que no existe todavía NO es una comprobación que pasó.
    # Este es exactamente el error que dejó pasar el #46.
    mal "$job: no ha arrancado"
    fallos=$((fallos + 1))
  elif [ "$linea" != "SUCCESS" ]; then
    mal "$job: $linea"
    fallos=$((fallos + 1))
  else
    ok "$job"
  fi
done

echo
if [ "$fallos" -gt 0 ]; then
  mal "$fallos de ${#ESPERADOS[@]} comprobaciones sin pasar. NO se mergea."
  echo
  echo "  Si aún están corriendo, espera y vuelve a ejecutarlo."
  echo "  Ver el detalle:  gh pr checks $PR"
  exit 1
fi

echo "Las ${#ESPERADOS[@]} en verde. Mergeando…"
gh pr merge "$PR" --merge --delete-branch
