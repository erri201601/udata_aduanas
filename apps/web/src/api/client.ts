/**
 * Cliente HTTP de la API.
 *
 * Los tipos NO se escriben a mano: salen de `schema.d.ts`, generado desde
 * el `openapi.json` del servidor con `npm run gen:api`.
 */

import { API_BASE_URL } from '../config'
import type { components } from './schema'

export type ReadinessResponse = components['schemas']['ReadinessResponse']
export type ProductRead = components['schemas']['ProductRead']
export type ProductDnaDetail = components['schemas']['ProductDnaDetail']
export type ProductAttributeRead = components['schemas']['ProductAttributeRead']
export type AttributeStatus = ProductAttributeRead['status']
export type ClassificationDecisionRead = components['schemas']['ClassificationDecisionRead']
export type ClassificationDetail = components['schemas']['ClassificationDetail']
export type ClassificationCandidateRead = components['schemas']['ClassificationCandidateRead']
export type EvidenceRecordRead = components['schemas']['EvidenceRecordRead']
export type EvidenceKind = NonNullable<EvidenceRecordRead['evidence_kind']>
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


/** Catálogo de productos. */
export async function fetchProducts(
  signal?: AbortSignal,
): Promise<ProductRead[]> {
  return pedir<ProductRead[]>('/products', signal)
}

/** Product DNA vigente de un producto, con sus atributos. */
export async function fetchProductDna(
  productId: string,
  signal?: AbortSignal,
): Promise<ProductDnaDetail> {
  return pedir<ProductDnaDetail>(`/products/${productId}/dna`, signal)
}

async function pedir<T>(ruta: string, signal?: AbortSignal): Promise<T> {
  const respuesta = await fetch(`${API_BASE_URL}${ruta}`, {
    signal,
    headers: { Accept: 'application/json' },
  })

  if (!respuesta.ok) {
    throw new ApiError(
      respuesta.status === 404
        ? 'No se encontró el recurso solicitado.'
        : `La API respondió ${respuesta.status}`,
      respuesta.status,
    )
  }

  return (await respuesta.json()) as T
}


/** Decisiones de clasificación, de la más reciente a la más antigua. */
export async function fetchClassifications(
  signal?: AbortSignal,
): Promise<ClassificationDecisionRead[]> {
  return pedir<ClassificationDecisionRead[]>('/classifications', signal)
}

/** Una decisión con sus candidatos y evidencias. */
export async function fetchClassification(
  decisionId: string,
  signal?: AbortSignal,
): Promise<ClassificationDetail> {
  return pedir<ClassificationDetail>(`/classifications/${decisionId}`, signal)
}
