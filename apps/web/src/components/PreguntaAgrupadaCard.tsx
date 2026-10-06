/**
 * Una pregunta del motor, con cuántos casos desatasca y los casos detrás.
 *
 * POR QUÉ LA BANDEJA EMPIEZA POR AQUÍ (6-oct)
 *
 * Medido: 119 casos pendientes, 30 con pregunta, y eran CUATRO preguntas
 * repetidas. Una respuesta vale para todos los casos que la comparten, pero la
 * pantalla enseñaba una tarjeta por caso con la pregunta dentro: para dar con
 * la que valía 14 había que bajar hasta la séptima. El tiempo del clasificador
 * es el recurso más escaso del proyecto, y la pantalla lo trataba como si
 * fuera infinito.
 *
 * LO QUE ESTA TARJETA NO HACE
 *
 * No decide qué preguntas se enseñan: las da el motor, y si una no mueve nada
 * se silencia allí, no aquí. Y no calcula «aplica a X de 14»: eso exigiría
 * copiar en el navegador la regla de emparejamiento del motor, y esa copia ya
 * se desvió una vez. El número real lo dice el servidor al contestar.
 */

import { useState } from 'react'

import type { PreguntaAgrupada } from '../api/client'
import { ContestarPregunta } from './ContestarPregunta'
import { DataOriginBadge } from './DataOriginBadge'

/** Cuántas fichas distintas se enseñan antes de resumir el resto. */
const FICHAS_VISIBLES = 3

interface Props {
  pregunta: PreguntaAgrupada
  onGuardada: (recalculando: number) => void
}

export function PreguntaAgrupadaCard({ pregunta, onGuardada }: Props) {
  const [verCasos, setVerCasos] = useState(false)
  const n = pregunta.casos.length
  const resto = pregunta.fichas.length - FICHAS_VISIBLES

  return (
    <li className="pregunta-grupo">
      <p className="pregunta-grupo__titular">
        <strong>
          {n} caso{n === 1 ? '' : 's'}
        </strong>{' '}
        · <code>{pregunta.codigo}</code> exige «{pregunta.exige}»
      </p>

      {/* Todas las fichas distintas, no sólo la primera: si son varias, la
          respuesta puede no valer igual para todas, y quien contesta tiene que
          verlo antes de elegir el término. */}
      <ul className="pregunta-grupo__fichas">
        {pregunta.fichas.slice(0, FICHAS_VISIBLES).map((ficha) => (
          <li key={ficha}>La ficha dice: {ficha}</li>
        ))}
        {resto > 0 && (
          <li className="pregunta-grupo__mas">
            …y {resto} ficha{resto === 1 ? '' : 's'} distinta{resto === 1 ? '' : 's'} más
            (en «ver los casos»)
          </li>
        )}
      </ul>

      {pregunta.fichas.length > 1 && (
        <p className="pregunta-grupo__aviso">
          Las fichas no dicen lo mismo. Tu respuesta se aplica a las que digan el
          término que elijas; las demás seguirán preguntando.
        </p>
      )}

      {pregunta.tambien_en.length > 0 && (
        <p className="pregunta-grupo__aviso">
          La misma cláusula aparece en {pregunta.tambien_en.join(', ')}. Contestar
          aquí también la contesta allí.
        </p>
      )}

      <ContestarPregunta
        exige={pregunta.exige}
        codigo={pregunta.codigo}
        mercancia={pregunta.fichas}
        onGuardada={onGuardada}
      />

      <button
        type="button"
        className="boton boton--plano pregunta-grupo__ver"
        onClick={() => setVerCasos((v) => !v)}
        aria-expanded={verCasos}
      >
        {verCasos ? 'ocultar los casos ▴' : `ver ${n === 1 ? 'el caso' : `los ${n}`} ▾`}
      </button>

      {verCasos && (
        <ul className="pregunta-grupo__casos">
          {pregunta.casos.map((caso) => (
            <li key={caso.decision_id}>
              <DataOriginBadge origin={caso.data_origin} />{' '}
              <strong>{caso.producto ?? 'Producto sin nombre'}</strong>
              {caso.sku && <code className="revision-fila__sku">{caso.sku}</code>}
              <span className="pregunta-grupo__caso-meta">
                {caso.fraction_code ?? 'sin fracción'} · operación del{' '}
                {caso.operation_date}
              </span>
              {pregunta.fichas.length > 1 && (
                <span className="pregunta-grupo__caso-ficha">{caso.mercancia}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}
