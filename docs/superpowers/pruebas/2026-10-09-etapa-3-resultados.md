# Etapa 3 del frontend rápido: resultados (09/10/2026)

Lo que midió la comprobación de tiempos (`rendimiento.yml`) al acabar la etapa 3 de
`docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`, en el commit `2460490`: la rama
frente a `main` (la 0.7.1), en la misma máquina, con las vueltas intercaladas; Python fijado del
dispositivo (3.14.8, Tk 9.0.4), 7 vueltas, mediana en ms. Comprobación de tiempos:
[Rendimiento 37969775672](https://github.com/Jeremaya25/prdrive/actions/runs/37969775672). Suite
de pruebas: [37969775676](https://github.com/Jeremaya25/prdrive/actions/runs/37969775676).
Instalador: [37969775780](https://github.com/Jeremaya25/prdrive/actions/runs/37969775780).

La etapa 3 hizo estas cosas:

- **La comprobación mide lo nuevo**: «Dispositivos», el editor de flags y el paso a «Dispositivo»
  del asistente.
- **La pregunta del agente baja a 11 widgets** (eran 16). La barra horizontal del `Visor` solo se
  crea cuando hace falta.
- **«Dispositivos» tiene una sola ficha** que cambia en su sitio y se construye al primer uso: no
  hay una tarjeta por equipo, y elegir otro dispositivo no crea widgets.
- **El asistente lee después de pintar**: sus lecturas (unidades, Python del equipo, verificación,
  nota de la flota y prueba de escritura del cifrado) salen del hilo de Tk; sus partes sin Tk
  están en `ui/lecturas_asistente.py`. Quedan en el hilo de Tk unas lecturas pequeñas sobre el
  volumen elegido (el espacio libre, la detección del cifrado, las medidas del panel de VeraCrypt).
- **`tk.Tabla` sobre un lienzo**, usada por «Dispositivos» y por el editor de flags.
- **El instalador se compila con Python 3.14.8, Tk 9.0.4 y PyInstaller 6.22.3**; el flujo de
  publicación usa la misma acción compuesta y se detiene si algo falla.

## Windows x64, 100 %

Mediana en ms, 5 parejas, escala 100 %. Suelo (ventana vacía de Tk): 134 ms. El resumen dice
«Pasa»: nada supera un techo ni empeora claramente frente a la base. La columna Meta es la de
`meta_ms` de `tests/rendimiento/presupuesto.toml`.

| Momento | 0.7.1 | Etapa 3 | Diferencia | Meta |
|---|---|---|---|---|
| Pregunta del agente, desde que se lanza | 1037 | 348 | -689 (-66 %) | ≤ 300, **no** |
| Asistente, desde que se lanza | 1135 | 595 | -540 (-48 %) | ≤ 300, **no** |
| `theme.apply()` del asistente | 610 | 113 | -497 (-82 %) | — |
| Asistente: pasar al paso «Dispositivo» | 411 | 302 | -109 (-27 %) | — |
| Abrir «Dispositivos» | 91 | 62 | -28 (-31 %) | — |
| Llegan las notas de la flota a «Dispositivos» | 2972 | 126 | -2845 (-96 %) | — |
| Elegir otro dispositivo de «Dispositivos» | 46 | 32 | -14 (-30 %) | ≤ 16, **no** |
| Abrir el editor de flags | 639 | 126 | -513 (-80 %) | — |

## Linux x64, 100 %

Mediana en ms, 5 parejas, escala 100 % (xvfb). Suelo: 102 ms. El resumen dice «Pasa». Linux no
tiene metas: `informe.py` solo aplica `meta_ms` a `windows-x64`, y la columna Meta lleva «—» en cada fila.

| Momento | 0.7.1 | Etapa 3 | Diferencia | Meta |
|---|---|---|---|---|
| Pregunta del agente, desde que se lanza | 606 | 206 | -400 (-66 %) | — |
| Asistente, desde que se lanza | 597 | 271 | -326 (-55 %) | — |
| `theme.apply()` del asistente | 362 | 72 | -290 (-80 %) | — |
| Asistente: pasar al paso «Dispositivo» | 55 | 58 | +3 (+5 %) | — |
| Abrir «Dispositivos» | 21 | 14 | -7 (-35 %) | — |
| Llegan las notas de la flota a «Dispositivos» | 403 | 44 | -359 (-89 %) | — |
| Elegir otro dispositivo de «Dispositivos» | 11 | 10 | -1 (-9 %) | — |
| Abrir el editor de flags | 91 | 24 | -67 (-73 %) | — |

## Cuentas

Las cuentas son deterministas. En cada celda, Windows primero y Linux después; el techo y la meta
son los mismos en los dos sistemas salvo los módulos.

| Cuenta | 0.7.1 | Etapa 3 | Techo | Meta |
|---|---|---|---|---|
| `widgets.agente` | 16 / 16 | 11 / 11 | 11 / 11 | ≤ 11, cumple |
| `widgets.wizard` | 20 / 20 | 19 / 19 | 19 / 19 | — |
| `widgets.dispositivos` | 137 / 137 | 44 / 44 | 44 / 44 | ≤ 35, **no** |
| `widgets.flags` | 70 / 70 | 26 / 26 | 26 / 26 | ≤ 34, cumple |
| `modulos.main` | 252 / 254 | 171 / 171 | 171 / 171 | — |
| `modulos.agente` | 241 / 242 | 158 / 157 | 158 / 157 | — |
| `modulos.wizard` | 237 / 237 | 235 / 234 | 235 / 234 | — |

Los techos de `tests/rendimiento/presupuesto.toml` ya son estos números (los widgets en `[techo]`,
los módulos en `[techo.windows]` y `[techo.linux]`); el archivo no se ha editado. Estilos, tema y
escrituras en la unidad al marcar una casilla están en cero, y el tema en 1 al arrancar cada ventana.

## El paso «Dispositivo» del asistente

En `2cff5a1` (Rendimiento [37956364698](https://github.com/Jeremaya25/prdrive/actions/runs/37956364698))
el paso «Dispositivo» tardaba **442 ms** en Windows (base 424). La meta de la tarea 4 no se
cumplía: la ventana se reajustaba tres veces y se volvía a centrar en cada paso. En `2460490` tarda
**302 ms** (base 411), con un solo reajuste por paso y sin volver a centrar. En el calentamiento
(`crudo.jsonl`, ronda -1, la misma pasada de `2460490`) la fase «clic» es de 236 ms en la 0.7.1 y de
62 en la etapa 3, y los eventos `Configure` de la ventana `Tk` son 4 y 2. Lo que queda, unos 250 ms,
es pintar el paso. En Linux el mismo paso va de 55 a 58 ms (+3 ms), y el resumen no lo marca como
empeoramiento.

## Metas que no se cumplen

- **«Dispositivos» ≤ 35 widgets: 44.** Con el mismo aspecto la ficha necesita sus widgets fijos;
  llegar a 35 pide que el bloque «Equipos» sea dos etiquetas de varias líneas, lo que cambia el
  aspecto. Es la decisión D1 del plan de la etapa 3
  (`docs/superpowers/plans/2026-10-09-frontend-rapido-etapa-3.md`): se mantiene el aspecto y se
  informa la falta.
- **«Verificación» del asistente ≤ 40 widgets.** No es alcanzable mientras `tabla_estado()` siga en
  ttk (R3): su detalle se parte en líneas. Se acota en las pruebas como una parte fija más 4 por fila
  de comprobación menos 1: la parte fija, con el indicador de espera, es de 13 como mucho con una
  unidad (12 + 4 por fila) y de 7 como mucho en «En este equipo» (6 + 4 por fila) (decisión D2 de
  `docs/superpowers/plans/2026-10-09-frontend-rapido-etapa-3.md`).
- **El asistente desde que se lanza ≤ 300 ms: 595 en Windows, 271 en Linux** (Linux no fija meta).
  `install.raiz_equipo` importa al nivel de módulo `crypto`, `deploy`, `device`, `platforms` y
  `fleet`; la etapa 4 lo mide con `PRDRIVE_PERF=1`.
- **La pregunta del agente desde que se lanza ≤ 300 ms: 348 en Windows, 206 en Linux.** Dentro
  de lo medido están arrancar Python, los imports y `Tk()` (el suelo de una ventana vacía son
  134 ms en Windows) y `theme.apply()` (114 ms en la pregunta). Repartir eso es de la etapa 4.
- **Otras filas con meta «no» (Windows, 5 parejas):** ventana principal desde que se lanza 590 (≤ 350);
  «Sincronizar ahora» hasta la ventana de la pasada 206 (≤ 100); abrir «Parejas» 202 (≤ 150);
  «Parejas» desde que se lanza 936 (≤ 500); llega el catálogo a «Parejas» 111 (≤ 30); elegir otra
  pareja 75 (≤ 40); volver a abrir «Parejas» 181 (≤ 150); abrir «Ajustes» 181 (≤ 150); apartados
  «Reparación» 170, «Nombre e icono» 224 y «Configuración» 145 (≤ 60 cada uno); volver a un apartado
  ya visto 135 (≤ 60); elegir otro dispositivo 32 (≤ 16). Casi todas son de la etapa 2, que ya dio sus
  causas (`docs/superpowers/pruebas/2026-10-09-etapa-2-resultados.md`, «Lo que no llega a su meta,
  y por qué»); en «Parejas» y «Ajustes» sigue sin saberse, sin un perfil de Windows, qué parte es de
  cada widget nativo y qué parte del tema. «Elegir otro dispositivo» no tiene causa medida en esta
  etapa.
- **Cuentas fuera de meta:** `widgets.main.p5` 45 (meta ≤ 26) y `widgets.parejas.p5` 83 (meta ≤ 70),
  los dos de `[meta]` en `presupuesto.toml`; no son techos y no hacen fallar la comprobación.

## El instalador

- El `.exe` pesa 18306804 bytes (17,5 MB). Se compiló con Python 3.14.8, Tk 9.0.4 y PyInstaller 6.22.3
  (hooks de contrib 2026.8).
- `--autoprueba` sobre el `.exe` congelado (Windows, [instalador 37969775780](https://github.com/Jeremaya25/prdrive/actions/runs/37969775780),
  verde): Python 3.14.8, Tk 9.0.4, `tk9` y `svg`: sí, tema: sí, letra «Noto Sans», ningún icono pintado con Python, y 29 módulos
  y 9 datos, todos «ok».
- La puerta de Tk 9 funciona: el Python 3.11.9 del runner trae Tk 8.6, y la instalación ligera lo
  rechaza porque pide Tk 9; la instalación completa trae su propio runtime.
- La suite ([37969775676](https://github.com/Jeremaya25/prdrive/actions/runs/37969775676)) está verde en Linux
  (xvfb, Tk 9), en Windows (Tk 9) y en la pata `python-minimo` (3.11).
