# Etapa 2 del frontend rápido: resultados (09/10/2026)

Lo que midió la comprobación de tiempos (`rendimiento.yml`) al acabar la etapa 2 de
`docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`: la ventana ya abierta. La rama
frente a `main` (la 0.7.1), en la misma máquina, con las vueltas intercaladas; Python fijado del
dispositivo (3.14.8, Tk 9.0.4), 7 vueltas, mediana en ms.

- Fin de la etapa 2 (`479fa13`): [Rendimiento 37917304018](https://github.com/Jeremaya25/prdrive/actions/runs/37917304018).
  Suelo de Windows (ventana vacía de Tk): 142 ms.
- Fin de la etapa 1b, con la misma comprobación (`3fe1bab`): [Rendimiento 37857959248](https://github.com/Jeremaya25/prdrive/actions/runs/37857959248),
  suelo 140 ms. La comprobación aprendió en la etapa 2 a medir la ventana abierta (marcar,
  sincronizar, volver), así que sus cifras de la 0.7.1 no son las de `2026-10-08-etapa-1b-resultados.md`:
  cuenta la diferencia dentro de cada tabla.

La etapa 2 son estas cosas:

- **Pintar primero, leer después**: la ventana principal, «Ajustes» y sus apartados salen sin
  esperar a la unidad; una sola lectura compartida (`ui/instantanea.py`) los rellena al llegar.
- **Cambiar en su sitio**: la principal (`ui/tk_principal.py`), «Parejas» y «Ajustes» cambian
  solo lo que cambia; marcar una casilla, volver de «Ajustes» o de la pasada ya no rehacen la
  ventana ni escriben en la unidad.
- **La lista de «Parejas» sobre un lienzo** (`ui/tk_tabla.py`): las mismas piezas con 5 parejas
  que con 50.
- **La principal recuerda su ancho** (`state/ventana.json`) y lo reserva desde el primer
  pintado: al llegar la lectura ya no se ensancha (en Windows con 50 parejas eso costaba 2,6 s).

## Windows x64, 100 % (5 parejas / 50 parejas)

| Momento | 0.7.1 | Fin de 1b | Etapa 2 | Meta (5) |
|---|---|---|---|---|
| Ventana principal, desde que se lanza | 1370 / 1983 | 666 / 1288 | 604 / 1238 | 350 |
| Llega a la principal la lectura del estado | — | — | **309 / 908** | (sin meta) |
| Marcar una pareja en la principal | 2 / 2 | 2 / 2 | 2 / 2 | 16, cumple |
| «Sincronizar ahora», hasta ver la ventana de la pasada | 710 / 3124 | 699 / 3139 | 212 / 1040 | 100 |
| Cerrar la ventana de la pasada y volver a la principal | 484 / 2957 | 510 / 3020 | 20 / 43 | 30, **cumple** |
| Abrir «Parejas» | 841 / 2123 | 778 / 2063 | 206 / 307 | 150 |
| «Parejas», desde que se lanza | 2226 / 4119 | 1443 / 3360 | 1150 / 2572 | 500 |
| Llega el catálogo a «Parejas» | 1227 / 6293 | 1198 / 6356 | 122 / 145 | 30 |
| Elegir otra fila de «Parejas» | 6 / 46 | 6 / 46 | 2 / 2 | 16, cumple |
| Elegir otra pareja de «Parejas» (carga el editor) | 95 / 99 | 89 / 97 | 74 / 46 | 40 |
| Volver a abrir «Parejas» | 713 / 1975 | 726 / 2006 | 191 / 281 | 150 |
| Abrir «Ajustes» | 228 / 271 | 205 / 244 | 186 / 209 | 150 |
| Apartado «Reparación» | 210 / 242 | 178 / 207 | 166 / 167 | 60 |
| Apartado «Nombre e icono» | 282 / 282 | 228 / 227 | 224 / 223 | 60 |
| Apartado «Actualizaciones» | 31 / 31 | 30 / 29 | 18 / 17 | 60, cumple |
| Apartado «Configuración» | 164 / 165 | 160 / 160 | 145 / 148 | 60 |
| Volver a un apartado ya visto de «Ajustes» | 169 / 200 | 167 / 197 | 139 / 140 | 60 |
| Cerrar «Ajustes» y volver a la principal | 479 / 2937 | 477 / 2904 | 33 / 56 | 30 |
| Pregunta del agente, desde que se lanza | 1134 | 371 | 364 | 300 |
| Asistente, desde que se lanza | 1209 | 618 | 610 | 300 |
| 10 000 líneas en la ventana de la pasada | 20319 | 6 | 6 | 200, cumple |

Al 150 %: la principal 703 ms (+16 % sobre el 100 %, dentro del +20 % de la meta); abrir
«Parejas» 263, la llegada del catálogo 150.

## Linux x64 (xvfb), 100 % (5 / 50 parejas)

| Momento | 0.7.1 | Etapa 2 |
|---|---|---|
| Ventana principal, desde que se lanza | 669 / 749 | 309 / 389 |
| Llega a la principal la lectura del estado | — | 17 / 40 |
| «Sincronizar ahora», hasta ver la ventana de la pasada | 74 / 239 | 31 / 68 |
| Abrir «Parejas» | 213 / 440 | 84 / 113 |
| Llega el catálogo a «Parejas» | 144 / 671 | 28 / 40 |
| Abrir «Ajustes» | 95 / 109 | 52 / 68 |
| Cerrar «Ajustes» y volver a la principal | 54 / 267 | 27 / 65 |

## Cuentas deterministas

Iguales en Windows y en Linux salvo los módulos. La última columna es lo que queda como techo
en `tests/rendimiento/presupuesto.toml`, con las tareas 2 y 3 de la etapa 3 ya en la rama.

| Cuenta | 0.7.1 | Etapa 2 | Techo |
|---|---|---|---|
| Widgets de la principal (5 / 50 parejas) | 51 / 231 | 46 / 226 | 45 / 225 |
| Widgets de «Parejas» (5 / 50 parejas) | 152 / 467 | 84 / 84 | 83 / 83 |
| Widgets de «Ajustes» | 39 | 39 | 38 |
| Widgets de la pregunta del agente | 16 | 16 | **11** (la meta) |
| Módulos al pintar la principal (Windows / Linux) | 252 / 254 | 171 / 171 | 171 / 171 |
| Escrituras en la unidad al marcar una casilla | 1 | **0** | 0 |
| Estilos creados después del primer widget, pasadas de `<<ThemeChanged>>` al abrir | 0 | 0 | 0 |

## Lo que no llega a su meta, y por qué

- **Lo que se mide desde que se lanza** (la principal, «Parejas», la pregunta, el asistente):
  quedan arrancar Python, los imports, `Tk()` y `theme.apply()` (115 ms); el suelo de una
  ventana vacía ya son 142 ms. Repartir lo demás es de la etapa 4 (`PRDRIVE_PERF=1`), como
  avisaba el plan (riesgo 1).
- **«Sincronizar ahora»** (212 ms): la principal se pone ocupada en el clic y la ventana de la
  pasada sale en el turno siguiente; lo que queda es construir esa ventana (unos 135 ms en
  Windows según la medida de R7).
- **Elegir otra pareja** (74 ms): lo que cuesta es cargar el editor de la pareja, no la lista
  (elegir fila: 2 ms).
- **Abrir y volver a abrir «Parejas», la llegada del catálogo, «Ajustes» y sus apartados**:
  ya no dependen del número de parejas, pero en Windows siguen por encima; sin un perfil de
  Windows no se sabe qué parte es cada widget nativo y qué parte el tema. Etapa 4.

## La llegada de la lectura en Windows: abierta al cerrar la etapa, arreglada después

Al cerrar la etapa (`479fa13`), cuando la lectura llegaba a la principal Windows tardaba **309 ms
con 5 parejas y 908 con 50** (Linux: 17 y 40), con la ventana a la vista y sin responder. Con 50
parejas la ventana salía antes que en la 0.7.1 pero se completaba más tarde.

La comprobación de tiempos reparte ahora esa llegada (`fc25171`: `fases`, `expose`, `configure` y
`geometria` de `llega-instantanea`, en el `crudo.jsonl` de cada pasada). En Windows
([Rendimiento 37924103960](https://github.com/Jeremaya25/prdrive/actions/runs/37924103960)):
aplicar el estado 3 ms, `encajar()` 38-49 ms y el `update()` que pinta 121 ms (5 parejas) y 430 ms
(50), con un `<Expose>` en **todos** los widgets a la vista. En Windows cada cambio de tamaño de la
ventana la repinta entera, y había dos:

- **Con 5 parejas, la ventana crecía**: la lectura trae la línea del arranque automático, debajo de
  la lista, y el pie bajaba 58 px. Arreglo (`360dde3`): la ventana recuerda en
  `state/ventana.json` lo que ocupa lo que va debajo de la lista y lo reserva desde el primer
  pintado, como ya hacía con lo de encima (`f08cf55`, la línea de «Reparación…», que la
  comprobación no ve porque su equipo no tiene nada que revisar).
- **Con 50 parejas, `Visor.encajar()` estiraba la ventana y la encogía**: para medir lo que sobra
  de la ventana ponía el recuadro al tamaño entero del contenido, más alto que la pantalla, y la
  ventana lo seguía. Pasaba en **cada** ajuste de una ventana que no cabe, aunque nada cambiara.
  Arreglo (`865a8f6`): mide primero con el recuadro como está y solo lo estira cuando no puede
  saber el tamaño final de otra forma (el primer desbordamiento, casi siempre con la ventana sin
  enseñar).

| Llegada de la lectura, Windows | Al cerrar la etapa | `360dde3` | `865a8f6` |
|---|---|---|---|
| 5 parejas | 309 ms | 58 ms | 79 ms |
| 50 parejas | 908 ms | 490 ms | 69 ms |
| Widgets repintados (5 / 50) | todos / todos los visibles | 7 / 100 | 7 / 2 |

Las máquinas de Windows varían mucho entre pasadas (suelo de 142, 93 y 132 ms en estas tres): lo
que no depende de la máquina es cuántos widgets se repintan. Con `865a8f6` ya no se mueve ni cambia
de tamaño ninguno; quedan los 6 que crea la lectura. De paso, «Sincronizar ahora» con 50 parejas
pasa de 1040 a 165 ms hasta ver la ventana de la pasada: la principal ya no se repinta entera al
ponerse ocupada.

## R3 y R7

Decididos con su medida en Windows (`2026-10-09-etapa-2-medidas.md`, «Decisión»): **la lista de
«Parejas» sobre un lienzo** (con 20 filas, 77 ms frente a 158 la ligera y 1230 la de la 0.7.1) y
**no esconder ventanas en vez de destruirlas** (ninguna llegaba a la ganancia del 50 %, y
«Ajustes» empeoraba).

## Pruebas

- `tests/run_all.py` en verde en Linux y Windows con el Python del dispositivo (Tk 9) y en el
  trabajo de Python 3.11 sin pantalla: [Tests 37917304013](https://github.com/Jeremaya25/prdrive/actions/runs/37917304013).
  Desde el 09/10 Tk 9 es el único Tk: la CI ya no prueba la interfaz con Tk 8.6.
- La CI de Windows encontró en la etapa cuatro cosas que en Linux no salían, todas arregladas:
  la principal que se ensanchaba al llegar la lectura (tarea 11b); variables de tkinter que el
  recolector liberaba desde otro hilo y paraban 1 s una prueba (`73c423d`); una ventana hija de
  una raíz escondida que Windows nunca mapea, en una prueba (`9026d43`); la altura de fila de la
  tabla al 125 %, en una prueba (`479fa13`).
