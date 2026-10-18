# Los tests se eligen por área, y las ventanas no se abren en local — diseño

Fecha: 18/10/2026. Estado: **diseño aprobado en conversación, sin construir**. Va en una sola PR.
Lo que hay hoy está en `docs/agents/reference/commands-testing.md` («Verification») y en
`tests/run_all.py`.

## Por qué

La batería pesa demasiado para lo que se toca, y los tests de ventanas molestan: en Windows
abren ventanas de Tk de verdad en el escritorio de quien trabaja y le quitan el foco. Hoy
`AGENTS.md` («Verification is `tests/run_all.py`») y el aviso de `.claude/hooks/session_start.sh`
mandan a cada agente a correrlo **todo** tras cualquier cambio: un arreglo de lógica en
`common/bisync.py` arrastra las 54 ventanas, el instalador y el agente.

Datos del CI de `main` (ejecución 39059986705, 17/10/2026; 180 ficheros de test):

| | Ventanas (`GUI`, 54 ficheros) | Sin ventana (126) | Pasada entera |
|---|---|---|---|
| Windows (`-j 4 --gui-jobs 1`) | 315 s sumados | 207 s sumados | 322,6 s |
| Linux (`-j 4`, Xvfb propio) | 166 s | 123 s | 77,8 s |
| Linux 3.11 sin pantalla | (se saltan) | 111 s | 43,4 s |

En Windows las ventanas marcan el reloj: en un escritorio compartido van de una en una. Lo que
no abre ventana cabe en un minuto en paralelo; `test_run_all.py` solo ya son 38 s.

## Qué se quiere

- Mientras se trabaja, un cambio se verifica con los tests **de lo que toca** y de lo que depende
  de ello, en segundos, **sin abrir ni una ventana**, y el agente sabe qué correr sin pensarlo.
- El CI sigue pasando **todo** (los 180, con ventanas, en Linux y Windows): es la red que pilla
  lo que la selección local deje fuera.

No se quiere: mover los tests de sitio, cambiar cómo se escribe un test, ni una segunda lista de
qué fuente pertenece a qué área.

## Decisiones del dueño (18/10/2026)

1. **Las ventanas no se abren en local salvo que se pidan**: por nombre de fichero o con
   `--ventanas`. Se prueban en el CI. Descartado: un escritorio de Windows oculto
   (`CreateDesktop`), porque habría que probar antes que el foco y los píxeles funcionan allí, y
   abrir solo las ventanas del área tocada.
2. **Alcance al iterar: el área tocada y las que dependen de ella**, no solo el área (lo de otras
   áreas lo vería solo el CI), ni toda la lógica siempre (no separa nada).
3. **El mapa de áreas es el de `.claude/rules/`** (enfoque A): cada regla ya lista los fuentes y
   los tests de su área. Descartados: un manifiesto propio (`tests/areas.toml`), que sería una
   segunda copia del mapa fuente → área que acabaría desviándose; y un mapa de impacto por
   cobertura (`sys.monitoring`), preciso pero que se queda viejo, exige una pasada completa *con
   ventanas* para regenerarse, no existe en 3.11 y no ve los tests que solo leen fuentes.

## Niveles y órdenes

| Cuándo | Orden | Qué corre | Ventanas |
|---|---|---|---|
| Mientras se itera (el agente) | `python tests/run_all.py --cambios -j auto` | los tests de las áreas que toca el diff y de las que dependen | no |
| Repaso amplio, a mano | `python tests/run_all.py -j auto` | todos los que no abren ventana (126 hoy) | no |
| CI | `run_all.py -j auto --ventanas …` | los 180 | sí |

- `--area A [B…]`: elige por nombre de área (el nombre de la regla, `engine`, `llavero`…), con la
  misma expansión a las dependientes que `--cambios`. Para correr un área antes de tocarla.
- Nombres de fichero (`run_all.py test_x.py`): exactamente esos, **con** ventanas si las abren.
  Nombrarlos es pedirlos.
- `--ventanas`: añade los de `GUI` a cualquier selección. Sin él, ninguna selección los lleva
  salvo por nombre.
- `--cambios` y `--area` no se combinan entre sí ni con nombres de fichero: error de argumentos.

