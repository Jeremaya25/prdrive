# Proteger la contraseña de VeraCrypt de los keyloggers: plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Una opción por unidad, apagada por defecto, que hace que VeraCrypt pida la contraseña en su escritorio seguro (Windows) o comprueba que la sesión es Wayland (Linux), y avisa con el motivo cuando no se puede.

**Architecture:** La opción es una línea `escritorio_seguro=1` en `.prdrive-vestibulo`, junto al contenedor. La leen tres lectores independientes (penwatch, que usa también el agente; `Abrir PRDRIVE.bat`; `abrir-prdrive.sh`) y la escribe la ventana desde «Ajustes → Configuración». La decisión es una función pura de penwatch; la versión del ejecutable, un punto de indirección.

**Tech Stack:** Python 3.11+ stdlib, ctypes (`version.dll`) en Windows, cmd + PowerShell en el `.bat`, POSIX sh en el `.sh`, Tk 9 en la casilla.

**Spec:** `docs/superpowers/specs/2026-11-01-escritorio-seguro-design.md`

## Global Constraints

- Clave y valor exactos: `escritorio_seguro=1` (otra cosa = apagada).
- Umbral de versión: 1.20 (`mayor*1000+menor >= 1020`); en el `.bat`, además `< 9000` (9009 es «no hay PowerShell»).
- Nunca `/enableIME`. Nunca tocar la configuración de un VeraCrypt instalado.
- penwatch no importa nada del proyecto: su copia de la clave, con su test.
- `.bat`: CRLF, ningún paréntesis en una línea de órdenes, `chcp 65001` antes de cualquier acento del mismo bloque.
- Texto para la persona y comentarios en español; nada se lee del dispositivo en el hilo de Tk.
- Sin la línea, las órdenes son byte a byte las de antes.

## Review Focus

1. Marca con CRLF (editada a mano en Windows): `escritorio_seguro=1\r` sigue contando como encendida, y `poner_escritorio_seguro()` conserva el `id=` → test en la tarea 1.
2. Marca ilegible o unidad retirada a media lectura: apagada, sin excepción, en penwatch y en la ventana → tests en las tareas 1 y 2.
3. VeraCrypt en una ruta con paréntesis o espacios (`Program Files (x86)`): el `.bat` pasa la ruta a PowerShell por `$env:VC`, nunca dentro del texto de la orden → test en la tarea 3.
4. En Windows, la marca sigue oculta tras cambiar la opción → test (solo Windows) en la tarea 1.
5. `GDK_BACKEND=wayland,x11` no avisa; `GDK_BACKEND=x11,wayland` sí → tests en las tareas 2 y 3.

---

### Task 1: La marca lleva la opción

**Files:**
- Modify: `common/vestibulo.py`, `install/vestibulo.py` (`marca()`, `escribir()`), `install/raiz_equipo.py` (`marcar()`)
- Test: `tests/test_vestibulo.py`, `tests/test_raiz_equipo.py`

**Interfaces:**
- Produces: `vestibulo.ESCRITORIO_SEGURO = "escritorio_seguro"`; `vestibulo.escritorio_seguro(raiz: Path | str) -> bool` (no lanza); `vestibulo.poner_escritorio_seguro(raiz: Path | str, valor: bool) -> None` (lanza `OSError`); `install.vestibulo.marca(device_id: str, escritorio_seguro: bool = False) -> str`.

- [ ] **Step 1: tests** en `test_vestibulo.py`: `marca(ID)` sin la línea; `marca(ID, True)` con `escritorio_seguro=1`; `escritorio_seguro()` de una raíz sin marca es `False`; `poner_escritorio_seguro(raiz, True)` → `True` y `leer_id()` sigue dando `ID`; otra vez `True` deja una sola línea; `False` la quita y el resto de líneas queda igual; marca escrita con CRLF a mano → `True`; `escribir()` sobre una marca encendida la deja encendida; en Windows, el fichero sigue oculto (`GetFileAttributesW & 2`). En `test_raiz_equipo.py`: `marcar()` sobre una marca encendida la conserva.
- [ ] **Step 2:** `python tests/test_vestibulo.py` falla por `ESCRITORIO_SEGURO`.
- [ ] **Step 3:** implementar. `poner_escritorio_seguro`: leer líneas (sin la clave), añadir `escritorio_seguro=1` si `valor`, escribir `"\n".join(...) + "\n"` en `<marca>.tmp` con `newline="\n"`, `store.unhide()`, `os.replace()`, `store.hide()`. `escribir()`/`marcar()`: `marca(id, vestibulo.escritorio_seguro(raiz))` antes de reescribir.
- [ ] **Step 4:** `python tests/test_vestibulo.py` y `python tests/test_raiz_equipo.py` pasan.
- [ ] **Step 5:** commit.

