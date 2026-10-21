/**
 * Panorama operativo: la pantalla con que abre la consola.
 *
 * Tiene que contestar tres preguntas sin desplazarse: qué requiere atención,
 * en qué está cada operación y cuál es la siguiente acción. Todo lo que
 * enseña sale de `/dashboard/operacion`; si la base no tiene algo, aquí no
 * aparece — no hay cifras de relleno.
 *
 * DOS COSAS QUE ESTA PANTALLA NO PUEDE DECIR
 *
 * «Revisión completa» habla de la revisión espejo INTERNA: que el motor pudo
 * contrastar todas las partidas. No es un despacho, ni una validación del SAT,
 * ni una autorización de nadie. Y un pedimento sin hallazgos que nadie revisó
 * no está limpio: está sin revisar.
 */

import { useEffect, useMemo, useState } from 'react'

import { fetchPanorama } from '../api/client'
import type { Operacion, Panorama, Severity } from '../api/client'
import type { Navegar } from '../App'
import { SyntheticBanner } from '../components/DataOriginBadge'
import { EstadoRevision } from '../components/Expediente'
import { fechaCorta } from '../components/expediente'
import { Icono } from '../components/Icono'
import { ORDEN_SEVERIDAD, SEVERIDADES, formatearMonto } from '../components/severity'
import { ExecutiveDashboard } from './ExecutiveDashboard'

type Filtro = 'todas' | 'criticos' | 'sin_revisar' | 'incompletas' | 'sin_accion'
type Orden = 'fecha' | 'pedimento' | 'cliente' | 'valor' | 'hallazgos'

const FILTROS: { id: Filtro; etiqueta: string; cumple: (o: Operacion) => boolean }[] = [
  { id: 'todas', etiqueta: 'Todas', cumple: () => true },
  { id: 'criticos', etiqueta: 'Con hallazgos críticos', cumple: (o) => o.criticos > 0 },
  { id: 'sin_revisar', etiqueta: 'Sin revisar', cumple: (o) => o.revisado_en == null },
  {
    id: 'incompletas',
    etiqueta: 'Revisión incompleta',
    cumple: (o) => o.revisado_en != null && o.revision_completa === false,
  },
  {
    id: 'sin_accion',
    etiqueta: 'Sin acción pendiente',
    cumple: (o) => o.siguiente_accion === 'Sin acción pendiente',
  },
]

/** El peso de la peor severidad, para ordenar: lo crítico primero. */
function pesoSeveridad(o: Operacion): number {
  const i = ORDEN_SEVERIDAD.indexOf(o.peor_severidad as Severity)
  return i === -1 ? ORDEN_SEVERIDAD.length : i
}

function comparar(a: Operacion, b: Operacion, orden: Orden): number {
  switch (orden) {
    case 'pedimento':
      return a.pedimento_number.localeCompare(b.pedimento_number)
    case 'cliente':
      return (a.cliente ?? '').localeCompare(b.cliente ?? '', 'es')
    case 'valor':
      return Number(a.valor_aduana ?? 0) - Number(b.valor_aduana ?? 0)
    case 'hallazgos':
      return pesoSeveridad(b) - pesoSeveridad(a) || a.hallazgos - b.hallazgos
    case 'fecha':
      return a.fecha.localeCompare(b.fecha)
  }
}

/** A qué pantalla lleva la siguiente acción, con el pedimento ya elegido. */
function destinoDe(o: Operacion): string | null {
  if (o.siguiente_accion === 'Revisar hallazgos críticos') return 'finding-detail'
  if (o.siguiente_accion === 'Sin acción pendiente') return null
  return 'pedimento-shadow'
}

/** «47-0 · Aeropuerto Internacional…»: la clave se lee, el nombre se consulta. */
function Aduana({ aduana }: { aduana: string | null | undefined }) {
  if (!aduana) return <span className="tenue">—</span>
  const [clave, ...resto] = aduana.split(' · ')
  const nombre = resto.join(' · ')
  return (
    <>
      <span className="mono">{clave}</span>
      {nombre && (
        <span className="tenue celda__sub celda__aduana" title={nombre}>
          {nombre}
        </span>
      )}
    </>
  )
}

function Hallazgos({ o }: { o: Operacion }) {
  if (o.revisado_en == null) return <span className="tenue">—</span>
  if (o.hallazgos === 0) {
    return <span className="tenue">{o.revision_completa ? 'Ninguno' : 'Ninguno en lo revisado'}</span>
  }
  const sev = o.peor_severidad as Severity | null
  return (
    <span className="hallazgos-celda">
      <span className="mono">{o.hallazgos}</span>
      {sev && (
        <span className={`sev sev--${sev.toLowerCase()}`} title={SEVERIDADES[sev]?.ayuda}>
          {o.criticos > 0 ? `${o.criticos} ${o.criticos === 1 ? 'crítico' : 'críticos'}` : SEVERIDADES[sev]?.etiqueta}
        </span>
      )}
    </span>
  )
}

