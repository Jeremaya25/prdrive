# El workdir de bisync fuera de la unidad — diseño

Fecha: 12/10/2026. Es la parte que la entrega 4 de
`docs/superpowers/specs/2026-10-11-watch-y-energia-hoja-de-ruta-design.md` dejó sin hacer a
propósito («toca las invariantes del baseline: especificación propia»). Lo que hay hoy está en
`docs/agents/reference/engine.md` («bisync», «State») y en `agent.md`. Estado: **borrador sin
construir**. Tiene decisiones abiertas (al final): las marcadas «del dueño» se contestan antes de
escribir código; las marcadas «a medir» se contestan con rclone de verdad antes de dar el diseño
por bueno. Quien lo construya lo hace en su propia PR.

## Qué se quiere

Que una pasada bisync **que no mueve nada** no escriba en la unidad su base (el *workdir* de
bisync, `state/<pareja>/`). Hoy rclone reescribe enteros sus cuatro listados en cada pasada aunque
solo cambie la fecha de su primera línea, más un `.lck` y dos `.lst-new`: 32 KB con 100 ficheros y
268 KB con 1 000, por pasada y pareja. Con cuatro parejas cada 5 minutos eran 36–300 MB al día en
la flash de un pendrive; tras el intervalo que se estira (entrega 1) quedan unos 60 MB al día.

No se quiere, y manda sobre lo anterior:

- que el equipo llegue a ser la verdad de nada. **La unidad es la única verdad** de qué base
  tiene cada pareja; lo del equipo es una copia de trabajo que se puede tirar siempre;
- cambiar cuándo una pareja pide `--resync`, ni que deje de pedirlo;
- tocar nada de lo que entra en `bisync.expected_prefix()`: los listados se llaman igual estén
  donde estén (su nombre sale de los dos extremos, no del workdir).

## Lo medido (11/10/2026, prueba de concepto)

`docs/superpowers/pruebas/2026-10-11-watch-energia-windows-medidas.md`, apartados 1 y 5, con
rclone 1.75.1, un disco virtual y un remoto local:

| Qué | Resultado |
|---|---|
| Una pasada bisync sin cambios | reescribe enteros sus 4 listados (solo cambia la fecha de la 1ª línea), más `.lck`, 2 `.lst-new` y `last_run.tmp`: 32 KB con 100 ficheros, 268 KB con 1 000 |
| La misma con `--workdir` en el equipo | los 4 listados, los `.lst-new` y el `.lck` dejan de escribirse en la unidad (266–351 KB por pasada sin cambios de 1 000 ficheros) |
| Copiando de vuelta solo los listados cuyo cuerpo cambia | la pasada normal siguiente no pide `--resync` |
| Lo que se sigue escribiendo en la unidad | `state/last_run.json` y `state/historial.jsonl`, en cada pasada |

No medido, y hace falta (ver «Decisiones abiertas», A): qué hace bisync cuando arranca con una
base **vieja pero entera** (la de una pasada antes), y qué deja en el workdir cada forma de acabar
mal.

## Enfoques

**A. Copia de trabajo en el equipo, con la unidad como verdad y una época (el recomendado).** El
agente ofrece una carpeta suya por unidad; `sync.py` siembra ahí la base desde la unidad, pasa a
rclone ese `--workdir`, y al acabar deja la unidad igual que la copia **solo si algo que cuenta ha
cambiado**. Una marca de época en la unidad, escrita la última, dice a qué estado de la unidad
corresponde la copia; si no coincide, la copia se tira.

**B. A, con una marca previa en la unidad.** Antes de cada pasada se escribe en la unidad «hay
una pasada en marcha desde el equipo H», y se quita al acabar. Cualquier otro equipo ve una
pasada que no llegó a volcarse. Cuesta dos escrituras pequeñas por pasada, que es parte de lo que
se quería quitar (cada una mueve al menos un clúster y la tabla del sistema de ficheros).

**C. La base solo en el equipo, sin copia en la unidad.** Cero escrituras, y la unidad deja de
saber qué base tiene: en otro equipo cada pareja pediría `--resync`. Descartado: rompe «la unidad
es la única verdad» y la portabilidad, que es para lo que existe el proyecto.

