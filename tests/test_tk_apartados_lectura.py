#!/usr/bin/env python3
"""Los apartados de «Ajustes» que leen: se pintan primero y leen después.

«Nombre e icono», «Arranque automático», «Versiones» y «Emparejar un móvil»
esperaban en el hilo de Tk a la unidad, a `schtasks`/`systemctl`, al remoto o a
la codificación del QR antes de enseñar nada. Ahora pintan su marco entero con
lo que espera cada uno (la línea de espera, o «Preparando el código…»), lo
dependiente apagado, y leen por `ui.segundo_plano`. Con Tk de verdad y, donde
hace falta, hilos de verdad, se comprueba:

- que cada apartado está entero antes de que llegue la lectura, con lo que
  depende de ella apagado, y que la lectura no corre en el hilo de Tk;
- que al llegar se enciende lo apagado y se pinta lo leído, y que con
  `segundo_plano.en_el_acto` (los tests de pantallas) está entero antes de
  enseñarse, como siempre;
- el tope de tiempo del vigilante: un `schtasks` que no contesta no deja la
  pantalla esperando para siempre, y si por fin llega, lo suyo sustituye a la
  frase;
- «Versiones»: una lectura trae la pareja con sus dos lados, «Purgar» usa ese
  trío y no se puede pulsar mientras se lee otra pareja, y lo que llega tarde
  de una pareja que ya no está elegida no pisa nada; purgar sigue yendo por
  `working()` detrás de su plan y de su confirmación;
- que `tk_llavero` y `tk_renombrar` piden su `Sondeo` y su `Indicador` al
  panel, para que un apartado escondido deje de mirar y de animar;
- que el QR no se lee con `lanzar_sin_repetir` (su tabla de lecturas vivas
  guardaría la clave después de irse el apartado).

El orden del QR (proteger antes de pintar) y su ciclo de vida están en
`test_captura_pantalla.py`.
"""

import gc
import sys
import threading
import time
import weakref
from datetime import datetime
from pathlib import Path

from _harness import Checks, sandbox

c = Checks("apartados de Ajustes que leen después de pintar")

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
    raiz = tk.Tk()
    raiz.withdraw()
except Exception as e:                                   # sin entorno gráfico
    print(f"  (saltado) no hay entorno gráfico: {e}")
    sys.exit(c.report())

from _vista import visibles  # noqa: E402

from common import catalog, model, pairing, store  # noqa: E402
from ui import (qr, segundo_plano, tk_llavero, tk_pairs, tk_qr, tk_renombrar,  # noqa: E402
                tk_versions, tk_volumen, tk_watch, versions_editor, volumen, watch)
from ui import tk as uitk  # noqa: E402

HILO_TK = threading.get_ident()
"""El hilo de Tk: el de este script."""

messagebox.showinfo = lambda *a, **k: None
messagebox.showerror = lambda *a, **k: None
errores: list[str] = []
raiz.report_callback_exception = (
    lambda tipo, valor, _tb: errores.append(f"{tipo.__name__}: {valor}"))

lanzar_real = segundo_plano.lanzar


def nunca(funcion):
    """Un encargo que no se corre jamás: la lectura que no termina."""
    return segundo_plano.Encargo(funcion)


def con_hilos() -> None:
    """Vuelve a los hilos de verdad y olvida las lecturas vivas de antes."""
    segundo_plano.lanzar = lanzar_real
    segundo_plano.olvidar_lecturas()


def sin_llegar() -> None:
    """Hace que ninguna lectura llegue, y olvida las vivas de antes."""
    segundo_plano.lanzar = nunca
    segundo_plano.olvidar_lecturas()


def dar_vueltas(condicion, limite: float = 2.0) -> bool:
    """Mueve el bucle de Tk hasta que se cumpla la condición o pase el límite."""
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        raiz.update()
        if condicion():
            return True
        time.sleep(0.01)
    return False


