# Versionado por pareja: `.prversions/` (issue #28)

Fecha: 2026-09-22 · Estado: implementado

## El problema

Una bóveda de Obsidian sincronizada con bisync produce conflictos constantes:
Obsidian reescribe `.obsidian/workspace.json` en cada cambio de panel, en cada
máquina. Hoy el perdedor de un conflicto se queda **dentro** de la bóveda como
`workspace.json.conflicto-remoto1`, se sincroniza a los dos lados y ahí se queda
hasta que alguien lo resuelve a mano.

Y cuando lo que se pisa es una nota de verdad, la versión anterior **no existe en
ninguna parte**: bisync elige un ganador y el otro contenido desaparece.

## Qué se construye

Una clave por pareja:

```toml
[[pair]]
name = "obsidian"
local = "sync-data/obsidian"
remote_path = "/PJ/Obsidian"
mode = "bisync"
versions = true
```

Con ella, cada lado guarda en `<raíz del pair>/.prversions/` lo que **ese lado**
pierde, con la estructura de carpetas del pair y el nombre
`<nombre>~<YYYYMMDD>-<HHMMSS>.<ext>`:

```
sync-data/obsidian/.prversions/Pere J/2. Literatura/P.004 — Cae el Sol~20260922-093000.md
```

Cubre tres cosas: ficheros **sobrescritos**, ficheros **borrados** (incluido el
borrado que llega del otro lado) y el **perdedor de un conflicto**.

## Lo que hace rclone, medido

Todo lo de abajo está comprobado con el rclone v1.75.1 del dispositivo, sobre un
remote `combine` igual que el `disp:` real. No es documentación citada.

| Prueba | Resultado |
|---|---|
| `--backup-dir1` dentro de Path1, **sin** excluirlo | `Bisync critical error: destination and parameter to --backup-dir mustn't overlap` |
| Lo mismo **con** `- .prversions/**` en el fichero de filtros | 0 errores; la versión aparece en `<pair>/.prversions/sub/nota~20260922-120000.md` |
| `--suffix "~YYYYMMDD-HHMMSS" --suffix-keep-extension` | produce exactamente `nombre~20260922-093000.md` |
| Fichero anidado | `v1/sub/hondo/prof~20260922-095000.md`: la estructura del pair se replica |
| Borrado propagado desde el otro lado | el fichero borrado acaba en el backup-dir de su lado |
| Durante un `--resync` | también guarda; hoy un resync se come el lado perdedor en silencio |
| `--conflict-loser delete` + `--backup-dir` | el perdedor **no se borra**: se aparta al backup-dir. Verificado por contenido |
| backup-dir en una ruta fuera del remote | `parameter to --backup-dir has to be on the same remote as destination` |
| backup-dir inexistente | rclone lo crea; no hace falta prepararlo |

**La exclusión no es una preferencia: es la condición que pone rclone** para
aceptar un backup-dir dentro del destino. Aislada la variable (misma orden, mismo
baseline, lo único que cambia es la regla), sin ella la pareja muere con error
crítico.

Consecuencia directa: los dos `.prversions/` son **independientes**, no se
replican. Es exactamente el modelo de Syncthing, de donde sale el formato del
nombre: `.stversions` es un nombre reservado que Syncthing nunca sincroniza, y
cada dispositivo guarda lo que él perdió.

## Diseño

### `common/model.py`

- `VERSIONS_DIR = ".prversions"`, constante única.
- `Pair.versions: bool`, leída de `raw.get("versions", False)`. **No hay
  `[defaults].versions`**: activarla para todas activaría también las que no son
  bisync.
- Validación en `_build_pair`: `versions = true` con un modo que no sea bisync →
  `ConfigError`. Es la única validación que hace falta; la carpeta vive dentro del
  pair, así que no puede solaparse con otra pareja.
- `Pair.versions_path1` / `Pair.versions_path2`: `source`/`dest` con
  `/.prversions` detrás. Path1 es `pair.source`, que en bisync es el lado local.

### `common/bisync.py`

`filters_content(pair)` emite `- .prversions/**` **como primera regla**, antes de
los `+` de `include`. rclone aplica las reglas en orden y gana la primera que
casa: detrás de un `+ **/*.md` la exclusión no serviría de nada.

### `sync.py`

`RunContext` gana `sello: str` — el `~YYYYMMDD-HHMMSS` en hora local, calculado
**una vez por invocación**, que es la definición de ese objeto. `build_command()`:

