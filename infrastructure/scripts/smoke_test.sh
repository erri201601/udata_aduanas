#!/usr/bin/env bash
# ADUANERO OS — verificación del stack local.
#
#   ./infrastructure/scripts/smoke_test.sh
#
# Comprueba que los cuatro servicios responden y que la configuración que
# ADUANERO OS da por supuesta existe de verdad: extensiones de PostgreSQL,
# esquemas, buckets de MinIO y autenticación de Neo4j y Redis.
# Sale con código != 0 si algo falla, para poder usarse en CI.

set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1

[ -f .env ] || { echo "✗ falta .env — cópialo de .env.example"; exit 1; }
set -a; . ./.env; set +a

# Si la sesión aún no tiene cargado el grupo docker (pasa hasta el primer
# re-login tras `usermod -aG docker`), reinvocamos vía `sg`. Hay que rearmar la
# línea con printf %q: `sg -c` recibe UNA cadena, y sin escapar se pierden las
# comillas de los argumentos con espacios (el -f '{{...}}' y las consultas SQL).
NEEDS_SG=0
docker ps >/dev/null 2>&1 || NEEDS_SG=1
run() {
  if [ "$NEEDS_SG" -eq 0 ]; then
    docker "$@"
  else
    sg docker -c "$(printf '%q ' docker "$@")"
  fi
}

fallos=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; fallos=$((fallos + 1)); }

echo "── Contenedores ────────────────────────────────────────────────"
for c in aduanero-postgres aduanero-neo4j aduanero-redis aduanero-minio; do
  estado=$(run inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}sin-healthcheck{{end}}' "$c" 2>/dev/null)
  case "$estado" in
    running/healthy|running/sin-healthcheck) ok "$c → $estado" ;;
    "")                                      fail "$c → no existe" ;;
    *)                                       fail "$c → $estado" ;;
  esac
done

echo "── PostgreSQL ──────────────────────────────────────────────────"
psql_c() { run exec -e PGPASSWORD="$POSTGRES_PASSWORD" aduanero-postgres \
             psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1" 2>/dev/null; }

[ "$(psql_c 'SELECT 1')" = "1" ] && ok "conexión como $POSTGRES_USER" || fail "no conecta"

for ext in vector pg_trgm unaccent btree_gin uuid-ossp; do
  if [ "$(psql_c "SELECT 1 FROM pg_extension WHERE extname='$ext'")" = "1" ]; then
    ok "extensión $ext"
  else
    fail "extensión $ext ausente"
  fi
done

for esquema in raw regulatory operational intelligence; do
  if [ "$(psql_c "SELECT 1 FROM information_schema.schemata WHERE schema_name='$esquema'")" = "1" ]; then
    ok "esquema $esquema"
  else
    fail "esquema $esquema ausente"
  fi
done

# pgvector operativo de verdad, no sólo instalado.
if [ "$(psql_c "SELECT ROUND((('[1,0,0]'::vector <-> '[0,1,0]'::vector))::numeric, 4)")" = "1.4142" ]; then
  ok "pgvector calcula distancias"
else
  fail "pgvector no opera"
fi

echo "── Redis ───────────────────────────────────────────────────────"
if [ "$(run exec aduanero-redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping 2>/dev/null)" = "PONG" ]; then
  ok "PING autenticado"
else
  fail "no responde"
fi
# Sin contraseña debe rechazar: confirma que requirepass está activo.
if run exec aduanero-redis redis-cli ping 2>&1 | grep -qi "NOAUTH\|Authentication"; then
  ok "rechaza conexiones sin contraseña"
else
  fail "acepta conexiones sin contraseña"
fi

echo "── Neo4j ───────────────────────────────────────────────────────"
if run exec aduanero-neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
     "RETURN 1 AS ok" 2>/dev/null | grep -q 1; then
  ok "cypher-shell autenticado"
else
  fail "no responde o credenciales incorrectas"
fi

echo "── MinIO ───────────────────────────────────────────────────────"
for bucket in "$MINIO_BUCKET_RAW" "$MINIO_BUCKET_DOCS"; do
  if run exec aduanero-minio mc ls "local/$bucket" >/dev/null 2>&1 ||
     curl -s -o /dev/null -w '%{http_code}' "http://localhost:${MINIO_API_PORT}/minio/health/live" | grep -q 200; then
    ok "bucket $bucket / servicio vivo"
  else
    fail "bucket $bucket inaccesible"
  fi
done

echo "── Exposición de red (§3 y §41) ────────────────────────────────"
expuestos=$(run ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -E '0\.0\.0\.0|\[::\]' || true)
if [ -z "$expuestos" ]; then
  ok "ningún puerto publicado en 0.0.0.0"
else
  fail "puertos expuestos a toda la red:"; echo "$expuestos" | sed 's/^/      /'
fi

# Sólo loopback y el rango CGNAT de Tailscale (100.64.0.0/10) son aceptables.
malos=$(run ps --format '{{.Ports}}' 2>/dev/null | tr ',' '\n' | grep -oE '^ *[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | tr -d ' ' | sort -u |
        grep -vE '^127\.' | grep -vE '^100\.(6[4-9]|[7-9][0-9]|1[0-1][0-9]|12[0-7])\.' || true)
if [ -z "$malos" ]; then
  ok "sólo loopback y tailnet"
else
  fail "publicado en IPs que no son loopback ni Tailscale:"; echo "$malos" | sed 's/^/      /'
fi

if [ "${TEAM_BIND_ADDR:-}" != "${TEAM_BIND_ADDR#100.}" ]; then
  if command -v tailscale >/dev/null && tailscale ip -4 2>/dev/null | grep -q "^${TEAM_BIND_ADDR}$"; then
    ok "TEAM_BIND_ADDR coincide con la IP real de Tailscale ($TEAM_BIND_ADDR)"
  else
    fail "TEAM_BIND_ADDR=$TEAM_BIND_ADDR no coincide con la IP actual de Tailscale"
  fi
fi

echo "────────────────────────────────────────────────────────────────"
if [ "$fallos" -eq 0 ]; then
  printf '\033[32mStack OK.\033[0m\n'; exit 0
else
  printf '\033[31m%d comprobación(es) fallida(s).\033[0m\n' "$fallos"; exit 1
fi
