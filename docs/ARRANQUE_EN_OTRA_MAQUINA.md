# Arrancar ADUANERO OS en otra máquina

Para levantar el proyecto en una laptop nueva copiando la carpeta. La guía de
[`infrastructure/scripts/00_INSTALACION.md`](../infrastructure/scripts/00_INSTALACION.md)
describe el **dev server** —la máquina de Persona 1, con Tailscale, firewall y
la API como servicio—. Ésta describe algo más modesto: que el proyecto corra.

---

## Lo primero, porque es lo que sorprende

**Copiar la carpeta NO copia los datos.**

Las 8 136 fracciones, los 15 pedimentos, el corpus jurídico y los documentos de
MinIO no están en el repositorio: viven en **volúmenes de Docker**
—`pgdata`, `neo4jdata`, `redisdata`, `miniodata`— que son del demonio de
Docker, no de la carpeta. En la máquina nueva arrancas con la base **vacía**.

Tres cosas más que viajan en la carpeta y no sirven al llegar:

| qué | por qué no sirve | qué hacer |
|---|---|---|
| `.venv/` | lleva grabada la ruta absoluta `/home/udata/Documentos/udata_aduanas/.venv` | borrarlo y recrearlo |
| `apps/web/node_modules/` | 153 MB de binarios compilados para esta máquina (esbuild, rollup) | borrarlo y `npm ci` |
| `.env` | apunta a la IP de Tailscale de **esta** laptop | ajustar dos variables |

> ⚠️ **`.env` lleva las contraseñas en claro.** Si pasas la carpeta por USB,
> Drive o WeTransfer, las credenciales viajan con ella. Bórralo antes de
> copiar y llévalas por el canal seguro, o asume que esa copia es sensible y
> destrúyela al terminar.

---

## 1. Requisitos de la máquina

```
Python 3.12 o superior      (pyproject exige >=3.12)
Docker + Compose v2
Node 20+                    (sólo para apps/web)
```

En Ubuntu/Debian, lo que suele faltar:

```bash
sudo apt install python3.12-venv python3-pip docker.io docker-compose-v2
sudo usermod -aG docker "$USER"   # y cerrar sesión, o usar: sg docker -c "..."
```

Si `docker ps` dice `permission denied ... /var/run/docker.sock`, es eso: el
grupo no está cargado hasta que vuelvas a entrar.

## 2. Limpiar lo que no es portable

```bash
cd ruta/a/udata_aduanas
rm -rf .venv apps/web/node_modules aduanero_os.egg-info
find . -name __pycache__ -type d -prune -exec rm -rf {} +
```

## 3. Configuración

```bash
cp .env.example .env          # si no lo trajiste
cp apps/web/.env.example apps/web/.env
```

Rellena las contraseñas y **ajusta lo que estaba atado a la otra máquina**:

- `TEAM_BIND_ADDR` — la IP de Tailscale del dev server. En una laptop suelta
  no hay tailnet: pon `127.0.0.1`.
- `VITE_API_BASE_URL` en `apps/web/.env` — tiene que apuntar a donde escuche
  la API de verdad. Si `TEAM_BIND_ADDR` es `127.0.0.1`, aquí va
  `http://127.0.0.1:8080`.

> **La API escucha en `API_HOST`, no en todas partes.** Si dejas la IP de la
> otra máquina, uvicorn no arranca —esa IP no existe aquí— y si la web apunta
> a un sitio donde la API no escucha, todas las pantallas salen vacías sin
> decir por qué. Es el fallo más caro de diagnosticar de esta lista.

Los puertos **8080** y **5433** se conservan tal cual. No son caprichosos en
el dev server —el 8000 y el 5432 están ocupados ahí— pero cambiarlos aquí te
obliga a tocar `.env`, la web y la documentación. Déjalos.

## 4. Levantar la infraestructura

```bash
docker compose up -d
```

La primera vez, con `pgdata` vacío, Postgres ejecuta
`infrastructure/docker/postgres/init/01_extensions.sql` y crea `vector`,
`pg_trgm`, `unaccent`, `btree_gin`, `uuid-ossp` y la configuración de búsqueda
en español. **Sólo ocurre con el volumen vacío**: si algún día restauras sobre
un volumen ya creado, esas extensiones no se vuelven a crear.

## 5. Python y esquema

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
```

## 6. Comprobar que la infraestructura está bien

```bash
./infrastructure/scripts/smoke_test.sh
```

Comprueba los cuatro servicios **y** lo que el proyecto da por supuesto:
extensiones, esquemas, buckets de MinIO y la autenticación de Neo4j y Redis.
Si algo falla aquí, no sigas: todo lo demás va a fallar de forma más confusa.

## 7. Comprobar que el código está bien

```bash
make test     # la suite completa
make lint     # ruff + mypy
```

Los tests marcados `integration` necesitan el Postgres de arriba levantado.

## 8. Los datos

Hasta aquí tienes un sistema **correcto y vacío**. Dos caminos:

### a) Traértelos del dev server — lo normal

Copia un dump de `~/backups/aduanero/` de la máquina origen y:

```bash
./infrastructure/scripts/restore.sh                       # lista lo disponible
./infrastructure/scripts/restore.sh <archivo.dump> --en-vivo
```

Por defecto restaura a una base desechable; `--en-vivo` pisa `aduanero` y pide
confirmación escrita, porque es destructivo.

> ⚠️ **`restore.sh` restaura PostgreSQL, no MinIO.** El respaldo sí copia los
> buckets a `~/backups/aduanero/minio/`, pero devolverlos hay que hacerlo a
> mano con `mc mirror`. Es una asimetría conocida: sin MinIO tienes los datos
> y las decisiones, pero no los documentos crudos que sostienen la
> trazabilidad del §13.

### b) Reconstruirlos desde las fuentes

Más largo y necesita las llaves de los proveedores, pero no depende de tener
un respaldo a mano. Los cargadores están en `ingestion/`.

## 9. Arrancar

```bash
make api                                   # API en 8080
cd apps/web && npm ci && npm run dev -- --port 5173
```

La API en `http://127.0.0.1:8080/docs`, la web en `http://localhost:5173`.

> **CORS.** `apps/api/main.py` admite exactamente dos orígenes:
> `http://localhost:5173` y `http://127.0.0.1:5173`. Abrir la web por la IP de
> la máquina deja las pantallas vacías: el navegador bloquea las llamadas sin
> avisar. Si necesitas otro origen, hay que añadirlo ahí.

## 10. Comprobar que el sistema hace lo que dice

Con datos cargados:

```bash
source .venv/bin/activate
python -m apps.evaluacion.deteccion_26 --escenarios
python -m apps.evaluacion.deteccion_26 --escenario corpus_espejo_v1
```

El reporte sella la fecha y la revisión del código. Si el recall no se parece
al de la máquina origen, algo no se cargó: no es el motor, son los datos.

---

## Resumen de lo que suele salir mal

| síntoma | causa |
|---|---|
| `pip` o `python` fallan raro tras copiar | el `.venv` viejo; hay que borrarlo |
| `vite` revienta al arrancar | `node_modules` de otra plataforma; `npm ci` |
| uvicorn no arranca, «cannot assign requested address» | `API_HOST`/`TEAM_BIND_ADDR` con la IP de la otra máquina |
| la web carga pero todo sale vacío | `VITE_API_BASE_URL` apunta donde la API no escucha, o CORS |
| `unaccent does not exist` | Postgres arrancó sobre un volumen que ya existía |
| la medición da un número distinto | faltan datos, no falla el motor |
