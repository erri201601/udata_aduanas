/**
 * Severidad de un hallazgo, y qué significa para quien lo revisa.
 *
 * El orden no es estético: es el orden de revisión. Quien audita empieza por
 * lo que puede detener la mercancía, no por lo que llegó antes.
 */

import type { Severity } from '../api/client'

export const ORDEN_SEVERIDAD: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

export const SEVERIDADES: Record<Severity, { etiqueta: string; ayuda: string }> = {
  CRITICAL: {
    etiqueta: 'Crítico',
    ayuda: 'Puede detener la mercancía o derivar en sanción. Atiéndelo primero.',
  },
  HIGH: { etiqueta: 'Alto', ayuda: 'Diferencia relevante frente a lo declarado.' },
  MEDIUM: { etiqueta: 'Medio', ayuda: 'Conviene revisarlo antes de presentar.' },
  LOW: { etiqueta: 'Bajo', ayuda: 'Diferencia menor, probablemente dentro de tolerancia.' },
  INFO: { etiqueta: 'Informativo', ayuda: 'No es un problema; se anota por trazabilidad.' },
}

/**
 * ¿Se puede llevar a un cliente?
 *
 * Un hallazgo sin impacto cuantificado se puede investigar, pero no presentar:
 * «tu fracción podría estar mal» no es accionable. Que NO sea accionable no lo
 * hace menos grave — una NOM faltante no cambia lo que se paga y aun así
 * detiene la mercancía.
 */
export function esAccionable(monto: string | number | null | undefined): boolean {
  if (monto == null) return false
  const valor = typeof monto === 'string' ? Number(monto) : monto
  return Number.isFinite(valor) && valor !== 0
}

/** Formatea un importe en pesos, sin inventar decimales que no vinieron. */
export function formatearMonto(
  monto: string | number | null | undefined,
  moneda: string | null | undefined,
): string | null {
  if (monto == null) return null
  const valor = typeof monto === 'string' ? Number(monto) : monto
  if (!Number.isFinite(valor)) return null

  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: moneda || 'MXN',
    maximumFractionDigits: 2,
  }).format(valor)
}
