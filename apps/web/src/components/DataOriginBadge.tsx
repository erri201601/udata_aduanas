/**
 * Marcado de procedencia del dato (§33 del maestro, regla 4 de CLAUDE.md).
 *
 * No es decoración: que alguien confunda un pedimento simulado con uno real
 * en una demo es el peor fallo posible de este producto. Todo dato operativo
 * dummy se marca SYNTHETIC DEMO DATA de forma visible.
 *
 * LO QUE LA REGLA 4 NO DICE
 *
 * Dice que lo SYNTHETIC se marca. No dice que se marque todo. Marcar como
 * simulado un dato que una persona validó es mentir en la otra dirección, y
 * encima gasta la marca: si las diez pantallas dicen SYNTHETIC, nadie la lee
 * en la única donde era verdad. Por eso el aviso recibe el origen del dato y
 * sólo grita cuando toca.
 *
 * Sin origen sigue avisando de simulado: no saber de dónde viene un dato no
 * autoriza a presentarlo como real.
 */

export type DataOrigin = 'SYNTHETIC' | 'OFFICIAL' | 'PUBLIC' | 'LICENSED' | 'HUMAN_VALIDATED'

/* Los cinco valores de la regla 3, no cuatro. Faltaba HUMAN_VALIDATED —el que
   escribe la revisión humana— y `ETIQUETAS[origin]` devolvía `undefined`: la
   insignia salía en blanco, con su borde y sin texto, justamente sobre el dato
   que más respaldo tiene. Quinta vez en este proyecto que un valor se escribe
   en la base y nadie lo lee de vuelta. */
const ETIQUETAS: Record<DataOrigin, string> = {
  SYNTHETIC: 'SYNTHETIC DEMO DATA',
  OFFICIAL: 'OFFICIAL SOURCE',
  PUBLIC: 'PUBLIC SOURCE',
  LICENSED: 'LICENSED SOURCE',
  HUMAN_VALIDATED: 'VALIDADO POR UNA PERSONA',
}

/** Qué significa cada origen, para quien no vive dentro del proyecto. */
const AYUDAS: Record<DataOrigin, string> = {
  SYNTHETIC: 'Dato inventado para la demo. No describe ninguna operación real.',
  OFFICIAL: 'Viene de una fuente oficial almacenada, con su hash y su vigencia.',
  PUBLIC: 'Viene de una fuente pública almacenada.',
  LICENSED: 'Viene de una fuente licenciada almacenada.',
  HUMAN_VALIDATED: 'Una persona lo revisó y lo sostuvo con su nombre.',
}

function esConocido(origin: string): origin is DataOrigin {
  return origin in ETIQUETAS
}

export function DataOriginBadge({ origin }: { origin: string }) {
  /* Un valor fuera de los cinco se dice tal cual en vez de salir en blanco:
     un origen que no reconocemos es un dato del que no podemos responder, y
     callarlo lo haría pasar por correcto. */
  if (!esConocido(origin)) {
    return (
      <span className="badge-origen badge-origen--desconocido" title="Origen no reconocido.">
        ORIGEN DESCONOCIDO: {origin}
      </span>
    )
  }
  return (
    <span
      className={`badge-origen badge-origen--${origin.toLowerCase()}`}
      title={AYUDAS[origin]}
    >
      {ETIQUETAS[origin]}
    </span>
  )
}

/** Aviso a pantalla completa con la procedencia de lo que se está viendo.
 *
 * `origin` ausente = se asume simulado, que es el lado prudente del error.
 */
export function SyntheticBanner({ origin }: { origin?: string | null } = {}) {
  const real = origin ?? 'SYNTHETIC'
  const simulado = real === 'SYNTHETIC'
  return (
    <div
      className={`aviso-sintetico${simulado ? '' : ' aviso-sintetico--real'}`}
      role="note"
    >
      <DataOriginBadge origin={real} />
      <p>
        {simulado
          ? 'Operación simulada. Motor y fuentes reales.'
          : 'Dato real. El motor y las fuentes son los mismos que en la operación simulada.'}
      </p>
    </div>
  )
}
