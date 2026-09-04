#!/usr/bin/env bash
# ADUANERO OS — respaldo de la base compartida y del landing RAW.
#
#   ./infrastructure/scripts/backup.sh            respaldo normal
#   ./infrastructure/scripts/backup.sh --verify   respaldo + prueba de restauración
#
# Respalda dos cosas que no se pueden reconstruir solas:
#   1. PostgreSQL — decisiones, evidencia, hallazgos. Irrecuperable si se pierde.
#   2. MinIO (bucket RAW) — los documentos crudos del DOF, SNICE, etc. Se podrían
#      volver a descargar, pero la fuente puede haber cambiado o desaparecido, y
#      entonces se rompe la trazabilidad que exige §13 del maestro.
#
# El dump va en formato custom (-Fc), no SQL plano: se comprime y permite
# restaurar una sola tabla con pg_restore -t, cosa que un .sql no permite.

set -Eeuo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESTINO="${ADUANERO_BACKUP_DIR:-$HOME/backups/aduanero}"
RETENCION_DIARIA=14   # días
RETENCION_SEMANAL=8   # semanas (se conserva el respaldo del domingo)

VERIFICAR=0
[ "${1:-}" = "--verify" ] && VERIFICAR=1

# ── Utilidades ───────────────────────────────────────────────────────────────
log()   { printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
fail()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; }
morir() { fail "$*"; exit 1; }

trap 'fail "Falló en la línea $LINENO"; exit 1' ERR

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

# ── Configuración ────────────────────────────────────────────────────────────
[ -f "$RAIZ/.env" ] || morir "falta $RAIZ/.env"
set -a; . "$RAIZ/.env"; set +a

: "${POSTGRES_DB:=aduanero}"
: "${POSTGRES_USER:=aduanero_app}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD no está en .env}"
: "${MINIO_BUCKET_RAW:=aduanero-raw}"
: "${MINIO_BUCKET_DOCS:=aduanero-docs}"

CONTENEDOR_PG="aduanero-postgres"
CONTENEDOR_MINIO="aduanero-minio"

SELLO="$(date +%Y%m%d_%H%M%S)"
DIA_SEMANA="$(date +%u)"   # 7 = domingo
mkdir -p "$DESTINO"/{diarios,semanales,minio}

log "Respaldo de ADUANERO OS → $DESTINO"

# ── 1. PostgreSQL ────────────────────────────────────────────────────────────
d inspect -f '{{.State.Status}}' "$CONTENEDOR_PG" >/dev/null 2>&1 \
  || morir "el contenedor $CONTENEDOR_PG no existe (¿docker compose up -d?)"

ARCHIVO="$DESTINO/diarios/aduanero_${SELLO}.dump"

log "Volcando PostgreSQL…"
# --no-owner y --no-privileges: el dump se restaura en cualquier instalación sin
# exigir que existan los mismos roles.
d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            --format=custom --compress=9 --no-owner --no-privileges \
  > "$ARCHIVO"

[ -s "$ARCHIVO" ] || morir "el dump salió vacío"

# Un archivo que pg_restore no puede listar está corrupto. Detectarlo AHORA y no
# el día que haga falta restaurar es toda la diferencia.
if ! pg_restore --list "$ARCHIVO" >/dev/null 2>&1; then
  if d exec -i "$CONTENEDOR_PG" pg_restore --list < "$ARCHIVO" >/dev/null 2>&1; then
    :   # sin pg_restore local; se validó dentro del contenedor
  else
    morir "el dump no es un archivo válido de pg_restore"
  fi
fi

