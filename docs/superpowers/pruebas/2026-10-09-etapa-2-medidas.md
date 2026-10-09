# Etapa 2 del frontend rápido: medidas en Windows (09/10/2026)

Las dos decisiones que la especificación
(`docs/superpowers/specs/2026-10-08-frontend-rapido-design.md`, «Decisiones para revisar»
3 y 4) deja a una medida en Windows:

- **R7**, esconder una ventana en lugar de destruirla: ¿cuánto se ahorra al volver a abrir
  «Parejas», «Ajustes» o la ventana de la pasada?
- **R3**, la lista de «Parejas»: ¿hace falta una tabla sobre un solo lienzo, bastan unas
  filas con menos widgets, o se queda como está?

Las dos se miden con `tests/rendimiento/etapa2_medir.py` (temporal, como los
`etapa2_*` que lo acompañan) en el trabajo `medida-etapa2` (Windows x64 y Linux x64, el
Python fijado del dispositivo: 3.14.8, Tk 9.0.4). La tarea 1 lo construye y lo lanza sobre
la rama con las etapas 1a y 1b; la tarea 12 lo repite sobre la rama con la etapa 2 y
decide. Esta nota recoge qué se mide, con qué regla se decide y lo que salió.

## Qué se mide

Cada medida es un proceso nuevo y en frío, con `--rondas` vueltas (siete en CI) más una de
calentamiento que se tira, y con el orden de las variantes alternado de una vuelta a otra.
Valen las medianas.

**Lista de «Parejas»** (`etapa2_tabla.py`), con 5, 10, 20 y 50 filas, de tres maneras:

| Variante | Qué es | Widgets por fila |
|---|---|---|
| `ref` | la `ListaParejas` del árbol | 7 (con el separador) |
| `ligera` | `etapa2_ligera.ListaLigera`: la casilla dentro de la etiqueta del nombre, las líneas entre filas sin separadores y diferenciada por nombre | 5 |
| `lienzo` | `etapa2_lienzo.ListaLienzo`: un `tk.Canvas`, las píldoras como imágenes SVG (solo Tk 9) | 0 |

Momentos (en ms, cada uno seguido de un `update()`): `construir` (crear la ventana y la
lista y enseñarla), `elegir` (otra fila), `refrescar` (`poner()` de los mismos nombres con
un tercio de los estados cambiados), `reemplazar` (`poner()` de nombres nuevos) y los
widgets de la lista. Tras cada `poner()` el hijo compara lo que la lista dibuja (nombre,
«local ↔ remoto», modo y estado) con lo que dicen las filas, y falla si difiere: una lista
más rápida que enseña otra cosa no decide nada.

**Rehacer o esconder** (`etapa2_reabrir.py`), con la ventana principal real:
`abrir-1` (en frío), `abrir-2` (cerrada y abierta otra vez: se rehace), `abrir-3` y
`reabrir-oculta` (la tercera apertura se esconde con `withdraw` en lugar de destruirla y se
enseña de nuevo con `ensenar()`, `grab_set()` y, si la pantalla la tiene, `aplicar()`), y lo
que cuesta cerrar de cada manera. «Parejas» pide el catálogo en cuanto se abre y repinta al
llegar: el hijo lo retiene (`common.catalog.load` espera a un `Event`) durante `abrir-1`,
`abrir-2` y `reabrir-oculta` y lo suelta después de cada medida, para que esa llegada no
caiga dentro de ninguna. Se comprobó con un contador de `ListaParejas.poner`: una llamada
por apertura y ninguna en la reapertura (con el catálogo suelto, dos por apertura).

**Perfil** (`etapa2_perfil.py`): un `cProfile` por momento (abrir «Parejas», llegar el
catálogo, abrir «Ajustes» y los apartados «Reparación» y «Configuración») con 5 y con 50
parejas, y el reparto del tiempo propio entre Python y Tcl/Tk.

## Reglas de decisión

- **R7, por ventana:** `ganancia = 1 − reabrir-oculta / abrir-2`. Se adopta para esa
  ventana con **0,50 o más** en Windows x64.
