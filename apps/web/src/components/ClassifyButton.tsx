/**
 * Dispara una clasificación desde la pantalla de Product DNA.
 *
 * Es lo que convierte el sistema en algo que se puede enseñar: hasta ahora
 * todas las pantallas leían un caso precargado. Con esto, alguien ve el
 * sistema clasificar delante de él y salta a la traza.
 *
 * La fecha de operación es obligatoria y editable, no un «hoy» implícito:
 * clasificar con la tarifa de hoy una operación de 2024 da un resultado que
 * parece correcto y no lo es (§14). Que el usuario la vea y la escriba es
 * parte de que entienda lo que está pidiendo.
 */

import { useState } from 'react'

import { classifyProduct } from '../api/client'
import type { ClassifyResponse } from '../api/client'

interface Props {
  productId: string
  /** Se llama con la decisión creada, para saltar a la traza. */
  onClasificado: (resultado: ClassifyResponse) => void
}

/** Hoy en formato ISO, que es lo que espera un `<input type="date">`. */
function hoy(): string {
  return new Date().toISOString().slice(0, 10)
}

export function ClassifyButton({ productId, onClasificado }: Props) {
  const [fecha, setFecha] = useState(hoy)
  const [corriendo, setCorriendo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  async function ejecutar() {
    setCorriendo(true)
    setError(null)
    setAviso(null)

    try {
      const resultado = await classifyProduct(productId, {
        operation_date: fecha,
        trade_flow: 'IMPORT',
        search_terms: [],
      })

      // Que el motor no resolviera NO es un error: es un resultado legítimo y
      // se persistió igual. Saber que el sistema no pudo, y por qué, vale
      // tanto como el código cuando sí puede.
      if (resultado.classified_without_legal_notes) {
        setAviso(
          'Se clasificó sin notas de sección ni capítulo: todavía no hay ' +
            'corpus jurídico cargado, así que no se pudo descartar ninguna ' +
            'partida por exclusión. El resultado es menos fundamentado.',
        )
      }

      onClasificado(resultado)
    } catch (causa: unknown) {
      setError(causa instanceof Error ? causa.message : 'No se pudo clasificar')
    } finally {
      setCorriendo(false)
    }
  }

  return (
    <div className="clasificar">
      <div className="clasificar__control">
        <label>
          <span>Fecha de la operación</span>
          <input
            type="date"
            value={fecha}
            onChange={(e) => setFecha(e.target.value)}
            max={hoy()}
          />
        </label>
        <button className="boton" onClick={ejecutar} disabled={corriendo || !fecha}>
          {corriendo ? 'Clasificando…' : 'Clasificar'}
        </button>
      </div>

      <p className="clasificar__nota">
        Determina qué tarifa regía. No se usa la de hoy para una operación
        pasada.
      </p>

      {error && (
        <p className="clasificar__error" role="alert">
          {error}
        </p>
      )}

      {aviso && (
        <p className="clasificar__aviso" role="note">
          {aviso}
        </p>
      )}
    </div>
  )
}