def abrir(modulo, llamada):
    """Abre un apartado suelto sin esperar a que se cierre y devuelve su ventana."""
    vistas: list = []
    real = modulo.mostrar
    modulo.mostrar = lambda dlg, parent=None: vistas.append(dlg)
    try:
        llamada()
    finally:
        modulo.mostrar = real
    return vistas[-1]


def boton(dlg, texto):
    """Devuelve el botón (o radio) a la vista con ese texto."""
    return next(w for w in visibles(dlg) if w.winfo_class() in ("TButton", "TRadiobutton")
                and str(w.cget("text")) == texto)


def apagado(widget) -> bool:
    """Indica si el control está apagado."""
    return widget.instate(["disabled"])


def textos(dlg) -> list[str]:
    """Devuelve el texto de las etiquetas a la vista."""
    return [str(w.cget("text")) for w in visibles(dlg, "TLabel") if str(w.cget("text"))]


def barras(dlg) -> list:
    """Devuelve las barras de espera a la vista."""
    return visibles(dlg, "TProgressbar")


def en_marcha(barra) -> bool:
    """Indica si Tcl tiene la barra animándose."""
    try:
        barra.tk.eval(f"set ::ttk::progressbar::Timers({barra})")
    except tk.TclError:
        return False
    return True


def imagenes_del_codigo(dlg) -> list:
    """Devuelve las etiquetas con imagen de la tarjeta blanca (el aviso ámbar lleva un icono)."""
    return [w for w in visibles(dlg, "TLabel")
            if str(w.cget("style")) == "Card.TLabel" and str(w.cget("image"))]


def cerrar(dlg) -> None:
    """Destruye la ventana de un caso."""
    dlg.destroy()
    segundo_plano.olvidar_lecturas()


# ---------------------------------------------------------------------------
# «Nombre e icono»
# ---------------------------------------------------------------------------
with sandbox():
    ESTADO = volumen.Estado(Path(model.DEVICE_ROOT), None, "MI PEN", "azul",
                            ".prdrive\\icono-azul.ico", "Mi pen")
    leidos: list = []
    volumen.leer = lambda: leidos.append(threading.get_ident()) or ESTADO

    sin_llegar()
    dlg = abrir(tk_volumen, lambda: tk_volumen.open_dialog(raiz))
    c("«Nombre e icono»: se pinta antes de leer, con la línea de espera y su barra",
      (len(barras(dlg)), en_marcha(barras(dlg)[0]) if barras(dlg) else None),
      (1, True))
    c("  sin leer la unidad (la lectura no llegó a correr)", leidos, [])
    campo = visibles(dlg, "TEntry")[0]
    radios = visibles(dlg, "TRadiobutton")
    c("  el campo del nombre, los iconos y «Guardar» esperan a la lectura",
      (apagado(campo), all(apagado(r) for r in radios), len(radios) >= 7,
       apagado(boton(dlg, "Guardar")), apagado(boton(dlg, "Elegir…"))),
      (True, True, True, True, True))
    c("  y «Cancelar» no espera", apagado(boton(dlg, "Cancelar")), False)
    c("  tiene su título y la explicación",
      "Nombre e icono de la unidad" in textos(dlg), True)
    cerrar(dlg)

    con_hilos()
    dlg = abrir(tk_volumen, lambda: tk_volumen.open_dialog(raiz))
    llego = dar_vueltas(lambda: not apagado(boton(dlg, "Guardar")))
    c("  al llegar se enciende todo", llego, True)
    c("  la unidad se leyó en otro hilo", [h != HILO_TK for h in leidos], [True])
    c("  el nombre y el color elegido son los leídos",
      (visibles(dlg, "TEntry")[0].get(),
       [r.cget("text") for r in visibles(dlg, "TRadiobutton") if r.instate(["selected"])]),
      ("MI PEN", ["Azul"]))
    c("  y la línea de espera se va", barras(dlg), [])
    cerrar(dlg)

    # Una lectura que falla deja la pantalla apagada y lo dice.
    volumen.leer = lambda: (_ for _ in ()).throw(OSError("unidad desaparecida"))
    dlg = abrir(tk_volumen, lambda: tk_volumen.open_dialog(raiz))
    dar_vueltas(lambda: not barras(dlg))
    c("  si la lectura falla: lo dice, sigue apagado y «Cancelar» sirve",
      (any("unidad desaparecida" in t for t in textos(dlg)),
       apagado(boton(dlg, "Guardar")), apagado(boton(dlg, "Cancelar"))),
      (True, True, False))
    cerrar(dlg)

    # Con `en_el_acto` (los tests de pantallas) está entera antes de enseñarse.
    volumen.leer = lambda: ESTADO
    segundo_plano.lanzar = segundo_plano.en_el_acto
    dlg = abrir(tk_volumen, lambda: tk_volumen.open_dialog(raiz))
    c("  con `en_el_acto` está entera antes de enseñarse",
      (barras(dlg), apagado(boton(dlg, "Guardar")), visibles(dlg, "TEntry")[0].get()),
      ([], False, "MI PEN"))
    cerrar(dlg)

    # Guardar usa lo leído y vuelve a leer al rehacerse.
    guardados: list = []
    volumen.guardar = lambda estado, nombre, clave, propio: guardados.append(
        (estado, nombre, clave)) or []
    uitk_working = tk_volumen.working
    tk_volumen.working = lambda parent, titulo, funcion, mensaje="", **k: (True, funcion())
    dlg = abrir(tk_volumen, lambda: tk_volumen.open_dialog(raiz))
    visibles(dlg, "TEntry")[0].delete(0, "end")
    visibles(dlg, "TEntry")[0].insert(0, "OTRO")
    boton(dlg, "Guardar").invoke()
    c("  «Guardar» guarda con lo que se leyó", guardados, [(ESTADO, "OTRO", "azul")])
    tk_volumen.working = uitk_working
    segundo_plano.olvidar_lecturas()

