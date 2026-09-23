# Ficha por dispositivo: dónde ha estado y desde cuándo falla (issue #17)

Fecha: 2026-09-23 · Estado: diseño aprobado · Versión: 0.2.4

## El problema

«Parejas → Dispositivos…» (`ui/tk_fleet.py`) enseña toda la flota en una tabla de
seis columnas y nada más. Dos preguntas que la pantalla existe para contestar no
tienen respuesta en ningún sitio:

- **¿Dónde ha estado conectado?** La nota no apunta el anfitrión. Cuando uno se
  pregunta dónde estaba el otro pendrive, no hay por dónde empezar.
- **¿Desde cuándo falla?** `last_result` es un instante. De un dispositivo en
  ámbar no se sabe si falló una vez y nadie lo ha vuelto a tocar o si lleva tres
  semanas fallando en cada pasada.

## Alcance

Decidido al plantearlo:

- **Entra:** los últimos equipos donde se ha enchufado, un «desde cuándo» del
  fallo actual y una ficha por dispositivo.
- **No entra:** la serie de pasadas (cuántas, cuántas bien, esta semana). Eso es
  el diario de #20, que todavía no existe; la ficha deja sitio para él.
- **Privacidad:** se publica el `hostname` tal cual, siempre, y la pantalla lo
  dice. Quien puede leer `devices/` tiene la clave del remoto y puede leer todo lo
  que se sincroniza; el nombre de red de un equipo es mucho menos que eso. Sin
  interruptor en esta versión.
- **Forma:** la ficha va **debajo de la tabla, en la misma ventana**. Nada de un
  tercer nivel de modales (principal → Parejas → Dispositivos → Ficha).

## El enfoque: todo se calcula al publicar

Descartados:

- **Seguimiento local en cada pasada** (apuntar equipo y hora en
  `state/fleet.json` desde cada `sync.py`): fechas exactas, pero una escritura
  más en el pendrive por pareja y por ciclo del servicio, que es justo lo que el
  proyecto evita al no guardar los logs buenos y al frenar las notas.
- **«Desde» como transición registrada** (fijar la hora en que `last_result`
  pasa de ok a fallo): depende de que la publicación salga. Sin red en ese
  momento, la fecha que queda es la de la primera publicación que funcionó, no la
  del fallo.

Elegido: **la lista de equipos se hereda de la última nota publicada** (que el
dispositivo ya guarda en `state/fleet.json` → `publicado`) y **`ultima_buena`
sale de `results.py`**, que ya guarda por pareja la última pasada buena
(`buena`) y la escribe en cada pasada, haya red o no. Ninguna escritura nueva en
el pendrive fuera de las publicaciones que ya existen.

El precio: la fecha de cada equipo tiene la precisión de `last_seen`, hasta
`HORAS_ENTRE_NOTAS` (6 h). Es la que la columna «Visto» ya tiene hoy.

## La nota

```toml
# prdrive — nota de presencia de un dispositivo.
# ...
equipos = ["PORTATIL-PERE", "OFICINA-07", "SOBREMESA"]
equipos_visto = ["2026-09-23 10:02:11", "2026-09-18 17:40:05", "2026-09-02 09:12:40"]
id = "3f9c…"
last_result = "fallo en fotos"
last_seen = "2026-09-23 10:02:11"
nombre = "El del trabajo"
plataformas = ["windows-x64", "linux-x64"]
ultima_buena = "2026-09-01 08:00:00"
version = "0.2.4"
```

(Orden alfabético: `dumps_table()` ordena las claves.)

- **`equipos`**: los últimos equipos desde los que se ha publicado, sin repetir y
  el más reciente primero. Como mucho `MAX_EQUIPOS = 5`, así la nota no crece.
  El nombre es `socket.gethostname()`, comparado tal cual.
- **`equipos_visto`**: lista paralela con la fecha de cada uno, en el formato de
  `store.stamp()`.