**D. Un sistema de ficheros en memoria o un `--workdir` temporal por pasada**, copiando de la
unidad y de vuelta cada vez. Es A sin copia persistente: se lee la base de la unidad en cada
pasada (lecturas, no desgaste) y no hay nada que invalidar. Más simple y más lento; queda como
plan B si la época de A resulta frágil (decisión abierta D3).

Se recomienda **A**. B es A más una decisión del dueño (D2).

## Diseño (enfoque A)

### Quién usa la copia, y dónde está

- **Solo con el agente de este equipo, y solo en una unidad que él atiende.** El agente crea
  `equipo.DIR/bases/<id de la unidad>/` cuando empieza a servirla. `sync.py` (el de la unidad)
  usa `…/<pareja>/` como workdir **si esa carpeta de la unidad existe**, lo lance quien lo lance
  en ese equipo: el agente, la ventana, el servicio de runsync o una terminal. Tienen que ver
  todos lo mismo, porque el `.lck` de bisync pasa a vivir ahí y es lo único que impide dos
  pasadas a la vez de una pareja. Sin esa carpeta (un equipo sin agente, una unidad que el agente
  no atiende), todo va como hoy, con el workdir en la unidad.
- **La ruta la calcula el código de la unidad** (`common/equipo.py` viaja con ella): es una
  constante repetida a propósito entre versiones, con su test, como las de `penwatch`.
- **No entran**: el llavero (cuatro ficheros, lo lee `llavero.listado_local()` y se resincroniza
  solo), una raíz de equipo (`model.es_equipo()`: ya está en el disco del equipo), las parejas
  que no son bisync (no tienen workdir) y, mientras no se decida otra cosa (D1), **una unidad
  cifrada** (`cifrada.estado()`): los listados llevan el nombre, el tamaño y la fecha de cada
  fichero, y fuera del contenedor quedarían en claro.
- **El agente la poda**: unidades que ya no están en su lista, parejas que ya no existen. Al
  desinstalar se va con `equipo.DIR`, como todo lo demás.

### Qué hay en la unidad y qué en el equipo

En la unidad, `state/<pareja>/` sigue teniendo los listados (`.path1.lst`, `.path2.lst`, sus
`-old`, y los `-err` si rclone los dejó) y gana un fichero, `epoca.json`:

```json
{"estado": "ok", "epoca": "<128 bits al azar, en hex>"}
{"estado": "copiando", "hacia": "<época nueva>", "equipo": "<HOST>"}
```

En el equipo, `bases/<id>/<pareja>/` tiene el workdir de rclone (lo mismo, más su `.lck` y sus
`.lst-new` mientras corre) y `sembrada.json`: la época de la unidad con la que está al día y la
firma de los listados de la unidad en ese momento (nombre, tamaño y `mtime_ns` de cada uno), más
`pendiente: true` desde que acaba una pasada hasta que la unidad queda igual.

**Todo lo que lee la base para decidir o para enseñar sigue leyendo la unidad**:
`bisync.pair_state()`, `resync_reasons()`, `last_run()`, `programa_en_listado()`,
`pair_editor`, `revision`, `instantanea`. `Pair.workdir` sigue siendo `state/<pareja>/`. Solo
`build_command()` (el `--workdir` de rclone) y `parte.base()` (qué cambió en la pasada) usan el
workdir de la pasada, por una función nueva de `common/bisync.py`.

### La regla de validez

La copia del equipo vale si, y solo si:

1. la unidad tiene `epoca.json` con `estado: "ok"` y su época es la de `sembrada.json`;
2. los listados de la unidad tienen la misma firma que `sembrada.json` apuntó (alguien que
   escribe en `state/<pareja>/` sin saber de épocas, un `sync.py` de antes o una mano, cambia
   una fecha o un nombre);
3. la copia tiene su juego de listados entero.

Si no, **la copia se tira y se siembra otra vez desde la unidad**. Nunca al revés: la copia solo
escribe en la unidad en «poner la unidad al día» (abajo), que exige la condición 1.

