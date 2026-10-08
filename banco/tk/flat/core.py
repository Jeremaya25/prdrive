"""Lo común del prototipo `tk-flat`: arranque de Tk (Xft), letra, tokens, escala, iconos y datos.

Todo lo de aquí es lo MÍNIMO que cualquier frontend Tk de prdrive necesita antes de pintar, escrito sin
importar el paquete `ui/` del repo (que arrastra `common/` entero). Se mide por separado en `detail`.

Portado a Windows: la densidad de pantalla (`utiles.nitidez()`, copia de `ui.theme.nitidez()`) y el
velo de DWM al enseñar (`utiles.ensenar()`, copia de `ui.tk.ensenar()`) son los de la aplicación real; la
letra propia se registra con `AddFontResourceExW` (Windows) o fontconfig (Linux), como `ui.theme`.
"""
import json
import os
import sys
import time
from pathlib import Path

import utiles

T_PROC = time.time()            # cuando el intérprete llegó aquí (el harness da BENCH_T0, el de antes)
QUIETA = Path(__file__).resolve().parent
TIEMPOS: dict[str, float] = {}


def marca(nombre: str, t0: float) -> None:
    TIEMPOS[nombre] = round((time.perf_counter() - t0) * 1000, 2)


# ---------------------------------------------------------------------------------------------- arranque
def tk_con_xft() -> bool:
    """Carga el Tk con Xft del runtime antes que el de serie (como `ui.tk_con_xft()`). Solo Linux."""
    return utiles.tk_con_xft()


def cargar_fuentes() -> bool:
    """Registra Noto Sans privada del proceso (fontconfig en Linux, GDI en Windows). Sin instalar nada.

    La letra es la de `ui/fuentes/` del árbol de la 0.7.1 (`BANCO_FUENTES`), la misma que lleva la
    aplicación; si no está, la copia que pudiera haber junto a este fichero."""
    carpeta = Path(os.environ.get("BANCO_FUENTES") or QUIETA / "fuentes")
    ficheros = sorted(carpeta.glob("*.ttf"))
    if not ficheros:
        return False
    try:
        import ctypes
        if sys.platform == "win32":
            gdi = ctypes.windll.gdi32
            gdi.AddFontResourceExW.argtypes = (ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p)
            return all([gdi.AddFontResourceExW(str(f), 0x10, None) for f in ficheros])  # FR_PRIVATE
        try:                     # el nombre directo: `find_library` lanza `ldconfig` y tarda
            fc = ctypes.CDLL("libfontconfig.so.1")
        except OSError:
            import ctypes.util
            fc = ctypes.CDLL(ctypes.util.find_library("fontconfig"))
        fc.FcConfigAppFontAddFile.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
        return all([fc.FcConfigAppFontAddFile(None, bytes(f)) for f in ficheros])
    except Exception:
        return False


_t = time.perf_counter()
XFT = tk_con_xft()
marca("xft_preload", _t)
_t = time.perf_counter()
FUENTES_OK = cargar_fuentes()
marca("fuentes", _t)
_t = time.perf_counter()
import tkinter as tk  # noqa: E402
from tkinter import font as tkfont  # noqa: E402
marca("import_tkinter", _t)

from tokens import CLARO, OSCURO  # noqa: E402


