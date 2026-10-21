import { useEffect, useState } from 'react'

import { Icono } from './components/Icono'
import { Placeholder } from './screens/Placeholder'
import { Classification } from './screens/Classification'
import { Copilot } from './screens/Copilot'
import { Evidence } from './screens/Evidence'
import { PanoramaOperativo } from './screens/PanoramaOperativo'
import { Findings } from './screens/Findings'
import { HumanReview } from './screens/HumanReview'
import { PedimentoShadow } from './screens/PedimentoShadow'
import { ProductDna } from './screens/ProductDna'
import { RegulatorySentinel } from './screens/RegulatorySentinel'
import { SystemStatus } from './screens/SystemStatus'
import { GRUPOS, PANTALLAS } from './screens/registro'

/** Lo que una pantalla puede pedir al navegar: abrir algo concreto. */
export interface Destino {
  decisionId?: string
  pedimentoId?: string
}

export type Navegar = (id: string, destino?: Destino) => void

export default function App() {
  const [activa, setActiva] = useState('executive-dashboard')
  // Lo que la pantalla de destino debe abrir (una decisión recién creada, el
  // pedimento elegido en el Panorama). Se limpia al navegar desde el menú.
  const [destino, setDestino] = useState<Destino>({})
  const [menuAbierto, setMenuAbierto] = useState(false)
  const pantalla = PANTALLAS.find((p) => p.id === activa) ?? PANTALLAS[0]

  const irA: Navegar = (id, nuevo) => {
    setDestino(nuevo ?? {})
    setActiva(id)
    setMenuAbierto(false)
    window.scrollTo({ top: 0 })
  }

  useEffect(() => {
    document.title = `${pantalla.titulo} · ADUANERO OS`
  }, [pantalla.titulo])

  return (
    <div className={`app ${menuAbierto ? 'app--menu-abierto' : ''}`}>
      <a className="saltar" href="#contenido">
        Saltar al contenido
      </a>

      <header className="barra-movil">
        <button
          className="barra-movil__boton"
          onClick={() => setMenuAbierto((v) => !v)}
          aria-expanded={menuAbierto}
          aria-controls="navegacion"
          aria-label={menuAbierto ? 'Cerrar menú' : 'Abrir menú'}
        >
          <Icono nombre={menuAbierto ? 'cerrar' : 'menu'} />
        </button>
        <span className="barra-movil__marca">ADUANERO OS</span>
        <span className="barra-movil__pantalla">{pantalla.titulo}</span>
      </header>

      <nav className="lateral" id="navegacion" aria-label="Módulos">
        <div className="marca">
          <span className="marca__sello" aria-hidden="true">
            AO
          </span>
          <div>
            <strong className="marca__nombre">ADUANERO OS</strong>
            <span className="marca__descriptor">Inteligencia y control aduanal</span>
          </div>
        </div>

        {GRUPOS.map((grupo) => (
          <div key={grupo} className="menu__grupo">
            <p className="menu__titulo">{grupo}</p>
            <ul className="menu">
              {PANTALLAS.filter((p) => p.grupo === grupo).map((p) => (
                <li key={p.id}>
                  <button
                    className={`menu__item ${p.id === activa ? 'menu__item--activo' : ''}`}
                    onClick={() => irA(p.id)}
                    aria-current={p.id === activa ? 'page' : undefined}
                    title={p.descripcion}
                  >
                    <Icono nombre={p.icono} />
                    <span>{p.titulo}</span>
                    {!p.implementada && <em className="menu__pendiente">pendiente</em>}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}

        <p className="lateral__pie">
          Herramienta interna de revisión. No sustituye la presentación ante la autoridad.
        </p>
      </nav>

      <main className="contenido" id="contenido" tabIndex={-1}>
        {pantalla.id === 'executive-dashboard' && <PanoramaOperativo irA={irA} />}
        {pantalla.id === 'system-status' && <SystemStatus />}
        {pantalla.id === 'product-dna' && (
          <ProductDna onClasificado={(decisionId) => irA('classification', { decisionId })} />
        )}
        {pantalla.id === 'classification' && (
          <Classification decisionInicial={destino.decisionId ?? null} />
        )}
        {pantalla.id === 'finding-detail' && (
          <Findings pedimentoInicial={destino.pedimentoId ?? null} />
        )}
        {pantalla.id === 'evidence' && <Evidence />}
        {pantalla.id === 'human-review' && <HumanReview />}
        {pantalla.id === 'regulatory-sentinel' && <RegulatorySentinel />}
        {pantalla.id === 'pedimento-shadow' && (
          <PedimentoShadow pedimentoInicial={destino.pedimentoId ?? null} />
        )}
        {pantalla.id === 'copilot' && <Copilot />}
        {!pantalla.implementada && (
          <Placeholder titulo={pantalla.titulo} descripcion={pantalla.descripcion} />
        )}
      </main>

      {menuAbierto && (
        <button
          className="velo"
          aria-label="Cerrar menú"
          onClick={() => setMenuAbierto(false)}
        />
      )}
    </div>
  )
}