# ---------------------------------------------------------------------------
# «Arranque automático»
# ---------------------------------------------------------------------------
FILAS = [("Registro en el sistema", "activo"), ("Modo", "ui"),
         ("Vigilante", "parado"), ("", "Aviso suelto de penwatch")]
lecturas_vigilante: list = []
tareas = {"estado": None}
watch.log_tail = lambda lines=10: ["linea del diario"]
watch.is_installed = lambda: True
watch.probe_rows = lambda: [("/media/pen", "sin PRDRIVE")]
watch.estado_vigilante = lambda: (lecturas_vigilante.append(threading.get_ident())
                                  or watch.EstadoVigilante(list(FILAS), True))
watch.deteccion = lambda: (lecturas_vigilante.append(threading.get_ident())
                           or [("/media/pen", "sin PRDRIVE")])

with sandbox():
    sin_llegar()
    dlg = abrir(tk_watch, lambda: tk_watch.open_dialog(raiz))
    c("«Arranque automático»: se pinta antes de preguntar al sistema, con su línea de espera",
      (len(barras(dlg)), en_marcha(barras(dlg)[0]) if barras(dlg) else None), (1, True))
    c("  sin preguntarle nada", lecturas_vigilante, [])
    c("  el diario y el botón de instalar no esperan (son ficheros)",
      (any("linea del diario" in t.get("1.0", "end") for t in visibles(dlg, "Text")),
       boton(dlg, "Reinstalar…").winfo_exists()), (True, 1))
    c("  la tarjeta no enseña todavía ninguna fila",
      [t for t in textos(dlg) if t in ("Registro en el sistema", "Vigilante")], [])
    cerrar(dlg)

    con_hilos()
    dlg = abrir(tk_watch, lambda: tk_watch.open_dialog(raiz))
    llego = dar_vueltas(lambda: "Registro en el sistema" in textos(dlg))
    c("  al llegar pinta las filas", llego, True)
    c("  preguntó desde otro hilo", [h != HILO_TK for h in lecturas_vigilante], [True])
    c("  la línea de espera se va y el aviso suelto sale",
      (barras(dlg), "Aviso suelto de penwatch" in textos(dlg)), ([], True))
    lecturas_vigilante.clear()
    boton(dlg, "Detectar el dispositivo").invoke()
    llego = dar_vueltas(lambda: "/media/pen" in textos(dlg))
    c("  «Detectar el dispositivo» también pregunta aparte",
      (llego, [h != HILO_TK for h in lecturas_vigilante]), (True, [True]))
    c("  y al llegar enseña dónde ha buscado", "sin PRDRIVE" in textos(dlg), True)
    cerrar(dlg)

    # El tope de tiempo: un sistema que no contesta no deja esperando para siempre.
    tope_real = watch.TOPE_VIGILANTE_S
    watch.TOPE_VIGILANTE_S = 0.05
    try:
        sin_llegar()
        pedidos: list = []

        def lanzar_guardado(funcion):
            """Un encargo que no corre y que el test puede soltar luego."""
            encargo = segundo_plano.Encargo(funcion)
            pedidos.append(encargo)
            return encargo

        segundo_plano.lanzar = lanzar_guardado
        dlg = abrir(tk_watch, lambda: tk_watch.open_dialog(raiz))
        dicho = dar_vueltas(lambda: any("no ha contestado" in t for t in textos(dlg)))
        c("el tope: con una lectura que no llega, la pantalla dice que no ha contestado",
          dicho, True)
        c("  y la línea de espera se para y se va", (barras(dlg), ), ([], ))
        c("  la fila dice cuántos segundos y qué no se sabe",
          [t for t in textos(dlg) if "no ha contestado" in t],
          ["El sistema no ha contestado en 0.05 s: no se sabe si la tarea está registrada."])
        pedidos[-1].correr()
        llego = dar_vueltas(lambda: "Registro en el sistema" in textos(dlg))
        c("  si la lectura llega después, lo suyo sustituye a la frase",
          (llego, any("no ha contestado" in t for t in textos(dlg))), (True, False))
        cerrar(dlg)

        # Y una lectura que llega a tiempo no deja el temporizador pendiente.
        segundo_plano.lanzar = segundo_plano.en_el_acto
        watch.TOPE_VIGILANTE_S = 0.05
        dlg = abrir(tk_watch, lambda: tk_watch.open_dialog(raiz))
        dar_vueltas(lambda: False, 0.3)
        c("  una lectura que llega a tiempo no deja ninguna frase de «no ha contestado»",
          any("no ha contestado" in t for t in textos(dlg)), False)
        cerrar(dlg)

        # El temporizador se va con el apartado: nada pinta en lo que ya no existe.
        sin_llegar()
        dlg = abrir(tk_watch, lambda: tk_watch.open_dialog(raiz))
        cerrar(dlg)
        errores.clear()
        dar_vueltas(lambda: False, 0.3)
        c("  si se cierra antes del tope, el temporizador no pinta en lo destruido",
          errores, [])
    finally:
        watch.TOPE_VIGILANTE_S = tope_real

    # Con `en_el_acto` está entera antes de enseñarse.
    segundo_plano.lanzar = segundo_plano.en_el_acto
    dlg = abrir(tk_watch, lambda: tk_watch.open_dialog(raiz))
    c("  con `en_el_acto` está entera antes de enseñarse",
      (barras(dlg), "Registro en el sistema" in textos(dlg)), ([], True))
    cerrar(dlg)

