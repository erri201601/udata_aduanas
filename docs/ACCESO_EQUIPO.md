# ADUANERO OS — Accesos para el equipo

**Para:** Persona 2 (Data Engineer) y Persona 3 (AI/Full Stack)  
**Administra:** Persona 1

> Las contraseñas **no viven en este archivo ni en Git** (§40 maestro).
> Persona 1 las entrega por canal seguro (gestor de contraseñas / 1:1).
> Los valores reales están en el `.env` de la laptop de Persona 1.

---

## 1. Requisito previo: Tailscale

No hay acceso sin Tailscale. Los servicios sólo escuchan en loopback y en la
IP del tailnet — nunca en la LAN ni en Internet.

**La IP del dev server de Persona 1 es `100.86.182.104`** (host `udata-nitro`).

Persona 1 debe invitarte antes al tailnet; sin eso, instalar Tailscale no
basta. Una vez invitado:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up          # abre el navegador para autenticarte
tailscale status           # debes ver udata-nitro en la lista
ping 100.86.182.104
```

---

## 2. PostgreSQL — la base donde se insertan los datos

| Parámetro | Valor |
|---|---|
| Host | `100.86.182.104` (desde la laptop de P1 también vale `localhost`) |
| **Puerto** | **5433** ← no 5432; el 5432 lo ocupa otro Postgres ajeno al proyecto |
| Base | `aduanero` |
| Usuario | `aduanero_app` |
| Contraseña | pídesela a Persona 1 |
| SSL | no requerido dentro de Tailscale |

Cadena de conexión:

```
postgresql://aduanero_app:<PASSWORD>@100.86.182.104:5433/aduanero
```

SQLAlchemy / Python:

```
postgresql+psycopg://aduanero_app:<PASSWORD>@100.86.182.104:5433/aduanero
```

Prueba:

```bash
psql "postgresql://aduanero_app:<PASSWORD>@100.86.182.104:5433/aduanero" -c "\dn"
```

### Las herramientas la leen de `ADUANERO_SHARED_URL`, no de `.env`

Hay una sola base y vive en la laptop de Persona 1. **Nadie levanta una
segunda**: dos bases serían dos verdades, y cualquier medición dejaría de
decir algo sobre el sistema.

Los CLIs que se conectan desde otra máquina —la métrica del §26, la proyección
del grafo— piden `--target shared` y leen la URL de la variable de entorno:

```bash
umask 077
cat > /tmp/.aduanero <<'EOF'
export ADUANERO_SHARED_URL='postgresql+psycopg://aduanero_app:<PASSWORD>@100.86.182.104:5433/aduanero'
EOF
source /tmp/.aduanero && rm /tmp/.aduanero
python -m apps.evaluacion.deteccion_26 --target shared --escenarios
```

La contraseña **no se escribe en `.env`, ni en el repositorio, ni en un chat**.
Vive en la variable durante la sesión que la necesita y se va con ella.

Desde la laptop de Persona 1 esto no hace falta: ahí `--target local` **ya es**
la base del equipo, y `shared` falla pidiendo una variable que en esa máquina
no existe.

### Esquemas y quién escribe en cada uno

| Esquema | Contenido | Escribe |
|---|---|---|
| `raw` | landing de ingestión, sin transformar (§12: nunca saltarse RAW) | Persona 2 |
| `regulatory` | LIGIE, NICO, Ley Aduanera, RGCE, Anexo 22, DOF — `OFFICIAL`/`PUBLIC`/`LICENSED` | Persona 2 |
| `operational` | clientes, pedimentos, facturas — hoy `SYNTHETIC` | Persona 2 |
| `intelligence` | decisiones, evidencia, hallazgos | Persona 1 |
| `public` | tablas canónicas compartidas | Persona 1 (vía Alembic) |

### Reglas de inserción — no negociables

1. **Ningún `CREATE TABLE` ni `ALTER TABLE` a mano.** Todo cambio de esquema
   pasa por una migración Alembic aprobada por Persona 1 (§10.4 y §10.5).
   Si necesitas una columna, abre issue/PR.
2. **Toda fila lleva `data_origin`**, con uno de estos cinco valores exactos:
   `OFFICIAL`, `PUBLIC`, `LICENSED`, `SYNTHETIC`, `HUMAN_VALIDATED`.
   No se inventan otros valores sin aprobación de Persona 1 (§9 maestro).
3. **Todo dato regulatorio lleva trazabilidad**: `source_url`, `source_document`,
   `retrieved_at`, `published_at`, `valid_from`, `valid_to`, `content_hash` (§13 maestro).
4. **Nunca `valid_to` inventado.** Si la norma sigue vigente, `valid_to = NULL`.
5. **RAW primero.** El documento crudo se guarda en MinIO y se referencia antes
   de parsear. No se inserta un dato NORMALIZED cuyo RAW no exista.
6. **Los datos sintéticos se marcan** con `data_origin = SYNTHETIC`,
   `synthetic_scenario_id` y `seed` (§10 maestro). Jamás se presentan como reales.

---

## 3. Neo4j — Knowledge Graph (Persona 3)

| Parámetro | Valor |
|---|---|
| Browser | `http://100.86.182.104:7474` |
| Bolt | `bolt://100.86.182.104:7687` |
| Usuario | `neo4j` |
| Contraseña | pídesela a Persona 1 |

---

## 4. Redis — cache y colas

| Parámetro | Valor |
|---|---|
| Host / puerto | `100.86.182.104:6379` |
| Contraseña | pídesela a Persona 1 (`requirepass` activo) |

```
redis://:<PASSWORD>@100.86.182.104:6379/0
```

---

## 5. MinIO — documentos (PDFs del DOF, fichas técnicas, imágenes)

| Parámetro | Valor |
|---|---|
| API S3 | `http://100.86.182.104:9000` |
| Consola web | `http://100.86.182.104:9001` |
| Access key | `aduanero_minio` |
| Secret key | pídesela a Persona 1 |
| Buckets | `aduanero-raw` (versionado), `aduanero-docs` |

---

## 6. API

| Parámetro | Valor |
|---|---|
| Base URL | `http://100.86.182.104:8080` |
| Health | `GET /health` |
| Readiness | `GET /health/ready` |
| OpenAPI | `http://100.86.182.104:8080/docs` |

> El puerto **8080**, no 8000: el 8000 lo ocupa otro proyecto en la laptop de Persona 1.

---

## 7. Rotación de credenciales

Si una credencial se filtra (commit accidental, captura de pantalla, chat):

1. Avisar a Persona 1 de inmediato.
2. Persona 1 cambia el valor en `.env`.
3. `docker compose down && docker compose up -d`.
4. Para Postgres el cambio no es automático — hay que hacer
   `ALTER ROLE aduanero_app WITH PASSWORD '...'` dentro del contenedor.
5. Reemitir credenciales al equipo por canal seguro.
