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

FALLO_MINIO=0

# ── 2. MinIO ─────────────────────────────────────────────────────────────────
if d inspect -f '{{.State.Status}}' "$CONTENEDOR_MINIO" >/dev/null 2>&1; then
  log "Espejando MinIO…"
  ESPEJO="$DESTINO/minio"
  for bucket in "$MINIO_BUCKET_RAW" "$MINIO_BUCKET_DOCS"; do
    mkdir -p "$ESPEJO/$bucket"
    # mirror es incremental: sólo copia lo que cambió. Sin --remove, para que un
    # borrado accidental en MinIO no se propague al respaldo.
    # El alias NO puede empezar con '_': mc lo rechaza. Costó un mes de
    # respaldos vacíos que nadie notó, porque el error iba a /dev/null y el
    # '|| true' lo daba por bueno (2026-09-08).
    if ! salida=$(d exec "$CONTENEDOR_MINIO" sh -c \
      "mc alias set bk http://localhost:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null && \
       mc mirror --overwrite --quiet bk/$bucket /tmp/bk_$bucket" 2>&1); then
      fail "MinIO $bucket no se pudo espejar: $salida"
      FALLO_MINIO=1
      continue
    fi
    d cp "$CONTENEDOR_MINIO:/tmp/bk_$bucket/." "$ESPEJO/$bucket/" 2>/dev/null || true
    d exec "$CONTENEDOR_MINIO" rm -rf "/tmp/bk_$bucket" 2>/dev/null || true

    # Contrastar contra el origen: un espejo con menos archivos que el bucket
    # es un respaldo incompleto, y un respaldo incompleto que dice ✓ es peor
    # que no tener respaldo.
    n=$(find "$ESPEJO/$bucket" -type f 2>/dev/null | wc -l)
    origen=$(d exec "$CONTENEDOR_MINIO" sh -c \
      "mc ls --recursive bk/$bucket 2>/dev/null | wc -l" | tr -d '[:space:]')
    if [ "$n" != "$origen" ]; then
      fail "MinIO $bucket: espejados $n de $origen archivos"
      FALLO_MINIO=1
    else
      ok "MinIO $bucket: $n archivos ($(du -sh "$ESPEJO/$bucket" | cut -f1))"
    fi
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

# ── 6. Réplica fuera del disco ───────────────────────────────────────────────
# Un respaldo en el mismo disco que la base no protege del fallo que más
# probable es: que muera el disco. `ADUANERO_BACKUP_REMOTO` es un destino de
# rsync (`maquina:~/ruta/`) y va en .env, no aquí: cada máquina replica a otra
# distinta y el script es el mismo para todas.
FALLO_REMOTO=0
if [ -n "${ADUANERO_BACKUP_REMOTO:-}" ]; then
  log "Replicando a $ADUANERO_BACKUP_REMOTO…"

  # Sin --delete a propósito. Un error en la purga local se propagaría al
  # remoto y borraría la única copia que queda cuando el disco local falla.
  # Que el remoto acumule dumps viejos es un problema mucho menor.
  #
  # La salida va a un archivo y NO por una tubería: el estado de `rsync | sed`
  # es el de `sed`, y un fallo de transferencia se daría por bueno. `pipefail`
  # lo cubriría, pero no se deja un respaldo colgando de ese detalle.
  BITACORA_REMOTA="$(mktemp)"
  if rsync -az --partial "$DESTINO/" "$ADUANERO_BACKUP_REMOTO" >"$BITACORA_REMOTA" 2>&1; then
    sed 's/^/    /' "$BITACORA_REMOTA"
    # Segunda pasada por CONTENIDO, no por fecha y tamaño: un archivo truncado
    # a medio transferir tiene el tamaño de destino y pasaría desapercibido.
    # Va en seco, así que no copia nada: sólo pregunta si queda algo distinto.
    PENDIENTE=$(rsync -az --checksum --dry-run --out-format='%n' \
      "$DESTINO/" "$ADUANERO_BACKUP_REMOTO" 2>/dev/null | grep -c '\.dump' || true)
    if [ "$PENDIENTE" -eq 0 ]; then
      ok "Réplica verificada por contenido: los dumps del remoto son idénticos"
    else
      FALLO_REMOTO=1
      fail "La réplica dejó $PENDIENTE dumps distintos del original"
    fi
  else
    FALLO_REMOTO=1
    fail "No se pudo replicar a $ADUANERO_BACKUP_REMOTO"
    sed 's/^/    /' "$BITACORA_REMOTA" >&2
  fi
  rm -f "$BITACORA_REMOTA"
fi

# ── Resumen ──────────────────────────────────────────────────────────────────
echo
log "Listo. Ocupado: $(du -sh "$DESTINO" | cut -f1) · $(find "$DESTINO" -name '*.dump' | wc -l) dumps"
if [ -z "${ADUANERO_BACKUP_REMOTO:-}" ]; then
  echo
  echo "  ⚠️  Estos respaldos viven en el MISMO disco que la base. Si el disco"
  echo "      muere, se pierden los dos. Define ADUANERO_BACKUP_REMOTO en .env:"
  echo "        ADUANERO_BACKUP_REMOTO=otro-equipo:~/backups/aduanero/"
fi

# Salir distinto de 0 si MinIO quedó incompleto: el respaldo de PostgreSQL sí
# sirve, pero el RAW es lo único irreversible (regla 7) y el cron tiene que
# enterarse. Un script que siempre devuelve 0 no avisa nunca.
if [ "$FALLO_MINIO" = "1" ]; then
  echo
  fail "El respaldo de PostgreSQL está completo, pero MinIO NO. Revisa arriba."
  exit 2
fi

# La réplica falla con su propio código: el respaldo local sirve, pero sigue en
# el mismo disco que la base, y eso es justo lo que la réplica existe para
# evitar. Silenciarlo daría por replicado lo que no salió de la máquina.
if [ "$FALLO_REMOTO" = "1" ]; then
  echo
  fail "El respaldo local está completo, pero NO salió de este disco."
  exit 3
fi
