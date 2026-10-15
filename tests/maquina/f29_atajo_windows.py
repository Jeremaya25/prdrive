"""F29: un atajo global con RegisterHotKey en la bandeja llega con otro programa delante (fila K1), y uno ocupado se rechaza (K2)."""

import ctypes
import subprocess
import time
from ctypes import wintypes

import comun

CODIGO = "F29"
SISTEMA = "W"
QUE = ("atajo global con RegisterHotKey en el hilo de la bandeja: llega como su petición con "
       "el Bloc de notas delante; uno que tiene otro programa se rechaza al ponerlo")

KEYEVENTF_KEYUP = 0x2
VK_CONTROL, VK_MENU, VK_F12, VK_A = 0x11, 0x12, 0x7B, 0x41
WM_GETTEXTLENGTH = 0x000E


def teclas(u32, *vks):
    """Pulsa y suelta esas teclas virtuales, como un teclado (`keybd_event`)."""
    for vk in vks:
        u32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        u32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def bloc(u32, pid):
    """Devuelve la ventana principal del Bloc de notas de ese proceso, o `None`."""
    encontradas = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada(hwnd, _l):
        dueño = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(dueño))
        if dueño.value == pid and u32.IsWindowVisible(hwnd):
            encontradas.append(hwnd)
        return True

    u32.EnumWindows(cada, 0)
    return encontradas[0] if encontradas else None


def probar(p: comun.Prueba) -> None:
    """Pone dos atajos en la bandeja de verdad, uno ocupado, y pulsa el otro con el Bloc delante."""
    from common import equipo
    from ui import atajos

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u32.IsWindowVisible.argtypes = [wintypes.HWND]
    u32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]

    with comun.bandeja_windows() as (b, _avisos):
        pedidas, puestos = [], []
        b.pedir = pedidas.append
        b.atajos_puestos = lambda co, re: puestos.append((co, re))
        mods, vk = atajos.windows("ctrl+alt+f11")
        p.ver("otro programa registra antes Ctrl+Alt+F11",
              bool(u32.RegisterHotKey(None, 0xB000, mods, vk)), True)
        b.poner_atajos({atajos.SINCRONIZAR: "ctrl+alt+f12", atajos.VENTANA: "ctrl+alt+f11"})
        comun.esperar(lambda: bool(puestos), 5)
        p.ver("al ponerlos, el ocupado se rechaza (ERROR_HOTKEY_ALREADY_REGISTERED)",
              puestos[-1][1] if puestos else None, {atajos.VENTANA: atajos.YA_LA_USA})
        u32.UnregisterHotKey(None, 0xB000)

        notepad = subprocess.Popen(["notepad.exe"])
        try:
            if not comun.esperar(lambda: bloc(u32, notepad.pid) is not None, 15):
                raise comun.Saltada("el Bloc de notas no abre ventana: sin escritorio")
            hwnd = bloc(u32, notepad.pid)
            # Windows solo deja traer una ventana delante a quien recibió la última
            # entrada: un Alt suelto antes es lo de siempre para que lo deje.
            teclas(u32, VK_MENU)
            u32.SetForegroundWindow(hwnd)
            time.sleep(0.5)
            delante = u32.GetForegroundWindow()
            if not delante:
                raise comun.Saltada("sin escritorio interactivo: no hay ventana delante")
            p.nota(f"delante: {'el Bloc de notas' if delante == hwnd else f'otra ({delante})'}")
            teclas(u32, VK_CONTROL, VK_MENU, VK_F12)
            llego = comun.esperar(lambda: bool(pedidas), 5)
            if not llego and delante != hwnd:
                raise comun.Saltada("las teclas generadas no llegan a esta sesión")
            p.ver("Ctrl+Alt+F12 con otro programa delante llega como su petición, como el menú",
                  pedidas, [{"pide": equipo.PIDE_ATAJO, "accion": atajos.SINCRONIZAR}])
            teclas(u32, VK_CONTROL, VK_MENU, VK_F12)
            comun.esperar(lambda: len(pedidas) > 1, 5)
            p.ver("  cada pulsación, una petición", len(pedidas), 2)
            b.poner_atajos({})
            comun.esperar(lambda: len(puestos) > 1, 5)
            teclas(u32, VK_CONTROL, VK_MENU, VK_F12)
            time.sleep(1.0)
            p.ver("soltados, ya no llegan", len(pedidas), 2)
        finally:
            notepad.kill()