### Task 2: penwatch decide y añade `/secureDesktop`

**Files:**
- Modify: `penwatch.py`
- Test: `tests/test_penwatch_vestibulo.py`

**Interfaces:**
- Consumes: la marca de la tarea 1 (formato, no código).
- Produces: `penwatch.VESTIBULE_SECURE_KEY = "escritorio_seguro"`; `penwatch.SECURE_DESKTOP_MIN = (1, 20)`; `penwatch.veracrypt_version(exe: str) -> tuple[int, int] | None`; `class Proteccion(NamedTuple): pedida: bool; motivo: str`; `penwatch.proteccion(container: Path, exe: str) -> Proteccion`; `veracrypt_command()` igual que hoy más `/secureDesktop` (justo detrás del ejecutable) cuando procede; `open_container(root, cwd=None, al_avisar: Callable[[str], None] | None = None) -> bool`.

- [ ] **Step 1: tests**: la copia de la clave es `vestibulo.ESCRITORIO_SEGURO`. Windows forzado, `veracrypt_version` sustituida: sin la línea → `Proteccion(False, "")` y orden sin `/secureDesktop`; con ella y (1, 26) → `(True, "")` y `orden[1] == "/secureDesktop"`; (1, 19) → motivo con «1.20»; `None` → motivo con «versión»; la raíz del equipo (`veracrypt_command(None, hc, "P:", respaldo=...)` con la marca junto al `.hc`) igual. Linux forzado: `WAYLAND_DISPLAY` vacío → motivo con «Wayland»; con él → sin motivo; `GDK_BACKEND=x11` → motivo con `GDK_BACKEND=x11`; `wayland,x11` → sin motivo; y la orden de Linux nunca cambia. `open_container()` con motivo: lo apunta en el diario y llama a `al_avisar(motivo)` una vez; sin motivo no lo llama. Marca ilegible → `Proteccion(False, "")`. En Windows de verdad (CI), `veracrypt_version(sys.executable)[:1] == (sys.version_info.major,)`; en Linux, `(saltado)`.
- [ ] **Step 2:** el test falla.
- [ ] **Step 3:** implementar. `veracrypt_version`: `ctypes.WinDLL("version")` con `argtypes`, firma `0xFEEF04BD`, `(ms >> 16, ms & 0xFFFF)`; cualquier fallo, `None`. Leer la línea con `startswith(f"{KEY}=")` y `== "1"` tras `strip()`.
- [ ] **Step 4:** `python tests/test_penwatch_vestibulo.py` pasa; también `tests/test_install_agente.py` (penwatch sigue sin importar el proyecto).
- [ ] **Step 5:** commit.

### Task 3: Los lanzadores

**Files:**
- Modify: `install/vestibulo.py` (`bat_abrir()`, `sh_abrir()`, nuevas `_PROTECCION_BAT`, `_PROTECCION_SH`)
- Test: `tests/test_vestibulo.py`

**Interfaces:**
- Produces: subrutina `:proteccion` del `.bat` (deja `VC_SEGURO`); función `proteccion ventana|terminal` del `.sh`; `vestibulo.MARCA_PROTECCION_BAT = ":proteccion"` (lo que la tarea 5 busca para saber si el `.bat` ya la tiene).

