# ADR 0024 — Identidad de la consola y Panorama operativo como inicio

- **Fecha:** 2026-10-21
- **Estado:** aceptado (2026-10-21, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.

## Contexto

La consola abría en un tablero de indicadores. Al entrar no se veía qué
requería atención, en qué estaba cada pedimento ni cuál era la siguiente
acción. El menú mezclaba nombres en inglés y en español, y no se agrupaba por
tareas. El aspecto, de herramienta genérica, no correspondía a un centro de
control de revisión aduanal.

## Decisión

1. **Inicio en «Panorama operativo»**, servido por `GET /dashboard/operacion`:
   - asuntos que esperan a alguien;
   - operaciones con su estado de revisión;
   - siguiente acción derivada de los datos.

   Cuenta lo del documento una sola vez por pedimento, con el mismo criterio
   que el tablero (#224). Los indicadores de antes siguen disponibles en un
   desplegable.
2. **Menú agrupado** en Operación, Control y cumplimiento, Consulta y
   Administración. Los `id` internos no cambian; sólo cambian las etiquetas.
   Se descartaron estos nombres:
   - «Pedimento espejo»: suena a simulación.
   - «Aprobación»: suena a autorización oficial.
3. **Tokens de identidad** en `index.css`:
   - marino `#142B3D` para la navegación;
   - verde petróleo `#136F68` para la acción principal;
   - fondo `#F3F5F4` y texto `#182B36`;
   - ámbar, rojo y verde sólo como estado, siempre con texto o icono.

   La estructura nueva está en `estilos/identidad.css`.
4. **Tipografía IBM Plex Sans y Plex Mono**, servida desde
   `@fontsource`, con versión exacta y sin CDN. La monoespaciada se usa en
   folios, fracciones y claves.
5. **Iconos SVG en línea**, sin librería nueva.
6. **Lenguaje de la revisión.** «Revisión completa» se refiere a la revisión
   espejo interna. La pantalla dice expresamente que no es una validación del
   SAT ni una autorización de despacho. En Estado del sistema se aclara que
   disponibilidad de infraestructura no equivale a operaciones validadas.

## Consecuencias

- Se agregan dos dependencias de fuentes, de unos 24 kB por peso (woff2 latin).
- Desde 1024 px de ancho, las operaciones se leen como fichas en lugar de tabla.
- Pendiente: las pantallas que no se tocaron heredan los tokens, pero
  conservan su maquetación anterior.
