/** Carga el dossier §49 de la decisión seleccionada. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchClassifications, fetchDossier } from '../api/client'
import type { DecisionEnLista, DossierRead } from '../api/client'

export interface EstadoDossier {
  dossier: DossierRead | null
  decisiones: DecisionEnLista[]
  error: string | null
  cargando: boolean
}

export function useDossier(decisionId: string | null): {
  dossier: DossierRead | null
  error: string | null
  cargando: boolean
} {
  const [dossier, setDossier] = useState<DossierRead | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const consultar = useCallback((id: string) => {
    abortRef.current?.abort()
    const control = new AbortController()
    abortRef.current = control
    setCargando(true)

    fetchDossier(id, control.signal)
      .then((d) => {
        setDossier(d)
        setError(null)
      })
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setDossier(null)
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

  return { dossier: decisionId ? dossier : null, error, cargando }
}

/** Las decisiones disponibles para auditar. */
export function useDecisionesAuditables(): {
  decisiones: DecisionEnLista[]
  error: string | null
  cargando: boolean
} {
  const [decisiones, setDecisiones] = useState<DecisionEnLista[]>([])
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
