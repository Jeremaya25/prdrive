# Plan: «Emparejar un móvil» fuera de las capturas, en Windows real (#59)

Fecha: 2026-10-02 · Estado: **por hacer**. Los resultados van en un fichero
aparte, al lado de este (`2026-10-02-captura-qr-pendiente-en-real-resultados.md`),
como los de la unidad G:.

La ventana «Ajustes» → «Emparejar un móvil…» (`ui/tk_qr.py`) enseña la clave
privada del remoto como un QR. En Windows pide a Windows que no salga en
capturas ni al compartir pantalla (`tk.proteger_de_capturas()`,
`SetWindowDisplayAffinity`). Los tests de `tests/test_captura_pantalla.py`
sustituyen user32 y la ventana de Tk, así que **nada de esto se ha visto
funcionar**. Esto es lo que solo un Windows de verdad puede decir.

«Lo esperado» sale del código y de la documentación de Windows; en un equipo
real manda lo que se vea: si no coincide, se apunta la discrepancia y no se
reinterpreta.

## Qué se supone y no se ha visto

Se dedujo de las fuentes de Tk 8.6.15 (`win/tkWinWm.c`, `win/tkWinWindow.c`,
`generic/tkFrame.c`), que es la versión del runtime de Windows que fija
`common/pins.py`:

1. Un `Toplevel` recién creado y retirado (`withdraw`) **no tiene todavía
   ventana envoltorio**. Hasta entonces `wm frame` devuelve la ventana propia de
   Tk, la misma que `winfo_id()` (un `WS_POPUP` sin padre).
2. El primer `update_idletasks()` ejecuta `MapFrame` → `TkWmMapWindow` →
   `UpdateWrapper`: crea el envoltorio **oculto** (`SW_HIDE`, porque el estado
   inicial es «retirada») y mete dentro la ventana propia con `SetParent`. A
   partir de ahí `wm frame` es el envoltorio, y es la ventana de nivel superior
   que pide `SetWindowDisplayAffinity`.
3. `geometry` y `deiconify` no recrean el envoltorio; `resizable`, `transient`,
   `overrideredirect` y los `attributes` de estilo sí (`UpdateWrapper` destruye
   el envoltorio y crea otro, y la afinidad se pierde con él). `modal()` hace las
   suyas antes de que exista, y `mostrar()` solo usa `geometry` y `deiconify`.

`proteger_de_capturas()` hace el `update_idletasks()` antes de pedir `wm frame`,
y no protege nada si `wm frame` sigue siendo igual a `winfo_id()`.

## Equipos

- **W**: Windows 11 x64, versión 22H2 o posterior.
- **WA**: Windows 11 ARM64.
- **W10**: Windows 10 **anterior a la 2004** (la 1909, por ejemplo, en una
  máquina virtual): no conoce `WDA_EXCLUDEFROMCAPTURE`.
- Un móvil con prdrive, para leer el código.

## 0. El manejador, con la ventana retirada

Antes de las capturas, lo que decide si todo lo demás tiene sentido. Desde la
raíz del repositorio, con el Python del runtime (`.prdrive\runtime\windows-x64\`
o el que se tenga), sin instalar nada:

```python
import ctypes
import tkinter as tk
from ui import tk as uitk

u = ctypes.WinDLL("user32", use_last_error=True)
u.GetParent.restype = ctypes.c_void_p
u.GetParent.argtypes = [ctypes.c_void_p]
u.IsWindowVisible.argtypes = [ctypes.c_void_p]
u.GetWindowDisplayAffinity.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_uint)]


def afinidad(hwnd):
    valor = ctypes.c_uint(0xFFFF)
    u.GetWindowDisplayAffinity(hwnd, ctypes.byref(valor))
    return hex(valor.value)


raiz = tk.Tk()
raiz.withdraw()
dlg = uitk.modal(raiz, "prueba")           # retirada, como la deja modal()
print("1 antes   frame", dlg.wm_frame(), "winfo_id", hex(dlg.winfo_id()))
dlg.update_idletasks()
frame = int(dlg.wm_frame(), 16)
print("2 despues frame", hex(frame), "winfo_id", hex(dlg.winfo_id()),
      "padre de winfo_id", hex(u.GetParent(dlg.winfo_id()) or 0),
      "visible", u.IsWindowVisible(frame))
print("3 proteger ->", hex(uitk.proteger_de_capturas(dlg)),
      "afinidad leida", afinidad(frame))
dlg.geometry("+200+200")
dlg.deiconify()
dlg.update()
print("4 mostrada  frame", dlg.wm_frame(), "afinidad", afinidad(frame),
      "visible", u.IsWindowVisible(frame))
