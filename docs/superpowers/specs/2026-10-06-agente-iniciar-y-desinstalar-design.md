# Iniciar el agente y desinstalarlo sin rastro

Fecha: 2026-10-06 · Estado: **propuesta** (diseño aprobado en la conversación; falta
la revisión de este texto) · Área: `docs/agents/reference/agent.md` · Sin probar en
real: nada de esto ha corrido en un equipo de verdad.

## Qué se pide

El agente residente no es una instalación de verdad: es un registro al iniciar
sesión (tarea `prdrive` en Windows, autostart XDG en Linux). Falta:

1. **Arrancarlo cuando se ha parado a mano** («Cerrar el agente» de la bandeja o
   `agente.py parar`). Hoy solo vuelve al iniciar sesión, con el acceso «prdrive»
   del menú (`agente.py abrir`), con `schtasks /Run` o reinstalando; el asistente
   no tiene ningún botón del equipo.
2. **Desinstalarlo sin dejar rastro del programa.** `install/agente.py::desinstalar()`
   quita el registro, el acceso del menú y `equipo.DIR`, y nada más.

## Decidido con la persona

- **«Sin rastro» = ningún rastro del programa, los datos se quedan.** La raíz del
  equipo y un contenedor cifrado `PRDRIVE.hc` no se borran ni se cierran nunca; el
  resultado dice dónde siguen (`host-root.md`).
- **Dónde:** panel del asistente + línea de órdenes. Nada nuevo en la bandeja ni
  en el menú (la bandeja desaparece con el agente: no puede arrancarlo).

## Supuestos (a corregir si no valen)

- Solo Windows y Linux: es lo que soporta el código (`platforms.host()`).
- Fuera de alcance: el `.prdrive/` de una unidad (es el dispositivo, no el equipo).
- Por comprobar al implementar: que `keepassxc.plan_cerrar_navegador(None, None,
  muertas=True)` deja en Windows el registro como estaba sin una unidad enchufada
  (no se ha leído esa función para este diseño); si no, se añade un argumento.
- Fuera de alcance: `agente_vivo()` no mira el arranque del sistema, así que un pid
  reciclado tras un cuelgue se lee como «vivo». `iniciar()` dirá «ya está en
  marcha»; se apunta en la lista de pruebas en real, no se arregla aquí.

## Diseño

### 1. `iniciar()` (`install/agente.py`)

`iniciar(progreso=None) -> list[str]`:

- Sin agente instalado (`instalado() is None`): `InstallError`.
- Ya vivo (`equipo.agente_vivo()`): «Ya está en marcha.», sin tocar nada.
- Si no: `Preparado` desde `instalacion.json` (`instalado_prep()`), el `arrancar()`
  que ya existe (`schtasks /Run` o lanzamiento desacoplado) y espera
  `ESPERA_ARRANQUE` (constante de módulo, sustituible) a que `agente_vivo()` lo vea.
  Dice «Agente arrancado.» o «No ha arrancado: mira agente.log».

No hay mecanismo de arranque nuevo. Orden: `prdrive-install.py --iniciar-agente`
(`cmd_iniciar_agente`, junto a `cmd_instalar_agente`).

### 2. `install/rastro.py` (módulo nuevo, sin Tk)

Una sola fuente de «qué deja prdrive en un equipo». Cada entrada es algo que se
puede **demostrar que es nuestro**.

| Rastro | Cómo se quita |
|---|---|
| tarea / autostart, acceso del menú | `desregistrar()`, `quitar_menu()` (existentes) |
| `equipo.DIR` | borrado, con la guarda de abajo |
| cachés del instalador `<LOCALAPPDATA o temporal>/prdrive-install/` | borrado de la carpeta madre, derivada de `rclone_bin.cache_dir()` (no se copia una sexta ruta) |
| `~/.cache/prdrive/` (KeePassXC extraído) | borrado, tras cerrar un KeePassXC huérfano (`agente.cerrar_keepassxc_huerfano`) |
| claves del navegador (HKCU) / manifiestos (Linux) | `keepassxc.cerrar_navegador(muertas=True)`; solo los `manifiesto_nuestro()`: los de un KeePassXC instalado no se tocan |
| restos de penwatch | `quitar_penwatch()` (existente) |