- **`ultima_buena`**: solo si la nota dice fallo. La `buena` **más antigua** entre
  las parejas que fallan (la que más tiempo lleva rota marca desde cuándo hay algo
  roto), o `"ninguna"` si de alguna de ellas no consta ninguna pasada buena.
  «Ninguna que conste», no «nunca»: `buena = None` sale igual de una pareja que
  nunca fue bien que de un registro anterior a la clave `buena` (bd7fd21), y las
  dos cosas no se distinguen.
- Las tres claves se **omiten** cuando están vacías.

**Dos listas paralelas, no una lista de tablas:** `config_file.dumps_table()` solo
escribe escalares y listas de cadenas. Enseñarle tablas en línea sería tocar el
módulo que escribe `sync_config.toml` y el catálogo con la comprobación estricta
de ida y vuelta, y una nota de presencia no lo merece. La comprobación de
`fleet.dumps()` (volver a leer lo generado antes de publicarlo) cubre lo nuevo.

### Compatibilidad

| Quién lee | Qué nota | Resultado |
|---|---|---|
| 0.2.3 o anterior | nueva | `parse()` ignora claves desconocidas: ve lo mismo que veía |
| 0.2.4 | vieja, sin `equipos` | `equipos = ()`; la ficha dice «No consta» |
| 0.2.4 | futura o mal formada | se recorre por posición; entrada de `equipos` que no sea cadena, fuera; fecha que falte o no sea cadena, `""` (se enseña «—»); más de `MAX_EQUIPOS`, se corta al leer |

## Diseño

### `common/results.py`

- `Fallo` gana un quinto campo, `buena: str | None = None`: la última pasada buena
  de esa pareja, calculada con `_buena()`, que ya existe. Con valor por defecto,
  `test_tk_principal` (que construye `Fallo` con cuatro argumentos) sigue igual.
- `fallos_de()` lo rellena. Nada más cambia.

### `common/fleet.py`

- **`Equipo(NamedTuple)`**: `nombre: str`, `visto: str`.
- **`Dispositivo`** gana `equipos: tuple[Equipo, ...] = ()` y
  `ultima_buena: str = ""`. Los valores por defecto mantienen válidos los
  constructores actuales (tests, `install/deploy.py`).
- **`MAX_EQUIPOS = 5`.**
- **`equipo_actual()`**: `socket.gethostname()`, o `""` si falla. Función de
  módulo para que los tests la sustituyan (la convención de AGENTS.md);
  `nombre_por_defecto()` pasa a usarla.
- **`_tabla(disp)`**: el dict de la nota, usado por `dumps()` **y** por
  `recordar()`. Hoy son dos literales que repiten las mismas seis claves; con
  tres más, divergirían.
- **`parse()`**: lee las tres claves nuevas con la tolerancia de la tabla de
  arriba.
- **Resultado y `ultima_buena` salen de una sola lectura** de `results.fallos()`,
  así que no pueden contradecirse. `resultado(config) -> str` (solo lo usa
  `nota()`) se sustituye por `estado(config) -> tuple[str, str]` —
  `(last_result, ultima_buena)` — con el criterio de hoy: sin config, `("ok",
  "")`; si `results` lanza, `("desconocido", "")`.
- **`nota_de(app_dir, como_se_llama, version, last_result, ultima_buena="")`**
  construye la lista de equipos:
  1. Parte de `publicado` en el `fleet.json` de ese dispositivo (el mismo que
     escribe `recordar()`): `<app_dir>/state/` si se le pasa `app_dir`,
     `ruta_estado()` si no — la misma relación que `model.STATE_DIR` guarda con
     `APP_DIR`. **Solo si su `id` es el actual**: «Reinstalar desde cero» renueva
     el id, para la flota es otro dispositivo, y empieza de cero.
  2. Pone `equipo_actual()` delante con la hora de esta pasada — el mismo
     `store.stamp()` que `last_seen` —, quita su entrada anterior y corta a
     `MAX_EQUIPOS`.
  3. Con `equipo_actual() == ""`, la lista anterior queda como estaba.
