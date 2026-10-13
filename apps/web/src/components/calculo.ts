/** El sobre del §22 tal como llega de la API (`impact_calculation`). */

export interface CalculoMonetario {
  formula: string
  inputs: Record<string, string>
  result: string
  currency: string | null
  calculation_version: string
  assumptions: string[]
  source_ids: string[]
  is_simulation: boolean
}

/** El sobre llega como un objeto genérico del OpenAPI; se comprueba lo mínimo. */
export function comoCalculo(valor: unknown): CalculoMonetario | null {
  if (!valor || typeof valor !== 'object') return null
  const c = valor as Partial<CalculoMonetario>
  if (typeof c.formula !== 'string' || typeof c.result !== 'string') return null
  return {
    formula: c.formula,
    inputs: c.inputs ?? {},
    result: c.result,
    currency: c.currency ?? null,
    calculation_version: c.calculation_version ?? '—',
    assumptions: c.assumptions ?? [],
    source_ids: c.source_ids ?? [],
    is_simulation: c.is_simulation ?? true,
  }
}
