# ADUANERO OS — Accesos para el equipo

**Para:** Persona 2 (Data Engineer) y Persona 3 (AI/Full Stack)
**Administra:** Persona 1

---

## Aquí ya no están las coordenadas, y es a propósito

Este documento tenía la IP del dev server, su nombre de host, los puertos de
cada servicio y los usuarios de Postgres, Neo4j y MinIO. **El repositorio es
público desde el 28 de septiembre de 2026**, y esa tabla no era una
configuración: era un mapa.

Ninguna contraseña estuvo nunca aquí —eso se hizo bien desde el principio—
pero un mapa con usuarios, puertos y direcciones le ahorra el reconocimiento a
cualquiera que algún día llegue a la red. El rol de Postgres es superusuario.

**Cómo se piden ahora:** a Persona 1, por canal seguro. Entrega la dirección,
el usuario y la contraseña juntos, y ninguno de los tres se escribe en el
repositorio, ni en un chat, ni «temporalmente».

**Requisito previo:** hay que estar invitado al tailnet. Sin eso no se alcanza
nada: los servicios escuchan sólo en loopback y en la IP del tailnet, nunca en
la LAN ni en Internet.

**Cómo las usan las herramientas:** por variable de entorno en la sesión que
las necesita, nunca en `.env` compartido ni en el código.

```bash
umask 077
export ADUANERO_SHARED_URL='postgresql+psycopg://<USUARIO>:<PASSWORD>@<HOST>:<PUERTO>/<BASE>'
python -m apps.evaluacion.deteccion_26 --target shared --escenarios
```

Desde la laptop de Persona 1 no hace falta: allí `--target local` **ya es** la
base del equipo.

---

## Qué hay en la base, y quién escribe en cada esquema

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

## Neo4j, Redis, MinIO y la API

Sus direcciones y usuarios salían aquí y se fueron por lo mismo. Lo que sí
conviene que siga escrito, porque son decisiones y no coordenadas:

- La API usa el puerto **8080**, no 8000 (ADR 0001).
- Postgres usa el **5433**, no 5432: el 5432 lo ocupa una instancia ajena al
  proyecto en esa máquina.
- MinIO guarda el RAW versionado. Nada se inserta NORMALIZED sin su RAW.
- El grafo de Neo4j es **proyección** de Postgres, nunca fuente (§28).

---

## 7. Rotación de credenciales

Si una credencial se filtra (commit accidental, captura de pantalla, chat):

1. Avisar a Persona 1 de inmediato.
2. Persona 1 cambia el valor en `.env`.
3. `docker compose down && docker compose up -d`.
4. Para Postgres el cambio no es automático — hay que hacer
   `ALTER ROLE aduanero_app WITH PASSWORD '...'` dentro del contenedor.
5. Reemitir credenciales al equipo por canal seguro.
