/**
 * Regulatory Sentinel (§32) — qué cambió en la norma y qué nos toca.
 *
 * La tentación de esta pantalla no es el número bonito del tablero: es
 * PARECER QUE VIGILA. Un centinela que enseña «0 alertas» sobre un vigilante
 * que nunca arrancó miente con un cero, y ese cero se lee como calma.
 *
 * Por eso lo primero que se pinta cuando `vigilancia_automatica` es falso no
 * es un contador en verde, es un aviso: el DOF Regulatory Watcher todavía no
 * publica nada. Lo que sí hay es real —366 normas con vigencia por artículo—
 * y de ahí salen las olas de reforma sin inventar un feed que no existe.
 *
 * La fecha no es un filtro cosmético: manda sobre §14. Cambiarla a 2024
 * enseña un corpus distinto porque, en 2024, la norma era distinta.
 */

import { useEffect, useState } from 'react'

import { fetchSentinel } from '../api/client'
import type { Sentinel } from '../api/client'
import { DataOriginBadge } from '../components/DataOriginBadge'
import type { DataOrigin } from '../components/DataOriginBadge'

/** Hoy en ISO, sin pasar por UTC: es una fecha de vigencia, no un instante. */
function hoyISO(): string {
  const d = new Date()
  const mes = `${d.getMonth() + 1}`.padStart(2, '0')
  const dia = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${mes}-${dia}`
}

function Cifra({
  valor,
  etiqueta,
  nota,
  tono = 'normal',
}: {
  valor: number | string
  etiqueta: string
  nota?: string
  tono?: 'normal' | 'atencion' | 'bien'
}) {
  return (
    <div className={`tablero__cifra tablero__cifra--${tono}`}>
      <span className="tablero__valor">{valor}</span>
      <span className="tablero__etiqueta">{etiqueta}</span>
      {nota && <span className="tablero__nota">{nota}</span>}
    </div>
  )
}

export function RegulatorySentinel() {
  const [fecha, setFecha] = useState(hoyISO)
  const [datos, setDatos] = useState<Sentinel | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    // Una fecha a medio teclear ('202-') no se consulta: el servidor la
    // rechazaría con un 422 y la pantalla parpadearía en rojo mientras
    // alguien escribe.
    if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha)) return

    const control = new AbortController()

    fetchSentinel(fecha, control.signal)
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
  }, [fecha])

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Regulatory Sentinel</h1>
          <p className="pantalla__sub">
            Qué ha cambiado en la norma, y qué de eso nos alcanza
          </p>
        </div>
        <label className="selector">
          <span>Vigencia al</span>
          <input
            type="date"
            value={fecha}
            onChange={(e) => setFecha(e.target.value)}
            aria-label="Fecha de vigencia"
          />
        </label>
      </header>

      {error && (
        <div className="alerta" role="alert">
          <strong>No se pudo cargar la vigilancia.</strong>
          <p>{error}</p>
        </div>
      )}

      {datos && (
        <>
          {!datos.vigilancia_automatica && (
            <div className="alerta centinela__aviso" role="note">
              <strong>No hay vigilancia automática del DOF todavía.</strong>
              <p>
                El watcher no ha publicado ningún evento, así que{' '}
                <code>eventos_dof: 0</code> significa «nadie está mirando», no
                «sin novedades». Lo que sigue sale del corpus ya cargado, que sí
                es real.
              </p>
            </div>
          )}

          <h2 className="seccion">La norma a esta fecha</h2>
          <div className="tablero">
            <Cifra valor={datos.normas_totales} etiqueta="normas en el corpus" />
            <Cifra
              valor={datos.vigentes_en_fecha}
              etiqueta={`vigentes el ${datos.fecha}`}
              nota="Artículo por artículo, no documento por documento (§14)."
              tono="bien"
            />
            <Cifra
              valor={datos.fuera_de_vigencia_total}
              etiqueta="ya no vigentes"
              nota="Se conservan: una operación vieja se juzga con su norma."
            />
            <Cifra
              valor={datos.eventos_dof}
              etiqueta="eventos del DOF"
              nota={
                datos.vigilancia_automatica
                  ? undefined
                  : 'El vigilante no ha arrancado. No es calma.'
              }
              tono={datos.vigilancia_automatica ? 'normal' : 'atencion'}
            />
          </div>

          <h2 className="seccion">Corpus vigilado</h2>
          <div className="tabla-scroll">
            <table className="atributos">
              <thead>
                <tr>
                  <th>Instrumento</th>
                  <th>Tipo</th>
                  <th>Desde</th>
                  <th>Normas</th>
                  <th>Procedencia</th>
                </tr>
              </thead>
              <tbody>
                {datos.corpus.map((d) => (
                  <tr key={d.short_name} className={d.normas === 0 ? 'fila--missing' : undefined}>
                    <td>
                      <span className="atributo__nombre">{d.short_name}</span>
                      <span className="tablero__nota">{d.title}</span>
                    </td>
                    <td>{d.kind}</td>
                    <td>{d.valid_from ?? <span className="sin-dato">—</span>}</td>
                    <td>
                      {d.normas === 0 ? (
                        <span className="sin-dato">sin cargar</span>
                      ) : (
                        d.normas
                      )}
                    </td>
                    <td>
                      <DataOriginBadge origin={d.data_origin as DataOrigin} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {datos.corpus_sintetico > 0 && (
            <p className="tablero__pie">
              {datos.corpus_sintetico} de los instrumentos listados no es fuente
              oficial. No puede fundamentar una clasificación, y por eso va
              marcado en vez de mezclado con los demás.
            </p>
          )}

          <h2 className="seccion">Olas de reforma</h2>
          <p className="centinela__explica">
            No son avisos del DOF: son los días en que un bloque de artículos
            entró en vigor, deducidos de la vigencia que trae cada norma. Es la
            vigilancia que se puede sostener hoy sin inventar un feed.
          </p>
          {datos.reformas.length === 0 ? (
            <p className="vacio">El corpus no registra ninguna fecha de entrada en vigor.</p>
          ) : (
            <ul className="reformas">
              {datos.reformas.map((ola) => (
                <li key={ola.fecha} className="reforma">
                  <div className="reforma__fecha">
                    <strong>{ola.fecha}</strong>
                    <span>{ola.documentos.join(', ')}</span>
                  </div>
                  <div className="reforma__cuerpo">
                    <span className="reforma__cuenta">
                      {ola.normas} {ola.normas === 1 ? 'norma' : 'normas'}
                    </span>
                    <span className="reforma__muestra">
                      {ola.muestra.map((n) => (
                        <code key={n}>{n}</code>
                      ))}
                      {ola.normas > ola.muestra.length && (
                        <em>y {ola.normas - ola.muestra.length} más</em>
                      )}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <h2 className="seccion">Impacto sobre lo que ya decidimos</h2>
          {datos.impacto.trazable ? (
            <div className="tablero">
              <Cifra valor={datos.impacto.decisiones} etiqueta="decisiones" />
              <Cifra
                valor={datos.impacto.afectadas}
                etiqueta="citan norma no vigente en su fecha"
                nota="Se juzgaron con una norma que no aplicaba ese día."
                tono={datos.impacto.afectadas > 0 ? 'atencion' : 'bien'}
              />
              <Cifra
                valor={datos.impacto.sin_normas_citadas}
                etiqueta="sin normas guardadas"
                nota="No se pueden contrastar. No cuentan como limpias."
                tono={datos.impacto.sin_normas_citadas > 0 ? 'atencion' : 'normal'}
              />
            </div>
          ) : (
            <div className="alerta" role="note">
              <strong>
                No se puede afirmar nada sobre el impacto: ninguna de las{' '}
                {datos.impacto.decisiones} decisiones guardó qué normas citó.
              </strong>
              <p>
                Contrastar una decisión contra un cambio normativo exige saber
                qué artículos usó. Sin <code>legal_rule_ids</code>, lo honesto
                es decir que no se sabe — no pintar cero afectadas.
              </p>
            </div>
          )}

          <h2 className="seccion">Normas que dejaron de estar vigentes</h2>
          {datos.fuera_de_vigencia.length === 0 ? (
            <p className="vacio">Ninguna norma del corpus tiene fecha de término.</p>
          ) : (
            <div className="tabla-scroll">
              <table className="atributos">
                <thead>
                  <tr>
                    <th>Artículo</th>
                    <th>Instrumento</th>
                    <th>Vigente desde</th>
                    <th>Hasta</th>
                  </tr>
                </thead>
                <tbody>
                  {datos.fuera_de_vigencia.map((n) => (
                    <tr key={`${n.documento}-${n.rule_number}-${n.valid_to}`}>
                      <td>
                        <span className="atributo__nombre">{n.rule_number}</span>
                        {n.encabezado && (
                          <span className="tablero__nota">{n.encabezado}</span>
                        )}
                      </td>
                      <td>{n.documento}</td>
                      <td>{n.valid_from}</td>
                      <td>{n.valid_to}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="tablero__pie">
            Cambiar la fecha de arriba cambia el corpus entero, no el orden de
            una lista: en otra fecha la norma era otra. Es la misma regla que
            usa el motor para clasificar, no una vista aparte.
          </p>
        </>
      )}

      {!datos && !error && cargando && <p className="vacio">Consultando la norma…</p>}
    </section>
  )
}
