# Plan: la contraseña de VeraCrypt protegida de los keyloggers (#199) en máquina real

Fecha: 2026-11-01 · Estado: **por hacer**. Los resultados van en un fichero aparte, al lado de
este (`2026-11-01-escritorio-seguro-pendiente-en-real-resultados.md`), como los de los demás
planes.

Los tests (`tests/test_penwatch_vestibulo.py`, `tests/test_vestibulo.py`,
`tests/test_agente_veracrypt.py`, `tests/test_tk_screens.py`) sustituyen VeraCrypt, la versión de
su ejecutable y el entorno de la sesión. Lo que comprueban es la decisión y las órdenes. Lo que
dice de VeraCrypt está leído en su código (`VeraCrypt_1.26.29`, `_1.20`, `_1.19`) y en el AppImage
fijado, no visto en marcha: **nada de esto se ha visto con un escritorio seguro de verdad, una
sesión Wayland ni un keylogger.** En Windows (CI) sí se ejecuta la lectura de la versión de un
`.exe` (ctypes y la línea de PowerShell del `.bat`) contra `python.exe`.

«Lo esperado» sale del código y de `docs/agents/reference/veracrypt.md` («The password, protected
from keyloggers»). En un equipo real manda lo que se vea: si no coincide, se apunta la diferencia
tal cual y no se reinterpreta.

## Equipos

- **W**: Windows 11 x64 con un dispositivo prdrive cifrado con VeraCrypt (con el VeraCrypt que
  viaja), el agente, y un VeraCrypt **instalado** que se pueda quitar y poner.
- **WA**: Windows 11 ARM64 con el mismo dispositivo.
- **G**: un escritorio GNOME en Wayland (Fedora o Ubuntu recientes) con VeraCrypt instalado o el
  AppImage, y `xinput`, `xev` y `wev` a mano.
- **K**: un escritorio KDE Plasma en Wayland, igual.
- **X**: una sesión X11 (la misma G con «GNOME en Xorg», o cualquier escritorio X11).

En todas: la opción encendida en «Ajustes → Configuración» con el contenedor abierto, y después
«Expulsar».

## Pruebas

| Código | Dónde | Qué hacer | Qué se espera |
|---|---|---|---|
| S1 | W | Sin VeraCrypt instalado, abrir con «Abrir PRDRIVE» (el que viaja, x64) | UAC; después la pantalla cambia a un escritorio vacío con solo el diálogo de contraseña; al acertar, de vuelta y la unidad se abre. La consola dice que la ventana sale en un escritorio aparte |
| S2 | WA | Lo mismo con `VeraCrypt-arm64.exe` | Igual que S1 |
| S3 | W | Con VeraCrypt 1.26.x instalado, «Abrir PRDRIVE» | Igual que S1, sin UAC del portable |
| S4 | W | Con un VeraCrypt 1.19 instalado (o un `.exe` con versión menor de 1.20 en su sitio), «Abrir PRDRIVE» | La consola avisa «anterior a la 1.20» y abre la ventana de siempre, sin `COMMAND_LINE_ERROR` |
| S5 | W | Con PowerShell bloqueado (AppLocker o renombrado en una máquina de pruebas), «Abrir PRDRIVE» | Aviso «no he podido saber qué versión» y la ventana de siempre |
| S6 | W | El agente, al enchufar la unidad cerrada | El diálogo en el escritorio seguro; ningún aviso del agente |
| S7 | W | Con la sesión **bloqueada** (Win+L) al enchufarla | VeraCrypt espera; al desbloquear la sesión sale el diálogo en el escritorio seguro. Que no se quede colgado ni salga detrás |
| S8 | W | Por **escritorio remoto** (RDP), «Abrir PRDRIVE» | Apuntar qué pasa: escritorio seguro, ventana normal sin aviso (el regreso silencioso) o algo peor (colgado). Si cuelga, es para un aviso previo por `%SESSIONNAME%` |
| S9 | W | En el escritorio seguro: pegar la contraseña (Ctrl+V), el teclado en pantalla (`osk`) y la autoescritura de un gestor de contraseñas del equipo | Apuntar cuáles funcionan; lo que no, va a la ayuda de la casilla |
| S10 | W | Con un keylogger de usuario de prueba (un `SetWindowsHookEx(WH_KEYBOARD_LL)` en Python con ctypes, en la misma sesión) mientras se teclea | Con la opción, el gancho no ve las teclas del diálogo; sin ella, sí |
| S11 | W | Abrir la ventana de VeraCrypt con la opción y el UAC del portable tapado por otras ventanas (#41) | El aviso de «Abrir PRDRIVE» al minuto sigue saliendo; el escritorio seguro sale después del UAC |
| L1 | G, K | Con VeraCrypt (instalado y AppImage), abrir con `abrir-prdrive.sh` y con el agente | Ningún aviso. `WAYLAND_DEBUG=1 veracrypt` (o `xlsclients`/`xwininfo -root -tree` vacío de VeraCrypt) dice si la ventana es cliente Wayland nativo |
| L2 | G, K | Con `xinput test-xi2 --root` y `xev -root` corriendo, teclear en la ventana de VeraCrypt | No ven las teclas (si la ventana es nativa) |
| L3 | G, K | Lo mismo tecleando en un campo de contraseña Tk de prdrive (el asistente) | Apuntar si las ven: confirma que el asistente no queda cubierto (XWayland) |
| L4 | G | `GDK_BACKEND=x11 sh abrir-prdrive.sh` | Aviso de `GDK_BACKEND`; la ventana va por XWayland y `xinput` ve las teclas |
| L5 | X | `abrir-prdrive.sh` y el agente | Aviso «no es Wayland» (terminal y aviso del sistema); abre como siempre |
| L6 | G | Sin VeraCrypt, por udisks2 o cryptsetup en una terminal | Aviso de que la terminal no la cubre; abre como siempre |