**Cambia el comportamiento sin argumentos**: `run_all.py` ya no corre `GUI`. La última línea lo
dice siempre que quede alguno fuera:
`Los 126 ficheros de test pasan (54 de ventanas sin correr: van en el CI, o con --ventanas).`
La de fallo igual: `FALLAN n de 126: … (54 de ventanas sin correr…)`. `-j` sigue con su valor por
defecto (1); los docs dicen `-j auto`.

## Cómo se eligen los tests

Un módulo nuevo, `tests/_seleccion.py`, puro (sin Tk, sin red, sin `_harness`): recibe la lista
de ficheros cambiados y devuelve la selección con sus motivos. `run_all.py` solo lo llama.

### 1. Los ficheros cambiados

`cambiados()`, función de módulo que los tests sustituyen (va al registro de puntos de
sustitución de `commands-testing.md`):

- la base es `git merge-base HEAD origin/main`; sin `origin/main`, `main`;
- `git -c core.quotepath=off diff --name-only --no-renames <base>`: el árbol de trabajo contra
  la base, o sea lo confirmado en la rama, lo preparado y lo modificado; con `--no-renames` un
  renombrado cuenta por sus dos nombres;
- más `git -c core.quotepath=off ls-files --others --exclude-standard`: lo nuevo sin seguimiento;
- rutas relativas a la raíz del repositorio, con `/`, sin repetir.

Si git no está, no es un repositorio o no hay base común, devuelve `None`, y la selección es
«todo lo que no abre ventana», con una línea que lo dice. Nunca acaba en «verde sin probar nada»
por no saber qué cambió.

### 2. De cada fichero, sus áreas

Las áreas son las reglas de `.claude/rules/*.md`; sus patrones son los `paths` de la cabecera,
leídos con la misma expresión (`CABECERA`) y el mismo `glob(…, root_dir=REPO, recursive=True)`
que ya usa `tests/test_reglas_claude.py`. Ese código se mueve a `_seleccion.py` y el test lo
importa: una sola lectura de las cabeceras.

- **Un fuente** (`*.py` de la raíz, `common/`, `ui/`, `install/`):
  - sus áreas, las de las reglas que lo cubren;
  - más las áreas de **cada fuente que lo importa**, a cualquier nivel (dentro de una función
    también, que aquí es lo normal: `ui.md` «lazy imports»), **un solo salto**;
  - más, si es un script que se lanza como proceso, las áreas de quien lo lanza (`LANZADO_POR`).
- **Un `tests/test_*.py`**: ese test, sin más.
- **Un ayudante `tests/_*.py`** (`_harness`, `_agente_falso`, `_vista`…): los tests que lo
  importan (`import _x` / `from _x import`), y nada más (la regla `commands-testing` los cubre,
  pero eso decide el doc, no los tests). `_harness.py` lo importan todos: todos.
- **`tests/run_all.py`** y **`tests/_seleccion.py`**: las áreas que los cubren (`commands-testing`).
- **`common/__init__.py`**: lo importan todos, sin área propia: todo lo que no abre ventana.
- **Cualquier otro fichero** (docs, `.toml`, `.yml`, `.bat`): las áreas cuyos `paths` lo cubren.
  Si ninguna lo cubre, no aporta tests.

El grafo de imports se construye con `ast` sobre los fuentes del repositorio, en cada llamada
(son unos 120 ficheros: milisegundos). El de los tests **no** sirve para elegir: `_harness.py`
importa `model`, `equipo`, `keepassxc` y `store`, y por ahí todo test alcanza 22 módulos, entre
ellos `bisync`. Por eso el salto va de fuente a fuente, y de fuente a área.

`LANZADO_POR` es una tabla en `_seleccion.py`: script → los fuentes que lo lanzan como proceso
(no lo importan, así que el grafo no los ve). Comprobada contra el código el 18/10/2026 (las
apariciones de `model.SYNC_PY`, `model.RUNSYNC_PY`, `model.PENWATCH_PY` y las rutas literales):

| Script | Lo lanzan |
|---|---|
| `sync.py` | `runsync.py`, `ui/tk.py`, `ui/console.py`, `common/llavero.py`, `agente.py` |
| `runsync.py` | `penwatch.py`, `agente.py`, `common/keepassxc.py`, `common/llavero.py`, `common/update.py` |
| `penwatch.py` | `ui/watch.py` (el agente lo importa: eso ya lo ve el grafo) |
| `pregunta.py` | `agente.py` |
| `agente.py` | `install/agente.py` |

`--area A` usa la misma expansión: las áreas pedidas, más las de los fuentes que importan o
lanzan algún fuente de esas áreas (un salto).

