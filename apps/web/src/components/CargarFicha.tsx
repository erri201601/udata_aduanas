/**
 * Cargar una ficha técnica y extraer de ella el Product DNA (§16, §48 primer
 * eslabón: «usuario carga ficha técnica + imagen»).
 *
 * Tres entradas —texto pegado, PDF o imagen— y un solo resultado: las tres
 * pasan por el mismo motor en la API y devuelven lo mismo.
 *
 * LO QUE ESTE CONTROL TIENE QUE DECIR, Y NO ES EL ÉXITO
 *
 * El caso interesante no es que funcione: es que no funcione por una razón que
 * quien lo usa puede arreglar. Que no haya proveedor configurado (503, con
 * CUÁL falta) o que el PDF sea un escaneo (422, «sin texto extraíble»). Ese
 * texto llega entero a la pantalla: un «error al subir» genérico deja a quien
 * lo ve sin saber si el problema es su archivo, la red o una llave en un
 * `.env` al que quizá ni tiene acceso.
 *
 * Y SE DICE SI SUSTITUYÓ A LA FICHA
 *
 * Una lectura que no encontró nada se guarda —el intento consta— pero no
 * sustituye a la ficha vigente. Sin decirlo, quien ve «versión 7» creería que
 * el producto se quedó sin datos.
 *
 * Y DÓNDE QUEDÓ EL CRUDO
 *
 * El hash no es un adorno: es lo único que prueba, meses después, que el
 * atributo salió de ESE archivo y no de otro.
 */

import { useRef, useState } from 'react'

import { extraerDnaDeImagen, extraerDnaDePdf, extraerDnaDeTexto } from '../api/client'
import type { DnaExtraido } from '../api/client'

type Entrada = 'texto' | 'pdf' | 'imagen'

const ETIQUETAS: Record<Entrada, string> = {
  texto: 'Pegar texto',
  pdf: 'Subir PDF',
  imagen: 'Subir imagen',
}

const PISTAS: Record<Entrada, string> = {
  texto:
    'La ficha técnica o el datasheet, tal cual. El texto se guarda entero, con su hash, antes de leerlo.',
  pdf: 'Una ficha técnica con texto. Un escaneo sin capa de texto no se puede leer: no hay OCR.',
  imagen: 'Una foto o una etiqueta. Lo leído de una imagen nunca queda como «observado».',
}

const ACEPTA: Record<'pdf' | 'imagen', string> = {
  pdf: 'application/pdf,.pdf',
  imagen: 'image/png,image/jpeg,image/webp,image/gif',
}

interface Props {
  productId: string
  /** Se llama al terminar, para que la pantalla vuelva a pedir el DNA. */
  onExtraido?: () => void
}

export function CargarFicha({ productId, onExtraido }: Props) {
  const archivo = useRef<HTMLInputElement>(null)
  const [entrada, setEntrada] = useState<Entrada>('texto')
  const [texto, setTexto] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [resultado, setResultado] = useState<DnaExtraido | null>(null)

  async function extraer(enviar: () => Promise<DnaExtraido>) {
    setEnviando(true)
    setError(null)
    setResultado(null)
    try {
      setResultado(await enviar())
      // Una pantalla que escribe tiene que volver a leer.
      onExtraido?.()
    } catch (causa: unknown) {
      setError(causa instanceof Error ? causa.message : 'No se pudo extraer el DNA')
    } finally {
      setEnviando(false)
      // Se limpia para poder subir DOS VECES el mismo archivo: sin esto el
      // input no dispara `change` la segunda vez y parece que se colgó.
      if (archivo.current) archivo.current.value = ''
    }
  }

  function alElegir(evento: React.ChangeEvent<HTMLInputElement>) {
    const elegido = evento.target.files?.[0]
    if (!elegido) return
    void extraer(() =>
      entrada === 'pdf'
        ? extraerDnaDePdf(productId, elegido)
        : extraerDnaDeImagen(productId, elegido),
    )
  }

  const textoListo = texto.trim().length >= 20

  return (
    <div className="subir">
      <div className="subir__entradas" role="tablist" aria-label="De dónde leer la ficha">
        {(Object.keys(ETIQUETAS) as Entrada[]).map((e) => (
          <button
            key={e}
            type="button"
            role="tab"
            aria-selected={entrada === e}
            className={`subir__entrada${entrada === e ? ' subir__entrada--activa' : ''}`}
            onClick={() => {
              setEntrada(e)
              setError(null)
            }}
            disabled={enviando}
          >
            {ETIQUETAS[e]}
          </button>
        ))}
      </div>

      {entrada === 'texto' ? (
        <div className="subir__texto">
          <textarea
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Pega aquí la ficha técnica: material, construcción, dimensiones, uso…"
            rows={6}
            disabled={enviando}
          />
          <div className="subir__accion">
            <button
              className="boton"
              type="button"
              onClick={() => void extraer(() => extraerDnaDeTexto(productId, texto))}
              disabled={enviando || !textoListo}
            >
              {enviando ? 'Leyendo el texto…' : 'Extraer del texto'}
            </button>
            <p className="subir__pista">
              {textoListo ? PISTAS.texto : 'Hacen falta al menos 20 caracteres para describir una mercancía.'}
            </p>
          </div>
        </div>
      ) : (
        <div className="subir__accion">
          <button
            className="boton"
            onClick={() => archivo.current?.click()}
            disabled={enviando}
            type="button"
          >
            {enviando
              ? 'Leyendo el archivo…'
              : entrada === 'pdf'
                ? 'Elegir un PDF'
                : 'Elegir una imagen'}
          </button>
          <input
            ref={archivo}
            type="file"
            accept={ACEPTA[entrada]}
            onChange={alElegir}
            hidden
          />
          <p className="subir__pista">{PISTAS[entrada]}</p>
        </div>
      )}

      {enviando && (
        <p className="subir__estado" role="status">
          Guardando el original y pidiéndole al modelo que lo lea. Tarda unos
          segundos.
        </p>
      )}

      {error && (
        <div className="alerta" role="alert">
          <strong>No se pudo extraer el DNA.</strong>
          {/* El texto de la API, ENTERO. Es donde dice qué llave falta, o que
              el PDF no tiene texto. */}
          <p>{error}</p>
        </div>
      )}

      {resultado && (
        <div className="subir__resultado" role="status">
          <strong>
            Versión {resultado.version} del DNA, con {resultado.atributos}{' '}
            {resultado.atributos === 1 ? 'atributo' : 'atributos'} leídos del documento.
          </strong>
          {resultado.summary && <p>{resultado.summary}</p>}

          {!resultado.vigente && (
            <p className="subir__no-vigente">
              No sustituye a la ficha vigente: el modelo no pudo afirmar ningún
              atributo de este documento. El intento queda guardado, con su
              archivo y su hash, pero la ficha del producto sigue siendo la que
              había.
            </p>
          )}

          {resultado.missing_information.length > 0 && (
            <p>
              Sigue faltando:{' '}
              {resultado.missing_information.map((m) => (
                <code key={m}>{m}</code>
              ))}
            </p>
          )}

          <p className="subir__huella">
            <span>Crudo en</span> <code>{resultado.minio_key}</code>
            <br />
            <span>Hash</span> <code>{resultado.content_hash}</code>
            {resultado.evidence_id && (
              <>
                <br />
                <span>Evidencia</span> <code>{resultado.evidence_id}</code>
              </>
            )}
          </p>
        </div>
      )}
    </div>
  )
}
