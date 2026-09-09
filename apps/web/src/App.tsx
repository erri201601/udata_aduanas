import { useState } from 'react'

import { Placeholder } from './screens/Placeholder'
import { Classification } from './screens/Classification'
import { Evidence } from './screens/Evidence'
import { ExecutiveDashboard } from './screens/ExecutiveDashboard'
import { Findings } from './screens/Findings'
import { HumanReview } from './screens/HumanReview'
import { ProductDna } from './screens/ProductDna'
import { RegulatorySentinel } from './screens/RegulatorySentinel'
import { SystemStatus } from './screens/SystemStatus'
import { PANTALLAS } from './screens/registro'

export default function App() {
  const [activa, setActiva] = useState(PANTALLAS[0].id)
  // La decisión recién creada, para que Classification abra en ella en vez de
  // en la primera de la lista. Se limpia al navegar a mano.
  const [decisionNueva, setDecisionNueva] = useState<string | null>(null)
  const pantalla = PANTALLAS.find((p) => p.id === activa) ?? PANTALLAS[0]

  function irA(id: string, decisionId?: string) {
    setDecisionNueva(decisionId ?? null)
    setActiva(id)
  }

  return (
    <div className="app">
      <nav className="lateral">
        <div className="marca">
          <strong>ADUANERO OS</strong>
          <span>consola</span>
        </div>

        <ul className="menu">
          {PANTALLAS.map((p) => (
            <li key={p.id}>
              <button
                className={`menu__item ${p.id === activa ? 'menu__item--activo' : ''}`}
                onClick={() => irA(p.id)}
                aria-current={p.id === activa ? 'page' : undefined}
              >
                <span>{p.titulo}</span>
                {!p.implementada && <em className="menu__pendiente">pendiente</em>}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <main className="contenido">
        {pantalla.id === 'executive-dashboard' && <ExecutiveDashboard />}
        {pantalla.id === 'system-status' && <SystemStatus />}
        {pantalla.id === 'product-dna' && (
          <ProductDna
            onClasificado={(decisionId) => irA('classification', decisionId)}
          />
        )}
        {pantalla.id === 'classification' && (
          <Classification decisionInicial={decisionNueva} />
        )}
        {pantalla.id === 'finding-detail' && <Findings />}
        {pantalla.id === 'evidence' && <Evidence />}
        {pantalla.id === 'human-review' && <HumanReview />}
        {pantalla.id === 'regulatory-sentinel' && <RegulatorySentinel />}
        {!pantalla.implementada && (
          <Placeholder titulo={pantalla.titulo} descripcion={pantalla.descripcion} />
        )}
      </main>
    </div>
  )
}
