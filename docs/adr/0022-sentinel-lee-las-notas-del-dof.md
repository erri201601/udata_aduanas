# ADR 0022 — Sentinel lee las notas del DOF y las cruza con los clientes

- **Fecha:** 2026-10-21
- **Estado:** aceptado (2026-10-21, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.

## Contexto

El vigilante del DOF (`watcher_cli`, dos veces al día) captura del sumario el
título y el enlace de cada publicación de comercio exterior. Al 21-oct tenía 5
eventos, entre ellos el decreto del 13-oct-2026 que deja exenta la 9803.00.01
y dos consultas para cancelar NOM. Pero en todos **`affected_fraction_codes`
estaba vacío y `effective_date` sin fecha**. El cargador lo dejaba escrito:
«identificar qué fracción afecta un decreto exige leer el documento completo».
Sentinel sólo podía contar eventos; no podía decir a quién tocaban.

## Decisión

1. **El vigilante lee la nota de cada evento** después del sumario
   (`ingestion.dof.afectacion`), y lo mismo hace `--solo-notas` para los
   pendientes. Cada nota va a RAW con el hash en la clave
   (`dof/notas/{codigo}_{sha16}.html`), y el hash queda en el evento
   (`note_content_hash`, migración nueva). `NULL` significa «no leída», que
   no es lo mismo que «no afecta».
2. **Qué se extrae:**
   - **Fracciones:** las que la nota cita, en sus tablas o en el texto, sin la
     columna lateral del DOF (tipo de cambio, encuestas).
   - **NOM:** sólo las del título. El cuerpo trae menciones de paso: el
     Código de Conducta de la SE cita la NOM-046-SSA2 sin relación con
     comercio exterior.
   - **Entrada en vigor:** del transitorio, sólo si es inequívoca («al día
     siguiente», «el día de su publicación», una fecha escrita, incluido
     «el primero de enero»). La «vigencia de N años» da `valid_to`. Un aviso
     de consulta pública no entra en vigor y su fecha queda vacía.
3. **Sentinel cruza** cada uno de los 15 eventos más recientes con lo que los
   clientes **declaran** (`pedimento_items`) o tienen **clasificado**
   (`classification_decisions`):
   - directamente, por las fracciones citadas;
   - o a través de la NOM, por las fracciones que exigen esa NOM según el
     Anexo 2.4.1 vigente.

   Dice cuántas partidas toca y si **todas son SYNTHETIC** (§33): impacto
   sobre la demo, no sobre un cliente real.
4. **Pantalla:** sección «Lo que publicó el DOF y a quién toca», con la fecha
   de entrada en vigor, las NOM, las fracciones de clientes y el aviso
   «nota aún sin leer» cuando corresponde.

## Lo que no hace

- No deduce fracciones que la nota no cita. Una publicación que cambia una
  regla sin nombrar fracciones no «toca» ninguna aquí; sólo dice que no cita
  fracciones.
- No interpreta el contenido del decreto (si sube o baja una tasa). Eso es el
  versionado de la tarifa por decreto (ADR 0018, parte 2).
