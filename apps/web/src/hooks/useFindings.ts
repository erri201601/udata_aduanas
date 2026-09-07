/** Carga los pedimentos revisables y los hallazgos del seleccionado. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchPedimentoFindings, fetchPedimentos } from '../api/client'
import type { PedimentoFindings, PedimentoRead } from '../api/client'

export interface EstadoPedimentos {
  pedimentos: PedimentoRead[]
  error: string | null
  cargando: boolean
}

export function usePedimentos(): EstadoPedimentos {
  const [pedimentos, setPedimentos] = useState<PedimentoRead[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    const control = new AbortController()

    fetchPedimentos(control.signal)
      .then((filas) => {
        setPedimentos(filas)
        setError(null)
      })
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setError(causa instanceof Error ? causa.message : 'No se pudo contactar la API')
      })
      .finally(() => {
        if (!control.signal.aborted) setCargando(false)
      })

    return () => control.abort()
  }, [])

  return { pedimentos, error, cargando }
}

export interface EstadoHallazgos {
  revision: PedimentoFindings | null
  error: string | null
  cargando: boolean
}

export function usePedimentoFindings(pedimentoId: string | null): EstadoHallazgos {
  const [revision, setRevision] = useState<PedimentoFindings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const consultar = useCallback((id: string) => {
    abortRef.current?.abort()
    const control = new AbortController()
    abortRef.current = control
    setCargando(true)

    fetchPedimentoFindings(id, control.signal)
      .then((d) => {
        setRevision(d)
        setError(null)
      })
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setRevision(null)
        setError(causa instanceof Error ? causa.message : 'No se pudo contactar la API')
      })
      .finally(() => {
        if (!control.signal.aborted) setCargando(false)
      })
  }, [])

  useEffect(() => {
    if (!pedimentoId) return undefined
    // Traer datos de una API es sincronizar con un sistema externo, que es el
    // caso que la propia regla exceptúa. Misma excepción que en useReadiness.
    // eslint-disable-next-line react/set-state-in-effect
    consultar(pedimentoId)

    return () => abortRef.current?.abort()
  }, [pedimentoId, consultar])

  return { revision: pedimentoId ? revision : null, error, cargando }
}