- [ ] **Step 1: tests**: `bat_abrir()` sigue sin paréntesis y con los acentos tras `chcp`; `call :proteccion` va después de `_ELEGIR_BAT` y antes del `start`; la orden lleva `"%VC%" %VC_SEGURO% /volume`; `:proteccion` busca `escritorio_seguro=1` con `findstr /b /l` en `%~dp0.prdrive-vestibulo`, llama a `powershell` con `$env:VC` (y no `%VC%`), y fija `VC_SEGURO=/secureDesktop` solo con `geq 1020` y `lss 9000`; nunca `/enableIME`. En Windows (CI): la línea de PowerShell, ejecutada con `VC=sys.executable`, sale con `mayor*1000+menor` de python.exe. `.sh` ejecutado con el `veracrypt` de mentira: sin la línea, nada nuevo en stderr; con ella y `WAYLAND_DISPLAY` vacío y `DISPLAY` puesto, aviso con «Wayland»; con `WAYLAND_DISPLAY`, sin aviso; con `GDK_BACKEND=x11`, aviso; por udisks2 (sin `veracrypt`), aviso de «terminal».
- [ ] **Step 2:** fallan.
- [ ] **Step 3:** implementar según el spec, §2 y §3.
- [ ] **Step 4:** `python tests/test_vestibulo.py` pasa (en este Linux, con sh, dash y bash si están).
- [ ] **Step 5:** commit.

### Task 4: El agente avisa del motivo

**Files:**
- Modify: `agente.py` (`abrir_contenedor()`, el «Desbloquear» de la raíz cifrada)
- Test: `tests/test_agente_veracrypt.py`

**Interfaces:**
- Consumes: `penwatch.open_container(..., al_avisar=)`, `penwatch.proteccion()`.

- [ ] **Step 1: tests**: con `penwatch.proteccion` sustituida para devolver un motivo, abrir una unidad cerrada y desbloquear la raíz dejan un aviso con el motivo (el `avisar` sustituido lo recoge); sin motivo, ninguno nuevo.
- [ ] **Step 2:** fallan.
- [ ] **Step 3:** `abrir_contenedor(raiz)` pasa `al_avisar=lambda m: avisar("Contraseña sin protección", ...)`; el «Desbloquear», tras construir `cmd`, `penwatch.proteccion(Path(unidad.contenedor), cmd[0])`.
- [ ] **Step 4:** `python tests/test_agente_veracrypt.py` pasa.
- [ ] **Step 5:** commit.

### Task 5: La casilla

**Files:**
- Modify: `ui/cifrado.py`, `ui/instantanea.py` (campo `escritorio_seguro`), `ui/tk_doctor.py` (se lo pasa), `ui/tk_configuracion.py` (`construir(panel, config, seguro=None)`)
- Test: `tests/test_cifrado_escritorio_seguro.py` (nuevo, sin Tk) y uno de ventana; los dos en los `paths` de la regla de `ui`

**Interfaces:**
- Consumes: tarea 1 (`escritorio_seguro`, `poner_escritorio_seguro`), tarea 3 (`MARCA_PROTECCION_BAT`).
- Produces: `class EscritorioSeguro(NamedTuple): valor: bool; bat_anterior: bool`; `cifrado.escritorio_seguro(fisica: Path | None) -> EscritorioSeguro | None`; `cifrado.guardar_escritorio_seguro(fisica: Path, valor: bool) -> bool`; `cifrado.ayuda_escritorio_seguro(bat_anterior: bool) -> str`.

- [ ] **Step 1: tests**: `escritorio_seguro(None)` y sin marca → `None`; con marca → `valor` según la línea; `bat_anterior` `True` con un `.bat` sin `:proteccion`, `False` con el de ahora y sin `.bat` (raíz del equipo); `guardar` → `True` y la marca cambia; sobre una carpeta de solo lectura → `False`. `instantanea.leer()` lo trae. Ventana: con `seguro=EscritorioSeguro(False, False)` sale la casilla y «Guardar» marcada llama a `guardar_escritorio_seguro(fisica, True)`; con `None` no sale.
- [ ] **Step 2:** fallan.
- [ ] **Step 3:** implementar; la ayuda dice lo de «Qué cubre y qué no» del spec.
- [ ] **Step 4:** `python tests/run_all.py --cambios -j auto` pasa (sin ventanas).
- [ ] **Step 5:** commit.

### Task 6: Documentación y plan de máquina real

**Files:**
- Modify: `docs/agents/reference/veracrypt.md`, `vestibule.md`, `penwatch.md`, `agent.md`, `ui.md`, `commands-testing.md` (punto de indirección `penwatch.veracrypt_version()`), la guía de usuario que hable de VeraCrypt en `docs/guia/`
- Create: `docs/superpowers/pruebas/2026-11-01-escritorio-seguro-pendiente-en-real.md`

- [ ] **Step 1:** escribir; `python tests/test_reglas_claude.py` pasa.
- [ ] **Step 2:** commit; push; PR en borrador con la plantilla.
