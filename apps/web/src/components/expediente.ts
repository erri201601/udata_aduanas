/** Tipos y funciones del expediente, aparte de los componentes (fast refresh). */

import type { ReactNode } from 'react'

export type Tono = 'ok' | 'mal' | 'aviso' | 'neutro'

export interface Voz {
  clave: 'declarado' | 'sugerido' | 'confirmado'
  titulo: string
  codigo: string | null | undefined
  nico?: string | null
  /** Qué decir cuando no hay código: «Pendiente» no es «Sin fracción». */
  sinCodigo?: string
  estado: { texto: string; tono: Tono }
  nota: ReactNode
  /** «coincide con lo declarado», «difiere de lo sugerido»… */
  contraste?: { texto: string; tono: Tono } | null
  accion?: ReactNode
  /** Lo que no cabe en la tarjeta: p. ej. todas las partidas declaradas. */
  extra?: ReactNode
}


/** «2026-08-19» → «19 ago 2026», sin correrlo un día por la zona horaria. */
export function fechaCorta(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString('es-MX', {
    timeZone: 'UTC',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

/** ¿Dicen la misma fracción? `null` si a alguna le falta: no hay qué comparar. */
export function contrastar(
  a: string | null | undefined,
  b: string | null | undefined,
  contra: string,
): Voz['contraste'] {
  if (!a || !b) return null
  return a === b
    ? { texto: `Coincide con lo ${contra}`, tono: 'ok' }
    : { texto: `Difiere de lo ${contra}`, tono: 'mal' }
}