function Encabezado({
  id,
  children,
  orden,
  asc,
  ordenar,
  numerico = false,
}: {
  id: Orden
  children: string
  orden: Orden
  asc: boolean
  ordenar: (id: Orden) => void
  numerico?: boolean
}) {
  const activo = orden === id
  return (
    <th
      scope="col"
      aria-sort={activo ? (asc ? 'ascending' : 'descending') : 'none'}
      className={numerico ? 'num' : undefined}
    >
      <button className="orden" onClick={() => ordenar(id)}>
        {children}
        <span className="orden__flecha" aria-hidden="true">
          {activo ? (asc ? '▲' : '▼') : '↕'}
        </span>
      </button>
    </th>
  )
}

export function PanoramaOperativo({ irA }: { irA: Navegar }) {
  const [datos, setDatos] = useState<Panorama | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [vuelta, setVuelta] = useState(0)

  const [busqueda, setBusqueda] = useState('')
  const [filtro, setFiltro] = useState<Filtro>('todas')
  const [orden, setOrden] = useState<Orden>('fecha')
  const [asc, setAsc] = useState(false)

  useEffect(() => {
    const control = new AbortController()

    fetchPanorama(control.signal)
      .then((d) => {
        setDatos(d)
        setError(null)
      })
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setError(causa instanceof Error ? causa.message : 'No se pudo contactar la API')
      })
      .finally(() => {
        if (!control.signal.aborted) setCargando(false)
      })

    return () => control.abort()
  }, [vuelta])

  const actualizar = () => {
    setCargando(true)
    setVuelta((v) => v + 1)
  }

  const ordenar = (id: Orden) => {
    if (id === orden) {
      setAsc((v) => !v)
    } else {
      setOrden(id)
      // Fechas y valores se leen de mayor a menor; los nombres, de la A a la Z.
      setAsc(id === 'pedimento' || id === 'cliente')
    }
  }

  const operaciones = useMemo(() => datos?.operaciones ?? [], [datos])
  const visibles = useMemo(() => {
    const texto = busqueda.trim().toLowerCase()
    const cumple = FILTROS.find((f) => f.id === filtro)?.cumple ?? (() => true)
    return operaciones
      .filter(cumple)
      .filter(
        (o) =>
          !texto ||
          [o.pedimento_number, o.cliente, o.rfc, o.aduana].some((c) =>
            (c ?? '').toLowerCase().includes(texto),
          ),
      )
      .sort((a, b) => (asc ? 1 : -1) * comparar(a, b, orden))
  }, [operaciones, busqueda, filtro, orden, asc])

  const haySimuladas = operaciones.some((o) => o.simulado)

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Panorama operativo</h1>
          <p className="pantalla__sub">
            Qué requiere atención, en qué está cada pedimento y qué sigue
          </p>
        </div>
        <button className="boton boton--secundario" onClick={actualizar} disabled={cargando}>
          <Icono nombre="actualizar" />
          {cargando ? 'Actualizando…' : 'Actualizar'}
        </button>
      </header>

      {haySimuladas && <SyntheticBanner />}

      {error && (
        <div className="alerta" role="alert">
          <strong>No se pudo cargar el panorama.</strong>
          <p>{error}</p>
          <button className="boton boton--secundario" onClick={actualizar}>
            Reintentar
          </button>
        </div>
      )}

      {!datos && cargando && !error && (
        <p className="vacio" aria-live="polite">
          Cargando el panorama…
        </p>
      )}

      {datos && (
        <>
          <section className="bloque" aria-labelledby="titulo-atencion">
            <h2 id="titulo-atencion" className="bloque__titulo">
              Requiere atención
            </h2>
            {datos.atencion.length === 0 ? (
              <p className="vacio vacio--ok">
                Nada espera a nadie: no hay críticos, revisiones pendientes ni clasificaciones
                por dictaminar.
              </p>
            ) : (
              <ul className="atencion">
                {datos.atencion.map((a) => (
                  <li key={a.clave} className={`atencion__item atencion__item--${a.tono}`}>
                    <span className="atencion__cifra mono">{a.cantidad}</span>
                    <div className="atencion__texto">
                      <strong>{a.titulo}</strong>
                      <span>{a.detalle}</span>
                    </div>
                    <button
                      className="boton boton--enlace"
                      onClick={() => irA(a.pantalla)}
                      aria-label={`Abrir: ${a.titulo}`}
                    >
                      Abrir
                      <Icono nombre="flecha" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="bloque" aria-labelledby="titulo-operaciones">
            <div className="bloque__cabecera">
              <h2 id="titulo-operaciones" className="bloque__titulo">
                Operaciones
                <span className="bloque__cuenta">
                  {visibles.length === operaciones.length
                    ? operaciones.length
                    : `${visibles.length} de ${operaciones.length}`}
                </span>
              </h2>
              <div className="filtros">
                <label className="campo">
                  <span className="campo__etiqueta">Buscar</span>
                  <input
                    type="search"
                    value={busqueda}
                    onChange={(e) => setBusqueda(e.target.value)}
                    placeholder="Pedimento, cliente, RFC o aduana"
                  />
                </label>
                <label className="campo">
                  <span className="campo__etiqueta">Estado</span>
                  <select value={filtro} onChange={(e) => setFiltro(e.target.value as Filtro)}>
                    {FILTROS.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.etiqueta}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            {operaciones.length === 0 ? (
              <p className="vacio">
                No hay pedimentos cargados todavía. Cuando entre el primero, aquí aparecerá con
                su estado de revisión.
              </p>
            ) : visibles.length === 0 ? (
              <p className="vacio">
                Ninguna operación coincide con la búsqueda o el filtro.{' '}
                <button
                  className="boton boton--enlace"
                  onClick={() => {
                    setBusqueda('')
                    setFiltro('todas')
                  }}
                >
                  Quitar filtros
                </button>
              </p>
            ) : (
              <div className="tabla-envoltura">
                <table className="tabla tabla--operaciones">
                  <thead>
                    <tr>
                      <Encabezado id="pedimento" orden={orden} asc={asc} ordenar={ordenar}>
                        Pedimento
                      </Encabezado>
                      <Encabezado id="cliente" orden={orden} asc={asc} ordenar={ordenar}>
                        Cliente
                      </Encabezado>
                      <th scope="col">Aduana</th>
                      <Encabezado id="fecha" orden={orden} asc={asc} ordenar={ordenar}>
                        Fecha
                      </Encabezado>
                      <Encabezado id="valor" orden={orden} asc={asc} ordenar={ordenar} numerico>
                        Valor en aduana
                      </Encabezado>
                      <th scope="col">Revisión</th>
                      <Encabezado id="hallazgos" orden={orden} asc={asc} ordenar={ordenar}>
                        Hallazgos
                      </Encabezado>
                      <th scope="col">Siguiente acción</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibles.map((o) => {
                      const destino = destinoDe(o)
                      return (
                        <tr key={o.pedimento_id}>
                          <th scope="row" data-etiqueta="Pedimento">
                            <span className="mono">{o.pedimento_number}</span>
                            <span className="tenue celda__sub">
                              {o.clave && <span className="mono">{o.clave}</span>} {o.tipo}
                            </span>
                            {o.simulado && <span className="sim">simulación</span>}
                          </th>
                          <td data-etiqueta="Cliente">
                            {o.cliente ?? <span className="tenue">Sin cliente</span>}
                            {o.rfc && <span className="mono tenue celda__sub">{o.rfc}</span>}
                          </td>
                          <td data-etiqueta="Aduana">
                            <Aduana aduana={o.aduana} />
                          </td>
                          <td data-etiqueta="Fecha" className="nowrap">
                            {fechaCorta(o.fecha)}
                          </td>
                          <td data-etiqueta="Valor en aduana" className="num mono">
                            {formatearMonto(o.valor_aduana, o.moneda) ?? (
                              <span className="tenue">—</span>
                            )}
                          </td>
                          <td data-etiqueta="Revisión">
                            <EstadoRevision o={o} />
                          </td>
                          <td data-etiqueta="Hallazgos">
                            <Hallazgos o={o} />
                          </td>
                          <td data-etiqueta="Siguiente acción">
                            {destino ? (
                              <button
                                className={`boton ${o.criticos > 0 ? 'boton--primario' : 'boton--secundario'} boton--chico`}
                                onClick={() => irA(destino, { pedimentoId: o.pedimento_id })}
                                aria-label={`${o.siguiente_accion}: pedimento ${o.pedimento_number}`}
                              >
                                {o.siguiente_accion}
                              </button>
                            ) : (
                              <span className="tenue">{o.siguiente_accion}</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="nota">
              «Revisión» es la revisión espejo interna de ADUANERO OS: contrasta lo declarado
              con lo esperado. No es una validación del SAT ni una autorización de despacho.
            </p>
          </section>

          <details className="bloque desplegable">
            <summary>Indicadores del sistema</summary>
            <ExecutiveDashboard embebido />
          </details>
        </>
      )}
    </section>
  )
}
