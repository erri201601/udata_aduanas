/** Consulta el readiness al montar y lo refresca en intervalo fijo. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchReadiness } from '../api/client'
import type { ReadinessResponse } from '../api/client'
import { HEALTH_POLL_MS } from '../config'

export interface EstadoReadiness {
  datos: ReadinessResponse | null
  error: string | null
  cargando: boolean
  consultadoEn: Date | null
  recargar: () => void
}

export function useReadiness(): EstadoReadiness {
  const [datos, setDatos] = useState<ReadinessResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [consultadoEn, setConsultadoEn] = useState<Date | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // `marcarCarga` va en falso en el arranque: el estado ya nace en `true`,
  // y llamar a setState de forma síncrona dentro del efecto encadena renders.
  const consultar = useCallback(async (marcarCarga = true) => {
    abortRef.current?.abort()
    const control = new AbortController()
    abortRef.current = control
    if (marcarCarga) setCargando(true)

    try {
      const respuesta = await fetchReadiness(control.signal)
      setDatos(respuesta)
      setError(null)
      setConsultadoEn(new Date())
    } catch (causa) {
      if (control.signal.aborted) return
      // Un fallo de red aquí casi siempre es Tailscale caído o la API apagada.
      setError(
        causa instanceof Error
          ? causa.message
          : 'No se pudo contactar la API',
      )
    } finally {
      if (!control.signal.aborted) setCargando(false)
    }
  }, [])

  useEffect(() => {
    // La regla no puede rastrear que `marcarCarga: false` evita el setState
    // síncrono. Sondear una API es precisamente sincronizar con un sistema
    // externo, que es el caso que la propia regla exceptúa.
    // eslint-disable-next-line react/set-state-in-effect
    void consultar(false)
    const temporizador = window.setInterval(() => void consultar(), HEALTH_POLL_MS)

    return () => {
      window.clearInterval(temporizador)
      abortRef.current?.abort()
    }
  }, [consultar])

  return { datos, error, cargando, consultadoEn, recargar: () => void consultar() }
}
