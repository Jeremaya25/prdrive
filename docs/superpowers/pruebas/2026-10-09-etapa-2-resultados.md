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

## Lo que queda abierto: la llegada de la lectura en Windows

Cuando la lectura llega a la principal, Windows tarda **309 ms con 5 parejas y 908 con 50**
(Linux: 17 y 40). En ese rato la ventana está a la vista y no responde. La llegada crea pocos
widgets (45 → 50, 225 → 230: medido en local), así que lo que cuesta es mover y repintar lo que
ya estaba: en Windows cada widget es una ventana nativa. Antes de la tarea 11b, que quitó el
ensanche, eran 461 y 2574 ms.

Lo que se mueve, medido en local comparando dónde está cada widget antes y después **con el
equipo falso de la comprobación**: solo aparece la línea del arranque automático, debajo de la
lista; con 5 parejas se mueven 4 widgets (el pie) y la ventana crece 58 px, y con 50 no se mueve
la lista. Así que en Windows el coste no es mover la lista, y sin medirlo allí no se sabe cuál
es: la comprobación apunta desde ahora, con `llega-instantanea`, cuánto se va en cada paso y
cuántos widgets se repintan (`commands-testing.md`).

En otro equipo, en cambio, el mismo dispositivo trae además la línea de «Reparación…» («Hay 3
cosas que revisar.»), **encima** de la lista, y entonces todo lo de debajo baja 51 px: 31
widgets con 5 parejas, 210 con 50. Eso es lo que quita la tarea 11c (`f08cf55`): la ventana
recuerda en `state/ventana.json` cuánto ocupa lo que va encima de la lista y lo reserva desde el
primer pintado. La comprobación de tiempos no lo ve (su equipo no tiene nada que revisar): en su
pasada por Windows con `f08cf55`, en una máquina más rápida (suelo de 119 ms), la llegada tardó
226 y 719 ms, lo mismo que antes en proporción a la 0.7.1 medida en la misma máquina.

La consecuencia con 50 parejas: la ventana sale antes que en la 0.7.1 (1238 frente a 1983 ms)
pero se completa más tarde (1238 + 908, más la lectura misma, que la comprobación no cuenta) y se
queda quieta casi un segundo. Con 5 parejas se completa antes (unos 913 ms frente a 1370).

Lo siguiente es leer ese reparto en Windows y, con él, decidir: reservar también lo que va
debajo de la lista, para que la ventana no cambie de tamaño al llegar la lectura, o llevar la
lista de la principal a un lienzo, como la de «Parejas».

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