# ---------------------------------------------------------------------------
# «Versiones guardadas»
# ---------------------------------------------------------------------------
DOS = {"defaults": {"remote": "nas"},
       "pair": [{"name": "notas", "local": "sync-data/notas", "remote_path": "/R/notas",
                 "mode": "bisync", "versions": True},
                {"name": "fotos", "local": "sync-data/fotos", "remote_path": "/R/fotos",
                 "mode": "bisync", "versions": True}]}
SOLTAR_FOTOS = threading.Event()
lecturas_versiones: list = []


def versiones_de(pair, n):
    """Devuelve `n` versiones viejas de la pareja."""
    return tuple(versions_editor.Version(
        ruta=f"{pair.name}/f{i}~20200101-120000.txt", original=f"f{i}.txt",
        cuando=datetime(2020, 1, 1, 12), tamano=1024) for i in range(n))


def leer_local_falso(pair):
    """Lee la pareja; anota desde qué hilo."""
    lecturas_versiones.append(("local", pair.name, threading.get_ident()))
    return versions_editor.Lado(versions_editor.DISPOSITIVO, str(pair.local_abs), True, "",
                                versiones_de(pair, 2 if pair.name == "notas" else 3))


def leer_remoto_falso(pair):
    """Lee el remoto de la pareja; el de «fotos» espera a que el test lo suelte."""
    lecturas_versiones.append(("remoto", pair.name, threading.get_ident()))
    if pair.name == "fotos":
        SOLTAR_FOTOS.wait(5)
    return versions_editor.Lado(versions_editor.REMOTO, pair.versions_path2, True, "",
                                versiones_de(pair, 4 if pair.name == "notas" else 5))