# ---------------------------------------------------------------------------------------------- contexto
class Ctx:
    """Tema + escala + letra + iconos de un intérprete.

    `u` es lo que mide un píxel de DISEÑO (96 ppp) en píxeles de esta pantalla: `tk scaling` / (96/72).
    Todo el diseño se da en píxeles de diseño y pasa por `S()`, como `theme.medida()` hace con puntos.
    """

    def __init__(self, raiz, tema: str):
        self.raiz = raiz
        self.tema = tema
        th = OSCURO if tema == "oscuro" else CLARO
        self.th = type("Tema", (), th)             # ctx.th.PAPEL ...
        self.u = float(raiz.tk.call("tk", "scaling")) * 72 / 96
        self.cubo = min((1.0, 1.5, 2.0), key=lambda c: abs(c - self.u))
        self.dir_iconos = QUIETA / "assets" / tema / str(self.cubo)
        self._img: dict[str, tk.PhotoImage] = {}
        fam = set(tkfont.families(raiz))
        self.xft_real = "Noto Sans" in fam
        self.f_texto = next((f for f in ("Noto Sans", "Segoe UI", "DejaVu Sans") if f in fam), "TkDefaultFont")
        self.f_fuerte = "Noto Sans SemiBold" if self.f_texto == "Noto Sans" and FUENTES_OK else self.f_texto
        self.f_mono = next((f for f in ("Noto Sans Mono", "Consolas", "DejaVu Sans Mono") if f in fam), "TkFixedFont")
        # Los roles de theme.fuente(), en puntos.
        self.fuentes = {
            "titulo": (self.f_fuerte, 16), "seccion": (self.f_fuerte, 11),
            "rotulo": (self.f_texto, 8, "bold"), "fuerte": (self.f_fuerte, 10),
            "pista": (self.f_texto, 9), "mono": (self.f_mono, 9),
            "mono_pequena": (self.f_mono, 8), "texto": (self.f_texto, 10),
        }
        self._medidas: dict[str, tkfont.Font] = {}

    def S(self, px: float) -> int:
        """Píxeles de diseño -> píxeles de pantalla."""
        return int(round(px * self.u))

    def medir(self, rol: str, texto: str) -> int:
        f = self._medidas.get(rol)
        if f is None:
            f = self._medidas[rol] = tkfont.Font(root=self.raiz, font=self.fuentes[rol])
        return f.measure(texto)

    def linea(self, rol: str) -> int:
        f = self._medidas.get(rol)
        if f is None:
            f = self._medidas[rol] = tkfont.Font(root=self.raiz, font=self.fuentes[rol])
        return f.metrics("linespace")

    def icono(self, nombre: str, margen: float = 0):
        """El PNG horneado de ese icono para este tema y cubo de escala (None si falta).

        `margen` (px de diseño) añade un hueco transparente a la derecha: el de un icono que va delante de un
        texto en un widget que no sabe separarlos (tk.Label, tk.Checkbutton). Se copia, no se vuelve a hornear."""
        clave = nombre if not margen else f"{nombre}@{margen}"
        img = self._img.get(clave)
        if img is None:
            try:
                img = tk.PhotoImage(master=self.raiz, file=str(self.dir_iconos / f"{nombre}.png"))
            except tk.TclError:
                return None
            if margen:
                ancho, alto = img.width(), img.height()
                grande = tk.PhotoImage(master=self.raiz, width=ancho + self.S(margen), height=alto)
                grande.tk.call(grande, "copy", img)
                img = grande
            self._img[clave] = img
        return img


def rotulo(texto: str) -> str:
    """Un rótulo de sección: mayúsculas y letras separadas (como `theme.rotulo()`)."""
    return "   ".join(" ".join(p) for p in texto.upper().split())


# ---------------------------------------------------------------------------------------------- datos
class Pareja:
    __slots__ = ("name", "local", "remote_path", "mode", "estado", "en_pen")

    def __init__(self, name, local, remote_path, mode, estado, en_pen):
        self.name, self.local, self.remote_path, self.mode = name, local, remote_path, mode
        self.estado, self.en_pen = estado, en_pen


TONO_DE = {"requiere resync": "aviso", "en uso": "ok", "espejo": "peligro"}


def cargar_datos():
    """Lee el config del dispositivo de muestra (TOML) y su estado (JSON), como lo haría la ventana."""
    import tomllib
    raiz = QUIETA / "fixture"
    cfg = tomllib.loads((raiz / "parejas.toml").read_text(encoding="utf-8"))
    est = json.loads((raiz / "state.json").read_text(encoding="utf-8"))
    if sys.platform == "win32":      # solo es un rótulo: la ruta que enseña la ventana
        est["carpeta"] = "E:\\prdrive-ref-q4s4cbfn"
    en_pen = set(cfg.get("daemon", {}).get("pairs", []))
    parejas = [Pareja(p["name"], p["local"], p["remote_path"], p.get("mode", "bisync"),
                      est["estado"].get(p["name"], "en uso"), True) for p in cfg["pair"]]
    return type("Datos", (), dict(cfg=cfg, parejas=parejas, remoto=cfg["defaults"]["remote"],
                                  en_servicio=en_pen, **{k: v for k, v in est.items() if k != "estado"}))


def rss_mb():
    return utiles.rss_mb()


def contar_widgets(raiz) -> int:
    n, pila = 0, [raiz]
    while pila:
        w = pila.pop()
        for h in w.winfo_children():
            n += 1
            pila.append(h)
    return n


def foto(ventana, destino: str) -> dict:
    """Captura una ventana tal como se ve en pantalla (`banco/captura.py`). Devuelve su informe."""
    return utiles.capturar_ventana(ventana, destino)
