"""Hijo de la medida de R7: rehacer una ventana frente a esconderla y enseñarla otra vez.

TEMPORAL, como todo `etapa2_*`: lo borra la tarea 15 de la etapa 2.

    python etapa2_reabrir.py VENTANA        (por `entrada.py etapa2_reabrir VENTANA`)

`VENTANA` es `parejas`, `ajustes` o `pasada`. Corre la ventana principal real del
dispositivo de muestra (`etapa2_marco.correr`) y, con el árbol de verdad, mide:

- `abrir-1`: abrirla por primera vez (en frío);
- `abrir-2`: cerrarla (destruirla) y abrirla otra vez: se rehace entera;
- `abrir-3` y `reabrir-oculta`: abrirla una tercera vez y, en lugar de destruirla,
  esconderla (`withdraw`, soltando la captura) y enseñarla de nuevo: `ui.tk.ensenar`,
  `grab_set` y, si la pantalla la tiene (las tareas 9 y 10 se la dan), `aplicar()`,
  que la deja como una abierta de nuevo. Es lo que cuesta volver a verla si no se
  destruye;
- `cerrar-destruir` y `cerrar-ocultar`: lo que cuesta cerrarla de cada manera;
- `proceso` (solo la pasada): lo que cuesta lanzar el proceso de una pasada, que
  `reabrir-oculta` no cuenta y una ventana de la pasada escondida tendría que pagar.

Cada medida va de la orden (el clic, o la llamada) a que la ventana está pintada
y enseñada. «Parejas» pide el catálogo al remoto en cuanto se abre y, al llegar,
repinta: `common.catalog.load` espera a un `Event` que el hijo tiene sin poner
mientras mide `abrir-1`, `abrir-2` y `reabrir-oculta` (y alrededor de
`aplicar()`) y que suelta DESPUÉS de cada medida, destruida ya la ventana o
medida la reapertura, para que esa llegada no caiga dentro de ninguna de ellas.

La ventana de la pasada se prueba aparte, sin el botón: `output_window()` con una
orden que no hace nada, y esconderla es limpiar su `Text` y volver a enseñarla.
"""

from __future__ import annotations

import subprocess
import sys
import time

import etapa2_marco as marco
from etapa2_marco import ms, record

BOTONES = {"parejas": ("Parejas…", "Parejas"), "ajustes": ("Ajustes…", "Ajustes")}
"""El texto del botón de la ventana principal que abre cada ventana."""
GUARDADA: dict = {}
"""La ventana que se escondió en lugar de destruirla (`dlg`)."""
ESPERA_PASADA = 10.0
"""Segundos que se espera a que acabe la orden de la pasada."""
VENTANA: list[str] = []
"""La ventana que se mide (`parejas`, `ajustes` o `pasada`); `correr()` cambia `sys.argv`."""


def _drenar(raiz) -> None:
    """Procesa lo pendiente fuera de toda medida: lo que dejó una ventana al cerrarse."""
    raiz.update()


# ------------------------------------------------------------------ parejas y ajustes
def pulsar(raiz, ventana: str, etiqueta: str, ocultar: bool = False) -> bool:
    """Pulsa el botón de una ventana y apunta lo que tarda en estar enseñada.

    El botón se busca cada vez: al cerrar «Ajustes» la ventana principal se
    rehace y el de antes ya no existe.

    Con `ocultar`, la ventana no se destruye al medirla: se esconde y se guarda
    en `GUARDADA`, y el catálogo se sigue reteniendo (lo suelta quien mide la
    reapertura). Sin él se destruye y se suelta el catálogo después.

    Returns:
        Si había botón que pulsar.
    """
    marco.retener_catalogo()
    _drenar(raiz)
    boton = marco.find_button(raiz, *BOTONES[ventana])
    if boton is None:
        marco.NOTES["error"] = f"no hay botón «{BOTONES[ventana][0]}»"
        return False
    t0 = time.perf_counter()

    def al_mostrar(dlg, hora) -> bool:
        record(etiqueta, ms(t0, hora), widgets=marco.contar(dlg))
        t1 = time.perf_counter()
        if ocultar:
            dlg.grab_release()
            dlg.withdraw()
            raiz.update()
            record("cerrar-ocultar", ms(t1, time.perf_counter()))
            GUARDADA["dlg"] = dlg
        else:
            dlg.destroy()
            raiz.update()
            record("cerrar-destruir", ms(t1, time.perf_counter()))
            marco.soltar_catalogo()
        return True

    marco.HOOK["al_mostrar"] = al_mostrar
    boton.invoke()
    return True