- La época cubre a quien escribe sabiendo (escribe la época la última); la firma, a quien no. Con
  la resolución de fecha de FAT (2 s) y un listado reescrito con el mismo tamaño, la firma sola
  podría no ver un cambio: por eso van las dos.
- **Un baseline aparcado no resucita nunca**: `shelve_baseline()` renombra `state/<pareja>/`
  entero, con su `epoca.json`. La unidad queda sin época y sin listados, la copia deja de valer,
  la pareja es `fresh` y pide su `--resync` como hoy. Renombrar una pareja deja su copia
  huérfana (va por nombre), que se poda.
- Una unidad sin `epoca.json` (la primera vez, o tras pasar por un `sync.py` de antes) no
  invalida nada por sí misma: se siembra desde ella y se le escribe una época, una vez.

### La pasada

En `_bisync_preflight()`, antes de `pair_state()`:

1. **Poner la unidad al día** si la copia tiene `pendiente` y se cumple la condición 1 (nadie ha
   tocado la base de la unidad desde entonces): es acabar el volcado que la pasada anterior no
   llegó a hacer (el proceso murió, la unidad se fue). Si no se cumple, la copia se tira.
2. `pair_state()`, `resync_reasons()` y el aborto de «hay baseline y no hay carpeta local», sobre
   la unidad, como hoy.
3. Si la copia no vale, **sembrar**: vaciar `bases/<id>/<pareja>/` y copiar los listados de la
   unidad. Con un `.lck` vivo en la copia no se siembra: hay otra pasada, o una cortada cuyo
   candado aún no ha caducado (`--max-lock 2m`), y falla rclone como hoy («prior lock file
   found»).

Después, rclone con `--workdir` en la copia. Al acabar, **acabe como acabe** (también con error),
se compara la copia con la unidad en lo que cuenta: los mismos nombres con sufijo `.lst`,
`.lst-old` y `.lst-err`, y el mismo cuerpo de cada listado (sin su primera línea, que lleva la
fecha: `parte.base()` ya lo hace así).

- **Iguales** (la pasada no movió nada): no se escribe nada en la base de la unidad.
- **Distintos** (movió algo, fue un `--resync`, o rclone apartó el baseline a `.lst-err`): el
  volcado.

Un simulacro (`--dry-run`) no vuelca nunca.

### El volcado

1. `sembrada.json` de la copia: `pendiente: true`, con la época de la unidad de la que parte.
2. En la unidad, `epoca.json` = `copiando`, con la época nueva y el equipo.
3. Cada listado, por un temporal y `os.replace` (`store.write_text()` ya escribe así); los que
   sobran en la unidad (un `.lst` que en la copia ya es `.lst-err`) se quitan.
4. En la unidad, `epoca.json` = `ok` con la época nueva. **Lo último.**
5. `sembrada.json`: la época nueva, la firma de lo recién escrito, sin `pendiente`.

**El bloqueo de rclone viaja a la unidad.** Si rclone apartó el baseline (`.lst-err`) para
impedir las pasadas siguientes, el volcado lo lleva a la unidad: en cualquier equipo la pareja
sale `broken` y pide `--resync`, como hoy. Sembrar no puede ser una forma de saltarse ese
bloqueo.

### Quien encuentra `copiando`

Es un volcado que se quedó a medias: los listados de la unidad pueden ser de dos pasadas
distintas, y **una base así no se usa**.

- En el equipo que lo dejó, con su copia entera y la misma época en `hacia`: se repite el
  volcado.
- En cualquier otro caso, `pair_state()` da `broken` con su frase («la base se quedó a medio
  copiar desde el equipo H: vuelve a conectarla allí, o resincroniza») y la pareja pide
  `--resync`. Un `--resync` aprobado escribe una base y una época nuevas, y la copia de H deja de
  valer.

### Lo que queda sin cubrir, dicho en voz alta

Entre que rclone acaba una pasada que movió algo y que el volcado termina, la unidad tiene la
base de la pasada anterior, entera. Si en ese hueco la unidad se va y **se usa en otro equipo
antes de volver al primero** (o el primero pierde su copia), ese otro equipo siembra una base
vieja de una pasada. Lo mismo si la pasada se cortó a medias.