versions_editor.leer_local = leer_local_falso
versions_editor.leer_remoto = leer_remoto_falso
borrados: list = []
versions_editor.borrar_local = lambda ruta: borrados.append(("local", ruta.name))
versions_editor.borrar_remoto = lambda raiz_remota, rutas: (
    borrados.append(("remoto", len(list(rutas)))) or (True, ""))


def cifras(dlg) -> list[str]:
    """Devuelve lo que dicen las dos cifras de la tarjeta."""
    return [t for t in textos(dlg) if "versiones" in t or t in ("—", "vacío")]


with sandbox():
    cfg = model.parse_config(DOS)
    sin_llegar()
    dlg = abrir(tk_versions, lambda: tk_versions.open_dialog(raiz, cfg))
    c("«Versiones»: se pinta antes de leer, con su línea de espera",
      (len(barras(dlg)), en_marcha(barras(dlg)[0]) if barras(dlg) else None), (1, True))
    c("  los dos lados dicen «—» y «Purgar…» y «Abrir la carpeta» esperan",
      (cifras(dlg), apagado(boton(dlg, "Purgar…")), apagado(boton(dlg, "Abrir la carpeta"))),
      (["—", "—"], True, True))
    c("  sin leer ningún lado", lecturas_versiones, [])
    c("  los botones de pareja y de antigüedad ya están",
      [t for t in ("notas", "fotos", "Más de 30 días") if boton(dlg, t)],
      ["notas", "fotos", "Más de 30 días"])
    cerrar(dlg)

    con_hilos()
    SOLTAR_FOTOS.set()
    dlg = abrir(tk_versions, lambda: tk_versions.open_dialog(raiz, cfg))
    llego = dar_vueltas(lambda: not apagado(boton(dlg, "Purgar…")))
    c("  al llegar enseña los dos lados y enciende los botones",
      (llego, len(cifras(dlg)), apagado(boton(dlg, "Abrir la carpeta"))),
      (True, 2, False))
    c("  los dos lados se leyeron fuera del hilo de Tk",
      sorted({(lado, h != HILO_TK) for lado, _p, h in lecturas_versiones}),
      [("local", True), ("remoto", True)])
    c("  la línea de espera se va", barras(dlg), [])
    cerrar(dlg)

    # Elegir otra pareja mientras se lee: «Purgar» espera, y lo que llega tarde
    # de la pareja anterior no pisa a la que se eligió después.
    SOLTAR_FOTOS.clear()
    lecturas_versiones.clear()
    dlg = abrir(tk_versions, lambda: tk_versions.open_dialog(raiz, cfg))
    dar_vueltas(lambda: not apagado(boton(dlg, "Purgar…")))
    boton(dlg, "fotos").invoke()
    dar_dentro = dar_vueltas(lambda: ("remoto", "fotos") in
                             [(a, b) for a, b, _h in lecturas_versiones])
    c("«Versiones»: elegir otra pareja relee, y mientras tanto «Purgar…» espera",
      (dar_dentro, apagado(boton(dlg, "Purgar…")), apagado(boton(dlg, "Abrir la carpeta")),
       cifras(dlg)), (True, True, True, ["—", "—"]))
    boton(dlg, "notas").invoke()
    dar_vueltas(lambda: not apagado(boton(dlg, "Purgar…")))
    c("  volver a «notas» enseña lo de «notas»",
      [t for t in cifras(dlg) if "versiones" in t],
      [f"2 versiones · 2.0 KiB", f"4 versiones · 4.0 KiB"])
    SOLTAR_FOTOS.set()
    dar_vueltas(lambda: False, 0.4)
    c("  y la lectura de «fotos», que llega tarde, no pisa lo de «notas»",
      [t for t in cifras(dlg) if "versiones" in t],
      [f"2 versiones · 2.0 KiB", f"4 versiones · 4.0 KiB"])
    cerrar(dlg)

    # «Purgar» usa la pareja y los dos lados de la misma lectura, detrás de su
    # plan y de su confirmación, y por `working()`.
    segundo_plano.lanzar = segundo_plano.en_el_acto
    planes: list = []
    plan_real = versions_editor.plan_purgar

    def plan_anotado(pair, local, remoto, corte):
        """Apunta con qué se pide el plan y devuelve el de verdad."""
        planes.append((pair.name, len(local.versiones), len(remoto.versiones)))
        return plan_real(pair, local, remoto, corte)

    versions_editor.plan_purgar = plan_anotado
    ejecutados: list = []
    confirmaciones: list = []
    confirmar_real, working_real = tk_pairs.confirmar_plan, tk_versions.working
    tk_pairs.confirmar_plan = lambda parent, plan, titulo, nota, **k: (
        confirmaciones.append(plan.pair_name) or respuesta["si"])
    tk_versions.working = lambda parent, titulo, funcion, mensaje="", **k: (
        ejecutados.append(mensaje), (True, funcion()))[1]
    respuesta = {"si": False}
    try:
        dlg = abrir(tk_versions, lambda: tk_versions.open_dialog(raiz, cfg))
        boton(dlg, "fotos").invoke()
        boton(dlg, "Purgar…").invoke()
        c("«Purgar…» pide el plan con la pareja elegida y sus dos lados",
          planes, [("fotos", 3, 5)])
        c("  lo enseña para confirmar, y sin confirmar no borra ni usa `working()`",
          (confirmaciones, ejecutados, borrados), (["fotos"], [], []))
        respuesta["si"] = True
        lecturas_versiones.clear()
        boton(dlg, "Purgar…").invoke()
        c("  confirmado, borra por `working()` los de los dos lados",
          (ejecutados, sorted(set(b[0] for b in borrados))),
          (["Purgando las versiones…"], ["local", "remoto"]))
        c("  y después vuelve a leer la pareja",
          sorted({(lado, p) for lado, p, _h in lecturas_versiones}),
          [("local", "fotos"), ("remoto", "fotos")])
        cerrar(dlg)
    finally:
        tk_pairs.confirmar_plan, tk_versions.working = confirmar_real, working_real
        versions_editor.plan_purgar = plan_real

    # Una lectura que revienta deja los dos lados como no disponibles, sin purgar.
    versions_editor.leer_local = lambda pair: (_ for _ in ()).throw(OSError("pen fuera"))
    dlg = abrir(tk_versions, lambda: tk_versions.open_dialog(raiz, cfg))
    c("  si la lectura falla, lo dice en los dos lados y «Purgar…» sigue apagado",
      (cifras(dlg), apagado(boton(dlg, "Purgar…"))), (["—", "—"], True))
    cerrar(dlg)
    versions_editor.leer_local = leer_local_falso