- **Solo se cuentan, no se quitan** (no se puede demostrar que sean nuestros):
  `loginctl enable-linger`, `/etc/udisks2/tcrypt.conf`, un controlador de VeraCrypt
  cargado (hasta reiniciar), los avisos ya mostrados.
- **Nunca se tocan:** la raíz del equipo, el contenedor cifrado, ninguna unidad.
- **`plan()` → `RastroPlan`** con `consequences`, `warnings` y `execute(progreso)`
  (la forma de `EditPlan`, `ui/pair_editor.py:186`), para pasar por
  `tk_pairs.confirmar_plan()` como exige `AGENTS.md`.
- **`execute()`:** `parar_agente()` (espera la pasada en curso) → quita → **vuelve a
  inventariar** (`restos()`) y el mensaje final lista lo que siga ahí (en uso, sin
  permiso) con su ruta. Éxito = solo se nombran los datos que se quedan.
- **Guarda:** no se borra ninguna ruta que contenga `sys.executable`, `__file__` o
  el instalador en marcha (el patrón de `podar()`); se cuenta como resto.
- **Idempotente:** una segunda pasada no encuentra nada.
- `desinstalar()` delega en `rastro.plan().execute()`: asistente y
  `--desinstalar-agente` comparten una implementación. La orden sigue sin preguntar
  (es explícita), ahora completa.
- **Límite que se dice tal cual:** el `.exe` o el zip del instalador que se
  descargó se queda (en Windows un programa no se borra a sí mismo).

### 3. Panel del asistente (`ui/tk_install.py` `_paso_donde`, `ui/tk_equipo.py`)

Donde hoy está la frase «Ya está instalado (versión X)» (`equipo.instalado()`), un
panel «Ya instalado en este equipo» con **Iniciar agente** (solo si no está vivo),
**Poner al día** (el de siempre) y **Desinstalar de este equipo…** (`Danger.TButton`,
icono `trash`, abre `confirmar_plan(rastro.plan())`).

- Las acciones van por `tk.working()`; el resultado se queda en el panel. **Sin ruta
  nueva.**
- `tk_*` solo dibuja; `tk_equipo` se importa dentro de la función (`tk_install` no
  importa `install.agente`). Textos en español; medidas por `theme.medida()`.

## Qué se toca

`install/agente.py`, **`install/rastro.py` (nuevo)**, `prdrive-install.py`,
`ui/tk_install.py`, `ui/tk_equipo.py`. `.claude/rules/agent.md` gana
`install/rastro.py` (un `install/*.py` sin regla rompe `tests/test_reglas_claude.py`);
no hay documento de área nuevo.

Documentación: `docs/agents/reference/agent.md`, `commands-testing.md` (la orden y
el registro de puntos de indirección: funciones de `rastro`, `ESPERA_ARRANQUE`),
`host-root.md`, `docs/guia/agente-residente.md`, y las pruebas en real
(`docs/superpowers/pruebas/2026-09-25-equipo-pendiente-en-real.md`).

## Pruebas

- **`tests/test_rastro.py` (nuevo, sin pantalla):** un equipo falso en los
  temporales del arnés (`equipo.DIR`, XDG, cachés, `registro` falso, manifiestos
  nuestros y uno ajeno). `execute()` deja solo la raíz y el contenedor; el
  manifiesto ajeno intacto; idempotente; guarda del ejecutable; rama Windows con
  `IS_WIN` forzado y `schtasks /Delete` sustituido; restos informados.
- **`test_install_agente.py`:** `iniciar()` (no instalado / ya vivo / arranca / no
  arranca), la orden `--iniciar-agente`, `desinstalar()` por el plan.
- **`test_install_wizard.py`:** los botones solo con agente instalado; «Iniciar»
  oculto si está vivo; «Desinstalar» pasa por `confirmar_plan`.
- **En real** (no demostrable en este contenedor): arrancar tras `parar`; desinstalar
  deja solo los datos; fichero en uso en Windows; pid reciclado.
