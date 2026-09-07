/** Carga las decisiones de clasificación y el detalle de la seleccionada. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchClassification, fetchClassifications } from '../api/client'
import type { ClassificationDecisionRead, ClassificationDetail } from '../api/client'

export interface EstadoDecisiones {
  decisiones: ClassificationDecisionRead[]
  error: string | null
  cargando: boolean
}

export function useClassifications(): EstadoDecisiones {
  const [decisiones, setDecisiones] = useState<ClassificationDecisionRead[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    const control = new AbortController()

    fetchClassifications(control.signal)
      .then((filas) => {
        setDecisiones(filas)
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

  return { decisiones, error, cargando }
}

export interface EstadoDetalle {
  detalle: ClassificationDetail | null
  error: string | null
  cargando: boolean
}

export function useClassification(decisionId: string | null): EstadoDetalle {
  const [detalle, setDetalle] = useState<ClassificationDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const consultar = useCallback((id: string) => {
    abortRef.current?.abort()
    const control = new AbortController()
    abortRef.current = control
    setCargando(true)

    fetchClassification(id, control.signal)
      .then((d) => {
        setDetalle(d)
        setError(null)
      })
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setDetalle(null)
        setError(causa instanceof Error ? causa.message : 'No se pudo contactar la API')
      })
      .finally(() => {
        if (!control.signal.aborted) setCargando(false)
      })
  }, [])

  useEffect(() => {
    if (!decisionId) return undefined
    // Traer datos de una API es sincronizar con un sistema externo, que es el
    // caso que la propia regla exceptúa. Misma excepción que en useReadiness.
    // eslint-disable-next-line react/set-state-in-effect
    consultar(decisionId)

    return () => abortRef.current?.abort()
  }, [decisionId, consultar])

  // Se deriva en vez de asignarse dentro del efecto: sin decisión no hay
  // detalle que mostrar.
  return { detalle: decisionId ? detalle : null, error, cargando }
}
