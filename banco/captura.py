"""Captura de una ventana tal como se ve en pantalla, para probar que se pinta.

Es del banco de la interfaz (temporal, ver `banco/LEEME.md`). En una máquina de
GitHub Actions puede no haber escritorio interactivo: una ventana que «se
enseña» sin pintarse daría tiempos que no son los de nadie. `capturar()` guarda
un PNG del rectángulo de la ventana y cuenta los colores distintos: dos o menos
es que no se pintó nada.

En Windows se copia lo que hay en pantalla (`BitBlt` desde el DC del escritorio)
y, aparte, lo que la ventana pinta para sí (`PrintWindow`): si lo primero sale
negro y lo segundo no, la ventana pinta pero no hay escritorio que la componga.
En Linux, `import -window` de ImageMagick.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path


def _png(ruta: Path, ancho: int, alto: int, filas: list[bytes]) -> None:
    """Escribe un PNG RGB de 8 bits con las filas dadas (sin filtro)."""
    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))
    crudo = b"".join(b"\x00" + f for f in filas)
    ruta.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + trozo(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0))
                     + trozo(b"IDAT", zlib.compress(crudo, 6)) + trozo(b"IEND", b""))


def _colores(filas: list[bytes], paso: int = 7) -> int:
    """Cuenta los colores distintos de una muestra de píxeles RGB."""
    vistos = set()
    for y in range(0, len(filas), paso):
        f = filas[y]
        for x in range(0, len(f) - 2, 3 * paso):
            vistos.add(f[x:x + 3])
            if len(vistos) > 4096:
                return len(vistos)
    return len(vistos)


def _windows(hwnd: int, ruta: Path) -> dict:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    dwm = ctypes.WinDLL("dwmapi")
    for f, res, args in (
            (user32.GetDC, wintypes.HDC, [wintypes.HWND]),
            (user32.ReleaseDC, ctypes.c_int, [wintypes.HWND, wintypes.HDC]),
            (user32.GetWindowRect, wintypes.BOOL, [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]),
            (user32.PrintWindow, wintypes.BOOL, [wintypes.HWND, wintypes.HDC, wintypes.UINT]),
            (gdi32.CreateCompatibleDC, wintypes.HDC, [wintypes.HDC]),
            (gdi32.CreateCompatibleBitmap, wintypes.HBITMAP, [wintypes.HDC, ctypes.c_int, ctypes.c_int]),
            (gdi32.SelectObject, wintypes.HGDIOBJ, [wintypes.HDC, wintypes.HGDIOBJ]),
            (gdi32.BitBlt, wintypes.BOOL, [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                                            wintypes.DWORD]),
            (gdi32.GetDIBits, ctypes.c_int, [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                             wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                                             wintypes.UINT]),
            (gdi32.DeleteObject, wintypes.BOOL, [wintypes.HGDIOBJ]),
            (gdi32.DeleteDC, wintypes.BOOL, [wintypes.HDC]),
            (dwm.DwmGetWindowAttribute, ctypes.c_long, [wintypes.HWND, wintypes.DWORD,
                                                         ctypes.c_void_p, wintypes.DWORD])):
        f.restype, f.argtypes = res, args

    rect = wintypes.RECT()
    # DWMWA_EXTENDED_FRAME_BOUNDS (9): el marco visible, sin la sombra.
    if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    ancho, alto = rect.right - rect.left, rect.bottom - rect.top
    if ancho <= 0 or alto <= 0:
        return {"ok": False, "ancho": ancho, "alto": alto, "colores": 0, "motivo": "rectángulo vacío"}

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    def copiar(desde_pantalla: bool) -> list[bytes]:
        pantalla = user32.GetDC(None)
        memoria = gdi32.CreateCompatibleDC(pantalla)
        mapa = gdi32.CreateCompatibleBitmap(pantalla, ancho, alto)
        viejo = gdi32.SelectObject(memoria, mapa)
        try:
            if desde_pantalla:
                # SRCCOPY | CAPTUREBLT: también las ventanas en capas.
                gdi32.BitBlt(memoria, 0, 0, ancho, alto, pantalla, rect.left, rect.top,
                             0x00CC0020 | 0x40000000)
            else:
                user32.PrintWindow(hwnd, memoria, 2)          # PW_RENDERFULLCONTENT
            cab = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), ancho, -alto, 1, 32, 0,
                                   0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(ancho * alto * 4)
            gdi32.SelectObject(memoria, viejo)
            gdi32.GetDIBits(memoria, mapa, 0, alto, buf, ctypes.byref(cab), 0)
        finally:
            gdi32.DeleteObject(mapa)
            gdi32.DeleteDC(memoria)
            user32.ReleaseDC(None, pantalla)
        crudo = buf.raw
        filas = []
        for y in range(alto):
            bgra = crudo[y * ancho * 4:(y + 1) * ancho * 4]
            rgb = bytearray(ancho * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
            filas.append(bytes(rgb))
        return filas

    filas = copiar(True)
    colores = _colores(filas)
    _png(ruta, ancho, alto, filas)
    propia = copiar(False)
    colores_propia = _colores(propia)
    _png(ruta.with_name(ruta.stem + "-printwindow.png"), ancho, alto, propia)
    return {"ok": colores > 2, "ancho": ancho, "alto": alto, "colores": colores,
            "colores_printwindow": colores_propia,
            "motivo": "" if colores > 2 else
            ("la ventana pinta pero la pantalla no la compone" if colores_propia > 2
             else "no se pinta nada")}


def _linux(ventana: int, ruta: Path) -> dict:
    if not shutil.which("import"):
        return {"ok": False, "ancho": 0, "alto": 0, "colores": 0, "motivo": "sin ImageMagick"}
    r = subprocess.run(["import", "-window", str(ventana), f"png:{ruta}"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or not ruta.is_file():
        return {"ok": False, "ancho": 0, "alto": 0, "colores": 0, "motivo": r.stderr.strip()[:200]}
    i = subprocess.run(["identify", "-format", "%w %h %k", str(ruta)],
                       capture_output=True, text=True, timeout=30)
    try:
        ancho, alto, colores = (int(x) for x in i.stdout.split())
    except ValueError:
        return {"ok": False, "ancho": 0, "alto": 0, "colores": 0, "motivo": i.stderr.strip()[:200]}
    return {"ok": colores > 2, "ancho": ancho, "alto": alto, "colores": colores,
            "motivo": "" if colores > 2 else "no se pinta nada"}


def capturar(ventana: int, ruta) -> dict:
    """Guarda en `ruta` (PNG) lo que se ve de la ventana y dice si hay algo pintado.

    Args:
        ventana: El HWND del marco en Windows (Tk: `int(w.wm_frame(), 16)`; Qt:
            `int(w.winId())`), o el id de ventana X en Linux.
        ruta: Dónde dejar el PNG.

    Returns:
        `{"ok", "ancho", "alto", "colores", "motivo"}`; `colores` <= 2 es que no
        se pintó nada. En Windows, además, `colores_printwindow`.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            return _windows(int(ventana), ruta)
        return _linux(int(ventana), ruta)
    except Exception as e:                           # una captura no para el banco
        return {"ok": False, "ancho": 0, "alto": 0, "colores": 0,
                "motivo": f"{type(e).__name__}: {e}"[:200]}


if __name__ == "__main__" and os.environ.get("BANCO_PRUEBA_CAPTURA"):
    # Prueba suelta: una ventana de Tk con dos colores, capturada.
    import tkinter as tk
    raiz = tk.Tk()
    raiz.geometry("300x200+50+50")
    tk.Frame(raiz, background="#2F5DA8", width=150, height=200).pack(side="left")
    tk.Label(raiz, text="banco", background="#FFFFFF").pack(side="left", expand=True, fill="both")
    raiz.update()
    hwnd = int(raiz.wm_frame(), 16) if sys.platform == "win32" else raiz.winfo_id()
    print(capturar(hwnd, sys.argv[1] if len(sys.argv) > 1 else "prueba.png"))
    raiz.destroy()
