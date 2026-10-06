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
export type Dashboard = components['schemas']['Dashboard']
export type PendienteRead = components['schemas']['PendienteRead']
export type RevisionRequest = components['schemas']['RevisionRequest']
export type RevisionResponse = components['schemas']['RevisionResponse']
export type ServiceCheck = components['schemas']['ServiceCheck']
export type ServiceStatus = ServiceCheck['status']
export type Sentinel = components['schemas']['Sentinel']
export type PedimentoEspejo = components['schemas']['PedimentoEspejo']
export type RespuestaCopilot = components['schemas']['Respuesta']
export type Pasaje = components['schemas']['Pasaje']
export type Consulta = components['schemas']['Consulta']
export type LineaEspejo = components['schemas']['LineaEspejo']
export type RespuestaVocabulario = components['schemas']['RespuestaVocabulario']
export type VocabularioGuardado = components['schemas']['VocabularioGuardado']
export type PrecisionClasificacion = components['schemas']['PrecisionClasificacion']
export type DivergenciaRead = components['schemas']['DivergenciaRead']
export type DocumentoVigilado = components['schemas']['DocumentoVigilado']
export type OlaDeReforma = components['schemas']['OlaDeReforma']
export type NormaFueraDeVigencia = components['schemas']['NormaFueraDeVigencia']

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

export interface DnaDesdeImagen {
  product_dna_id: string
  version: number
  atributos: number
  summary: string | null
  missing_information: string[]
  minio_key: string
  content_hash: string
}

/**
 * Sube una imagen y extrae de ella el Product DNA (§16).
 *
 * No usa `pedir()` porque manda `multipart/form-data` y, sobre todo, porque
 * aquí el CUERPO DEL ERROR importa: el 503 de «no hay proveedor de visión
 * configurado» dice cuál falta, y perder ese texto dejaría al usuario con un
 * «La API respondió 503» que no le sirve para nada.
 */
export async function extraerDnaDeImagen(
  productId: string,
  imagen: File,
  signal?: AbortSignal,
): Promise<DnaDesdeImagen> {
  const cuerpo = new FormData()
  cuerpo.append('imagen', imagen)

  const respuesta = await fetch(`${API_BASE_URL}/products/${productId}/dna/from-image`, {
    method: 'POST',
    body: cuerpo,
    signal,
    headers: { Accept: 'application/json' },
  })

  if (!respuesta.ok) {
    let detalle = `La API respondió ${respuesta.status}`
    try {
      const json = (await respuesta.json()) as { detail?: string }
      if (json.detail) detalle = json.detail
    } catch {
      // Un error sin cuerpo JSON: se queda el genérico, que es mejor que nada.
    }
    throw new ApiError(detalle, respuesta.status)
  }

  return (await respuesta.json()) as DnaDesdeImagen
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

/** La precisión del §39, medida contra los veredictos humanos. */
export async function fetchPrecisionClasificacion(
  signal?: AbortSignal,
): Promise<PrecisionClasificacion> {
  return pedir<PrecisionClasificacion>('/metrics/classification', signal)
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


/** Cifras del sistema para el tablero ejecutivo. */
export async function fetchDashboard(signal?: AbortSignal): Promise<Dashboard> {
  return pedir<Dashboard>('/dashboard', signal)
}


/** Decisiones esperando a una persona, de la más antigua a la más reciente. */
/** Cuántos casos pide la bandeja: el máximo que acepta la API (`LIMITE_MAXIMO`).
 *
 * LA BANDEJA ESCONDÍA CASOS SIN DECIRLO
 *
 * Se pedía `/review` sin límite y el servidor devuelve 50 por omisión. Con 91
 * casos pendientes (6-oct), la pantalla enseñaba los 50 más antiguos y nada
 * decía que faltaban 41: nueve de los quince fregaderos que el clasificador
 * tenía que confirmar caían después del 50 y no los habría visto nunca.
 */
export const BANDEJA_MAXIMO = 200

export async function fetchPendientes(signal?: AbortSignal): Promise<PendienteRead[]> {
  return pedir<PendienteRead[]>(`/review?limit=${BANDEJA_MAXIMO}`, signal)
}

/**
 * Registra un veredicto humano.
 *
 * NO edita la decisión de la máquina: crea una fila nueva. Medir la precisión
 * del sistema exige conservar las dos respuestas (§39).
 */
export async function revisarDecision(
  decisionId: string,
  peticion: RevisionRequest,
  signal?: AbortSignal,
): Promise<RevisionResponse> {
  const respuesta = await fetch(`${API_BASE_URL}/review/${decisionId}`, {
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

  return (await respuesta.json()) as RevisionResponse
}

/**
 * Contesta una pregunta de desempate y la guarda firmada.
 *
 * Sin esto la cadena no servía para nada: el motor generaba la pregunta, la
 * consola la mostraba, la base sabía guardarla — y no había dónde contestarla.
 * Un clasificador tenía que mandar la respuesta por un chat y que alguien la
 * metiera a mano con `curl`.
 */
export async function responderVocabulario(
  peticion: RespuestaVocabulario,
  signal?: AbortSignal,
): Promise<VocabularioGuardado> {
  const respuesta = await fetch(`${API_BASE_URL}/review/vocabulario`, {
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

  return (await respuesta.json()) as VocabularioGuardado
}

/**
 * Vigilancia normativa a una fecha (§32).
 *
 * `fecha` decide qué normas cuentan como vigentes (§14): sin ella, el
 * servidor usa hoy. Se manda tal cual la escribe la pantalla, en ISO, para
 * que no haya conversión de zona horaria por el camino — es una fecha de
 * vigencia, no un instante.
 */
export async function fetchSentinel(
  fecha?: string,
  signal?: AbortSignal,
): Promise<Sentinel> {
  const ruta = fecha ? `/sentinel?fecha=${encodeURIComponent(fecha)}` : '/sentinel'
  return pedir<Sentinel>(ruta, signal)
}

/**
 * El pedimento declarado frente a su espejo (§36).
 *
 * LEE la última auditoría, no dispara una nueva: abrir una pantalla no debería
 * gastar llamadas a modelo ni escribir filas. Para auditar está
 * `POST /pedimentos/{id}/review`.
 */
export async function fetchEspejo(
  pedimentoId: string,
  signal?: AbortSignal,
): Promise<PedimentoEspejo> {
  return pedir<PedimentoEspejo>(`/pedimentos/${pedimentoId}/shadow`, signal)
}

/** Estado del corpus antes de preguntar: con qué se va a buscar. */
export async function fetchCoberturaCopilot(
  signal?: AbortSignal,
): Promise<RespuestaCopilot> {
  return pedir<RespuestaCopilot>('/copilot/cobertura', signal)
}

/**
 * Pregunta al corpus jurídico.
 *
 * Devuelve PASAJES, no una respuesta redactada. Parafrasear la ley es como se
 * producen las citas inventadas; quien lee saca la conclusión sobre el texto
 * de la norma.
 */
export async function consultarCopilot(
  consulta: Consulta,
  signal?: AbortSignal,
): Promise<RespuestaCopilot> {
  const respuesta = await fetch(`${API_BASE_URL}/copilot/consultas`, {
    method: 'POST',
    signal,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(consulta),
  })

  if (!respuesta.ok) {
    throw new ApiError(`La API respondió ${respuesta.status}`, respuesta.status)
  }

  return (await respuesta.json()) as RespuestaCopilot
}
