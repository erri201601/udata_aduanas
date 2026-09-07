/** Carga el catálogo y el Product DNA del producto seleccionado. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchProductDna, fetchProducts } from '../api/client'
import type { ProductDnaDetail, ProductRead } from '../api/client'

export interface EstadoCatalogo {
  productos: ProductRead[]
  error: string | null
  cargando: boolean
}

export function useProducts(): EstadoCatalogo {
  const [productos, setProductos] = useState<ProductRead[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    const control = new AbortController()

    fetchProducts(control.signal)
      .then((filas) => {
        setProductos(filas)
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

  return { productos, error, cargando }
}

export interface EstadoDna {
  dna: ProductDnaDetail | null
  error: string | null
  cargando: boolean
  recargar: () => void
}

export function useProductDna(productId: string | null): EstadoDna {
  const [dna, setDna] = useState<ProductDnaDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const consultar = useCallback(
    (id: string) => {
      abortRef.current?.abort()
      const control = new AbortController()
      abortRef.current = control
      setCargando(true)

      fetchProductDna(id, control.signal)
        .then((detalle) => {
          setDna(detalle)
          setError(null)
        })
        .catch((causa: unknown) => {
          if (control.signal.aborted) return
          setDna(null)
          setError(causa instanceof Error ? causa.message : 'No se pudo contactar la API')
        })
        .finally(() => {
          if (!control.signal.aborted) setCargando(false)
        })
    },
    [],
  )

  useEffect(() => {
    if (!productId) return undefined
    // Traer datos de una API es sincronizar con un sistema externo, que es el
    // caso que la propia regla exceptúa. Misma excepción que en useReadiness.
    // eslint-disable-next-line react/set-state-in-effect
    consultar(productId)

    return () => abortRef.current?.abort()
  }, [productId, consultar])

  return {
    // Se deriva en vez de asignarse dentro del efecto: sin producto no hay DNA
    // que mostrar, y un setState síncrono en el efecto encadena renders.
    dna: productId ? dna : null,
    error,
    cargando,
    recargar: () => productId && consultar(productId),
  }
}
