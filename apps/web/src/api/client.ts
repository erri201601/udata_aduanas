/**
 * Cliente HTTP de la API.
 *
 * Los tipos NO se escriben a mano: salen de `schema.d.ts`, generado desde
 * el `openapi.json` del servidor con `npm run gen:api`.
 */

import { API_BASE_URL } from '../config'
import type { components } from './schema'

export type ReadinessResponse = components['schemas']['ReadinessResponse']
export type ServiceCheck = components['schemas']['ServiceCheck']
export type ServiceStatus = ServiceCheck['status']

/** Error de la API con el código HTTP, para distinguirlo de un fallo de red. */
export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * Consulta el readiness: estado de Postgres, Redis, Neo4j y MinIO.
 * Es el único endpoint con datos reales disponible hoy.
 */
export async function fetchReadiness(
  signal?: AbortSignal,
): Promise<ReadinessResponse> {
  const respuesta = await fetch(`${API_BASE_URL}/health/ready`, {
    signal,
    headers: { Accept: 'application/json' },
  })

  if (!respuesta.ok) {
    throw new ApiError(
      `La API respondió ${respuesta.status}`,
      respuesta.status,
    )
  }

  return (await respuesta.json()) as ReadinessResponse
}