# ---------------------------------------------------------------------------
# «Emparejar un móvil»: se lee fuera del hilo de Tk y sin `lanzar_sin_repetir`
# ---------------------------------------------------------------------------
LLAVE = (b"-----BEGIN OPENSSH PRIVATE KEY-----\n" + b"b3BlbnNza" * 40
         + b"\n-----END OPENSSH PRIVATE KEY-----\n")
SECRETO = "b3BlbnNzab3BlbnNza"
hilos_qr: list = []
construir_real = pairing.construir
codificar_real = qr.codificar


def construir_anotado(raw=None, app_dir=None):
    """Monta la carga de mentira y apunta desde qué hilo."""
    hilos_qr.append(("construir", threading.get_ident()))
    return pairing.dumps("nas", {"type": "sftp", "host": "nas.example.org", "port": "22",
                                 "user": "pere"}, key_name="id_ed25519",
                         catalog_path="/prdrive-catalog/pairs.toml", private_key=LLAVE)


def codificar_anotado(texto, nivel="M", version=None):
    """Codifica de verdad y apunta desde qué hilo."""
    hilos_qr.append(("codificar", threading.get_ident()))
    return codificar_real(texto, nivel, version)


pairing.construir = construir_anotado
qr.codificar = codificar_anotado
proteger_real = tk_qr.proteger_de_capturas
llamadas_proteger: list = []
tk_qr.proteger_de_capturas = lambda dlg: llamadas_proteger.append(1) or 0
try:
    sin_llegar()
    dlg = abrir(tk_qr, lambda: tk_qr.open_dialog(raiz, {}))
    c("«Emparejar un móvil»: se pinta antes de preparar el código, con «Preparando el código…»",
      ("Preparando el código…" in textos(dlg), hilos_qr, llamadas_proteger),
      (True, [], []))
    c("  con el aviso ámbar y su botón, y sin ninguna imagen del código",
      (tk_qr.AVISO.partition("\n")[2] in textos(dlg), boton(dlg, "Cerrar").winfo_exists(),
       imagenes_del_codigo(dlg)), (True, 1, []))
    cerrar(dlg)

    con_hilos()
    dlg = abrir(tk_qr, lambda: tk_qr.open_dialog(raiz, {}))
    llego = dar_vueltas(lambda: bool(imagenes_del_codigo(dlg)))
    c("  al llegar pinta el código", llego, True)
    c("  la carga se monta y se codifica fuera del hilo de Tk",
      sorted((q, h != HILO_TK) for q, h in hilos_qr),
      [("codificar", True), ("construir", True)])
    c("  «Preparando el código…» se va y sale la línea de la versión",
      ("Preparando el código…" in textos(dlg),
       any(t.startswith("versión ") for t in textos(dlg))), (False, True))
    c("  protegió la ventana al llegar el código", llamadas_proteger, [1])
    c("  y no guarda la lectura: ni en la tabla de `lanzar_sin_repetir` ni en un texto",
      (segundo_plano._EN_VUELO, [t for t in textos(dlg) if SECRETO in t]), ({}, []))
    cerrar(dlg)

    # El `Encargo` (y con él el código) se suelta en cuanto llega.
    referencias: list = []

    def lanzar_vigilado(funcion):
        """El `lanzar` de verdad, apuntando una referencia débil al encargo."""
        encargo = lanzar_real(funcion)
        referencias.append(weakref.ref(encargo))
        return encargo

    segundo_plano.lanzar = lanzar_vigilado
    dlg = abrir(tk_qr, lambda: tk_qr.open_dialog(raiz, {}))
    dar_vueltas(lambda: bool(imagenes_del_codigo(dlg)))
    gc.collect()
    c("  llegado el código, nadie conserva el encargo que lo trajo",
      [r() for r in referencias], [None])
    cerrar(dlg)

    # Sin conexión que enseñar: lo dice, y no protege nada.
    llamadas_proteger.clear()
    pairing.construir = lambda raw=None, app_dir=None: (_ for _ in ()).throw(
        pairing.PairingError("Este dispositivo no tiene conexión que compartir"))
    con_hilos()
    dlg = abrir(tk_qr, lambda: tk_qr.open_dialog(raiz, {}))
    dar_vueltas(lambda: "Preparando el código…" not in textos(dlg))
    c("  un dispositivo sin conexión lo dice al llegar la lectura, y no protege nada",
      ("Este dispositivo no tiene conexión que compartir" in textos(dlg),
       llamadas_proteger, imagenes_del_codigo(dlg)), (True, [], []))
    cerrar(dlg)
    pairing.construir = construir_anotado

    c("`preparar_codigo` devuelve el código y no el texto de la carga",
      type(tk_qr.preparar_codigo({})).__name__, "Codigo")

    def no_cabe(texto, nivel="M", version=None):
        """Un `qr.codificar` al que la carga no le cabe."""
        datos = texto.encode("utf-8")        # como el de verdad: la carga en sus variables
        raise qr.QRError(f"{len(datos)} bytes no caben")

    qr.codificar = no_cabe
    try:
        tk_qr.preparar_codigo({})
    except qr.QRError as e:
        marcos = []
        traza = e.__traceback__
        while traza is not None:
            marcos.append(traza.tb_frame.f_code.co_name)
            traza = traza.tb_next
        c("  si no cabe, lanza `QRError` con su mensaje y sin arrastrar los marcos del "
          "codificador, que llevan la carga",
          (str(e).endswith("bytes no caben"), "no_cabe" in marcos,
           marcos[-1], e.__context__, e.__cause__),
          (True, False, "preparar_codigo", None, None))
    else:
        c("  si no cabe, lanza `QRError`", "no lanzó", "QRError")
    finally:
        qr.codificar = codificar_anotado