```python
if pair.versions:                       # el parseo ya garantiza que es bisync
    flags["backup-dir1"] = pair.versions_path1
    flags["backup-dir2"] = pair.versions_path2
    flags["suffix"] = ctx.sello
    flags["suffix-keep-extension"] = True
    flags.setdefault("conflict-loser", "delete")
```

`conflict-loser` va con `setdefault` para que un `[pair.flags]` del usuario siga
mandando; los otros cuatro son de la pasada y se reservan.

### `ui/flags_editor.py`

`RESERVED` gana `backup-dir`, `backup-dir1`, `backup-dir2`, `suffix` y
`suffix-keep-extension`, con el motivo escrito. `conflict-loser` **no** se
reserva.

### `ui/pair_editor.py`

- `versions` entra en `FORM_KEYS` y en `OPTIONAL_KEYS` (apagada = la clave
  desaparece del TOML, como el resto de opcionales).
- `clean_form()` necesita una rama para `bool`: hoy `str(False)` es `"False"`,
  que es una cadena no vacía, y la clave se guardaría como texto.
- `EditPlan.consequences` avisa al cambiar `versions`: el fichero de filtros
  cambia, así que **la pareja pedirá `--resync`**. Y al apagarla, además,
  `.prversions/` deja de estar excluida y empezaría a sincronizarse. Ese aviso es
  el mecanismo que el proyecto ya tiene para esto; no se resuelve con código que
  decida por el usuario.

### `ui/tk_pairs.py`

Una casilla «Guardar en .prversions/ lo que se sobrescriba o se borre», debajo
del modo. Con un modo que no sea bisync se **deshabilita** en vez de esconderse
—y se apaga sola—: que exista y esté gris explica por qué no se puede; que
desaparezca, no.

### Doctor → «Versiones…»

Entrada nueva en `tk_doctor.ENTRADAS`, que es donde va lo que se hace de tarde en
tarde. Se parte en dos como el resto de la UI:

- `ui/versions_editor.py` — sin Tk: qué hay en cada lado (número de ficheros y
  tamaño), y `plan_purgar(pareja, anterior_a)` → plan con consecuencias.
- `ui/tk_versions.py` — solo dibuja. Abrir la carpeta local con `ui.abrir()`,
  purgar con `confirmar_plan()`.

El lado remoto se lista con `catalog.run()`, que es la indirección que ya tiene el
proyecto para no congelar la ventana con un remoto muerto.

**Fuera de v1: restaurar.** Con la carpeta abierta y el nombre delante, copiar y
renombrar lo hace el usuario. Restaurar escribiendo sobre el fichero vivo, y en el
lado remoto, es otro mecanismo entero.

## Lo que NO cambia

- `common/conflicts.py`, `ui/conflict_editor.py`: intactos. En una pareja
  versionada simplemente no encuentran ficheros `.conflicto-*`, y `cargar()` ya se
  autolimpia. Los que existan de antes se siguen viendo, que es lo correcto: son
  restos reales.
- `pen_environment()` y los upstreams del `combine`: la carpeta vive dentro del
  pair, no hay que salir de él.
- `expected_prefix()`: no depende de `versions`. Hay un test que lo fija, porque
  ahí un descuido cuesta un baseline.

## Divergencia consciente respecto a Syncthing

Syncthing deja el perdedor del conflicto **suelto en la carpeta** y lo
sincroniza (`<nombre>.sync-conflict-<fecha>-<hora>-<id>.<ext>`), y reserva
`.stversions` solo para sobrescrituras y borrados. Aquí el perdedor va a
`.prversions/`, para que la bóveda quede limpia. Es una decisión, no un descuido.

## Pruebas — `tests/test_versions.py`

1. Derivación de `versions_path1` / `versions_path2`, con y sin `device_remote`.
2. `versions = true` en cada modo no-bisync → `ConfigError`.
3. `filters_content()` emite la regla, y **la emite primero**, por delante de los
   `+`.
4. `filters_content()` **no** la emite cuando `versions` está apagada.
5. `build_command()` pone los cinco flags, y `conflict-loser` del usuario gana.
6. `expected_prefix()` idéntico con `versions` encendida y apagada.
7. `config_file` round-trip con la clave nueva.
8. `clean_form()` con un bool: `True` se guarda, `False` desaparece.

## Documentación

`sync_config.example.toml` (la clave y las dos consecuencias), `AGENTS.md` (una
sección, con las citas de lo medido) y `README.md` (breve).