def reabrir(raiz, dlg, etiqueta: str) -> None:
    """Enseña de nuevo la ventana escondida y apunta lo que tarda en estar pintada."""
    import tkinter as tk
    from ui import tk as uitk
    _drenar(raiz)
    t0 = time.perf_counter()
    uitk.ensenar(dlg)
    dlg.update_idletasks()
    try:
        dlg.grab_set()
    except tk.TclError:
        pass
    aplicar = getattr(dlg, "aplicar", None)
    if aplicar is not None:
        aplicar()
    dlg.update()
    record(etiqueta, ms(t0, time.perf_counter()), aplicar=aplicar is not None,
           widgets=marco.contar(dlg))
    marco.soltar_catalogo()
    dlg.destroy()
    raiz.update()


def medir_dialogo(raiz, ventana: str) -> None:
    if not (pulsar(raiz, ventana, "abrir-1") and pulsar(raiz, ventana, "abrir-2")
            and pulsar(raiz, ventana, "abrir-3", ocultar=True)):
        return
    if "dlg" not in GUARDADA:
        marco.NOTES["error"] = "la ventana no llegó a esconderse"
        return
    reabrir(raiz, GUARDADA.pop("dlg"), "reabrir-oculta")


# ---------------------------------------------------------------------------- pasada
def lanzar_pasada(raiz):
    """Abre la ventana de una pasada que no hace nada; devuelve `(ventana, ms)`.

    Espera a que la orden acabe y su veredicto esté en el título: así una
    ventana que se cierra después no corta un proceso a medias.
    """
    from ui import tk as uitk
    antes = {str(w) for w in raiz.winfo_children()}
    t0 = time.perf_counter()
    uitk.output_window("Prueba", [sys.executable, "-c", "pass"], parent=raiz, modal=False)
    ventana = next(w for w in raiz.winfo_children() if str(w) not in antes)
    ventana.update()
    t1 = time.perf_counter()
    limite = time.time() + ESPERA_PASADA
    while time.time() < limite and not ventana.title().endswith("OK"):
        raiz.update()
        time.sleep(0.005)
    return ventana, ms(t0, t1)


def medir_pasada(raiz) -> None:
    from ui import tk as uitk
    for etiqueta in ("abrir-1", "abrir-2"):
        _drenar(raiz)
        ventana, valor = lanzar_pasada(raiz)
        record(etiqueta, valor, widgets=marco.contar(ventana))
        t0 = time.perf_counter()
        ventana.destroy()
        raiz.update()
        record("cerrar-destruir", ms(t0, time.perf_counter()))
    _drenar(raiz)
    ventana, valor = lanzar_pasada(raiz)
    record("abrir-3", valor, widgets=marco.contar(ventana))
    t0 = time.perf_counter()
    ventana.withdraw()
    raiz.update()
    record("cerrar-ocultar", ms(t0, time.perf_counter()))
    texto = next((w for w in marco.walk(ventana) if w.winfo_class() == "Text"), None)
    if texto is None:
        marco.NOTES["error"] = "la ventana de la pasada no tiene Text"
        return
    t0 = time.perf_counter()
    texto.configure(state="normal")
    texto.delete("1.0", "end")
    texto.configure(state="disabled")
    uitk.ensenar(ventana)
    ventana.update()
    record("reabrir-oculta", ms(t0, time.perf_counter()), widgets=marco.contar(ventana))
    ventana.destroy()
    raiz.update()
    # Lo que no cuenta el reenseñado y una pasada sí tendría que pagar.
    t0 = time.perf_counter()
    proceso = subprocess.Popen([sys.executable, "-c", "pass"], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    record("proceso", ms(t0, time.perf_counter()))
    proceso.communicate()


def sonda(raiz) -> None:
    ventana = VENTANA[0]
    if ventana == "pasada":
        medir_pasada(raiz)
    else:
        medir_dialogo(raiz, ventana)
    marco.NOTES["ventana"] = ventana


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("parejas", "ajustes", "pasada"):
        raise SystemExit("uso: etapa2_reabrir.py parejas|ajustes|pasada")
    VENTANA.append(sys.argv[1])
    marco.correr(sonda)


if __name__ == "__main__":
    main()
