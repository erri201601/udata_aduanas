# ADR 0001 — Puertos y bind del dev server

- **Fecha:** 2026-09-02
- **Estado:** aceptado
- **Decide:** Persona 1

## Contexto

El dev server (laptop de Persona 1) ya tiene procesos ajenos a ADUANERO OS:

- Un **PostgreSQL 16.15 nativo** escuchando en `5432`, de otro proyecto.
- Un **uvicorn en `8000`**, del proyecto `Conta_inteligente/Tzol_Udata`.

Además, ese PostgreSQL nativo tiene `listen_addresses = '*'` y responde tanto
en la IP de LAN (`192.168.1.58:5432`) como en la **IPv6 global** de la máquina.
Se verificó la conectividad TCP en ambas. Esto contradice §3 y §41 del documento
de Persona 1: *"nunca exponer PostgreSQL directamente a Internet"*.

## Decisión

1. La API de ADUANERO OS usa el puerto **8080**.
2. El PostgreSQL del proyecto (contenedor) publica en **5433**.
3. Cada puerto se publica **dos veces**: en `127.0.0.1` fijo (la propia
   laptop) y en `${TEAM_BIND_ADDR}` (la IP de Tailscale, para Persona 2 y 3).
   Un único binding no sirve: apuntar sólo a la IP del tailnet rompería
   `localhost` para la API y las herramientas locales de Persona 1.
   `TEAM_BIND_ADDR` vale `127.0.0.2` por defecto — loopback, así que un stack
   sin Tailscale no expone nada, y distinta de `127.0.0.1` para que los dos
   bindings no choquen. **`0.0.0.0` queda prohibido.**
4. No se modifica el PostgreSQL nativo desde este proyecto: es de otro equipo.
   Se reporta el hallazgo a su responsable.

## Consecuencias

- Cualquier documentación, script o cliente debe usar 8080 y 5433. Los tests en
  `tests/test_config.py` fijan estos valores para que nadie los "corrija".
- Tailscale quedó instalado el 2026-09-02. El dev server es `udata-nitro`,
  IP `<IP-DEL-DEV-SERVER>`. Persona 2 y 3 deben ser **invitados al tailnet** por
  Persona 1: instalar el cliente no basta.
- Si la IP de Tailscale cambia, hay que actualizar `TEAM_BIND_ADDR` en `.env`,
  `docs/ACCESO_EQUIPO.md` y recrear los contenedores. El smoke test detecta la
  discrepancia.
- Si algún día se retira el PostgreSQL nativo, migrar a 5432 exige cambiar
  `.env`, la documentación de acceso y los tests. No se hará por comodidad.

## Alternativas descartadas

- **Apagar el PostgreSQL nativo.** Rompería otro proyecto en curso; no es
  decisión de este equipo.
- **Usar el PostgreSQL nativo para ADUANERO OS.** Mezclaría el ciclo de vida de
  dos proyectos en un mismo clúster y ataría el entorno a una máquina concreta,
  en contra del objetivo de que `docker compose up -d` reproduzca el entorno.
