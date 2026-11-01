# «Servidor…» como el Explorador — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La ventana «Servidor» con barra de direcciones (atrás, adelante, subir, releer, migas, ruta escrita, menú de servidores, búsqueda en subcarpetas), botonera de dos botones, acciones en el clic derecho, redimensionable y con el tamaño recordado (issue #195).

**Architecture:** Lo que decide sigue en `ui/servidor.py` (sin Tk): historial, migas, ruta escrita y el recorrido de la búsqueda son clases y funciones puras. Lo que dibuja la barra va a un módulo nuevo, `ui/tk_direcciones.py`; la botonera y los menús, a `ui/tk_gestion.py`; `ui/tk_servidor.py` encadena. El `Visor` de `ui/tk.py` gana un modo `redimensionable`.

**Tech Stack:** Python 3.11+ stdlib, Tk 9 (`tkinter`/`ttk`), tests como scripts (`tests/_harness.Checks`).

**Spec:** `docs/superpowers/specs/2026-11-01-servidor-barra-explorador-design.md`

## Global Constraints

- Comentarios, docstrings y todo lo que ve el usuario, en español; docs de `docs/agents/`, en inglés.
- `import tkinter` solo dentro de funciones; `tk_*` solo dibujan; ningún hex en un `tk_*` (colores de `theme`, leídos al dibujar: son globales que pone `theme.apply()`); distancias con `theme.medida()`/`icons.px()`, nunca un entero suelto (`tests/test_tk_densidad.py`).
- Nada de red ni Tk en `ui/servidor.py`; toda llamada al `rcd` va por `segundo_plano.lanzar` y se recoge con un `Sondeo` (un encargo por `Sondeo`).
- La última petición gana (`Navegacion`); la búsqueda, por generación.
- Ninguna orden nueva al servidor: la búsqueda solo usa `operations/list` no recursivo con `fs = "<remote>:/"`.
- Valores fijados por la spec: `FILAS_VISIBLES = 12`, `FILAS_MINIMAS = 5`, `ESPERA_BUSQUEDA_MS = 400`, `CONCURRENCIA_BUSQUEDA = 4`, `LIMITE_ELEMENTOS = 100_000`.
- Textos fijados: «Subir», «Archivos…», «Carpeta…», «Nueva carpeta…», «Abrir», «Bajar…», «Abrir la ubicación», «Releer», «Detener», «Buscar en {carpeta}», «Buscando «{t}»… {n} carpetas · {m} encontrados», «{m} encontrados en {n} carpetas», « · {k} carpetas no se pudieron leer», «Búsqueda parada: demasiados elementos; busca desde una carpeta más concreta.», «Nada coincide con «{t}».».
- Tk 9 es el único Tk soportado; con Tk 8.6 la ventana tiene que abrir igual (pista del campo por `theme.pista_campo`).
- Verificación mientras se trabaja: `python tests/run_all.py --cambios -j auto` y los tests de ventana nombrados a mano (`python tests/test_tk_servidor.py`), bajo `xvfb-run` si hace falta.

## Review Focus

