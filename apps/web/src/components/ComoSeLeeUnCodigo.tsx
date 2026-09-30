/**
 * Los cinco niveles de un código arancelario, para quien nunca ha visto uno.
 *
 * Va plegado: quien entiende la nomenclatura no necesita verlo cada vez, y
 * quien no la entiende no puede seguir el resto de la pantalla sin esto. Los
 * seis primeros dígitos son internacionales y los dos siguientes mexicanos —
 * de ahí que acertar la subpartida y fallar la fracción sea un error mexicano
 * y no de fondo, distinción que la pantalla de métricas usa y nadie explica.
 */

const NIVELES = [
  { digitos: '73', nombre: 'Capítulo', nota: 'La familia: manufacturas de hierro o acero' },
  { digitos: '7305', nombre: 'Partida', nota: 'Internacional' },
  { digitos: '730512', nombre: 'Subpartida', nota: 'Internacional. Es el nivel armonizado' },
  {
    digitos: '73051291',
    nombre: 'Fracción',
    nota: 'Mexicana. Es la que se declara en el pedimento y la que fija el arancel',
  },
  { digitos: '00', nombre: 'NICO', nota: 'Mexicano, estadístico' },
]

export function ComoSeLeeUnCodigo() {
  return (
    <details className="glosario">
      <summary>¿Cómo se lee un código arancelario?</summary>
      <ul className="glosario__niveles">
        {NIVELES.map((n) => (
          <li key={n.nombre}>
            <code>{n.digitos}</code>
            <strong>{n.nombre}</strong>
            <span>{n.nota}</span>
          </li>
        ))}
      </ul>
      <p className="glosario__pie">
        Los primeros seis dígitos son iguales en todo el mundo; los dos
        siguientes son de México. Por eso acertar la subpartida y fallar la
        fracción es un error mexicano, no de fondo.
      </p>
    </details>
  )
}
