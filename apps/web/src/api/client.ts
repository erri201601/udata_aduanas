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
export type PedimentoRead = components['schemas']['PedimentoRead']
export type PedimentoFindings = components['schemas']['PedimentoFindings']
export type RiskFindingRead = components['schemas']['RiskFindingRead']
export type Severity = RiskFindingRead['severity']
export type DossierRead = components['schemas']['DossierRead']
export type ClassifyRequest = components['schemas']['ClassifyRequest']
export type ClassifyResponse = components['schemas']['ClassifyResponse']
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


/** Pedimentos revisables. */
export async function fetchPedimentos(signal?: AbortSignal): Promise<PedimentoRead[]> {
  return pedir<PedimentoRead[]>('/findings/pedimentos', signal)
}

/** Un pedimento con sus hallazgos y su cobertura declarada. */
export async function fetchPedimentoFindings(
  pedimentoId: string,
  signal?: AbortSignal,
): Promise<PedimentoFindings> {
  return pedir<PedimentoFindings>(`/findings/pedimentos/${pedimentoId}`, signal)
}


/** Dossier §49 de una decisión: las diez preguntas y lo que falta. */
export async function fetchDossier(
  decisionId: string,
  signal?: AbortSignal,
): Promise<DossierRead> {
  return pedir<DossierRead>(`/evidence/${decisionId}`, signal)
}


/**
 * Clasifica un producto y persiste la decisión.
 *
 * Es la única llamada que ESCRIBE. `operation_date` es obligatoria: clasificar
 * con la tarifa de hoy una operación de 2024 da un resultado que parece
 * correcto y no lo es (§14).
 */
export async function classifyProduct(
  productId: string,
  peticion: ClassifyRequest,
  signal?: AbortSignal,
): Promise<ClassifyResponse> {
  const respuesta = await fetch(`${API_BASE_URL}/products/${productId}/classify`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(peticion),
  })

  if (!respuesta.ok) {
    const detalle = await respuesta.json().catch(() => null)
    throw new ApiError(
      detalle?.detail ?? `La API respondió ${respuesta.status}`,
      respuesta.status,
    )
  }

  return (await respuesta.json()) as ClassifyResponse
}