finally:
    pairing.construir = construir_real
    qr.codificar = codificar_real
    tk_qr.proteger_de_capturas = proteger_real

# ---------------------------------------------------------------------------
# Los apartados escondidos dejan de mirar y de animar: `panel.sondeo()`/`indicador()`
# ---------------------------------------------------------------------------


def panel_suelto(titulo):
    """Devuelve `(ventana, panel)` para dibujar un apartado como dentro de «Ajustes»."""
    dlg = uitk.modal(raiz, titulo)
    marco = uitk.cuerpo_visible(dlg, padding=(0, 0, 0, 0))
    marco.columnconfigure(0, weight=1)
    return dlg, uitk.Panel(dlg, marco, incrustado=True)


def pendientes() -> tuple:
    """Los `after` que Tk tiene pendientes."""
    return raiz.tk.splitlist(raiz.tk.call("after", "info"))


with sandbox():
    sin_llegar()
    from ui import catalog_editor  # noqa: E402
    viejo = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/pairs.toml"}}
    store.write_json(catalog.cache_meta(), {"endpoint": "nas:/prdrive-catalog/pairs.toml"})
    llavero_raw = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/remote.toml"},
                   "pair": [{"name": "notas", "local": "sync-data/notas",
                             "remote_path": "/R/notas"}]}
    segundo_plano.lanzar = nunca
    volumen.leer = lambda: ESTADO
    versions_editor.leer_local = leer_local_falso
    versions_editor.leer_remoto = leer_remoto_falso
    for nombre, construir in (("«Catálogo del remoto»",
                               lambda p: tk_renombrar.construir(p, dict(viejo))),
                              ("«Llavero»",
                               lambda p: tk_llavero.construir_ajustes(p, dict(llavero_raw))),
                              ("«Nombre e icono»", tk_volumen.construir),
                              ("«Arranque automático»", tk_watch.construir),
                              ("«Versiones»",
                               lambda p: tk_versions.construir(p, model.parse_config(DOS)))):
        dlg, panel = panel_suelto(nombre)
        construir(panel)
        barra = visibles(dlg, "TProgressbar")[0]
        sondeo = dlg.sondeo
        c(f"{nombre}: espera con su sondeo y su barra en marcha",
          (sondeo._id in pendientes(), en_marcha(barra)), (True, True))
        panel.ocultado()
        c("  escondido, no mira ni anima, y no pierde lo que espera",
          (sondeo._id, sondeo.esperando, en_marcha(barra)), (None, True, False))
        panel.mostrado()
        c("  al volver a enseñarse, mira y anima otra vez",
          (sondeo._id in pendientes(), en_marcha(barra)), (True, True))
        dlg.destroy()

sys.exit(c.report())