```

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| C0 | W | El script de arriba. | **1**: `frame` y `winfo_id` iguales. **2**: distintos; el padre de `winfo_id` es `frame`; `visible` 0 (el envoltorio se crea sin enseñarse). **3**: devuelve `0x11` y la afinidad leída es `0x11`. **4**: el mismo `frame` que en 2 (no se recreó), afinidad aún `0x11`, `visible` 1. Si 1 sale distinto, `proteger_de_capturas()` ya no necesita su comprobación; si 2 sale igual, devolverá 0 siempre y la ventana saldrá sin protección. | `tk.proteger_de_capturas()`, `tkWinWm.c` `WmFrameCmd` / `UpdateWrapper` |

## 1. Que de verdad no salga

Con «Ajustes» → «Emparejar un móvil…» abierto en un dispositivo con conexión.
La línea bajo el recuadro ámbar tiene que decir «Esta ventana no aparece en
capturas de pantalla ni al compartir pantalla.»

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| C1 | W | Recortes (Win+Shift+S), a pantalla completa y por rectángulo, y la captura de ventana. También Impr Pant. | La ventana **no sale**: se ve lo que hay detrás, no un recuadro negro. | `WDA_EXCLUDEFROMCAPTURE` |
| C2 | W | Compartir pantalla entera en Teams y en Meet, con otra persona mirando. | Quien mira no ve la ventana. Apuntar si ve un hueco o lo de detrás. | ídem |
| C3 | W | OBS: captura de pantalla (los dos métodos, DXGI y Windows Graphics Capture) y captura de ventana de la propia ventana. | No sale en la grabación con ninguno. Apuntar qué método falla, si alguno. | ídem |
| C4 | W | Escritorio remoto (`mstsc`) desde otro equipo, con la ventana abierta en el remoto. | Quien se conecta la ve **en negro**. Apuntar exactamente qué ve, que es lo que la documentación no promete. | ídem |
| C5 | W | Apuntar la cámara del móvil al monitor y emparejar. | El móvil lee el código igual que antes: en el monitor la ventana se ve normal. Nada de parpadeos ni cambios de contraste. | `SetWindowDisplayAffinity` solo afecta a la captura |
| C6 | WA | C0 y C1–C5, con el Python ARM64 nativo y también con uno x64 emulado. | Igual en los dos. Apuntar si el manejador de `wm frame` y la afinidad cambian con la emulación. | ídem |
| C7 | W | Grabar con OBS a 60 fps y abrir la ventana diez veces seguidas; mirar la grabación fotograma a fotograma. | **Ningún** fotograma la enseña, ni el primero. Es la comprobación de «ni un fotograma sin proteger». | `open_dialog()` protege antes de `mostrar()` |
| C8 | W | Cerrar la ventana y abrirla otra vez, dos veces. | Cada una sale protegida y con su línea: es otra ventana, otro manejador. | `proteger_de_capturas()` por ventana |

## 2. Lo que no puede prometer

| Código | Dónde | Qué hacer | Qué se espera | Código a prueba |
|---|---|---|---|---|
| L1 | W10 (anterior a la 2004) | Abrir la ventana y capturarla con Recortes. | `0x11` se rechaza y se queda en `WDA_MONITOR`: la captura enseña un **recuadro negro** con el marco. **La línea dice «En las capturas de pantalla y al compartir pantalla, esta ventana sale en negro.»** y en ningún sitio «no aparece». | `LINEA_CAPTURA[CAPTURA_EN_NEGRO]` |
| L2 | W | La Lupa (Win++) y el Narrador sobre la ventana. | Se sabe que la ven (no pasan por la captura que filtra la afinidad). Apuntar qué se ve: es el límite que la documentación de `proteger_de_capturas()` dice. | límite conocido |
| L3 | W | Una foto con otro móvil a la pantalla. | La recoge, claro. Por eso el recuadro ámbar sigue diciéndolo y es la barrera principal. | `tk_qr.AVISO` |
| L4 | W | Un equipo donde `SetWindowDisplayAffinity` falle con las dos (sin composición del escritorio, o una sesión remota que lo rechace), si se encuentra uno. | La ventana se abre igual, **sin línea**: ni promete ni avisa. Si no hay forma de verlo, vale lo que dicen los tests. | `LINEA_CAPTURA`, «nunca debe impedir que se abra» |
| L5 | W | Abrir la ventana en un dispositivo sin conexión (un checkout sin provisionar). | Sale el mensaje de que no hay conexión, sin QR, sin línea y **sin protección**: no hay nada que proteger. Una captura la recoge, y no pasa nada. | `tk_qr.open_dialog()` |
| L6 | L | Abrir la ventana en Linux (X11 y Wayland). | Sin línea de capturas: no hay equivalente y la ventana no insinúa lo contrario. Se abre y funciona como antes. | `IS_WIN` falso |

## Qué hacer con lo que salga

- **C0 distinto de lo esperado**: el manejador es lo único que se dedujo del
  código; antes de seguir, corregir `proteger_de_capturas()` y la nota de
  `docs/agents/reference/pairing-qr.md` (antes «Pairing a phone» en `AGENTS.md`).
- **C1–C3 con alguna aplicación que la graba**: apuntar cuál y con qué método de
  captura, y decirlo en `docs/agents/reference/pairing-qr.md`; la línea de la
  ventana no puede seguir prometiéndolo para esa.
- **C4**: lo que ve quien se conecta por Escritorio remoto va a
  `docs/agents/reference/pairing-qr.md` tal cual se vea.
