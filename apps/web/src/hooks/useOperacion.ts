/** La fila del Panorama de un pedimento: lo que su cabecera de expediente lee. */

import { useEffect, useState } from 'react'

import { fetchOperacion } from '../api/client'
import type { Operacion } from '../api/client'

/**
 * `version` vuelve a pedirla (tras «Revisar ahora», la revisión cambió).
 *
 * Si falla, devuelve `null` y la pantalla sigue sin cabecera: esconder el
 * espejo o los hallazgos por no poder pintar la cabecera sería peor. Nunca
 * devuelve la de otro pedimento mientras llega la nueva.
 */
export function useOperacion(pedimentoId: string | null, version = 0): Operacion | null {
  const [operacion, setOperacion] = useState<Operacion | null>(null)

  useEffect(() => {
    if (!pedimentoId) return
    const control = new AbortController()
    fetchOperacion(pedimentoId, control.signal)
      .then(setOperacion)
      .catch(() => {
        if (!control.signal.aborted) setOperacion(null)
      })
    return () => control.abort()
  }, [pedimentoId, version])

  return operacion?.pedimento_id === pedimentoId ? operacion : null
}
