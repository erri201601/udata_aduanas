/**
 * Product DNA — la primera pantalla contra datos reales (§16 y §33).
 *
 * Existe para que un agente aduanal pueda ver DE DÓNDE salió cada dato. Si la
 * pantalla no dejara ver eso, no serviría para lo que existe el producto: de
 * ello depende que confíe o no en la clasificación que venga después.
 *
 * Los atributos se ordenan por cercanía al documento —observado primero,
 * ausente al final— y no alfabéticamente: quien revisa quiere ver antes lo
 * sólido y detectar de un vistazo lo que hay que cuestionar.
 */

import { AttributeStatusBadge, ConfidenceMeter } from '../components/AttributeStatusBadge'
import { ClassifyButton } from '../components/ClassifyButton'
import { SubirImagen } from '../components/SubirImagen'
import { SyntheticBanner } from '../components/DataOriginBadge'
import { useProductDna, useProducts } from '../hooks/useProductDna'
import type { AttributeStatus, ProductAttributeRead } from '../api/client'
import { useState } from 'react'

/** Cercanía al documento: lo sólido arriba, lo que falta al final. */
const ORDEN: Record<AttributeStatus, number> = {
  OBSERVED: 0,
  EXTRACTED: 1,
  INFERRED: 2,
  MISSING: 3,
}

function porCercania(a: ProductAttributeRead, b: ProductAttributeRead): number {
  return ORDEN[a.status] - ORDEN[b.status] || a.name.localeCompare(b.name)
}

interface Props {
  /** Se llama con el id de la decisión creada, para saltar a su traza. */
  onClasificado?: (decisionId: string) => void
}

export function ProductDna({ onClasificado }: Props = {}) {
  const { productos, error: errorCatalogo, cargando: cargandoCatalogo } = useProducts()
  const [seleccionado, setSeleccionado] = useState<string | null>(null)
  const activo = seleccionado ?? productos[0]?.id ?? null
  const { dna, error, cargando, recargar } = useProductDna(activo)

  const atributos = [...(dna?.attributes ?? [])].sort(porCercania)
  const ausentes = atributos.filter((a) => a.status === 'MISSING')

  return (
    <section className="pantalla">
      <header className="pantalla__encabezado">
        <div>
          <h1>Product DNA</h1>
          <p className="pantalla__sub">
            Atributos de la mercancía, con el origen de cada dato
          </p>
        </div>
        <button className="boton" onClick={recargar} disabled={cargando || !activo}>
          {cargando ? 'Cargando…' : 'Actualizar'}
        </button>
      </header>

      <SyntheticBanner />

      {activo && <SubirImagen productId={activo} onExtraido={recargar} />}

      {activo && onClasificado && (
        <ClassifyButton
          productId={activo}
          onClasificado={(r) => onClasificado(r.decision_id)}
        />
      )}

      {(errorCatalogo || error) && (
        <div className="alerta" role="alert">
          <strong>No se pudieron cargar los datos.</strong>
          <p>{errorCatalogo ?? error}</p>
          <p className="alerta__pista">
            Verifica que Tailscale esté activo y que la API responda.
          </p>
        </div>
      )}

      {productos.length > 1 && (
        <label className="selector">
          <span>Producto</span>
          <select
            value={activo ?? ''}
            onChange={(e) => setSeleccionado(e.target.value)}
          >
            {productos.map((p) => (
              <option key={p.id} value={p.id}>
                {p.sku} — {p.commercial_name}
              </option>
            ))}
          </select>
        </label>
      )}

      {dna && (
        <>
          <div className="ficha">
            <h2>{productos.find((p) => p.id === activo)?.commercial_name}</h2>
            {dna.summary && <p className="ficha__resumen">{dna.summary}</p>}
            <dl className="ficha__meta">
              <div>
                <dt>Versión</dt>
                <dd>{dna.version}</dd>
              </div>
              <div>
                <dt>Modelo</dt>
                <dd>{dna.model_name ?? '—'}</dd>
              </div>
              <div>
                <dt>Prompt</dt>
                <dd>{dna.prompt_version ?? '—'}</dd>
              </div>
              <div>
                <dt>Revisión humana</dt>
                <dd>{dna.requires_human_review ? 'requerida' : 'no requerida'}</dd>
              </div>
            </dl>
          </div>

          {ausentes.length > 0 && (
            <div className="faltantes" role="note">
              <strong>Faltan {ausentes.length} datos para clasificar.</strong>
              <p>
                Hay que pedírselos al importador. El sistema no los deduce: un
                valor inventado cambiaría la fracción arancelaria.
              </p>
              <ul>
                {dna.missing_information.map((nombre) => (
                  <li key={nombre}>
                    <code>{nombre}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="tabla-scroll">
            <table className="atributos">
              <thead>
                <tr>
                  <th>Atributo</th>
                  <th>Valor</th>
                  <th>Origen</th>
                  <th>Confianza</th>
                  <th>Evidencia</th>
                </tr>
              </thead>
              <tbody>
                {atributos.map((a) => (
                  <tr key={a.id} className={`fila fila--${a.status.toLowerCase()}`}>
                    <td className="atributo__nombre">{a.name}</td>
                    <td>
                      {a.value ? (
                        <>
                          {a.value}
                          {a.unit && <span className="unidad"> {a.unit}</span>}
                        </>
                      ) : (
                        <span className="sin-dato">sin dato</span>
                      )}
                    </td>
                    <td>
                      <AttributeStatusBadge status={a.status} />
                    </td>
                    <td>
                      <ConfidenceMeter value={a.confidence ? Number(a.confidence) : null} />
                    </td>
                    <td>
                      {a.evidence_reference ? (
                        <code className="evidencia">
                          {a.evidence_reference.slice(0, 8)}
                        </code>
                      ) : (
                        <span className="sin-dato">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!dna && !error && (cargando || cargandoCatalogo) && (
        <p className="vacio">Cargando el Product DNA…</p>
      )}

      {!dna && !cargando && !cargandoCatalogo && !error && !errorCatalogo && (
        <p className="vacio">No hay productos con Product DNA todavía.</p>
      )}
    </section>
  )
}
