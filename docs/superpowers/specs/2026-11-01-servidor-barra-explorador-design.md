# «Servidor…» como el Explorador: barra de direcciones, botonera corta, búsqueda y tamaño libre — diseño

Fecha: 01/11/2026. Estado: **aprobado** (diseño en el chat del issue #195); se construye en cuatro
etapas en un solo PR. Parte de las piezas 1 a 3 del explorador, ya construidas
(`docs/superpowers/specs/2026-10-27-explorador-servidor-design.md`,
`…-servidor-transferencias-design.md`, `…-servidor-gestion-design.md`) y contadas en
`docs/agents/reference/servidor.md`.

## Por qué

El issue #195 pide acercar la ventana «Servidor» a la experiencia del Explorador de Windows: hoy
tiene dos barras de botones (la de gestión arriba, la de transferencias y «Cerrar» abajo), un
desplegable de remote que ocupa sitio, la ruta como texto que no se puede pulsar ni escribir, no
hay atrás ni adelante, no se puede buscar y la ventana no se puede agrandar.

## Qué se quiere

- **Botonera corta**: solo «Subir» (archivos y carpeta en un único botón) y «Nueva carpeta…».
  Renombrar, cortar y borrar pasan al clic derecho; «Cerrar» desaparece (cierra la X).
- **Releer** con F5 y como icono solo, en la barra de direcciones.
- **Barra de direcciones** con atrás, adelante, subir y releer; la ruta en migas
  (`servidor › d › CargaDatos › plantillas`) que se pulsan; escribir la ruta a mano (clic en la
  barra: Intro va, Esc cancela); el selector de servidor reducido a un icono con menú, para varios
  servidores; y a la derecha «Buscar en ‹carpeta›».
- **Búsqueda en subcarpetas** desde la carpeta que se ve.
- **Ventana redimensionable**, fluida, que recuerda su tamaño.

No se quiere: arrastrar y soltar (Tk no lo trae sin `tkdnd`), el desplegable de subcarpetas en cada
«›» de las migas (un listado por clic), actuar (bajar, renombrar, cortar, borrar) sobre los
resultados de una búsqueda, ni los botones laterales del ratón (en Tk 9 los números cambian de
sistema a sistema; queda Alt+← / Alt+→).

## Decisiones del dueño (01/11/2026)

1. **La búsqueda recorre las subcarpetas** del servidor (no filtra solo la carpeta que se ve).
2. **«Bajar…» va al clic derecho**, primera acción de una fila; no se queda en la botonera.
3. **La ventana recuerda su tamaño** entre aperturas, recortado a la pantalla.
4. Diseño aprobado tal como se presentó; el dueño pidió seguir sin más revisiones (spec, plan e
   implementación seguidos).

## La ventana, de arriba abajo

```
 ← → ↑ ⟳ │ 🖧▾  servidor › d › CargaDatos › plantillas        │ Buscar en plantillas
 (línea del indicador: conectando, errores, pareja, progreso de la búsqueda + botón)
 [Subir ▾] [Nueva carpeta…]
 (línea de lo cortado, como hoy)
 ┌ lista ──────────────────────────────────────────────── estira ┐
 └───────────────────────────────────────────────────────────────┘
 (panel de una copia o un cambio, como hoy)
 41 elementos
```

- El pie solo lleva la cuenta (`servidor.cuantos`), como la barra de estado del Explorador. Sin
  «Cerrar»: la X de la ventana pasa por el mismo `cerrar_ventana()` (la pregunta «¿Cancelarla y
  cerrar?» con un lote en marcha no cambia).
- Sin «Bajar…», «Subir archivos…» ni «Subir carpeta…» en el pie.

## Barra de direcciones

Un módulo nuevo que solo dibuja, `ui/tk_direcciones.py`; lo que decide, en `ui/servidor.py`.

### Botones de navegación

Cuatro botones de icono solo (`Quiet.TButton`, `compound="image"`, el texto queda como nombre
accesible): atrás (`back`), adelante (icono nuevo `adelante`, el espejo de `back`), subir
(`arriba`) y releer (`reload`). Cada uno se apaga cuando no hay a dónde ir (sin historial, en la
raíz) o no hay `rcd`.

### Historial

`servidor.Historial`, sin Tk: una lista de lugares `(remote, ruta)` y un índice. Se apunta **al
llegar** un listado, nunca al pedirlo: una carpeta que falla no entra ni mueve nada. Cada petición
lleva su movimiento:

- `nuevo` (entrar, subir, una miga, la ruta escrita, otro servidor, un resultado de la búsqueda):
  al llegar, si el lugar no es el actual, se añade detrás del actual y se tira lo que había delante.
- `atras` / `adelante`: al llegar, el índice se mueve uno.
- `releer`: no mueve nada.

Cruza servidores: volver atrás a una carpeta de otro remote es pedir ese remote y esa ruta
(`Navegacion.ir(remote, ruta)`, nueva; la regla de que `pedir()` solo pide el remote que se ve se
mantiene: `ir()` lleva los dos explícitos). Un lugar que también guarda una búsqueda (abajo)
vuelve a ella.

### Migas

Un **solo `tk.Canvas`** con textos y separadores «›», no un botón por carpeta: en Windows cada
widget es una ventana del sistema que se coloca y se pinta sola, y redimensionar una fila de
botones las mueve todas. En el lienzo solo se recolocan unos pocos textos, y solo si cambia su
ancho.

- `servidor.migas(remote, ruta)` da los tramos `(rótulo, ruta)`: el primero es el remote (su
  raíz), luego cada carpeta.
- `servidor.recoger(anchos, disponible)` decide cuántos tramos del principio se recogen en «…»
  cuando no caben: siempre se ve el último y, si cabe, el primero (el servidor). Es aritmética
  pura, se prueba sin Tk.
- Clic en un tramo: va a esa ruta (`nuevo`). Clic en «…»: menú con los tramos recogidos. El tramo
  bajo el ratón se resalta con el fondo de `theme` (como los botones `Quiet`).
- A la izquierda, el icono del servidor (`nas`) con «▾»: un menú con todos los remotes de
  `servidor.remotes_de()` (el que se ve, marcado); elegir otro es `nuevo` a su raíz. Con uno solo
  el menú lo enseña igual. Sin remotes, apagado.

### Escribir la ruta

Clic en el hueco del lienzo (a la derecha de la última miga), Ctrl+L o Alt+D: el lienzo cede su
sitio (`grid_remove`) a un `ttk.Entry` con la ruta de la carpeta (`/d/CargaDatos/plantillas`)
seleccionada entera.

- Intro: `servidor.ruta_escrita(texto)` la normaliza (`remote_picker.normalizar`: `\` vale como
  `/`, siempre desde la raíz del servidor; vacío es la raíz) y se pide como `nuevo`. Si no existe,
  la línea del indicador lo dice (`frase_error`) y la barra vuelve a la carpeta que se ve.
- Esc o perder el foco: vuelve a las migas sin pedir nada.
- No se escribe el remote en la ruta: para eso está el menú del servidor (un `a:b` en la raíz de
  un SFTP es una carpeta y sería ambiguo).

### Campo de búsqueda

`ttk.Entry` a la derecha con la pista «Buscar en ‹nombre de la carpeta›» (el del remote en la
raíz) por `theme.pista_campo()`. Ctrl+F o Ctrl+E le dan el foco. Esc lo vacía. Ver «Búsqueda».

## Botonera y clic derecho

- **«Subir ▾»**: un botón (`theme.boton_icono` con `up` y la flecha `abajo` a la derecha del
  texto) que despliega un menú con «Archivos…» y «Carpeta…»: los diálogos del sistema no dejan
  elegir archivos y carpetas a la vez. Cada entrada hace lo que hacían «Subir archivos…» y «Subir
  carpeta…» (mismos diálogos, mismos avisos y bloqueos).
- **«Nueva carpeta…»**, a su lado.
- Apagados como hoy (sin `rcd` o con un lote o un cambio en marcha). `tk_gestion.Barra` pasa a
  dibujar estos dos.
- **Clic derecho sobre una fila** (elige la fila si no lo estaba, como hoy): «Abrir» (solo con
  una carpeta), «Bajar…», separador, «Renombrar…» F2, «Cortar» Ctrl+X, «Pegar aquí» Ctrl+V,
  separador, «Borrar…» Supr.
- **Clic derecho en el hueco** de la lista (sin fila debajo): quita la selección y ofrece «Nueva
  carpeta…», «Pegar aquí», separador, «Subir archivos…», «Subir carpeta…», separador, «Releer» F5.
- Todo lo de después de elegir no cambia: las comprobaciones, los avisos de pareja, las
  confirmaciones, los textos.

## Teclas

| Tecla | Dónde | Hace |
|---|---|---|
| F5 | toda la ventana | releer (con una búsqueda, recorrer de nuevo) |
| Alt+← / Alt+→ | toda la ventana | atrás / adelante |
| Alt+↑ | toda la ventana | subir |
| Retroceso | la lista | subir (como hoy) |
| Ctrl+L, Alt+D | toda la ventana | escribir la ruta |
| Ctrl+F, Ctrl+E | toda la ventana | ir al campo de búsqueda |
| Intro, F2, Supr, Ctrl+X, Ctrl+V, Ctrl+Mayús+N | la lista | como hoy |
| Esc | el campo de ruta / el de búsqueda | cancelar / vaciar |

Las de la lista siguen atadas a la lista (en un campo, Ctrl+X corta texto). Las de toda la ventana
se atan al `Toplevel` y devuelven `"break"`.

## Búsqueda en subcarpetas

Solo lee: listados `operations/list` no recursivos, uno por carpeta, con el mismo `fs` fijo
(`<remote>:/`) que la navegación, así que se reutiliza la conexión en caché. Nada se escribe en el
servidor.

### El recorrido (`servidor.Busqueda`, sin Tk)

- Nace con `(remote, raíz, permisos)`; guarda `pendientes` (carpetas por leer, en anchura: lo
  cercano primero), `leidas` (`{carpeta: entradas}`), `fallidas` y un `numero` de generación.
- `siguientes(n)` da hasta `n` carpetas para pedir. `recibir(carpeta, entradas)` las guarda y
  añade sus subcarpetas a `pendientes`; `fallo(carpeta)` la cuenta como no leída y sigue (un
  permiso denegado no para la búsqueda). Una respuesta de otra generación no cuenta.
- **Tope**: al pasar de `LIMITE_ELEMENTOS = 100 000` elementos leídos se para y lo dice.
- `resultados(texto)` filtra todo lo leído: el nombre contiene el texto, sin mayúsculas ni
  acentos (`unicodedata`, como «Ajustes»); con `*` o `?` el texto es un patrón (`fnmatch` sobre
  los dos lados plegados: `*.pdf`). Cada resultado es `(carpeta, Entrada)`.
- `resultados_nuevos(texto, carpeta)` da solo los de una carpeta recién leída, para añadirlos a
  la lista sin rehacerla.

### En la ventana

- Empieza al dejar de teclear `ESPERA_BUSQUEDA_MS = 400` ms o con Intro, si hay texto. Si ya hay
  un recorrido de esa misma `(remote, raíz)`, **no se vuelve al servidor**: cambiar el texto
  vuelve a filtrar lo ya leído al instante y el recorrido sigue donde iba.
- `CONCURRENCIA_BUSQUEDA = 4` listados a la vez, cada uno con su `segundo_plano.lanzar` y su
  `Sondeo` (un `Sondeo` espera un encargo cada vez). Cuatro conexiones SSH como mucho: rclone usa
  ocho comprobadores por defecto en sus propios recorridos.
- La lista pasa a «modo resultados»: la columna «Carpeta» (oculta fuera de la búsqueda, por
  `displaycolumns`) dice dónde está cada uno, relativa a la raíz de la búsqueda; la iid es la ruta
  completa. Los resultados se añaden según llegan.
- La línea del indicador: «Buscando «x»… 230 carpetas · 14 encontrados» con la barra que va y
  viene y el botón «Detener»; al acabar, «14 encontrados en 230 carpetas» (más « · 3 carpetas no
  se pudieron leer» y, si se paró por el tope, «Búsqueda parada: demasiados elementos; busca desde
  una carpeta más concreta.»). Sin resultados: la etiqueta de encima de la lista dice «Nada
  coincide con «x».».
- **«Detener»** deja de pedir; lo que está en vuelo se descarta al llegar (otra generación). Lo
  leído se queda: seguir escribiendo filtra eso, e Intro reanuda el recorrido.
- **En los resultados**: doble clic o Intro en una carpeta entra en ella; en un archivo va a su
  carpeta y lo deja elegido. Clic derecho: «Abrir» (carpeta) y «Abrir la ubicación». Bajar,
  renombrar, cortar y borrar se hacen en su carpeta: esas acciones, sus comprobaciones y sus
  avisos suponen una carpeta. La botonera sigue valiendo para la carpeta raíz de la búsqueda.
- **Salir**: Esc o vaciar el campo vuelve a la carpeta (sus entradas siguen en `nav`, no se
  piden otra vez). Navegar (cualquier `nuevo`, atrás, adelante) acaba la búsqueda y vacía el
  campo; el lugar del historial desde el que se buscó guarda el texto, así que «Atrás» desde una
  ubicación **vuelve a los resultados** (de lo guardado, sin servidor, si sigue valiendo).
- **Lo guardado** es el de la última búsqueda (un solo recorrido); se tira con F5, al subir o
  cambiar algo en el servidor desde esta ventana (el mismo momento en que hoy se relee), al
  reconectar, o al buscar desde otra carpeta.

## Redimensionar

- `dlg.resizable(True, True)` tras `modal()` y antes de enseñarla (las reglas de DWM: `ui.md`).
- **El contenido pide su mínimo**: la lista nace con `FILAS_MINIMAS = 5` filas y su fila de la
  rejilla tiene peso; el nombre estira (`stretch`), las demás columnas no.
- **Abre más grande**: con el tamaño recordado o, si no hay, con el de hoy (`FILAS_VISIBLES = 12`
  filas). Las dos cosas recortadas a `pantalla_util`.
- **Mínimo de la ventana** (`minsize`): lo que pide con la lista mínima, también recortado.
- **Ya enseñada, no cambia de tamaño sola**: no hay más `reajustar()` (`Visor.crecer` + `centrar`)
  tras abrirse. El panel de una copia, la línea de lo cortado o la del indicador le quitan sitio a
  la lista, como en el Explorador. Se acabó el salto de la ventana al llegar el primer listado.
- **El `Visor` aprende un modo `redimensionable`**: con la ventana enseñada, el hueco es el
  tamaño real de la mirilla (`_hueco()` deja de quedarse con el mayor entre el pedido y el real),
  así que al encoger el contenido se ajusta en vez de quedar recortado. Si se encoge por debajo del
  mínimo (una pantalla diminuta), salen sus barras como en cualquier pantalla. Las demás pantallas
  no cambian.
- **Recordar**: al cerrar se guarda el tamaño (`winfo_width`/`height` del `Toplevel`) en
  `state/ventana.json`, campo nuevo `servidor` de `prefs.CAMPOS_VENTANA`, con la clave de
  `prefs.clave_ancho()` (sistema, Tk, escala: un tamaño medido al 150 % no vale al 100 %) y el
  valor `"ANCHOxALTO"`. Mismas reglas que el ancho de la principal (atómico, nunca lanza, solo si
  cambió).
- **Fluidez**: al redimensionar no se crea ni se destruye nada; el lienzo de las migas solo se
  recoloca si su ancho cambió; la frase del indicador corta por su ancho de diseño como hoy.

## Seguridad

Nada nuevo escribe: la búsqueda solo lista. Siguen igual la lista blanca de órdenes
(`rcd.ORDENES_PERMITIDAS`), las comprobaciones antes de lanzar, las confirmaciones (`EditPlan`) y
«la última petición gana» (`Navegacion`), que se extiende a la búsqueda por su generación.

## Pruebas

- **Sin Tk** (`tests/test_servidor.py`): `Historial` (nuevo tras atrás tira lo de delante, un
  fallo no mueve, releer no mueve, cruzar remotes, el texto de búsqueda guardado); `migas` y
  `recoger` (cabe todo, se recoge desde el principio, el último siempre, el primero si cabe);
  `ruta_escrita` (barras invertidas, vacío, espacios); `Busqueda` (anchura, generación, fallo que
  sigue, tope, `resultados` con mayúsculas, acentos y patrón, `resultados_nuevos`); `Navegacion.ir`.
- **Ventana** (`tests/test_tk_servidor*.py`, adaptados): la botonera de dos, «Subir ▾» y sus dos
  entradas, sin «Cerrar» ni «Bajar…» en el pie, los dos menús del clic derecho (fila y hueco), F5,
  Alt+flechas, atrás/adelante tras una carpeta que falla, las migas (clic, «…», menú del servidor),
  escribir la ruta (Intro, Esc, una que no existe), la búsqueda con el `rcd` falso (resultados según
  llegan, «Detener», afinar sin volver al servidor, abrir la ubicación, atrás a los resultados, el
  tope), redimensionar (encoger y estirar: el pie siempre a la vista, la lista crece, sin barras del
  `Visor` por encima del mínimo, nada cambia de tamaño solo al llegar un panel) y el tamaño
  recordado.
- `tests/test_tk_medidas.py`: «Servidor» abre dentro de `pantalla_util` en todas las `PANTALLAS`
  y su mínimo también.
- `tests/test_tk_visor.py`: el modo `redimensionable` (encoger sin recortar; las demás pantallas
  igual).

## Máquina real (filas nuevas en `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md`)

- **R1** (W): redimensionar con una carpeta de 5 000 entradas, arrastrando la esquina: sin
  parpadeo ni retraso visible; el pie no se pierde.
- **R2** (W, L): buscar en un SFTP real grande (miles de carpetas): resultados según aparecen,
  «Detener» para en el acto, cuántas conexiones SSH abre (`sshd` log).

## Fuera de alcance (queda dicho en `servidor.md`)

- Actuar sobre los resultados de una búsqueda (bajar, renombrar, cortar, borrar varios de
  carpetas distintas).
- El menú de subcarpetas en cada «›».
- Los botones laterales del ratón.