- **`_sin_fecha()`** añade el equipo actual (`equipos[0].nombre`, o `""`) y
  `ultima_buena`:
  - misma máquina: nada cambia, una nota cada 6 h o cuando cambie el resultado;
  - otra máquina: se publica en la primera pasada, que es cuando más importa;
  - `ultima_buena` solo cambia cuando cambia `last_result`: no añade notas;
  - un `publicado` de 0.2.3 no trae equipos: la primera pasada tras actualizar
    publica una vez, que es lo que se quiere.
- **`recordar()`** guarda también `equipos`, `equipos_visto` y `ultima_buena`
  (vía `_tabla()`): de ahí hereda la nota siguiente, y con eso compara el freno.
- **Docstring del módulo:** hoy dice «nada de rutas, ni de parejas, ni de nada
  que no se pueda enseñar». Pasa a decir que el nombre de red de los equipos
  **sí** se publica, y por qué; y que `equipos` es «desde dónde ha podido
  publicar»: si la publicación falla no se apunta nada, y el reintento sale solo
  en la pasada siguiente porque el equipo sigue sin coincidir con el de la última
  nota. Un equipo donde nunca hubo red no aparece, y es correcto: allí tampoco se
  sincronizó nada, porque el remoto *es* la red.

### `install/deploy.py`

`publish_fleet_note()` ya llama a `fleet.nota_de(app, …)`: el equipo que
aprovisiona entra como primer equipo, que es verdad. Sin `ultima_buena`
(`NOTA_INICIAL` no sale de `results`). `nota_de()` saca de `app` dónde leer
`publicado`, así que la llamada no cambia.

### `ui/tk_fleet.py`

**Tabla:** cuatro columnas — `Este`, `Dispositivo`, `Visto`, `Última pasada`.
`Versión` y `Para` pasan a la ficha. Alto `min(8, max(3, n))` en lugar de
`min(12, max(4, n))`: la ficha se lleva parte de la ventana.

**Ficha:** una `Card.TFrame` bajo la tabla, repintada en `<<TreeviewSelect>>` (el
mismo evento que ya usa `repasar_quitar`).

```
EL DEL TRABAJO                                    id 3f9c1a2b
VERSIÓN   0.2.1
PARA      windows-x64, linux-x64
ESTADO    fallo en fotos
          Última pasada buena: 2026-09-01
EQUIPOS   PORTATIL-PERE              ayer
          OFICINA-07 · este equipo   18/09
          SOBREMESA                  2026-09-02
```

- **Título + id corto** en mono (`MonoPista`). Dos pendrives aprovisionados en el
  mismo PC reciben el mismo nombre por defecto (el `hostname`); el id es lo único
  que los distingue, y es el nombre de su fichero en `devices/`.
- **Rótulos** con `theme.rotulo()`; el canal se reserva con
  `theme.ancho_rotulo()` + `columnconfigure(minsize=…)`, nunca `width=` en
  caracteres (`test_tk_densidad`).
- **Estado:** `last_result`, y debajo, en pista, «Última pasada buena: …» o «No
  consta ninguna pasada buena.» cuando hay `ultima_buena`. Con `wraplength`:
  «fallo en a, b, c…» puede ser largo.
- **Equipos:** fecha con la regla de la columna «Visto» (relativa si es reciente,
  fecha entera con año si pasa de `DIAS_OBSOLETO`). `_visto(disp)` se generaliza a
  `_fecha(sello)` y la usan las dos. «· este equipo» marca la entrada igual a
  `fleet.equipo_actual()`: contesta directamente si el otro pendrive ha estado en
  este ordenador. Sin equipos: «No consta: las versiones anteriores no lo
  apuntaban.»
- **Alto fijo:** la zona de equipos reserva siempre `MAX_EQUIPOS` filas. Recorrer
  la lista con las flechas no cambia el tamaño de la ventana, y el `Visor` encaja
  una sola vez.
