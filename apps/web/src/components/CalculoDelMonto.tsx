/**
 * Cómo sale una cifra (§22): fórmula, entradas, versión, supuestos y fuentes.
 *
 * Un importe solo —«se movería 15 000 MXN»— se tiene que creer. Con esto se
 * puede rehacer a mano, que es lo que un agente aduanal necesita para firmarlo.
 * Va plegado: quien sólo quiere el número no lo ve, y quien duda lo abre.
 */

import type { CalculoMonetario } from './calculo'

export function CalculoDelMonto({ calculo }: { calculo: CalculoMonetario }) {
  return (
    <details className="calculo">
      <summary>Cómo sale esta cifra</summary>
      <p>
        <code>{calculo.formula}</code> = <strong>{calculo.result}</strong>{' '}
        {calculo.currency ?? ''}
      </p>
      <dl className="calculo__entradas">
        {Object.entries(calculo.inputs).map(([nombre, valor]) => (
          <div key={nombre}>
            <dt>{nombre}</dt>
            <dd>
              <code>{valor}</code>
            </dd>
          </div>
        ))}
      </dl>
      {calculo.assumptions.length > 0 && (
        <p className="calculo__nota">Supuestos: {calculo.assumptions.join(' · ')}</p>
      )}
      <p className="calculo__nota">
        Versión del cálculo {calculo.calculation_version}
        {calculo.source_ids.length > 0 && ` · ${calculo.source_ids.length} fuente(s)`}
        {calculo.is_simulation && ' · simulación: alguna entrada es sintética'}
      </p>
    </details>
  )
}