Es la situación para la que rclone tiene `--recover` (que prdrive ya pasa): volver al listado de
la última pasada buena y repetir. Lo que se espera de bisync con una base vieja pero entera es
que no pierda nada: lo ya copiado está igual en los dos lados y no es conflicto, un fichero
borrado en un lado tras esa pasada puede volver del otro, y uno cambiado puede salir como
conflicto. **Eso es lo que hay que medir antes de construir (A1)**; si no se cumple, este
enfoque no vale sin la marca previa de B.

La unidad nunca queda más de una pasada atrás: una copia con `pendiente` se vuelca antes de la
pasada siguiente o se tira.

### En el agente

- Crea `bases/<id>/` al tomar una unidad que entra en el alcance, y solo si el `sync.py` de esa
  unidad sabe usarla (`agente.VERSION_MINIMA` no vale: hace falta la versión que traiga esto).
- `consumo.json` y el parte (`parte.Medida.escrito`) cuentan lo que el volcado escribe en la
  unidad, no lo que rclone escribe en el equipo.
- `equipo.pasada_cortada()` y `ESPERA_TRAS_CORTE` no cambian: el `.lck` caduca igual, ahora en
  la copia.
- Nada que cifrar ni que proteger aparte: `equipo.DIR` es del usuario. Lo que deja de ser
  cierto es «No secret there» (`agent.md`) si entran las unidades cifradas (D1).

### Lo que ve la persona

Nada nuevo en ninguna ventana, salvo la frase de `copiando`. `agente.py status` dice, por unidad,
si su base se lleva en el equipo. «Reparación» y `--doctor` siguen mirando la unidad.

## Riesgos

- **El hueco de una pasada** (arriba). Es el precio del enfoque A.
- **Dos sitios para el candado.** Si algún camino lanzara rclone con el workdir en la unidad
  mientras otro usa la copia, no habría `.lck` común. La regla «si la carpeta existe, todos la
  usan» lo evita en un mismo equipo; no hay dos equipos a la vez con la misma unidad.
- **Una herramienta de limpieza borra `bases/`**: se siembra otra vez; como mucho, el hueco de
  una pasada.