- **Sin selección** (flota vacía, o recién quitado un dispositivo): la ficha se
  oculta con `grid_remove()`, como hoy aparece `SIN_NOTA`.
- **La cabecera** añade que cada nota dice también «en qué equipos se ha
  enchufado, por su nombre de red». Es el aviso de privacidad acordado.

**Qué es decisión y qué es dibujo.** El contenido de la ficha lo produce una
función pura de módulo, `ficha(disp, equipo_aqui, ahora=None)`, que devuelve las
filas (rótulo, líneas, cuál va en pista). Vive en `tk_fleet.py` junto a `_fecha` y
`_tono`, como ellas: el módulo no importa Tk arriba, así que se prueba sin
pantalla. `open_dialog` solo la dibuja.

## Lo que NO cambia

- Cada dispositivo escribe **solo su nota**; la única excepción sigue siendo
  `olvidar()` (#16).
- `publicar()`, `leer()` no lanzan; `leer()` sigue siendo un solo `rclone copy`.
- `HORAS_ENTRE_NOTAS`, `DIAS_OBSOLETO`, el orden de la lista, `_tono()`.
- Ninguna escritura nueva en el pendrive: `state/fleet.json` se escribe donde ya
  se escribía (al publicar y al aprovisionar).
- `config_file.py` no se toca.
- La pantalla sigue colgando de «Parejas», no de la ventana principal.

## Pruebas

- **`tests/test_fleet.py`**
  - Ida y vuelta de una nota con `equipos` y `ultima_buena`; las claves vacías no
    se escriben.
  - `parse()`: nota vieja → `()`; listas desparejadas → fecha `""`; entradas no
    cadena descartadas; más de `MAX_EQUIPOS` → cortada.
  - `nota()` con `equipo_actual` sustituido: el actual va primero; uno repetido
    pasa al frente sin duplicarse; corte a 5; id distinto → lista nueva;
    `hostname` vacío → lista anterior intacta.
  - Freno: misma máquina dentro de 6 h → no publica; otra máquina → publica;
    `publicado` sin equipos (0.2.3) → publica una vez; publicación fallida → no
    se recuerda nada y la pasada siguiente reintenta con la misma lista.
  - `ultima_buena`: vacía si todo va bien; la `buena` de la pareja si falla una;
    la más antigua si fallan dos; `"ninguna"` si de alguna no consta ninguna.
- **`tests/test_results.py`**: `Fallo.buena`, incluidos los registros anteriores
  a la clave `buena` (el segundo camino de `_buena()`).
- **`tests/test_install_deploy.py`**: la nota inicial lleva el equipo que
  aprovisiona.
- **`tests/test_tk_screens.py`**: `ficha()` sin pantalla (nota completa, vieja,
  «· este equipo», «ninguna»); en la ventana, elegir otra fila repinta la ficha y
  una flota vacía la oculta.
- **`tests/test_tk_medidas.py`**: la ventana con el peor caso en toda la matriz de
  resolución × `tk scaling`: 8 dispositivos, uno con 5 equipos de `hostname` de 63
  caracteres (el límite de una etiqueta DNS), un `last_result` largo y
  `ultima_buena`.
- `python tests/run_all.py` en verde.

## Documentación

- **`AGENTS.md`**, sección «The fleet registry»: las tres claves y las listas
  paralelas con su motivo; el `hostname` como decisión tomada y dicha en la
  pantalla; qué entra en `_sin_fecha()`; que `equipos` es «desde dónde pudo
  publicar»; el alto fijo de la ficha.
- **`README.md`**: «El modelo» (el registro de la flota) y la entrada
  «Dispositivos…» — la nota incluye el nombre de red de los equipos, y hay ficha.
- **`device-readme.md`**: no se toca (sin detalles internos).
- **`VERSION`** → `0.2.4`.

## Después

- **#20** (diario de pasadas): cuando exista, la ficha es su sitio natural para
  la serie, y el banner ámbar de la ventana principal puede usar `Fallo.buena`
  para decir desde cuándo falla.
