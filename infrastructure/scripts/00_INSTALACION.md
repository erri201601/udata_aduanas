# ADUANERO OS — Instalación del DEV SERVER (laptop de Persona 1)

Estado detectado en la laptop al 2026-09-02:

| Componente | Estado |
|---|---|
| Python 3.12.3 | ✅ ya instalado |
| Node v24.16 | ✅ ya instalado |
| Git 2.43 | ✅ ya instalado |
| PostgreSQL 16.15 nativo | ⚠️ corriendo en `:5432` — **es de otro proyecto**, no lo tocamos |
| pgvector 0.6.0 | ✅ disponible en el sistema |
| Docker | ❌ falta |
| Neo4j / Redis / MinIO | ❌ faltan (los pone Docker) |
| Tailscale | ❌ falta |

Todo lo que falta requiere `sudo`. Ejecútalo tú, Persona 1.

---

## 1. Docker + Compose v2

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

### ⚠️ `permission denied ... /var/run/docker.sock`

`usermod -aG docker` **no afecta a las sesiones ya abiertas**. Aunque
`getent group docker` te liste, tu shell actual no tiene el grupo cargado:
compruébalo con `id -nG`.

Solución definitiva: **cierra sesión y vuelve a entrar**.

Salida rápida sin cerrar sesión, para el shell actual:

```bash
newgrp docker              # abre un subshell CON el grupo
# o, para un solo comando:
sg docker -c 'docker compose up -d'
```

Verifica:

```bash
docker --version && docker compose version && docker run --rm hello-world
```

---

## 2. pip para Python (falta el módulo)

```bash
sudo apt install -y python3-pip python3-venv
```

---

## 3. Tailscale — acceso de Persona 2 y Persona 3

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Anota la IP que te asigna (formato `100.x.y.z`):

```bash
tailscale ip -4
```

Esa IP va en `.env` como `BIND_ADDR`. Es lo que permite que Persona 2 y 3
conecten **sin** exponer nada a Internet.

---

## 4. Firewall — cerrar lo que hoy está abierto

⚠️ **Hallazgo de seguridad.** El PostgreSQL nativo tiene
`listen_addresses = '*'` y responde en `192.168.1.58:5432` **y en la IPv6
global de la laptop**. Salvo que el router bloquee IPv6 entrante, esa base de
datos está expuesta a Internet. Viola §3 y §41 del documento de Persona 1.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on tailscale0          # solo el equipo, por red privada
sudo ufw allow 22/tcp                    # ssh local, opcional
sudo ufw enable
sudo ufw status verbose
```

Y limitar el Postgres nativo a loopback (revísalo con el dueño de ese proyecto):

```bash
sudo sed -i "s/^listen_addresses.*/listen_addresses = 'localhost'/" \
  /etc/postgresql/16/main/postgresql.conf
sudo systemctl restart postgresql@16-main
```

---

## 5. Levantar ADUANERO OS

```bash
cd /home/udata/Documentos/aduanas
cp .env.example .env        # si aún no existe; ya viene generado con credenciales
docker compose up -d
docker compose ps
```

Espera a que los healthchecks pasen a `healthy` (~20 s).

Verifica el stack completo — extensiones, esquemas, buckets, autenticación y
que nada quede expuesto en `0.0.0.0`:

```bash
./infrastructure/scripts/smoke_test.sh
```

---

## 6. Entorno Python y API

```bash
cd /home/udata/Documentos/aduanas
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn apps.api.main:app --reload --port 8080
```

Comprobar:

```bash
curl -s http://localhost:8080/health | python3 -m json.tool
curl -s http://localhost:8080/health/ready | python3 -m json.tool
```

---

## 7. Desinstalar / reiniciar desde cero

```bash
docker compose down -v      # ⚠️ -v BORRA los volúmenes y todos los datos
docker compose up -d
```

---

## 8. La API como servicio permanente

Para que el equipo pueda usarla sin depender de que Persona 1 tenga una
terminal abierta, la API corre como servicio de usuario de systemd.

```bash
cp infrastructure/systemd-aduanero-api.service \
   ~/.config/systemd/user/aduanero-api.service
systemctl --user daemon-reload
systemctl --user enable --now aduanero-api.service
```

Se enlaza a `${TEAM_BIND_ADDR}` (la IP de Tailscale), **no** a `0.0.0.0`.

### Operación

```bash
systemctl --user status  aduanero-api    # estado
systemctl --user restart aduanero-api    # tras cambiar código
systemctl --user stop    aduanero-api    # apagar
journalctl --user -u aduanero-api -f     # logs en vivo
```

### Para que sobreviva al cierre de sesión

```bash
sudo loginctl enable-linger udata
```

Sin esto, systemd mata los servicios de usuario al cerrar sesión y el equipo
se queda sin API.

### Si la IP de Tailscale cambia

Actualiza `TEAM_BIND_ADDR` en `.env`, y después:

```bash
systemctl --user restart aduanero-api
docker compose up -d
```


---

## 9. Respaldos

La base compartida no se puede reconstruir: contiene decisiones, evidencia y
hallazgos. El bucket RAW de MinIO tampoco, en la práctica — los documentos se
podrían volver a descargar, pero la fuente puede haber cambiado, y entonces se
rompe la trazabilidad que exige §13 del maestro.

### Automático

Un timer de systemd corre a las 03:00 todos los días.

```bash
cp infrastructure/systemd-aduanero-backup.service ~/.config/systemd/user/aduanero-backup.service
cp infrastructure/systemd-aduanero-backup.timer   ~/.config/systemd/user/aduanero-backup.timer
systemctl --user daemon-reload
systemctl --user enable --now aduanero-backup.timer
```

`Persistent=true`: si la laptop estaba apagada a las 3, el respaldo corre al
encenderla. Sin eso, un fin de semana sin encender la máquina son tres días sin
respaldo y nadie se entera.

### Manual

```bash
make backup         # respalda y verifica la restauración
make backup-list    # lista lo disponible
make backup-timer   # estado del timer y últimas corridas
```

### Restaurar

```bash
./infrastructure/scripts/restore.sh                            # lista
./infrastructure/scripts/restore.sh <archivo.dump>             # a una base desechable
./infrastructure/scripts/restore.sh <archivo.dump> --en-vivo   # SOBRESCRIBE aduanero
```

Por defecto restaura a una base nueva, nunca sobre producción. `--en-vivo` pide
escribir `SOBRESCRIBIR` y, antes de pisar nada, guarda un dump del estado
actual.

### Qué se guarda

| | |
|---|---|
| Ubicación | `~/backups/aduanero/` |
| PostgreSQL | dump `-Fc` comprimido, con su `.sha256` |
| MinIO | espejo incremental de `aduanero-raw` y `aduanero-docs` |
| Retención | 14 diarios · 8 semanales (domingo) |

### ⚠️ Estos respaldos NO son suficientes por sí solos

Viven en el mismo disco que la base. Si ese disco muere, se pierden los dos.
Copiarlos fuera es obligatorio:

```bash
rsync -az ~/backups/aduanero/ otro-equipo:~/backups/aduanero/
```

Con Tailscale, cualquier nodo del equipo sirve como destino.