- **R3, con 20 filas y `construir`, en Windows x64:** el lienzo si `ligera − lienzo` es de
  **20 ms o más**; si no, las filas ligeras si `ref − ligera` es de **10 ms o más**; si no,
  ninguna. La ganadora no puede ser más de 5 ms peor que otra en `elegir` y `refrescar`.

El resumen del trabajo las aplica solo, en sus primeras líneas, pero las aplica la tarea 12
con la medida de la rama fusionada, no esta.

## Lo que hay que saber al leer los números

- **Un proceso quieto.** La ventana principal arranca dos hilos (la versión nueva y los
  conflictos) que con 50 parejas corren un segundo entero; el hijo espera a que acaben antes
  de medir, porque alargan la medida y se cuelan en el perfil. El driver de `correr.py` no
  espera, así que sus cifras de «abrir» pueden llevar dentro ese trabajo.
- **`lienzo` solo con SVG.** En un Tk 8.6 la variante se salta (`saltado: sin SVG`). Las
  píldoras del lienzo son aproximaciones del chip de verdad (disco, glifo y palabra), no
  las mismas piezas.
- **`ligera` tiene cinco widgets por fila.** Con cuatro habría que quitar un chip o el
  resalte de la fila, que cambia lo que se ve. Con cinco se ve lo mismo salvo el hueco exacto
  entre la casilla y el nombre y las esquinas de los chips: su padre es el marco del color de
  la línea, que el tema no conoce como superficie (`theme` lo avisa una vez por la salida de
  error y las esquinas se asientan sobre la superficie más cercana). Para adoptarla habría
  que resolverlo; para medir lo que cuesta, no importa.
- **La pasada.** La ventana de la pasada se prueba con `output_window()` y una orden que no
  hace nada; esconderla es limpiar su `Text` y volver a enseñarla. `reabrir-oculta` no
  cuenta el proceso que una pasada escondida tendría que lanzar: se mide aparte (`proceso`).
- **El perfil de «Ajustes».** «Ajustes» abre en «Configuración», así que hacer clic en ella
  primero no haría nada: se va antes a «Reparación» y luego a «Configuración». Un perfil
  alarga lo que es Python, y solo vale el reparto.

## Cómo repetirlo

```
xvfb-run -a -s "-screen 0 1920x1080x24" $PYTHON tests/rendimiento/etapa2_medir.py \
    --arbol . --trabajo /tmp/e2 --python $PYTHON --rondas 7 [--solo tabla|reabrir|perfil]
```

En CI, el trabajo `medida-etapa2` se lanza al subir cambios a los `etapa2_*` o al propio
workflow (tocarlo es la manera de repetirlo) y a mano. Deja en el resumen del trabajo las
decisiones y las tablas, y en el artefacto `medida-etapa2-<plataforma>` el `resumen.md`, el
`resultados.json` y el `crudo.jsonl` (todas las líneas, con las de los hijos que fallaron
marcadas).

## Primera lectura (B1)

