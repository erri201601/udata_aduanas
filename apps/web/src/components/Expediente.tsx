/**
 * Piezas de un expediente: su cabecera y las voces que opinan sobre él.
 *
 * LAS TRES VOCES NO SE MEZCLAN
 *
 * Lo declarado (lo que dice el pedimento), lo sugerido (lo que propone el
 * motor) y lo confirmado (lo que una persona revisó) son tres cosas, y cada
 * una puede estar mal. Se enseñan en columnas separadas y con su nombre, para
 * que nadie lea una sugerencia como si alguien la hubiera confirmado.
 *
 * Y «confirmado» es una revisión INTERNA: no es una resolución de la
 * autoridad, ni un despacho, ni una clasificación oficial.
 */

import type { ReactNode } from 'react'

import type { Operacion } from '../api/client'
import type { Navegar } from '../App'
import { formatearMonto } from './severity'
import { fechaCorta } from './expediente'
import type { Cifra, Tono, Voz } from './expediente'


export function Chip({ tono, children }: { tono: Tono; children: ReactNode }) {
  return (
    <span className={`chip chip--${tono}`}>
      <span className="chip__punto" aria-hidden="true" />
      {children}
    </span>
  )
}

/** El estado de la revisión espejo de un pedimento, igual en todas partes. */
export function EstadoRevision({ o }: { o: Operacion }) {
  if (o.revisado_en == null) return <Chip tono="aviso">Sin revisar</Chip>
  const cuando = new Date(o.revisado_en).toLocaleString('es-MX', {
    dateStyle: 'short',
    timeStyle: 'short',
  })
  return (
    <span title={`Revisión espejo interna · ${cuando}`}>
      {o.revision_completa ? (
        <Chip tono="ok">Completa</Chip>
      ) : (
        <Chip tono="aviso">Incompleta</Chip>
      )}
    </span>
  )
}

export interface Dato {
  etiqueta: string
  valor: ReactNode
  mono?: boolean
}

export function CabeceraExpediente({
  tipo,
  folio,
  titulo,
  datos,
  marcas,
  acciones,
  cifra,
}: {
  tipo: string
  folio: string | null | undefined
  titulo: ReactNode
  datos: Dato[]
  marcas?: ReactNode
  acciones?: ReactNode
  /** La cifra que se lee primero: en un pedimento, el dinero en juego. */
  cifra?: Cifra | null
}) {
  return (
    <section className="expediente" aria-label={`${tipo} ${folio ?? ''}`.trim()}>
      <div className="expediente__fila">
        <div className="expediente__identidad">
          <p className="expediente__tipo">
            {tipo}
            {folio && (
              <>
                {' · '}
                <code className="expediente__folio">{folio}</code>
              </>
            )}
          </p>
          <h2 className="expediente__titulo">{titulo}</h2>
        </div>
        <div className="expediente__lado">
          {marcas && <div className="expediente__marcas">{marcas}</div>}
          {cifra && (
            <div className="expediente__cifra">
              <span className="expediente__cifra-etiqueta">{cifra.etiqueta}</span>
              <span className="expediente__cifra-valor mono">{cifra.valor}</span>
              {cifra.nota && <span className="expediente__cifra-nota">{cifra.nota}</span>}
            </div>
          )}
        </div>
      </div>
      <dl className="expediente__datos">
        {datos.map((d) => (
          <div key={d.etiqueta}>
            <dt>{d.etiqueta}</dt>
            <dd className={d.mono ? 'mono' : undefined}>{d.valor ?? '—'}</dd>
          </div>
        ))}
      </dl>
      {acciones && <div className="expediente__acciones">{acciones}</div>}
    </section>
  )
}

export function Voces({ voces }: { voces: Voz[] }) {
  return (
    <ol className="voces" aria-label="Declarado, sugerido y confirmado">
      {voces.map((v) => (
        <li key={v.clave} className={`voz voz--${v.clave}`}>
          <div className="voz__cabecera">
            <h3 className="voz__titulo">{v.titulo}</h3>
            <Chip tono={v.estado.tono}>{v.estado.texto}</Chip>
          </div>
          <p className={`voz__codigo ${v.codigo ? '' : 'voz__codigo--sin'}`}>
            {v.codigo ? (
              <>
                <span className="mono">{v.codigo}</span>
                {v.nico && <span className="mono voz__nico">{v.nico}</span>}
              </>
            ) : (
              (v.sinCodigo ?? 'Sin fracción')
            )}
          </p>
          {v.contraste && (
            <p className={`voz__contraste voz__contraste--${v.contraste.tono}`}>
              {v.contraste.texto}
            </p>
          )}
          <p className="voz__nota">{v.nota}</p>
          {v.extra}
          {v.accion && <div className="voz__accion">{v.accion}</div>}
        </li>
      ))}
    </ol>
  )
}

/** Quién, dónde, cuándo y en qué estado: lo que se lee antes de las partidas. */
export function CabeceraPedimento({
  o,
  irA,
  enlace,
  cifra,
}: {
  o: Operacion
  irA?: Navegar
  /** A dónde lleva el botón: Pedimentos enlaza a Hallazgos y viceversa. */
  enlace?: { texto: string; pantalla: string }
  cifra?: Cifra | null
}) {
  const [clave, ...resto] = (o.aduana ?? '').split(' · ')
  return (
    <CabeceraExpediente
      tipo="Pedimento"
      cifra={cifra}
      folio={o.pedimento_number}
      titulo={o.cliente ?? 'Sin cliente registrado'}
      marcas={
        <>
          <EstadoRevision o={o} />
          {o.revisado_en != null &&
            (o.criticos > 0 ? (
              <Chip tono="mal">
                {o.criticos} {o.criticos === 1 ? 'hallazgo crítico' : 'hallazgos críticos'}
              </Chip>
            ) : o.hallazgos > 0 ? (
              <Chip tono="aviso">
                {o.hallazgos} {o.hallazgos === 1 ? 'hallazgo' : 'hallazgos'}
              </Chip>
            ) : (
              <Chip tono="neutro">Sin hallazgos en lo revisado</Chip>
            ))}
          {o.simulado && <span className="sim">simulación</span>}
        </>
      }
      datos={[
        { etiqueta: 'RFC', valor: o.rfc, mono: true },
        {
          etiqueta: 'Aduana',
          valor: o.aduana ? (
            <>
              <span className="mono">{clave}</span> {resto.join(' · ')}
            </>
          ) : null,
        },
        {
          etiqueta: 'Clave y tipo',
          valor: (
            <>
              {o.clave && <span className="mono">{o.clave}</span>} {o.tipo}
            </>
          ),
        },
        { etiqueta: 'Fecha de operación', valor: fechaCorta(o.fecha) },
        {
          etiqueta: 'Valor en aduana',
          valor: formatearMonto(o.valor_aduana, o.moneda),
          mono: true,
        },
        { etiqueta: 'Siguiente acción', valor: o.siguiente_accion },
      ]}
      acciones={
        irA && enlace && (o.hallazgos > 0 || enlace.pantalla !== 'finding-detail') ? (
          <button
            className="boton boton--secundario boton--chico"
            onClick={() => irA(enlace.pantalla, { pedimentoId: o.pedimento_id })}
          >
            {enlace.texto}
          </button>
        ) : null
      }
    />
  )
}