### 3. De las áreas, los tests

Los `tests/test_*.py` que cubren los `paths` de esas áreas, más los que se añadieron por nombre
en el paso 2, menos los de `GUI` si no hay `--ventanas`. `GUI` sigue siendo la única definición
de «test de ventana».

### 4. Lo que imprime antes de correr

Una línea por área con su motivo, y los tests de ventanas que se quedan fuera, por nombre, para
que quien quiera pueda pedirlos:

```
Áreas (por los cambios de esta rama):
  engine         ← common/bisync.py
  llavero        ← common/llavero.py importa common/bisync.py
  service        ← runsync.py lanza sync.py
Fuera, por abrir ventanas (van en el CI; por nombre o con --ventanas): test_tk_pasada.py, …
```

Si los cambios no tienen ningún test (solo `LICENSE`, que no cubre ninguna regla): `Estos
cambios no tienen tests: LICENSE`, y sale con **0**. «No hay tests que ejecutar.» y su 1 se quedan para cuando
no hay ningún fichero de test. Un nombre de área que no es una regla sale con 2, como hoy un
nombre que no es un test.

## Las áreas de los 29 tests que no tienen

151 de los 180 ya están en los `paths` de alguna regla. Los demás se añaden a la de lo que
prueban; de paso, el agente que los edite recibe también el puntero a su doc. Comprobado el
18/10/2026 por su docstring y por qué doc los cita:

| Área | Tests |
|---|---|
| `engine` | `test_logs_acotados`, `test_parseo_seguro`, `test_rclone_portable`, `test_referencia_vacia`, `test_salida_utf8`, `test_ventana_hora` |
| `service` | `test_resync_desatendido` (y `repair`), `test_servicio_ritmo`, `test_store_ocupado` |
| `agent` | `test_agente_bitlocker`, `test_store_creado` |
| `agent-window` | `test_agente_actualizar_unidad`, `test_agente_pedir_al_conectar`, `test_buzon_carrera` |
| `llavero` | `test_agente_registro` (y `agent`), `test_keepassxc_pin` |
| `updating` | `test_precompilar` |
| `ui` | `test_hijos`, `test_matar_arbol`, `test_perf`, `test_perf_ajustes`, `test_perf_anfitrion`, `test_perf_flota`, `test_perf_parejas`, `test_perf_principal` |
| `commands-testing` | `test_run_all`, `test_rendimiento_informe`, `test_maquina_real_yml`, `test_seleccion` (nuevo) |
| `docs-maintenance` | `test_reglas_claude`, y el patrón `.claude/rules/*.md` (cambiar una regla corre ese test) |

Un test puede ir en más de un área si prueba la frontera entre dos (`test_agente_registro`:
`llavero` y `agent`).

## Guardas

- **Todo `tests/test_*.py` está en los `paths` de alguna regla.** En `test_reglas_claude.py`,
  junto a la que ya exige que cada módulo tenga regla. Un test nuevo sin área falla ahí, con su
  nombre.
- **`LANZADO_POR` no miente**: cada script y cada lanzador existen, y cada lanzador nombra de
  verdad el script (su nombre de fichero o su constante de `model`). En `test_seleccion.py`.
- **El CI abre ventanas**: el trabajo `tests` de `.github/workflows/tests.yml` pasa `--ventanas`
  en sus dos pasos. En `test_run_all.py`.
- **`tests/test_seleccion.py`** prueba el selector con reglas y fuentes de mentira en un
  directorio temporal, y `cambiados()` sustituido:
  - un fuente del motor → su área y las de quien lo importa (un salto, no dos);
  - `sync.py` → las áreas de sus lanzadores;
  - un `test_*.py` → ese test; `_harness.py` → todos; otro ayudante → los que lo importan;
  - `LICENSE` sin regla → ninguno, y sale con 0;
  - `cambiados()` devuelve `None` → todo lo que no abre ventana, con su línea;
  - `GUI` fuera, salvo con `--ventanas` o por nombre;
  - `--cambios` con nombres o con `--area` → error de argumentos.

  Y una vez contra el repositorio de verdad: cambiar `common/bisync.py` selecciona `engine` y
  ningún test de `GUI`.

## Agentes, docs y CI