1. Un nombre de carpeta o de remote con espacios, muy largo o con «›»: las migas lo miden y lo recogen en «…» sin desbordar; la ruta escrita con `\` o una barra final va a la misma carpeta. → test en Task 2 (`recoger`, `ruta_escrita`) y en Task 3 (miga larga en una ventana estrecha).
2. Una respuesta tardía de una búsqueda anterior (tras «Detener», otra búsqueda o navegar) no pinta resultados. → test en Task 5 (generación).
3. Una subcarpeta sin permiso o que ya no existe en medio de la búsqueda: se cuenta y se sigue. → test en Task 5.
4. Encoger la ventana con el panel de un lote a la vista: el pie y «Cancelar» siguen a la vista o con la barra del `Visor`, nunca recortados sin barra. → test en Task 4.
5. Un tamaño recordado mayor que la pantalla de ahora, o un `ventana.json` con basura: se recorta o se ignora. → test en Task 4.

---

### Task 1: Botonera corta, «Subir ▾» y los dos menús del clic derecho

**Files:**
- Modify: `ui/tk_gestion.py` (`ROTULOS`, `ORDEN_BARRA`, `Barra`, `menu_contextual`, nuevo `menu_subir`)
- Modify: `ui/tk_servidor.py` (pie, `acciones`, `estados_menu`, `menu_derecho`, F5)
- Test: `tests/test_tk_gestion.py`, `tests/test_tk_servidor.py`, `tests/test_tk_servidor_gestion.py`, `tests/test_tk_medidas.py`

**Interfaces:**
- Produces: `tk_gestion.ORDEN_BARRA = ("subir", "nueva")`; `tk_gestion.ORDEN_MENU_FILA = ("abrir", "bajar", None, "renombrar", "cortar", "pegar", None, "borrar")`, `ORDEN_MENU_HUECO = ("nueva", "pegar", None, "archivos", "carpeta", None, "releer")`, `ORDEN_MENU_RESULTADO = ("abrir", "ubicacion")` (Task 5) (`None` = separador); `ATAJOS = {"renombrar": "F2", "cortar": "Ctrl+X", "pegar": "Ctrl+V", "borrar": "Supr", "releer": "F5"}`; `Barra(padre, acciones)` con `.subir` y `.nueva` y `encender(subir: bool, nueva: bool)`; `menu_subir(padre, acciones, estados) -> tk.Menu` (entradas «Archivos…», «Carpeta…»); `menu_contextual(padre, orden, acciones, estados) -> tk.Menu`.
- Produces en la ventana (para los tests): `dlg.acciones: dict[str, Callable[[], None]]` (`abrir`, `bajar`, `archivos`, `carpeta`, `nueva`, `renombrar`, `cortar`, `pegar`, `borrar`, `releer`) y `dlg.estados_menu() -> dict[str, bool]`; desaparecen `dlg.bajar`, `dlg.subir_archivos`, `dlg.subir_carpeta` y el botón «Cerrar».

- [ ] **Step 1: Tests de `tk_gestion`**: `Barra` tiene exactamente `subir` y `nueva` (texto «Subir» con el icono, «Nueva carpeta…»), nacen apagados y `encender(True, False)` enciende solo «Subir»; `menu_subir` da dos entradas con esos rótulos y estados; `menu_contextual(..., ORDEN_MENU_FILA, ...)` da 6 entradas y 2 separadores en ese orden, con `accelerator` F2/Ctrl+X/Ctrl+V/Supr, apagadas las de estado falso; `ORDEN_MENU_HUECO` da «Nueva carpeta…», «Pegar aquí», «Subir archivos…», «Subir carpeta…», «Releer» (rótulos de `ROTULOS_HUECO` cuando difieren: en el hueco «archivos» es «Subir archivos…»). Sin color ni distancia sueltos.
- [ ] **Step 2: Ejecutarlos y verlos fallar** — `xvfb-run -a python tests/test_tk_gestion.py` → FAIL (`ORDEN_MENU_FILA` no existe).
- [ ] **Step 3: Implementar en `tk_gestion.py`**. «Subir» es un `ttk.Button` con texto «Subir» y el icono `abajo` a la DERECHA (`theme.boton_icono` y luego `compound="right"`: un botón ttk lleva una sola imagen, y la flecha es lo que dice «despliega»; nada de «▾» en el texto, que puede no estar en las fuentes del programa). La acción `"subir"` de `Barra` la da la ventana, que enseña `menu_subir` justo debajo del botón (`_mostrar_menu(menu, boton.winfo_rootx(), boton.winfo_rooty() + boton.winfo_height())`).
- [ ] **Step 4: En `tk_servidor.py`**: el pie solo con `cuenta`; `acciones` y `estados_menu()` (`abrir`: una carpeta elegida; `bajar`: libre y algo elegido; `archivos`/`carpeta`/`nueva`: libre; `releer`: hay `rcd`; los demás como hoy); «Subir» abre `menu_subir` por `_mostrar_menu`; `menu_derecho`: con fila debajo, elige si no lo estaba y enseña `ORDEN_MENU_FILA`; sin fila, `selection_remove` de todo y enseña `ORDEN_MENU_HUECO`; F5 atado a `dlg` (devuelve `"break"`, solo si `estados_menu()["releer"]`). `WM_DELETE_WINDOW` sigue en `cerrar_ventana`.
- [ ] **Step 5: Adaptar los tests de ventana**: donde decían `dlg.bajar.invoke()` → `dlg.acciones["bajar"]()`; `dlg.subir_archivos/subir_carpeta.invoke()` → `dlg.acciones["archivos"/"carpeta"]()`; los estados de los botones → `dlg.estados_menu()[…]`; `dlg.barra.renombrar/cortar/borrar` → `dlg.acciones[…]` y `estados_menu`. Nuevos: el pie no tiene botones (`[w for w in pie.winfo_children() if isinstance(w, ttk.Button)] == []`); F5 relee (un `operations/list` más de la misma carpeta); clic derecho en el hueco quita la selección y su menú tiene «Nueva carpeta…» encendida; «Abrir» del menú de fila entra en la carpeta.
- [ ] **Step 6: Pasar** `xvfb-run -a python tests/test_tk_gestion.py`, `…/test_tk_servidor.py`, `…/test_tk_servidor_gestion.py`, `…/test_tk_medidas.py` → PASS.
- [ ] **Step 7: Commit** «Servidor: botonera de dos botones y las acciones en el clic derecho».

### Task 2: Historial, migas y ruta escrita (sin Tk)

**Files:**
- Modify: `ui/servidor.py`
- Test: `tests/test_servidor.py`

**Interfaces:**
- Produces:
  - `Lugar(remote: str, ruta: str, busqueda: str = "")` (frozen dataclass).
  - `NUEVO, ATRAS, ADELANTE, RELEER = "nuevo", "atras", "adelante", "releer"`.
  - `class Historial`: `actual -> Lugar | None`; `puede_atras/puede_adelante -> bool`; `anterior()/siguiente() -> Lugar | None` (no mueve); `llegar(lugar: Lugar, movimiento: str) -> None`; `apuntar_busqueda(texto: str) -> None` (guarda el texto en el lugar actual).
  - `Peticion` gana `movimiento: str = NUEVO` y `busqueda: str = ""`; `Navegacion.pedir(ruta, movimiento=NUEVO)`, `Navegacion.cambiar_remote(nombre)` igual, nuevo `Navegacion.ir(remote, ruta, movimiento, busqueda="") -> Peticion`.
  - `migas(remote: str, ruta: str) -> tuple[tuple[str, str], ...]` (`(rótulo, ruta)`; el primero `(remote, RAIZ)`).
  - `recoger(anchos: Sequence[int], disponible: int, ancho_puntos: int) -> int` (cuántos tramos del principio, después del primero, van a «…»; 0 si cabe todo).
  - `ruta_escrita(texto: str) -> str` (normalizada desde la raíz).

- [ ] **Step 1: Tests** en `tests/test_servidor.py`: `Historial` — tras `llegar(A,NUEVO)`, `llegar(B,NUEVO)`: `puede_atras`, `anterior()==A`; `llegar(A,ATRAS)` → `puede_adelante`, `siguiente()==B`; `llegar(C,NUEVO)` → `puede_adelante` False; `llegar(C,NUEVO)` otra vez no duplica; `RELEER` no mueve; un lugar en otro remote cuenta; `apuntar_busqueda("x")` y tras ir a D y `anterior()` da el lugar con `busqueda == "x"`. `migas("nas", "/d/Carga Datos")` → `(("nas","/"),("d","/d"),("Carga Datos","/d/Carga Datos"))`; raíz → solo el primero. `recoger([40,30,30,30], 200, 10)` → 0; `recoger([40,30,30,30], 110, 10)` → 2 (quedan primero, «…», último); con `disponible` menor que primero+«…»+último, recoge todos los de en medio. `ruta_escrita("d\\Carga\\")` → `"/d/Carga"`; `""` y `"  "` → `"/"`; `"/a//b/"` → `"/a/b"`. `Navegacion.ir("otro","/x",ATRAS)` da una `Peticion` con ese remote; `recibir` la acepta y cambia `remote`.
- [ ] **Step 2: Verlos fallar** — `python tests/test_servidor.py` → FAIL (`Historial` no existe).
- [ ] **Step 3: Implementar** en `ui/servidor.py`. `Historial`: lista de `Lugar` + índice; `llegar(NUEVO)` con un lugar igual (mismo remote y ruta) al actual no hace nada; `ATRAS`/`ADELANTE` mueven el índice solo si el lugar es el que toca (si no, se trata como `NUEVO`). `recoger`: algoritmo — si `sum(anchos) <= disponible` → 0; si no, k desde 1 mientras `anchos[0] + ancho_puntos + sum(anchos[1+k:]) > disponible` y `1+k < len(anchos)-1` → k+1.
- [ ] **Step 4: Pasar** `python tests/test_servidor.py` → PASS.
- [ ] **Step 5: Commit** «Servidor: historial, migas y ruta escrita, sin Tk».

### Task 3: La barra de direcciones en la ventana

**Files:**
- Create: `ui/tk_direcciones.py`
- Modify: `ui/icons.py` (icono `adelante`), `ui/tk_servidor.py`, `.claude/rules/servidor.md` (paths), `docs/agents/reference/servidor.md` (lista de archivos)
- Test: `tests/test_tk_direcciones.py` (nuevo, ventana), `tests/test_tk_servidor.py`, `tests/test_tk_servidor_gestion.py`, `tests/test_tk_medidas.py`

**Interfaces:**
- Consumes: Task 2.
- Produces: `class Direcciones(padre, acciones)` con `acciones` = `atras`, `adelante`, `subir`, `releer` (sin args), `ir(ruta)`, `servidor(nombre)`, `escrita(texto)`, `buscar(texto)` (cada cambio del campo), `buscar_ya(texto)` (Intro), `vaciar()` (Esc en la búsqueda). Atributos: `marco`, `atras`, `adelante`, `arriba`, `releer`, `servidor` (botones), `lienzo` (`tk.Canvas` de las migas), `campo` (`ttk.Entry` de la ruta), `busqueda` (`ttk.Entry`), `texto_busqueda` (`StringVar`). Métodos: `poner(remote, ruta, remotes)`, `encender(atras, adelante, arriba, releer, servidor, buscar)`, `editar()`, `editando -> bool`, `tramos() -> list[tuple[str, str | None]]` (lo dibujado: rótulo y ruta, «…» con `None`), `pulsar(i)` (lo que hace un clic en el tramo `i`), `menu_servidores() -> tk.Menu`, `menu_recogidos() -> tk.Menu`.
- Produces en la ventana: `dlg.direcciones`; desaparecen `dlg.elegido`, `dlg.ruta`, `dlg.arriba`.

- [ ] **Step 1: Tests de `tk_direcciones`**: `poner("nas", "/d/CargaDatos/plantillas", ["nas","otro"])` → `tramos()` es nas, d, CargaDatos, plantillas; en un lienzo estrecho (`lienzo.configure(width=…)` + `update`) aparece «…» y siguen el primero y el último; `pulsar(1)` llama `ir("/d")`; `pulsar` en «…» enseña `menu_recogidos()` con los tramos ocultos; `menu_servidores()` tiene «nas» y «otro», el actual con marca, y elegir «otro» llama `servidor("otro")`; `editar()` enseña `campo` con `/d/CargaDatos/plantillas` seleccionado y quita el lienzo; Intro llama `escrita(texto)` y vuelve a las migas; Esc vuelve sin llamar; la pista de búsqueda es «Buscar en plantillas» (en la raíz, «Buscar en nas»); `encender(False, …)` apaga «atrás». Sin hex ni enteros sueltos (`test_tk_densidad`).
- [ ] **Step 2: Verlos fallar.**
- [ ] **Step 3: Implementar `ui/tk_direcciones.py`**: rejilla `[atras][adelante][arriba][releer][servidor▾][migas o campo (peso)][búsqueda]`; los cuatro primeros `Quiet.TButton` con `compound="image"`; el lienzo con fondo `theme.SUPERFICIE`, borde `theme.BORDE` (`highlightthickness`), alto el de un `TEntry` (`campo.winfo_reqheight()`), textos con `theme.fuente()`, separadores «›» en `theme.TINTA3`, resalte bajo el ratón `theme.ACENTO_SUAVE`; `<Configure>` del lienzo vuelve a colocar los tramos solo si cambió el ancho; clic fuera de un tramo → `editar()`; la búsqueda con `theme.pista_campo` (con Tk 8.6 se guarda la etiqueta y se le cambia el texto). Icono `adelante` en `icons.py`: el espejo de `back`.
- [ ] **Step 4: En `tk_servidor.py`**: `estado["historial"] = servidor.Historial()`; `lanzar_peticion(pedida, esperar=None)` acepta `("ruta", r, movimiento)`, `("remote", nombre)` y `("lugar", Lugar, movimiento)`; `llega()` llama `historial.llegar(Lugar(p.remote, p.ruta, p.busqueda), p.movimiento)` tras `nav.recibir`; `pintar()` llama `direcciones.poner(...)` y `encender(...)`; `fallo()` vuelve a poner las migas de la carpeta que se ve. Teclas en `dlg`: `<Alt-Left>`, `<Alt-Right>`, `<Alt-Up>`, `<Control-l>`, `<Alt-d>`, `<Control-f>`, `<Control-e>`; `<BackSpace>` en la lista sigue subiendo; `releer` usa `RELEER`.
- [ ] **Step 5: Tests de ventana**: atrás/adelante tras entrar en «datos» y «notas»; una carpeta que falla («privado») no entra en el historial; cambiar de servidor por el menú y volver atrás al primero; escribir `datos\notas` + Intro abre `/datos/notas`; escribir `/no-existe` dice «no existe» y las migas siguen en la carpeta de antes; Alt+← y Alt+→; un tramo pulsado navega. Adaptar los usos de `dlg.elegido` (`menu_servidores().invoke(i)`), `dlg.ruta` (`direcciones.tramos()`), `dlg.arriba` (`direcciones.arriba`). Medidas: con el remote largo de `test_tk_medidas`.
- [ ] **Step 6: Pasar** los cuatro scripts → PASS.
- [ ] **Step 7: Commit** «Servidor: barra de direcciones con atrás, adelante, migas y ruta escrita».

### Task 4: Ventana redimensionable y tamaño recordado

**Files:**
- Modify: `ui/tk.py` (`Visor`, `cuerpo_visible`), `ui/prefs.py` (`CAMPOS_VENTANA`), `ui/tk_servidor.py`, `ui/tk_transferencia.py` (cortes del panel), `docs/agents/reference/ui.md`
- Test: `tests/test_tk_visor.py`, `tests/test_prefs.py`, `tests/test_tk_servidor.py`, `tests/test_tk_medidas.py`

**Interfaces:**
- Produces: `Visor(padre, ancho=None, alto=None, redimensionable=False)`; `cuerpo_visible(ventana, directo=False, redimensionable=False, **opciones)`; `prefs.CAMPOS_VENTANA` gana `"servidor_ancho": 1, "servidor_alto": 1`; en `tk_servidor`: `FILAS_MINIMAS = 5`, `ANCHO_INICIAL = 820`, `ANCHO_MINIMO = 640` (px del diseño, del recuadro), `_tamano_inicial(dlg) -> tuple[int, int]`.

- [ ] **Step 1: Tests**: `test_tk_visor` (sección nueva) — un `Visor(redimensionable=True)` en un `Toplevel` enseñado: tras `geometry` más pequeña (por encima del mínimo del contenido) el interior mide lo que la mirilla y no hay barras; por debajo, sale la vertical; uno normal sigue como antes (`_hueco()` el mayor). `test_prefs` — `recordar("servidor_ancho", clave, 900)` y `recordado` lo devuelve; basura (`"900"`, `True`, `0`) → `None`. `test_tk_servidor` — `dlg.resizable()` es `(True, True)`; `wm minsize` > 0 y ≤ `pantalla_util`; encoger con `dlg.geometry` al mínimo: `cuenta` sigue dentro de la ventana; estirar: la lista (su `winfo_height`) crece; abrir el panel de un lote no cambia `winfo_width/height` del `Toplevel`; cerrar guarda `servidor_ancho/alto` y la siguiente apertura abre a ese tamaño; un recordado de 10 000 × 10 000 abre dentro de `pantalla_util`. `test_tk_medidas` — «Servidor» cabe y no queda recortado (ya existe) y también su `minsize` cabe.
- [ ] **Step 2: Verlos fallar.**
- [ ] **Step 3: `Visor`**: con `redimensionable`, `_hueco()` devuelve `(winfo_width, winfo_height)` de la mirilla cuando está mapeada y mide más de 1; si no, lo de siempre. `cuerpo_visible` pasa el argumento.
- [ ] **Step 4: `tk_servidor`**: `dlg.resizable(True, True)` tras `modal()`; `cuerpo_visible(..., redimensionable=True)`; la lista con `height=FILAS_MINIMAS`, su fila con `rowconfigure(weight=1)` y `tarjeta` con `sticky="nsew"`; `COLUMNAS` «Nombre» a 220 con `stretch`; el indicador con `ancho=440`; antes de `mostrar`: `dlg.visor.base = _tamano_inicial(dlg)` (lo recordado si lo hay; si no, `max(natural_x, medida(ANCHO_INICIAL))` × natural + `(FILAS_VISIBLES - FILAS_MINIMAS)` filas de `rowheight` del estilo `Treeview`) y `dlg.minsize(...)` con el natural mínimo más las franjas del `Visor`, recortado a `pantalla_util`; `reajustar()` no hace nada con la ventana enseñada; al cerrar (`cerrar()`), si la mirilla está mapeada, `prefs.recordar` de su `winfo_width/height`. En `tk_transferencia.Panel`, `titulo`, `archivo`, `cuenta` y `ritmo` cortan a `theme.medida(ANCHO_RESULTADO)`.
- [ ] **Step 5: Pasar** los cuatro scripts → PASS.
- [ ] **Step 6: Commit** «Servidor: ventana redimensionable que recuerda su tamaño».

### Task 5: Búsqueda en subcarpetas

**Files:**
- Modify: `ui/servidor.py`, `ui/tk_servidor.py`, `ui/tk_gestion.py` (`ORDEN_MENU_RESULTADO`)
- Test: `tests/test_servidor.py`, `tests/test_tk_servidor_busqueda.py` (nuevo), `.claude/rules/servidor.md` (paths)

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `LIMITE_ELEMENTOS = 100_000`; `coincide(nombre: str, texto: str) -> bool`; `Resultado(carpeta: str, entrada: Entrada)` (frozen; `ruta` = `remote_picker.entrar(carpeta, nombre)`).
  - `class Busqueda(remote: str, raiz: str, permisos: bool)`: `numero: int`; `pendientes`, `leidas: dict[str, tuple[Entrada, ...]]`, `fallidas: int`, `parada: bool`, `elementos: int`; `siguientes(n: int) -> list[str]` (las saca de `pendientes` y las marca en vuelo); `recibir(carpeta, entradas) -> None`; `fallo(carpeta) -> None`; `acabada -> bool` (sin pendientes ni en vuelo, o `parada`); `detener() -> None` (`numero += 1`, vacía en vuelo y deja `pendientes` para reanudar); `reanudar()`; `resultados(texto) -> list[Resultado]`; `de_carpeta(texto, carpeta) -> list[Resultado]`; `texto_progreso(texto) -> str`; `texto_final(texto) -> str`.
- Produces en la ventana: `dlg.busqueda_actual() -> servidor.Busqueda | None`, `dlg.en_resultados() -> bool`.

- [ ] **Step 1: Tests sin Tk**: `coincide("Foto Ñandú.JPG", "nandu")` True; `"*.jpg"` True; `"*.png"` False; `"a?c"` con «abc» True. `Busqueda("nas", "/", False)`: `siguientes(4) == ["/"]`; `recibir("/", (carpeta a, carpeta b, archivo x))` → `siguientes(4) == ["/a", "/b"]`; `fallo("/a")` → `fallidas == 1` y sigue; `recibir` de una carpeta no pedida o tras `detener()` no cuenta; `elementos` > `LIMITE_ELEMENTOS` → `parada` y `acabada`; `resultados("x")` da `Resultado("/", x)`; `de_carpeta("x", "/b")` solo los de «/b»; los textos de progreso y final con las frases de la spec (singular «1 carpeta», «1 encontrado»).
- [ ] **Step 2: Verlos fallar.**
- [ ] **Step 3: Implementar en `ui/servidor.py`** (anchura: `pendientes` es una `deque`; las subcarpetas en el orden del listado).
- [ ] **Step 4: Ventana**: `direcciones.acciones["buscar"]` programa `after(ESPERA_BUSQUEDA_MS)` (cancela el anterior); al vencer o con Intro: texto vacío → `salir_de_busqueda()`; si no hay `Busqueda` de `(nav.remote, nav.ruta)` se crea; se entra en modo resultados (`lista["displaycolumns"]` con «carpeta» tras el nombre, iids = ruta completa), se pinta `resultados(texto)` y se lanzan hasta `CONCURRENCIA_BUSQUEDA` lecturas, cada una con su `Sondeo` de un grupo `sondeos_busqueda` (uno por hueco) y `partial(_listar, rcd, remote, carpeta, permisos)`; al llegar: `recibir`/`fallo`, añadir `de_carpeta(texto, carpeta)` a la lista, el indicador con `texto_progreso` y la barra que va y viene, el botón de acción «Detener» (`decir(..., boton="Detener")`), y lanzar más. Acabada: `texto_final`, sin barra ni botón. «Detener»: `busqueda.detener()`, indicador con `texto_final`. En resultados: doble clic/Intro en carpeta → `("lugar", Lugar(remote, ruta), NUEVO)`; en archivo → va a su carpeta y deja elegido el nombre (`estado["tras"]`); clic derecho → `ORDEN_MENU_RESULTADO`; Esc en el campo → vacía y vuelve a la carpeta (`pintar_lista()`, sin pedir); navegar: antes de pedir, si hay texto, `historial.apuntar_busqueda(texto)` y se vacía el campo; al llegar un `Lugar` con `busqueda`, se pone el texto y se busca (de lo guardado si la `Busqueda` sigue). Se tira la `Busqueda` en F5 (y se vuelve a buscar si había texto), `releer_si_subida`, `releer_tras_gestion`, `reconectar` y al buscar desde otra carpeta. Mientras hay resultados, `estados_menu` apaga renombrar/cortar/borrar/bajar/pegar; la botonera sigue para la carpeta raíz.
- [ ] **Step 5: Tests de ventana** (`tests/test_tk_servidor_busqueda.py`, con el `RcdFalso` y `segundo_plano.en_el_acto`): escribir «a» + Intro busca desde «/» y enseña `a.txt` de «/datos» con su columna «Carpeta» = «datos»; «privado» (403) cuenta como no leída y el final lo dice; afinar el texto no pide más listados; «Detener» con lecturas en vuelo (hilos de verdad, un `rcd` que se bloquea en un evento) no pinta lo que llega después; doble clic en un archivo abre su carpeta con él elegido; «Atrás» vuelve a los resultados sin pedir listados; Esc vuelve a la carpeta sin pedirla; F5 con texto vuelve a recorrer; el tope (`LIMITE_ELEMENTOS` bajado en el test) para y lo dice; dos archivos con el mismo nombre en carpetas distintas son dos filas.
- [ ] **Step 6: Pasar** `python tests/test_servidor.py`, `xvfb-run -a python tests/test_tk_servidor_busqueda.py` y los demás de ventana → PASS.
- [ ] **Step 7: Commit** «Servidor: buscar en las subcarpetas».

### Task 6: Documentación, máquina real y PR

**Files:**
- Modify: `docs/agents/reference/servidor.md`, `docs/agents/reference/ui.md` (`Visor` redimensionable; ventanas redimensionables), `docs/agents/reference/commands-testing.md` (tests nuevos, si hay registro), `docs/guia/servidor.md`, `docs/superpowers/pruebas/2026-10-27-servidor-pendiente-en-real.md` (filas R1, R2), `docs/superpowers/specs/2026-11-01-servidor-barra-explorador-design.md` (estado: construida), `.claude/rules/servidor.md`
- Test: `tests/test_reglas_claude.py`

- [ ] **Step 1:** Contar en `servidor.md` lo nuevo (barra, historial, migas, búsqueda, redimensionar, lo que queda fuera) y quitar lo que ya no es (botones del pie, combobox, «Cerrar»).
- [ ] **Step 2:** `python tests/test_reglas_claude.py` y `python tests/run_all.py --cambios -j auto` → PASS.
- [ ] **Step 3: Commit**, push a `ccr-4a2893b0-da7q0y`, PR en borrador con la plantilla `.github/pull_request_template.md` y título en español para el usuario; suscribirse al PR.
