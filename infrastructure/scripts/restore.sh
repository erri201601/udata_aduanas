#!/usr/bin/env bash
# ADUANERO OS — restauración de un respaldo de PostgreSQL.
#
#   ./infrastructure/scripts/restore.sh                      lista los respaldos
#   ./infrastructure/scripts/restore.sh <archivo.dump>       restaura a una base
#                                                            desechable (seguro)
#   ./infrastructure/scripts/restore.sh <archivo> --en-vivo  SOBRESCRIBE aduanero
#
# Por defecto restaura a una base nueva, NO sobre la de producción. Para pisar
# la base real hay que pedirlo con --en-vivo y escribir una confirmación: es
# una operación destructiva y no debe poder ocurrir por un error de dedo.

set -Eeuo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESTINO="${ADUANERO_BACKUP_DIR:-$HOME/backups/aduanero}"

log()   { printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
morir() { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# Si la sesión aún no tiene cargado el grupo docker, reinvocar vía sg. `sg`
# ejecuta con /bin/sh, y `printf %q` sobre una cadena con saltos de línea genera
# comillas ANSI-C ($'...') que sh no entiende: revienta con "Syntax error".
# Por eso escribimos la orden a un script temporal con shebang de bash y le
# pasamos a sg sólo la ruta. Así no hay nada que citar.
NECESITA_SG=0
docker ps >/dev/null 2>&1 || NECESITA_SG=1
d() {
  if [ "$NECESITA_SG" -eq 0 ]; then
    docker "$@"
    return $?
  fi
  local guion rc
  guion="$(mktemp)"
  { printf '#!/usr/bin/env bash\n'; printf '%q ' docker "$@"; printf '\n'; } > "$guion"
  chmod +x "$guion"
  sg docker -c "$guion"
  rc=$?
  rm -f "$guion"
  return $rc
}

[ -f "$RAIZ/.env" ] || morir "falta $RAIZ/.env"
set -a; . "$RAIZ/.env"; set +a
: "${POSTGRES_DB:=aduanero}"
: "${POSTGRES_USER:=aduanero_app}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD no está en .env}"
CONTENEDOR_PG="aduanero-postgres"

# ── Sin argumentos: listar lo disponible ─────────────────────────────────────
if [ $# -eq 0 ]; then
  echo "Respaldos disponibles en $DESTINO:"
  echo
  find "$DESTINO" -name '*.dump' -printf '%TY-%Tm-%Td %TH:%TM  %8s  %p\n' 2>/dev/null \
    | sort -r | head -25 | awk '{printf "  %s %s  %6.1f MB  %s\n", $1, $2, $3/1048576, $4}'
  echo
  echo "Uso:  $0 <archivo.dump>              → restaura a una base desechable"
  echo "      $0 <archivo.dump> --en-vivo    → SOBRESCRIBE $POSTGRES_DB"
  exit 0
fi

ARCHIVO="$1"
[ -f "$ARCHIVO" ] || morir "no existe: $ARCHIVO"
EN_VIVO=0
[ "${2:-}" = "--en-vivo" ] && EN_VIVO=1

# ── Integridad antes de tocar nada ───────────────────────────────────────────
if [ -f "$ARCHIVO.sha256" ]; then
  (cd "$(dirname "$ARCHIVO")" && sha256sum -c "$(basename "$ARCHIVO").sha256" >/dev/null 2>&1) \
    && ok "Suma de verificación correcta" \
    || morir "el archivo no coincide con su .sha256 — está corrupto o alterado"
fi

d exec -i "$CONTENEDOR_PG" pg_restore --list < "$ARCHIVO" >/dev/null 2>&1 \
  || morir "no es un archivo válido de pg_restore"

# ── Destino ──────────────────────────────────────────────────────────────────
if [ "$EN_VIVO" -eq 1 ]; then
  BASE="$POSTGRES_DB"
  echo
  echo "  ⚠️  Vas a SOBRESCRIBIR la base '$BASE' del dev server."
  echo "      Todo lo que tenga ahora se pierde y se reemplaza por"
  echo "      $(basename "$ARCHIVO")"
  echo
  read -r -p "  Escribe SOBRESCRIBIR para continuar: " confirmacion
  [ "$confirmacion" = "SOBRESCRIBIR" ] || morir "cancelado"

  log "Respaldando el estado actual antes de pisarlo…"
  PREVIO="$DESTINO/diarios/pre_restauracion_$(date +%Y%m%d_%H%M%S).dump"
  mkdir -p "$(dirname "$PREVIO")"
  d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
      pg_dump -U "$POSTGRES_USER" -d "$BASE" --format=custom --compress=9 \
              --no-owner --no-privileges > "$PREVIO"
  ok "Estado previo guardado en $(basename "$PREVIO")"

  d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
    psql -U "$POSTGRES_USER" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
     WHERE datname='$BASE' AND pid <> pg_backend_pid();" >/dev/null
  d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
    psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $BASE;" >/dev/null
  d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
    psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $BASE;" >/dev/null
else
  BASE="aduanero_restaurada_$(date +%H%M%S)"
  log "Restaurando a la base desechable '$BASE' (no toca $POSTGRES_DB)"
  d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
    psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $BASE;" >/dev/null
fi

# ── Extensiones y esquemas antes del restore ─────────────────────────────────
d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
  psql -U "$POSTGRES_USER" -d "$BASE" >/dev/null <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS btree_gin;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS regulatory;
CREATE SCHEMA IF NOT EXISTS operational;
CREATE SCHEMA IF NOT EXISTS intelligence;
CREATE SCHEMA IF NOT EXISTS raw;
SQL

log "Restaurando…"
d exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
  pg_restore -U "$POSTGRES_USER" -d "$BASE" --no-owner --no-privileges \
  < "$ARCHIVO" >/dev/null 2>&1 || true   # avisos de objetos ya existentes

TABLAS=$(d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
  psql -U "$POSTGRES_USER" -d "$BASE" -tAc \
  "SELECT count(*) FROM information_schema.tables
   WHERE table_schema IN ('public','raw','regulatory','operational','intelligence')" | tr -d '[:space:]')

ok "Restauradas $TABLAS tablas en '$BASE'"

if [ "$EN_VIVO" -eq 0 ]; then
  echo
  echo "  Revísala y, cuando termines, bórrala:"
  echo "    docker exec -e PGPASSWORD=\$POSTGRES_PASSWORD aduanero-postgres \\"
  echo "      psql -U $POSTGRES_USER -d postgres -c 'DROP DATABASE $BASE;'"
fi
