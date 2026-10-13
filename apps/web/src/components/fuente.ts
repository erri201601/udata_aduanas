/** Una fila que sostiene un hallazgo (§21), tal como llega en `sources`. */
export interface Fuente {
  what: string
  table: string
  row_id: string | null
  document: string | null
  url: string | null
  content_hash: string | null
  valid_from: string | null
  valid_to: string | null
  data_origin: string | null
}

/** Las fuentes llegan como objetos genéricos del OpenAPI; se comprueba lo mínimo. */
export function comoFuentes(valor: unknown): Fuente[] {
  if (!Array.isArray(valor)) return []
  return valor
    .filter((f): f is Record<string, unknown> => !!f && typeof f === 'object')
    .filter((f) => typeof f.what === 'string' && typeof f.table === 'string')
    .map((f) => ({
      what: f.what as string,
      table: f.table as string,
      row_id: (f.row_id as string) ?? null,
      document: (f.document as string) ?? null,
      url: (f.url as string) ?? null,
      content_hash: (f.content_hash as string) ?? null,
      valid_from: (f.valid_from as string) ?? null,
      valid_to: (f.valid_to as string) ?? null,
      data_origin: (f.data_origin as string) ?? null,
    }))
}