- **`AGENTS.md`**, «Commands and verification»: en el bloque de órdenes,
  `python tests/run_all.py --cambios -j auto` es la verificación mientras se trabaja y
  `run_all.py -j auto` el repaso sin ventanas; una línea: «windows never open locally unless named
  or `--ventanas`; CI runs them». Dos o tres líneas: el fichero se carga en cada sesión.
- **`.claude/hooks/session_start.sh`**: `Verificación: python tests/run_all.py --cambios -j auto
  (sin ventanas; las ventanas, en el CI)`.
- **`.claude/settings.json`**: se permiten `Bash(python tests/run_all.py *)` y
  `Bash(python3 tests/run_all.py *)`, para que `--cambios` no pida permiso cada vez.
- **`docs/agents/reference/commands-testing.md`**: los niveles, las opciones, el algoritmo,
  `LANZADO_POR`, «un test nuevo va en los `paths` de la regla de su área», y `cambiados()` en el
  registro de puntos de sustitución.
- **`.claude/skills/new-area-doc`**: al crear un área, sus tests van en los `paths` de su regla.
- **`.github/workflows/tests.yml`**: el trabajo `tests` añade `--ventanas` en Linux y Windows.
  `python-minimo` no cambia (no hay Tk). El paso del pintor de iconos ya pasa sus tests por
  nombre: tampoco cambia.

## Lo que no cambia

- Ningún dispositivo: nada de esto viaja a una unidad (`tests/` no se despliega).
- Dónde viven los tests, cómo se escriben, `_harness.py`, `GUI`/`GUI_NO`/`SERIE`/`PESO`, `-j`,
  `--display`, `--gui-jobs`, `--timeout`, Ctrl-C.
- `rendimiento.yml`, `instalador.yml`, `llavero-real.yml`, `maquina-real.yml`,
  `prefijo-alias-real.yml`, `tk-xft.yml`.

## Riesgos

- **La selección local deja algo fuera**: un salto de imports no ve dependencias de dos saltos ni
  lo que pasa por ficheros o procesos no declarados. Es a propósito (decisión 2): el CI lo pasa
  todo en cada PR. El mensaje de `--cambios` dice que es una selección.
- **El ejecutor lee `.claude/rules/`**: el mapa de áreas vive en la configuración de Claude Code.
  Se acepta porque ya es la taxonomía del repositorio (docs, reglas y tabla de `AGENTS.md`, que
  vigila `test_reglas_claude.py`); una segunda copia sería peor.
- **Quien corría `run_all.py` sin argumentos esperando todo** ya no abre ventanas: la última
  línea lo dice siempre, con el número que quedó fuera.

## Cambios tras la revisión final (18/10/2026)

La revisión de la rama entera vio que la selección se quedaba corta en casos que la decisión 2
(«pillar en local casi todo lo que rompería el CI») no quería dejar fuera. Se añadió:

- **Los tests que importan el fuente cambiado**, aunque estén en otra área: `test_frenos.py` y
  `test_forzar.py` importan `sync` y son de `repair`; ahora los elige un cambio en `sync.py`.
- **Los tests que nombran el fichero cambiado** por su nombre (`maquina-real.yml`,
  `sync_config.example.toml`, un ayudante que se lanza como `"_runtime_ci.py"`): antes salían
  como «Estos cambios no tienen tests».
- **`test_reglas_claude.py`** cuando el cambio puede romperlo: un fuente o un test que no está
  en ninguna regla, o un fichero borrado que una regla nombra.
- **`python-minimo` también pasa `--ventanas`**: sin pantalla las partes de Tk se saltan, pero
  esos ficheros prueban cosas sin ventana (la consola de respaldo, `matar_arbol`) que deben
  seguir corriendo con el 3.11. «`python-minimo` no cambia» (arriba) ya no vale.
- `tests/_seleccion.py` se trata como ayudante (los tests que lo importan), no por las áreas de
  su regla como decía «2. De cada fichero, sus áreas».

## Cómo se comprueba

- `tests/test_seleccion.py`, `tests/test_reglas_claude.py` y `tests/test_run_all.py` en verde.
- En la máquina de desarrollo (Windows): `run_all.py --cambios -j auto` con un cambio solo en
  `common/bisync.py` no abre ninguna ventana y corre unos 40 tests (medido con las listas de hoy:
  40 de 126); con un cambio solo en `LICENSE` no corre nada y sale con 0.
- El CI de la PR corre los 180 en Linux y Windows (el resumen dice `Los 180 ficheros de test
  pasan.`, sin «sin correr»).