- **Rutas largas en Windows.** El nombre de un listado ya es largo (lleva los dos extremos) y
  ahora cuelga de `%LOCALAPPDATA%\prdrive\bases\<32 hex>\<pareja>\`. Hay que medir el peor caso
  y, si pasa de 260, acortar la carpeta de la unidad (A4).
- **Un reloj que retrocede o una FAT** no afectan a la época (es al azar); sí a la firma, que es
  solo la segunda comprobación.
- **Más código en el camino de cada pasada bisync.** Un fallo al sembrar o al volcar tiene que
  acabar en «la pasada falla y se dice», nunca en «se sigue con lo que haya».

## Lo que no se hace

- Quitar las otras escrituras de cada pasada (`last_run.json`, `historial.jsonl`, `daemon.log`):
  son pequeñas y otra discusión.
- Llevar fuera de la unidad los filtros (`filters/<pareja>.txt` y su `.md5`): bisync los
  reescribe solo en un `--resync`.
- Limpiar `.lst-err`, `.lst-old` o lo que rclone deje: el workdir sigue sin ser cosa nuestra,
  esté donde esté. El volcado copia lo que hay.
- Ninguna migración: una unidad sin época funciona, y gana la suya la primera vez.

## Pruebas

- **Las reglas, puras** (`tests/test_bisync_copia.py`, nuevo): la tabla de validez entera (cada
  condición que falla, de una en una); sembrar; el volcado paso a paso, cortado después de cada
  paso, y qué ve después el mismo equipo y otro; `copiando` con y sin su copia; un baseline
  aparcado y vuelto a poner a mano; una pareja renombrada; un `.lck` vivo.
- **Con rclone de verdad** (como la pasada de verdad de `tests/rendimiento/consumo.py`, contra
  un remoto local): una pasada sin cambios no toca `state/<pareja>/`; una con cambios lo deja
  igual que la copia; la siguiente no pide `--resync`; un `--resync` vuelca siempre; un
  `--dry-run`, nunca; y los casos de A1.
- **El agente** (`tests/test_agente_*.py`): crea y poda `bases/`; no la crea para una unidad
  cifrada, una raíz de equipo ni una unidad de versión anterior; el parte y `consumo` cuentan lo
  volcado.
- **`tests/rendimiento/presupuesto.toml`**: `consumo.pasada.ficheros` y `consumo.pasada.kb`
  bajan (hoy 6 ficheros y 29 KB por pasada sin cambios), y un presupuesto nuevo para la pasada
  con la base en el equipo.
- **Equipos reales** (filas nuevas en `2026-09-25-equipo-pendiente-en-real.md`): un pendrive de
  verdad arrancado justo al acabar una pasada que movió algo, y llevado a otro equipo; la misma
  unidad alternando entre dos equipos con agente; el desgaste medido (bytes escritos en un día
  de uso).

## Decisiones abiertas

**Del dueño (antes de escribir código):**

- **D1. ¿Entran las unidades cifradas?** Sus listados (nombres, tamaños, fechas) quedarían en
  claro en el perfil del usuario del equipo. Propuesto: no, en esta primera versión. Es la mayor
  parte de las unidades en uso, así que decide cuánto ahorra todo esto.
- **D2. ¿Marca previa (enfoque B)?** Cierra el hueco de una pasada al precio de dos escrituras
  pequeñas por pasada. Propuesto: no, si A1 sale como se espera.
- **D3. ¿Copia persistente (A) o temporal por pasada (D)?** D no tiene época ni nada que
  invalidar, y lee la base de la unidad en cada pasada. Propuesto: A.
- **D4. ¿La ventana y la terminal usan también la copia?** Propuesto: sí (por el candado). La
  alternativa, que solo la use el agente, obliga a otra forma de impedir dos pasadas a la vez.
- **D5. ¿Encendido de fábrica o detrás de un ajuste** (`agente.py ajuste base_en_el_equipo`),
  como se hizo con `avisos_veracrypt`? Propuesto: detrás de un ajuste hasta verlo en un pendrive
  de verdad.

**A medir con rclone de verdad (antes de dar el diseño por bueno):**

- **A1. bisync con una base vieja pero entera.** Para cada caso (fichero nuevo, cambiado,
  borrado y renombrado, en un lado y en los dos, ya propagado por la pasada que no se volcó): qué
  hace la pasada siguiente desde la base anterior, con y sin `--recover`. Lo que no se admite:
  que se pierda un fichero o un cambio sin dejar copia.
- **A2. Qué deja rclone en el workdir** según cómo acabe: bien, con un error «menor»
  (`--resilient`), con un error crítico, cortado con una señal y matado en seco. Y si un workdir
  sembrado solo con los dos `.lst` (sin sus `-old`) se comporta igual, por si basta con volcar
  dos ficheros en vez de cuatro.
- **A3. El `--resync`** con el workdir en la copia: qué escribe y en qué orden, y qué pasa si se
  corta a medias (hoy deja la pareja `fresh` o `broken` en la unidad).
- **A4. La ruta más larga** de un listado bajo `%LOCALAPPDATA%\prdrive\bases\…` con las rutas
  largas de Windows apagadas.
- **A5. Lo que se ahorra de verdad** tras la entrega 1: bytes escritos en la unidad en un día,
  con y sin esto, en una unidad con parejas de 1 000 y de 10 000 ficheros.

**De quien lo construya (se resuelven al escribirlo):**

- El nombre de la función que da el workdir de la pasada, y si `parte.base()` la recibe o la
  pregunta.
- Si la época se guarda dentro de `state/<pareja>/` (se va con el baseline al aparcarlo, que es
  lo que se quiere) y con qué nombre para que `pair_state()` y `parte.base()` no la tomen por un
  listado.
- Cómo sabe el agente que el `sync.py` de una unidad sabe usar la copia (su `VERSION`, que ya
  lee, o un fichero que deje la propia unidad).
- Qué documentos de `docs/agents/reference/` cambian: `engine.md` («State»), `agent.md` («Files
  and ownership», «No secret there»), `commands-testing.md`, y la invariante del baseline de
  `AGENTS.md`, que gana una frase.
