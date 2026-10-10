# Etapa 4 del frontend rápido: resultados (09/10/2026)

Lo que hizo la etapa 4 y lo que se midió al cerrarla, según `docs/superpowers/specs/2026-10-08-frontend-rapido-design.md` («Limpieza») y su plan. La comprobación de tiempos mide el código de `52edd7d` y se repitió en el tip `ddd9a53`; entre ambos cambian pruebas, el drenaje del modo de tiempos (apagado en la comprobación), la documentación y, en `5845a3a`, `common/keepassxc.py` (el reloj de las esperas del llavero).

La etapa 4 añadió la marca de tiempos del propio dispositivo (`PRDRIVE_PERF=1`: `logs/perf.log`, y `perf.log` junto al del agente en las ventanas de host), marcas en cada familia de ventanas, la documentación de lo que queda de Tk 8.6, la checklist de máquina real y la fila F21 en la nube.

## Ejecuciones de CI

| Qué | Commit | Resultado | Enlace |
|---|---|---|---|
| Comprobación de tiempos, etapa 4 | 52edd7d | Pasa en Windows y en Linux | [37983163179](https://github.com/Jeremaya25/prdrive/actions/runs/37983163179) |
| Suite, etapa 4 | c1cf24d | Verde: Linux (xvfb, Tk 9), Python 3.11 sin pantalla, Windows (Tk 9); 145 ficheros | [37984842783](https://github.com/Jeremaya25/prdrive/actions/runs/37984842783) |
| Comprobación de tiempos, tip | ddd9a53 | Pasa en Windows y en Linux | [37988241590](https://github.com/Jeremaya25/prdrive/actions/runs/37988241590) |
| Suite, tip | ddd9a53 | Verde: Linux (xvfb, Tk 9), Python 3.11 sin pantalla, Windows (Tk 9); 145 ficheros | [37988241571](https://github.com/Jeremaya25/prdrive/actions/runs/37988241571) |
| Máquina real, F21 | 41faea0 | Linux 9/9, Windows 20/20 | [37978573740](https://github.com/Jeremaya25/prdrive/actions/runs/37978573740) |
| Comprobación de tiempos, etapa 3 (comparación) | 2460490 | Pasa | [37969775672](https://github.com/Jeremaya25/prdrive/actions/runs/37969775672) |

## Las medianas con las marcas apagadas

Las marcas están apagadas en la comprobación. Windows, 100 %, 5 parejas, mediana en ms, columna PR:

| Momento | Etapa 3 (2460490) | Etapa 4 (52edd7d) | Dif. |
|---|---|---|---|
| Ventana principal, desde que se lanza | 590 | 561 | -29 (-5 %) |
| `theme.apply()` de la principal | 113 | 101 | -12 (-11 %) |
| «Sincronizar ahora», hasta la ventana de la pasada | 206 | 196 | -10 (-5 %) |
| Abrir «Parejas» | 202 | 182 | -20 (-10 %) |
| «Parejas», desde que se lanza | 936 | 883 | -53 (-6 %) |
| Asistente, desde que se lanza | 595 | 568 | -27 (-5 %) |
| Asistente: pasar al paso «Dispositivo» | 302 | 333 | +31 (+10 %) |
| Suelo (ventana vacía de Tk) | 134 (de 130 a 149) | 136 (de 131 a 157) | |

Las cuentas deterministas (widgets, módulos, `escrituras.marcar` = 0) son iguales en las dos. En Windows, `52edd7d` baja las medianas de la tabla salvo el paso «Dispositivo» (que sube 31 ms) y el suelo (que sube 2 ms).

El paso «Dispositivo» sube 31 ms en la mediana (302 a 333), pero sus siete vueltas se agrupan así (etapa 4: 283,2 a 287,3 ms en tres vueltas y 333,2 a 358,1 en otras tres; etapa 3: 297,4 a 307,1 ms en seis), más una vuelta de unos 440 ms en cada etapa. El mejor tiempo baja de 297,4 a 283,2 ms. Su base también se movió (411 a 388 ms), así que no se puede atribuir a una deriva de la máquina; la causa no está investigada.

Las metas de `tests/rendimiento/presupuesto.toml` siguen sin cumplirse: en `52edd7d`, quince filas de Windows con meta no la cumplen. Por ejemplo, la ventana principal (561 frente a ≤ 350), «Parejas» (883 frente a ≤ 500), el asistente (568 frente a ≤ 300) y la pregunta del agente (332 frente a ≤ 300). La etapa 4 no las lleva a la meta.

En Linux el suelo subió de 102 a 123 ms, lo que apunta a un runner más lento. Dividido entre su suelo, «Ventana principal» pasa de 2,75 a 2,82 y el asistente de 2,66 a 2,67, pero ocho de las 28 filas comparables a 5 parejas y 100 % suben más de un 10 %:

| Momento (5 parejas, 100 %) | Cociente etapa 3 | Cociente etapa 4 | Cambio | ms (etapa 3 a etapa 4) |
|---|---|---|---|---|
| Abrir «Parejas» | 0,64 | 0,75 | +17 % | 65 a 92 |
| Volver a abrir «Parejas» | 0,57 | 0,67 | +19 % | 58 a 83 |
| Llega el catálogo a «Parejas» | 0,22 | 0,28 | +28 % | 22 a 34 |
| Elegir otra pareja (carga el editor) | 0,07 | 0,11 | +54 % | 7 a 13 |
| Abrir «Dispositivos» | 0,14 | 0,15 | +13 % | 14 a 19 |
| Llegan las notas de la flota a «Dispositivos» | 0,43 | 0,54 | +24 % | 44 a 66 |
| Elegir otro dispositivo de «Dispositivos» | 0,10 | 0,15 | +49 % | 10 a 18 |
| Apartado «Actualizaciones» | 0,05 | 0,06 | +16 % | 5 a 7 |

Las tres ejecuciones de Linux (etapa 3, `52edd7d` y el tip) repiten la subida de «Abrir «Parejas»»: la mediana pasa de 65 a 92 ms y a 111 ms, y el mejor tiempo de 63,2 a 91,0 y 91,0 ms. El suelo es estable en las dos últimas (123 y 122 ms). La causa no está investigada.

**El tip (`ddd9a53`).** Su comprobación (37988241590) da Pasa en las dos plataformas. En Windows sube frente a `52edd7d` en casi todas las filas, y su base del mismo run también: en 56 de 61 filas sube el PR y en 58 de 61 la base. La ventana principal pasa de 561 a 624 ms (base de 1253 a 1374) y «Abrir «Parejas»» de 182 a 224 (base de 781 a 868); el suelo pasa de 136 a 145 ms. En Linux las medianas quedan cerca de `52edd7d`, salvo «Abrir «Parejas»» (92 a 111 ms, +21 %), el catálogo (34 a 39 ms, +15 %) y el editor de flags (30 a 34 ms, +13 %); el suelo baja de 123 a 122 ms. Como la base de Windows sube a la vez, la subida no se atribuye al código sin más medidas; no está investigada.

## El diario del dispositivo frente a la comprobación

Una pasada local (Linux con xvfb, Python 3.14.8 y Tk 9.0.4 fijados, `correr.py --rondas 1 --env PRDRIVE_PERF=1`): el `perf-*.log` del dispositivo frente al valor que el driver anota en el mismo proceso, en la ronda medida. «Dentro» es ±20 % o ±10 ms, lo que sea más holgado.

| Momento | Driver (ms) | Dispositivo (ms) | Dif. (ms) | Dif. (%) | Dif. 50 parejas | Dif. 150 % | Veredicto |
|---|---|---|---|---|---|---|---|
| Abrir «Parejas» | 140,1 | 139,9 | -0,2 | 0 % | -0,2 | -0,2 | dentro |
| Reabrir «Parejas» (`open-parejas` vez=2) | 144,0 | 143,8 | -0,2 | 0 % | -0,3 | -0,3 | dentro |
| Llega el catálogo a «Parejas» | 62,8 | 62,5 | -0,3 | 0 % | -0,2 | -0,4 | dentro |
| «Parejas» desde que se lanza (suma) | 638,7 | 615,0 | -23,7 | -4 % | -21,9 | -33,2 | dentro |
| Arranque hasta la principal (`start-main`) | 475,6 | 475,1 | -0,5 | 0 % | -4,9 | -7,8 | excepción |
| Abrir «Ajustes» | 93,6 | 93,3 | -0,3 | 0 % | -0,2 | -0,2 | dentro |
| Cuatro apartados de «Ajustes» | 13,0 a 53,5 | 12,7 a 53,2 | -0,2 a -0,3 | -1 a -2 % | -0,2 a -0,3 | -0,2 a -0,4 | dentro |
| Cerrar «Ajustes» y volver | 37,2 | 31,0 | -6,2 | -17 % | -6,7 | -6,6 | dentro |
| «Sincronizar ahora», hasta la ventana de la pasada | 45,6 | 45,3 | -0,3 | -1 % | -0,4 | — | dentro |
| Cerrar la ventana de la pasada y volver | 53,6 | 51,6 | -2,0 | -4 % | -1,9 | — | dentro |
| Asistente: arranque (`start-wizard`) | 426,8 | 422,1 | -4,7 | -1 % | — | — | excepción |
| Asistente: paso «Dispositivo» | 95,4 | 95,2 | -0,2 | 0 % | — | — | dentro |
| Pregunta del agente: arranque (`start-agente`) | 357,8 | 354,8 | -3,0 | -1 % | — | — | excepción |
| 10 000 líneas en la pasada (`log-10k`) | 6,6 | 23,3 | +16,7 | +253 % | — | — | alcance distinto |

Quedan fuera de la tabla once momentos más, todos dentro de la banda a 5 parejas y 100 %, con su diferencia (dispositivo menos driver): `apply-main` -0,6, `apply-wizard` -0,7, `apply-agente` -0,8, `llega-instantanea` -0,2, `marcar` +0,2 (+20 %, dentro solo por la regla de 10 ms), `elegir-pareja` -0,4, `pane-otra-vez` -0,2, `open-dispositivos` -0,3, `llega-flota` -0,2, `elegir-dispositivo` -0,3 y `open-flags` -0,3. Los cuatro apartados de «Ajustes» van agrupados en su fila.

La mayoría de las filas quedan a menos de 0,5 ms por debajo del driver: el driver empieza su cronómetro justo antes del clic, y el dispositivo empieza el suyo cuando el clic ya se ha despachado; la marca acaba después del `update()` que la pinta. Excepciones, dichas aquí:

- **`start-*`**: el dispositivo cuenta desde la creación del proceso y el driver desde antes de lanzar el hijo (aquí, de 0,5 a 7,8 ms menos en el dispositivo). En Linux, el inicio del proceso tiene la resolución de un tic: 10 ms.
- **«Parejas» desde que se lanza** es una suma, no una marca: `start-main` + `open-parejas` deja fuera `llega-instantanea`, que el driver sí incluye. Con sus 20,9 ms, la diferencia es -2,8 ms (dispositivo menos driver); a 50 parejas, con sus 14,4 ms, es -7,5 ms (la tabla muestra -21,9), y al 150 %, con sus 23,4 ms, es -9,8 ms (la tabla muestra -33,2).
- **«Cerrar «Ajustes»»**: el driver empieza a contar antes de destruir el diálogo; el dispositivo, después. Esa destrucción es lo que recoge la diferencia constante de -6 a -7 ms; cuánto tarda no se ha medido aparte.
- **`log-10k`** y **`elegir-fila`** (1,8 ms en el driver, sin marca en el dispositivo): alcances distintos o momento sin marca. El driver además envuelve `Text.insert`, llama a `_mirar()` del sondeo y sustituye `wait_window`, el catálogo y la flota: nada de eso lo tiene el dispositivo.

Con `PRDRIVE_PERF=1` la comprobación de módulos falla (`modulos.main` 172 frente a 171; `agente` 159 frente a 157; `wizard` 236 frente a 234): son importaciones de la propia medida (`atexit`, `encodings.ascii` y, en el asistente, `unicodedata`). Con la variable apagada, la misma pasada da 171, 157 y 234, que son los techos de Linux en `tests/rendimiento/presupuesto.toml` (`[techo.linux]`); la CI no la pone.

Una vuelta local es ruido: «Cerrar la ventana de la pasada y volver» con 50 parejas dio 99 y 140 ms entre base y PR, que son el mismo árbol. Por eso se compara dispositivo contra driver en el mismo proceso.

**La lección del temporizador.** La versión anterior cerraba «sincronizar-ventana» a mitad de colocación: el diario registraba 0,6 ms para unos 51 ms de trabajo. Una callback de inactividad corre también dentro de `update_idletasks()` ajeno, y su `update()` ejecutaba temporizadores y entradas a medio colocar. `after(0)` solo corre en el bucle de eventos o en un `update()` completo. Y la marca drena antes de medir: sin ese `update()`, un cambio que mueve 400 widgets se medía en 1 ms y tarda 47 ms.

## Tk 8.6

- «Which Tk» de `ui.md` nombra tres sitios que aún usan Tk 8.6: un dispositivo en 3.13, el agente mientras siga en 3.13 y los lanzadores con Python de respaldo. El agente corre en su propio runtime, no en un Python del equipo (corregido en `9fe2bed`).
- Se queda `pista_etiqueta()` con la rama `TclError` de `pista_campo()`: sin ella, «Ajustes» y «Parejas» no abren en un 3.13 y no se llega a «Actualizar…». Se quedan también el pintor PNG de `icons._foto()` y la clave de anchos con la versión de Tk. La lista de borrado y su condición están en `ui.md` («Stage-4 removal list»).
- Prueba local con `/usr/bin/python3.12` (Tk 8.6) bajo xvfb: antes fallaban 2 de 145 ficheros (`test_perf_flota.py` y `test_tk_tabla.py`, línea 1118: `ttk::style theme styles` solo existe en Tk 9); después, 1 de 145 (`test_perf_flota.py`, un clic sobre una ventana sin mapear). `66fb533` y `c1cf24d` lo corrigen. La suite completa en 8.6 no se ha vuelto a correr.

## Arreglos de integración y tiempos de la suite

- `4c2e6dc`: «Dispositivos» dice su momento con `Tabla.momento_elegir`, una propiedad pública.
- `52edd7d`: el asistente carga los mismos módulos antes de pintar; `unicodedata` solo con la medida.
- `c1cf24d`: las pruebas de tiempos hacen el clic con la ventana a la vista.
- `e5556b8`: la prueba de la ventana principal suelta sus imágenes antes de salir (1596 líneas «Exception ignored» en Windows, cero después).
- `ddd9a53`: la marca espera en un temporizador (ver la lección).
- `5845a3a`: las pruebas del llavero dejan de esperar el arranque de KeePassXC (según su mensaje, 40 s menos por trabajo de la CI).

Paso de tests en Windows: 356 s para 138 ficheros en la etapa 3 (`37969775676`), 421 s para 145 en `c1cf24d` y 384 s para 145 en el tip (`37988241571`). En Linux: 202 s en la etapa 3, 179 s en `c1cf24d` y 202 s en el tip, así que la mejora de `c1cf24d` no se mantiene. La causa de la subida en Windows no está medida.

## Windows 11 ARM64, en un equipo de verdad (10/10/2026)

Pasada local en el equipo de desarrollo: Windows 11 Home (10.0.26200) ARM64, 12 núcleos, pantalla de 2944×1840 al 200 % (`tk scaling` 2,67) y tema oscuro del sistema. El código es el tip `f375528` ([PR 99](https://github.com/Jeremaya25/prdrive/pull/99)) frente a `main` en `f76fae3`, con el Python fijado de `windows-arm64` (3.14.8, Tk 9.0.4), extraído del archivo que ya estaba en la caché del instalador. La CI solo mide esta plataforma a mano. El disco es el interno y la caché del sistema estaba tibia: no es E1. Los ficheros de las pasadas (`resumen.md`, `crudo.jsonl`, capturas, `perf-*.log`) quedaron en el equipo, sin subir.

**Suite.** `run_all.py -j auto --gui-jobs 1`: pasan los 146 ficheros en 312,5 s (`-j 12`, una ventana a la vez, pantalla compartida), con 10 981 comprobaciones y ningún fallo. Las 44 líneas `(saltado)` son de otro sistema (POSIX, Linux, X11, permiso para crear enlaces): ninguna es por falta de pantalla o de `tkinter`. Los más lentos: `test_tk_servicio.py` 36,8 s, `test_run_all.py` 35,0 s, `test_tk_principal_ancho.py` 29,5 s, `test_tk_medidas.py` 26,7 s, y `test_perf_flota.py` y `test_tk_tabla.py` 26,0 s. `test_tk_asistente.py` pasa, pero escribe dos veces `Exception ignored … Variable.__del__ … main thread is not in main loop` antes de «asistente: lo de una unidad se lee después de pintar»: es el caso que describe `commands-testing.md` (una `Variable` recogida desde un hilo, con 1 s de espera cada una), y ahí falta el `gc.collect()`.

**Comprobación de tiempos.** `correr.py --rondas 7 --capturas`, con las marcas apagadas: **Pasa**. Ninguna cuenta supera su techo (`modulos.agente` 158, `modulos.main` 171 y `modulos.wizard` 235 quedan justo en él) y ningún momento empeora frente a la base. El resumen no enseña metas de tiempo en esta plataforma. Suelo: 115 ms (de 108 a 127). Mediana en ms; las filas que el resumen llama «100 %» corren aquí a la escala de la pantalla, el 200 %:

| Momento | Parejas | Base (`f76fae3`) | PR (`f375528`) | Dif. |
|---|---|---|---|---|
| Ventana principal, desde que se lanza | 5 | 1278 | 557 | -721 (-56 %) |
| Ventana principal, desde que se lanza | 50 | 1951 | 1232 | -719 (-37 %) |
| `theme.apply()` de la principal | 5 | 624 | 69 | -555 (-89 %) |
| «Sincronizar ahora», hasta la ventana de la pasada | 5 | 864 | 225 | -640 (-74 %) |
| «Sincronizar ahora», hasta la ventana de la pasada | 50 | 3822 | 232 | -3590 (-94 %) |
| Abrir «Parejas» | 5 | 1112 | 258 | -854 (-77 %) |
| Abrir «Parejas» | 50 | 2263 | 346 | -1917 (-85 %) |
| «Parejas», desde que se lanza | 5 | 2388 | 970 | -1417 (-59 %) |
| Llega el catálogo a «Parejas» | 50 | 6867 | 201 | -6666 (-97 %) |
| Llegan las notas de la flota a «Dispositivos» | 5 | 3598 | 197 | -3401 (-95 %) |
| Cerrar «Ajustes» y volver a la principal | 50 | 3547 | 89 | -3458 (-97 %) |
| Pregunta del agente, desde que se lanza | — | 978 | 262 | -716 (-73 %) |
| Asistente, desde que se lanza | — | 1103 | 518 | -584 (-53 %) |
| Asistente: pasar al paso «Dispositivo» | — | 494 | 500 | +6 (+1 %) |
| 10 000 líneas en la ventana de la pasada | — | 13786 | 5 | -13781 (-100 %) |

Con 50 parejas en lugar de 5, el PR tarda 675 ms más en la ventana principal (557 a 1232), 88 ms más en abrir «Parejas» (258 a 346) y 820 ms más en «Parejas» desde que se lanza (970 a 1790); el resumen da como meta +50 ms. Al 150 % forzado (`tk scaling` 2,0), que aquí es menos que la escala de la pantalla, la principal baja de 557 a 487 ms y abrir «Ajustes» de 212 a 158; abrir «Parejas» sube de 258 a 296. El paso «Dispositivo» es el único momento que no mejora: lee las unidades de verdad del equipo en los dos árboles.

**El diario del dispositivo frente al driver.** Otra pasada, `correr.py --rondas 1 --capturas --env PRDRIVE_PERF=1 --env PRDRIVE_TEMA=oscuro`: la vuelta medida del árbol del PR, con la misma banda que arriba (±20 % o ±10 ms). De 57 momentos comparados, 53 quedan dentro:

| Momento | Driver (ms) | Dispositivo (ms) | Dif. (ms) | Veredicto |
|---|---|---|---|---|
| Arranque hasta la principal (`start-main`) | 555,2 | 546,3 | -8,9 | dentro |
| Abrir «Parejas» | 260,8 | 260,7 | -0,1 | dentro |
| Llega a la principal la lectura del estado | 112,9 | 112,8 | -0,1 | dentro |
| «Sincronizar ahora», hasta la ventana de la pasada | 219,7 | 219,7 | 0,0 | dentro |
| Cerrar la ventana de la pasada y volver | 19,6 | 15,3 | -4,3 | dentro |
| Cerrar «Ajustes» y volver | 36,4 | 10,7 | -25,7 | fuera |
| Cerrar «Ajustes» y volver, al 150 % | 37,6 | 9,2 | -28,4 | fuera |
| Cerrar «Ajustes» y volver, 50 parejas | 90,7 | 61,8 | -28,9 | fuera |
| Asistente: arranque (`start-wizard`) | 513,8 | 509,0 | -4,8 | dentro |
| Asistente: paso «Dispositivo» | 488,0 | 487,9 | -0,1 | dentro |
| Pregunta del agente: arranque (`start-agente`) | 265,8 | 260,9 | -4,9 | dentro |
| 10 000 líneas en la pasada (`log-10k`) | 4,6 | 38,0 | +33,4 | alcance distinto |

Los demás quedan a 0,4 ms o menos del driver, salvo los `apply-*` (de -0,7 a -1,0 ms), los `start-*` (de -4,6 a -8,9 ms) y «Cerrar la ventana de la pasada» (-4,2 y -4,3 ms). «Cerrar «Ajustes»» se sale de la banda: la diferencia es de 26 a 29 ms, frente a los 6 a 7 ms de Linux. Si es lo mismo que allí (el driver cuenta la destrucción del diálogo y el dispositivo no), destruir «Ajustes» cuesta eso en este Windows; no se ha medido aparte. `cold-parejas` (una suma) y `elegir-fila` (sin marca) no tienen línea en el diario, como en Linux. Con `PRDRIVE_PERF=1` los tres techos de módulos fallan por uno: `modulos.agente` 159 frente a 158, `modulos.main` 172 frente a 171 y `modulos.wizard` 236 frente a 235. Es una sola vuelta y en tema oscuro: vale para comparar dispositivo y driver, que miden el mismo proceso, no como medianas.

**Capturas.** 13 de 13 pintadas en las dos pasadas, en tema claro la primera y en oscuro la segunda. Se han mirado cinco: «Parejas» y «Dispositivos» en claro, y la principal, «Ajustes» y la pregunta del agente en oscuro, todas al 200 %. Los colores son los del tema, los iconos salen nítidos, no hay texto cortado ni un control sobre otro, y la barra de título sale oscura con el tema oscuro. «Parejas» (2012×1680 px) y «Dispositivos» con la flota (2079×1680 px) llegan al alto de la pantalla y salen con barra de desplazamiento. No sustituye a E2: es un solo equipo, ARM64, sin el asistente del `.exe` y sin pantallas al 100 % ni al 150 % de verdad.

**El dispositivo del equipo.** El equipo tiene un prdrive en uso montado en `P:`. Sus 263 ficheros de programa y la raíz de la unidad quedaron iguales antes y después de las tres pasadas, y el agente residente siguió en marcha.

**Después de la pasada.** El ruido de `test_tk_asistente.py` se reproduce en Linux haciendo que cada hilo recoja la basura al empezar (`threading.Thread.run` envuelto con un `gc.collect()` delante): salen las mismas dos líneas en el mismo sitio y el fichero tarda 2 s más. Con ese peor caso, otros ocho ficheros escriben la misma línea (`test_perf_principal.py`, `test_tk_equipo_lecturas.py`, `test_tk_medidas.py`, `test_tk_parejas_vista.py`, `test_tk_pasada.py`, `test_tk_reparacion.py`, `test_tk_segundo_plano.py` y `test_tk_servicio.py`; 54 líneas entre los nueve en una pasada) y dos fallan una comprobación de tiempo («1080p: y se cierra al terminar» y «reabrir con el hilo vivo: el remoto oyó un solo `cat`»). Los nueve recogen ahora la basura antes de mover Tk con un hilo de verdad y, con el peor caso, ya no la escriben. Ese peor caso destapó además una carrera en el paso de VeraCrypt del asistente (`ui/tk_crypto.py`): si la medida de escritura acababa entre que se pintaba la espera y se miraba si seguía midiendo, la línea se quedaba en «Midiendo lo que escribe la unidad…» (`test_tk_equipo_lecturas.py`, «la sonda llega sola», fallaba en la mayoría de las pasadas). Ahora se mira antes de pintar, y un test lo fija.

## Lo que queda en una máquina de verdad

- **E1**: arranque en frío desde una memoria USB, en W y en L, con cronómetro o con `perf.log`. Sigue por hacer: la pasada de Windows ARM64 de arriba va con el disco interno y la caché tibia.
- **E2**: el aspecto en pantalla real (claro, oscuro; 100, 150 y 200 %), en W y en W10. Sigue por hacer; visto en parte, al 200 %, en el Windows 11 ARM64 de arriba.
- **E3**: F21 en la nube, hecha (L 9/9, W 20/20 en `maquina-real-resultados.md`).

La lista completa y lo que hacer con lo que salga: `docs/superpowers/pruebas/2026-10-09-frontend-pendiente-en-real.md` (estado: por hacer).

**Decisiones del dueño, estado actual.** Las tomadas por defecto siguen para revisar.

**Decisión 1.** Tk 8.6, abierta (corregida). No se borra nada en la etapa 4. El agente corre en su propio runtime, así que exigir Tk 9 a las ventanas de host no hace falta por el agente. Quitar Tk 8.6 pide: ningún dispositivo en 3.13, ningún agente en 3.13 y los lanzadores de respaldo exigiendo Tk 9.

**Decisión 5.** Abierta. Los paneles de «Ajustes» se quedan como están. La medida del alfa binario (run 37848307713, `2026-10-08-etapa-1b-resultados.md` §1c) la informa; el workflow `alfa-binario-pintor.yml` que cita el plan ya no está en el árbol.

**Decisión 10.** Abierta. Comprobación de accesibilidad en Windows (DLL de Tk 9.0.4 y UI Automation): sigue en la especificación.

**Decisiones 2–4 y 6–9.** Tomadas: `start-*` desde la creación del proceso; drenaje con `update()` en modo de tiempos; F21 precompila un árbol copiado; `perf.log` en `logs/`; detalles solo con números y palabras fijas; apagado salvo `PRDRIVE_PERF`; escritura en un hilo de fondo.

## Encontrado de paso, fuera de esta etapa

- `common/keepassxc.py`, `sonda_cli` (línea 1408): usa `CREATE_NO_WINDOW` sin definir en el módulo (el resto del fichero escribe `model.CREATE_NO_WINDOW`). Lo introdujo `dddeae8`. En Windows, `llave_vale()` lanza `NameError`; en Linux no se ve. Arreglado en `main` por la PR 98 (`0845c14`).