TABLAS=$(d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "SELECT count(*) FROM information_schema.tables
   WHERE table_schema IN ('public','raw','regulatory','operational','intelligence')" | tr -d '[:space:]')

sha256sum "$ARCHIVO" > "$ARCHIVO.sha256"
ok "PostgreSQL: $(du -h "$ARCHIVO" | cut -f1) · $TABLAS tablas · $(basename "$ARCHIVO")"

[ "$TABLAS" = "0" ] && log "  (aviso: la base no tiene tablas todavía)"

# ── 2. MinIO ─────────────────────────────────────────────────────────────────
if d inspect -f '{{.State.Status}}' "$CONTENEDOR_MINIO" >/dev/null 2>&1; then
  log "Espejando MinIO…"
  ESPEJO="$DESTINO/minio"
  for bucket in "$MINIO_BUCKET_RAW" "$MINIO_BUCKET_DOCS"; do
    mkdir -p "$ESPEJO/$bucket"
    # mirror es incremental: sólo copia lo que cambió. Sin --remove, para que un
    # borrado accidental en MinIO no se propague al respaldo.
    d exec "$CONTENEDOR_MINIO" sh -c \
      "mc alias set _bk http://localhost:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null 2>&1 && \
       mc mirror --overwrite --quiet _bk/$bucket /tmp/_bk_$bucket >/dev/null 2>&1 || true"
    d cp "$CONTENEDOR_MINIO:/tmp/_bk_$bucket/." "$ESPEJO/$bucket/" 2>/dev/null || true
    d exec "$CONTENEDOR_MINIO" rm -rf "/tmp/_bk_$bucket" 2>/dev/null || true
    n=$(find "$ESPEJO/$bucket" -type f 2>/dev/null | wc -l)
    ok "MinIO $bucket: $n archivos"
  done
else
  log "  MinIO no está corriendo; se omite"
fi

# ── 3. Copia semanal ─────────────────────────────────────────────────────────
if [ "$DIA_SEMANA" = "7" ]; then
  cp "$ARCHIVO" "$DESTINO/semanales/"
  cp "$ARCHIVO.sha256" "$DESTINO/semanales/"
  ok "Copia semanal guardada"
fi

# ── 4. Retención ─────────────────────────────────────────────────────────────
borrados=$(find "$DESTINO/diarios" -name '*.dump*' -mtime +$RETENCION_DIARIA -print -delete | wc -l)
borrados=$((borrados + $(find "$DESTINO/semanales" -name '*.dump*' -mtime +$((RETENCION_SEMANAL * 7)) -print -delete | wc -l)))
[ "$borrados" -gt 0 ] && ok "Purgados $borrados archivos fuera de retención"

# ── 5. Verificación de restauración (opcional pero recomendada) ──────────────
if [ "$VERIFICAR" -eq 1 ]; then
  log "Probando la restauración en una base desechable…"
  PRUEBA="aduanero_restore_test_$$"
  limpiar() {
    d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
      psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS $PRUEBA;" >/dev/null 2>&1 || true
  }
  trap 'limpiar; fail "Falló la verificación"; exit 1' ERR

  d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
    psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $PRUEBA;" >/dev/null

  d exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
    pg_restore -U "$POSTGRES_USER" -d "$PRUEBA" --no-owner --no-privileges \
    < "$ARCHIVO" >/dev/null 2>&1 || true   # avisos de extensiones no son fatales

  RESTAURADAS=$(d exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$CONTENEDOR_PG" \
    psql -U "$POSTGRES_USER" -d "$PRUEBA" -tAc \
    "SELECT count(*) FROM information_schema.tables
     WHERE table_schema IN ('public','raw','regulatory','operational','intelligence')" | tr -d '[:space:]')

  limpiar
  trap 'fail "Falló en la línea $LINENO"; exit 1' ERR

  if [ "$RESTAURADAS" = "$TABLAS" ]; then
    ok "Restauración verificada: $RESTAURADAS de $TABLAS tablas"
  else
    morir "restauración incompleta: $RESTAURADAS de $TABLAS tablas"
  fi
fi

# ── Resumen ──────────────────────────────────────────────────────────────────
echo
log "Listo. Ocupado: $(du -sh "$DESTINO" | cut -f1) · $(find "$DESTINO" -name '*.dump' | wc -l) dumps"
echo
echo "  ⚠️  Estos respaldos viven en el MISMO disco que la base. Si el disco"
echo "      muere, se pierden los dos. Copia $DESTINO a otra máquina o disco:"
echo "        rsync -az $DESTINO/ otro-equipo:~/backups/aduanero/"
