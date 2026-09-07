/**
 * Estado de un atributo del Product DNA (§16).
 *
 * No es decoración. Un dato leído de una ficha técnica y uno deducido por un
 * modelo no pueden verse igual: de eso depende que un agente aduanal confíe o
 * no en la clasificación que venga después. Cada estado lleva su propio color
 * y su explicación, para que la distinción no dependa de recordar qué
 * significa una palabra en inglés.
 */

import type { AttributeStatus } from '../api/client'

interface Descripcion {
  etiqueta: string
  ayuda: string
}

const ESTADOS: Record<AttributeStatus, Descripcion> = {
  OBSERVED: {
    etiqueta: 'Observado',
    ayuda: 'Aparece literal en el documento.',
  },
  EXTRACTED: {
    etiqueta: 'Extraído',
    ayuda: 'Está en el documento, pero hubo que interpretarlo o convertirlo.',
  },
  INFERRED: {
    etiqueta: 'Inferido',
    ayuda: 'No aparece: lo dedujo un modelo. Revísalo antes de confiar en él.',
  },
  MISSING: {
    etiqueta: 'Ausente',
    ayuda: 'El documento no lo aporta. El sistema no lo inventa.',
  },
}

export function AttributeStatusBadge({ status }: { status: AttributeStatus }) {
  const { etiqueta, ayuda } = ESTADOS[status]

  return (
    <span
      className={`estado estado--${status.toLowerCase()}`}
      title={ayuda}
      aria-label={`${etiqueta}. ${ayuda}`}
    >
      {etiqueta}
    </span>
  )
}

/** Barra de confianza. Sin confianza declarada no se pinta nada. */
export function ConfidenceMeter({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="sin-dato">—</span>

  const porcentaje = Math.round(value * 100)
  // El umbral no es estético: por debajo de 0.7 el dato no debería sostener
  // una clasificación por sí solo.
  const nivel = porcentaje >= 90 ? 'alta' : porcentaje >= 70 ? 'media' : 'baja'

  return (
    <span className="confianza" title={`Confianza declarada: ${porcentaje}%`}>
      <span className="confianza__pista">
        <span
          className={`confianza__valor confianza__valor--${nivel}`}
          style={{ width: `${porcentaje}%` }}
        />
      </span>
      <span className="confianza__cifra">{porcentaje}%</span>
    </span>
  )
}