[Medida etapa 2, run 37857276077](https://github.com/Jeremaya25/prdrive/actions/runs/37857276077), árbol
`af36fe1` (etapa 1b y la tanda 1 de la etapa 2), Python 3.14.8 y Tk 9.0.4, 7 vueltas y una de
calentamiento. Milisegundos, mediana.

**La lista de «Parejas» (R3)**, Windows x64:

| Filas | Variante | construir | elegir | refrescar | reemplazar | widgets |
|---|---|---|---|---|---|---|
| 5 | ref | 388.5 | 3.3 | 347.3 | 346.5 | 41 |
| 5 | ligera | 67.5 | 1.3 | 9.9 | 31.9 | 31 |
| 5 | lienzo | 47.1 | 1.1 | 4.2 | 4.3 | 1 |
| 20 | ref | 1403.4 | 13.7 | 1450.4 | 1376.2 | 146 |
| 20 | ligera | 162.2 | 1.2 | 50.3 | 127.9 | 106 |
| 20 | lienzo | 78.9 | 1.3 | 13.4 | 12.9 | 1 |
| 50 | ref | 1951.4 | 31.8 | 3527.6 | 3981.3 | 356 |
| 50 | ligera | 403.0 | 1.2 | 103.2 | 309.4 | 256 |
| 50 | lienzo | 143.4 | 1.3 | 32.7 | 31.5 | 1 |

En Linux (xvfb), con 20 filas: ref 294.3, ligera 89.8, lienzo 46.6.

- Windows: ligera − lienzo = 83.3 ms (regla: 20 ms) y ref − ligera = 1241.2 ms (regla: 10 ms):
  **el lienzo**. Linux, lo mismo (43.2 y 204.5 ms). La ganadora no es peor en `elegir` ni en
  `refrescar`.
- La lista de hoy es lo que pesa en Windows: cada fila son siete ventanas del sistema, y
  rehacerlas o repintarlas cuesta del orden de 70 ms por fila. El perfil lo confirma: el 93 % de
  abrir «Parejas» y el 98 % de la llegada del catálogo son llamadas a Tk.

**Esconder en vez de destruir (R7)**, Windows x64:

| Ventana | abrir-1 | abrir-2 | reabrir-oculta | ganancia |
|---|---|---|---|---|
| parejas | 588.6 | 554.8 | 493.1 | 0.11 |
| ajustes | 152.4 | 102.3 | 84.7 | 0.17 |
| pasada | 146.9 | 137.1 | 73.5 | 0.46 |

Linux: 0.15, 0.27 y 0.27. **Ninguna llega a 0.50: no se adopta.** Volver a enseñar «Parejas»
escondida cuesta casi lo mismo que rehacerla, porque Windows repinta sus 152 ventanas igual: lo que
pesa es cuántos widgets hay, no rehacerlos, y eso es lo que arregla el lienzo. La reapertura no
llamó a `dlg.aplicar()` (aún no existe en este árbol).

## Decisión

[Medida etapa 2, run 37888659462](https://github.com/Jeremaya25/prdrive/actions/runs/37888659462),
árbol `ae93325`: la tanda 2 fusionada con lo que estas dos medidas tocan («Parejas» en su sitio,
«Ajustes» con sus apartados guardados y su `dlg.aplicar()` al volver a enseñarse; la ventana
principal en su sitio no cambia ninguna de las dos). Mismo Python y vueltas que la primera lectura.

**R3, la lista de «Parejas»**, `construir` con 20 filas, Windows x64: ref 1229.7, ligera 158.4,
lienzo 77.3 (Linux: 166.9, 78.4, 38.5). ligera − lienzo = **81.1 ms** (regla: 20 ms) y
ref − ligera = 1071.3 ms (regla: 10 ms); en Linux 39.9 y 88.5 ms. El lienzo no es peor que las
otras en `elegir` (lienzo 1.2 ms, ligera 1.2, ref 5.9 en Windows) ni en `refrescar` (11.6 frente a
46.9 y 59.6). Con 50 filas: ref 1713.1, ligera 321.0, lienzo 140.7. **Se adopta el lienzo**: la
tarea 14, rama A (`ui/tk_tabla.py`), y la tarea 13 no hace nada. La lista en su sitio de la tarea 10
ya no rehace filas al llegar el catálogo (`refrescar` con 20 filas: 1450 → 60 ms), pero abrir sigue
pagando sus siete ventanas por fila.

**R7, esconder en vez de destruir**, Windows x64 (ganancia = 1 − reabrir-oculta / abrir-2):

| Ventana | abrir-2 | reabrir-oculta | ganancia | Linux |
|---|---|---|---|---|
| parejas | 511.6 | 483.8 | 0.05 | 0.19 |
| ajustes | 109.7 | 203.8 | −0.86 | −0.16 |
| pasada | 135.2 | 75.8 | 0.44 | 0.41 |

**No se adopta en ninguna** (regla: 0.50). «Ajustes» empeora: rehecha ya es barata (sus
apartados se pintan al momento y leen después) y volver a enseñarla escondida repinta más que
crearla. La de la pasada se queda cerca (rehacerla son 135 ms frente a 76), y lo que se nota al
pulsar lo quita la tarea 11 por otro lado: la principal se ocupa en el clic y la pasada sale en
el turno siguiente (se mide en Windows al cerrar la etapa).
