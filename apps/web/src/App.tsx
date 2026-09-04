import { useState } from 'react'

import { Placeholder } from './screens/Placeholder'
import { SystemStatus } from './screens/SystemStatus'
import { PANTALLAS } from './screens/registro'

export default function App() {
  const [activa, setActiva] = useState(PANTALLAS[0].id)
  const pantalla = PANTALLAS.find((p) => p.id === activa) ?? PANTALLAS[0]

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
                onClick={() => setActiva(p.id)}
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
        {pantalla.implementada ? (
          <SystemStatus />
        ) : (
          <Placeholder titulo={pantalla.titulo} descripcion={pantalla.descripcion} />
        )}
      </main>
    </div>
  )
}
