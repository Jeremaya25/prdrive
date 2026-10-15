#!/usr/bin/env python3
"""Los atajos de teclado globales: la mitad que decide (`ui/atajos.py`), sin Tk ni sistema.

Cómo se lee y se escribe una combinación, qué necesita cada sistema, cuál vale,
sobre qué unidad actúa un atajo (la última usada; si no, la última conectada),
qué peticiones del buzón hace cada acción y qué aviso da, lo que la ventana va
viendo mientras graba, y cómo se guardan en `agente.json` (ninguno de fábrica).
"""

from __future__ import annotations

import sys

from _harness import Checks

from common import equipo
from ui import atajos as a

c = Checks("atajos de teclado: la decisión")

# --- leer, escribir, enseñar
c("se lee en cualquier orden y con los nombres en español", a.normal("Mayús+ALT+control+s"),
  "ctrl+alt+shift+s")
c("  y con «Win», «Súper» o «logo» para la tecla del logotipo",
  {a.normal(f"{m}+ctrl+1") for m in ("Win", "súper", "logo", "super")}, {"ctrl+super+1"})
c("  las teclas con nombre, con su alias", [a.normal("ctrl+Supr"), a.normal("alt+RePág"),
                                            a.normal("ctrl+F12"), a.normal("ctrl+espacio")],
  ["ctrl+delete", "alt+pageup", "ctrl+f12", "ctrl+space"])
c("  lo que no se entiende es «»",
  [a.normal(x) for x in ("", "ctrl+", "hiper+s", "ctrl+ñ", "ctrl+alt+f25", None, 7)],
  ["", "", "", "", "", "", ""])
c("se enseña con los nombres del teclado: Win en Windows",
  a.texto("ctrl+shift+super+s", True), "Ctrl+Mayús+Win+S")
c("  y Súper en Linux", a.texto("super+alt+pagedown", False), "Alt+Súper+AvPág")
c("  sin combinación, nada", a.texto("", True), "")

# --- lo que necesita cada sistema
c("Windows: MOD_CONTROL|MOD_ALT|MOD_NOREPEAT y la tecla virtual de la S",
  a.windows("ctrl+alt+s"), (0x2 | 0x1 | 0x4000, 0x53))
c("  F1 es VK_F1 y F24 VK_F24; Win es MOD_WIN, Mayús MOD_SHIFT",
  (a.windows("super+f1"), a.windows("shift+ctrl+f24")[1]), ((0x8 | 0x4000, 0x70), 0x87))
c("  la flecha arriba y el espacio", (a.windows("alt+up")[1], a.windows("alt+space")[1]),
  (0x26, 0x20))
c("X11: ControlMask|Mod1Mask y el keysym en minúscula", a.x11("ctrl+alt+s"), (0x4 | 0x8, "s"))
c("  Súper es Mod4 y Mayús ShiftMask", a.x11("super+shift+f5"), (0x40 | 0x1, "F5"))
c("  y se agarra también con el bloqueo de mayúsculas y el numérico",
  sorted(a.BLOQUEOS_X11), [0, 0x2, 0x10, 0x12])
c("  el estado de un KeyPress se compara sin los bloqueos",
  a.de_x11(0x4 | 0x8 | 0x2 | 0x10 | 0x2000), 0x4 | 0x8)
c("portal: el formato «shortcuts» de freedesktop",
  [a.portal("ctrl+alt+s"), a.portal("super+shift+pageup")],
  ["CTRL+ALT+s", "SHIFT+LOGO+Prior"])
for funcion in (a.windows, a.x11, a.portal):
    try:
        funcion("hola")
        c(f"{funcion.__name__}: lo ilegible lanza", False, True)
    except ValueError:
        c(f"{funcion.__name__}: lo ilegible lanza ValueError", True, True)

# --- qué vale
c("vale con Ctrl, con Alt o con el logotipo",
  [a.problema(a.leer(x)) for x in ("ctrl+s", "alt+1", "super+f3", "ctrl+shift+s")],
  [None, None, None, None])
c("  sin ninguno de los tres no: dejaría de escribirse esa tecla",
  "Ctrl, Alt o la tecla del logotipo" in (a.problema(a.leer("shift+s")) or ""), True)
c("  ni una tecla sola", a.problema(a.Combinacion(frozenset(), "f5")) is not None, True)
c("  sin tecla, que falta", "Falta la tecla" in a.problema(a.Combinacion(frozenset({a.CTRL}))),
  True)
c("  una tecla que no está en la tabla, que no vale",
  "no vale" in a.problema(a.Combinacion(frozenset({a.CTRL}), "?exclam")), True)

# --- lo que dice el sistema
c("Windows: ERROR_HOTKEY_ALREADY_REGISTERED es que otro la usa", a.motivo_windows(1409),
  a.YA_LA_USA)
c("  otro error, con su número", "error 5" in a.motivo_windows(5), True)
titulo, texto_ = a.aviso_de_rechazo(a.SINCRONIZAR, "ctrl+alt+s", a.YA_LA_USA, True)
c("el aviso de un atajo rechazado dice la combinación, la acción y qué hacer",
  ("Ctrl+Alt+S" in titulo, "«Sincronizar ahora»" in texto_, "Se queda sin atajo" in texto_),
  (True, True, True))

# --- con qué se ponen
c("Windows: RegisterHotKey", a.mecanismo(True, {}), (a.WINDOWS, ""))
c("Linux X11: XGrabKey", a.mecanismo(False, {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}),
  (a.X11, ""))
c("Linux Wayland: el portal, aunque haya XWayland",
  a.mecanismo(False, {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}), (a.PORTAL, ""))
c("  también si solo lo dice XDG_SESSION_TYPE",
  a.mecanismo(False, {"XDG_SESSION_TYPE": "Wayland", "DISPLAY": ":1"})[0], a.PORTAL)
c("sin escritorio, no, y por qué", a.mecanismo(False, {}), (None, a.SIN_ESCRITORIO))

# --- sobre qué unidad
A = {"id": "A", "nombre": "PRDRIVE-A", "en_lista": True, "atendida": True}
B = {"id": "B", "nombre": "PRDRIVE-B", "en_lista": True, "atendida": True}
N = {"id": "N", "nombre": "NUEVA", "en_lista": False, "ahora_no": True}
R = {"id": "R", "nombre": "EQUIPO", "en_lista": True, "atendida": True, "del_equipo": True}
c("sin ninguna de la lista conectada, ninguna", a.objetivo({"unidades": [N]}, {}, {}), None)
c("con una sola, esa (aunque se usara otra)",
  a.objetivo({"unidades": [N, A]}, {"N": 9.0}, {})["id"], "A")
c("con varias, la última usada",
  a.objetivo({"unidades": [A, B]}, {"A": 20.0, "B": 10.0}, {"A": 1.0, "B": 2.0})["id"], "A")
c("  una usada antes cuenta sobre otra que nunca se usó y se conectó después",
  a.objetivo({"unidades": [A, B]}, {"A": 5.0}, {"A": 1.0, "B": 50.0})["id"], "A")
c("  lo usado de una que ya no está no cuenta",
  a.objetivo({"unidades": [A, B]}, {"Z": 99.0}, {"A": 3.0, "B": 2.0})["id"], "A")
c("sin ninguna usada, la última que se conectó",
  a.objetivo({"unidades": [A, B]}, {}, {"A": 3.0, "B": 2.0})["id"], "A")
c("  y sin saber cuándo, la última de la lista",
  a.objetivo({"unidades": [A, B]}, {}, {})["id"], "B")
c("la raíz de este equipo cuenta como un dispositivo más",
  a.objetivo({"unidades": [R, A]}, {"R": 7.0}, {})["id"], "R")

# --- qué hace cada acción
usos = {"A": 10.0}
r = a.pulsado(a.SINCRONIZAR, {"unidades": [A, B]}, usos, {})
c("sincronizar: la misma petición que «Sincronizar ahora» de la bandeja, con aviso",
  (r.peticiones, r.aviso[0], r.unidad),
  (({"pide": equipo.PIDE_PASADA, "id": "A", "parejas": []},), "PRDRIVE-A: sincronizando", "A"))
r = a.pulsado(a.SINCRONIZAR, {"unidades": [{**A, "atendida": False,
                                            "motivo": "en pausa: hay una ventana de runsync "
                                                      "abierta"}]}, {}, {})
c("  sin servicio, no pide nada y dice por qué",
  (r.peticiones, "ventana de runsync" in r.aviso[1]), ((), True))
r = a.pulsado(a.SINCRONIZAR, {"unidades": [{**A, "atendida": False, "pausada": True}]}, {}, {})
c("  pausada, lo dice y cómo se reanuda", "atajo de pausar" in r.aviso[1], True)
r = a.pulsado(a.CARPETA, {"unidades": [A]}, {}, {})
c("abrir su carpeta: «Abrir en explorador», sin aviso",
  (r.peticiones, r.aviso), (({"pide": equipo.PIDE_EXPLORAR, "id": "A"},), None))
r = a.pulsado(a.VENTANA, {"unidades": [A]}, {}, {})
c("abrir su ventana: «Configurar», sin aviso",
  (r.peticiones, r.aviso), (({"pide": equipo.PIDE_ABRIR, "id": "A"},), None))
r = a.pulsado(a.PAUSAR, {"unidades": [A]}, {}, {})
c("pausar: la pausa de esa unidad, la del «Pausar» de su ventana, con aviso",
  (r.peticiones, r.aviso[0]), (({"pide": equipo.PIDE_PAUSAR_RAIZ, "id": "A"},),
                               "PRDRIVE-A: en pausa"))
r = a.pulsado(a.PAUSAR, {"unidades": [{**A, "pausada": True}], "pausado": True}, {}, {})
c("  pausada, la reanuda (antes que la pausa de todo)",
  (r.peticiones, r.aviso[0]), (({"pide": equipo.PIDE_REANUDAR, "id": "A"},),
                               "PRDRIVE-A: reanudada"))
r = a.pulsado(a.PAUSAR, {"unidades": [A], "pausado": True}, {}, {})
c("  con la pausa de todo puesta, la quita, como «Reanudar todo»",
  r.peticiones, ({"pide": equipo.PIDE_SIGUE},))
r = a.pulsado(a.VENTANA, {"unidades": [N]}, {}, {})
c("sin unidad a mano: nada que pedir y un aviso que lo dice",
  (r.peticiones, "no hay ninguna unidad" in r.aviso[0]), ((), True))
c("una acción que no existe no hace nada", a.pulsado("formatear", {"unidades": [A]}, {}, {}),
  a.Respuesta())

# --- grabar: lo que llega del teclado
t = a.Teclas(windows=False)
c("X11: un modificador solo deja la combinación a medias", t.pulsa("Control_L", 37, 0), None)
c("  y con la tecla, la combinación (la S de Mayús es la s)",
  str(t.pulsa("S", 39, 0x1 | 0x4)), "ctrl+shift+s")
t.suelta("Control_L")
c("  Alt por el estado (Mod1) aunque no se viera su KeyPress",
  str(t.pulsa("F5", 71, 0x8)), "alt+f5")
c("  el bloqueo numérico (Mod2) no es un modificador", str(t.pulsa("a", 38, 0x8 | 0x10)), "alt+a")
c("  Súper por su KeyPress", (t.pulsa("Super_L", 133, 0), str(t.pulsa("1", 10, 0x40))),
  (None, "super+1"))
t.soltar_todo()
c("  perdido el foco, se olvidan", str(t.pulsa("s", 39, 0)), "s")
w = a.Teclas(windows=True)
w.pulsa("Win_L", 91, 0)
c("Windows: la tecla se lee de su tecla virtual y Win por su KeyPress",
  str(w.pulsa("s", 0x53, 0x4)), "ctrl+super+s")
c("  Alt es 0x20000 y el 0x8 (bloqueo numérico) no cuenta",
  str(a.Teclas(windows=True).pulsa("F12", 0x7B, 0x20000 | 0x8)), "alt+f12")
c("  una tecla que no vale sale como tal, y problema() lo dice",
  a.problema(a.Teclas(windows=False).pulsa("exclam", 10, 0x4)) is not None, True)

# --- grabar: la ventana
estado = {"acciones": {a.SINCRONIZAR: {"combo": "ctrl+alt+s", "error": ""},
                       a.VENTANA: {"combo": "", "error": a.YA_LA_USA}}}
e = a.Edicion.desde(estado, windows=False)
filas = {f.accion: f for f in e.filas()}
c("empieza con lo que tiene el agente", (filas[a.SINCRONIZAR].combinacion,
                                          filas[a.CARPETA].combinacion), ("Ctrl+Alt+S",
                                                                          "Sin atajo"))
c("  y el que no se pudo poner dice por qué", a.YA_LA_USA in filas[a.VENTANA].nota, True)
c("  sin cambios no hay nada que guardar", e.cambiada, False)
e = e.grabar(a.CARPETA)
c("grabando, la fila lo dice", e.filas()[1].combinacion, "Pulsa la combinación…")
e2 = e.pulsada(a.leer("shift+c"))
c("  lo que no vale se dice y sigue grabando",
  (e2.grabando, "Ctrl, Alt" in e2.notas[a.CARPETA]), (a.CARPETA, True))
e = e2.pulsada(a.leer("ctrl+alt+c"))
c("  lo que vale se pone, deja de grabar y hay algo que guardar",
  (e.atajos[a.CARPETA], e.grabando, e.cambiada, a.CARPETA in e.notas),
  ("ctrl+alt+c", "", True, False))
e = e.grabar(a.VENTANA).pulsada(a.leer("ctrl+alt+s"))
c("la combinación de otra acción pasa a esta, y la otra lo dice",
  (e.atajos.get(a.SINCRONIZAR), e.atajos[a.VENTANA], "«Abrir su ventana»" in e.notas[
      a.SINCRONIZAR]), (None, "ctrl+alt+s", True))
e = e.borrar(a.CARPETA)
c("borrar la quita", (a.CARPETA in e.atajos, e.filas()[1].borrable), (False, False))
c("lo que se pide al guardar", e.pedido(), {a.VENTANA: "ctrl+alt+s"})
e = e.veredicto({a.VENTANA: a.YA_LA_USA})
c("un rechazo al guardar la deja sin atajo y su fila dice por qué",
  (e.atajos, e.guardados, a.YA_LA_USA in e.notas[a.VENTANA]), ({}, {}, True))
c("  y después ya no hay nada que guardar", e.cambiada, False)

# --- el «Guardar» que llega al agente
validos, rechazados = a.validar({a.SINCRONIZAR: "Ctrl+Alt+S", a.CARPETA: "ctrl+alt+s",
                                 a.PAUSAR: "shift+p", a.VENTANA: "", "otra": "ctrl+o"})
c("validar: lo que vale, en su forma de dentro", validos, {a.SINCRONIZAR: "ctrl+alt+s"})
c("  la repetida y la que no vale, rechazadas con su motivo",
  (sorted(rechazados), "«Sincronizar ahora»" in rechazados[a.CARPETA]),
  ([a.CARPETA, a.PAUSAR], True))
c("  algo que no es un diccionario no pide nada", a.validar(["ctrl+s"]), ({}, {}))
res = a.resumen_de(a.X11, "", {a.SINCRONIZAR: "ctrl+alt+s"}, {a.VENTANA: a.YA_LA_USA}, False,
                   {"vez": "x", "rechazados": {}})
c("lo que cuenta el agente: solo las acciones con algo que decir",
  (sorted(res["acciones"]), res["mecanismo"], res["respuesta"]["vez"]),
  ([a.SINCRONIZAR, a.VENTANA], a.X11, "x"))

# --- en agente.json
aj = equipo.desde_dict({"atajos": {"sincronizar": " Ctrl+Alt+S ", "ventana": "ctrl+alt+v",
                                   "borrar": "ctrl+b", "carpeta": "rm -rf /",
                                   "pausar": 3}})
c("agente.json: se guardan por acción y en minúsculas; lo que no tiene su forma, fuera",
  dict(aj.atajos), {"sincronizar": "ctrl+alt+s", "ventana": "ctrl+alt+v"})
c("  y se escriben tal cual", equipo.a_dict(aj)["atajos"],
  {"sincronizar": "ctrl+alt+s", "ventana": "ctrl+alt+v"})
c("de fábrica, ninguno, y agente.json no cambia de forma",
  (dict(equipo.Ajustes().atajos), "atajos" in equipo.a_dict(equipo.Ajustes()),
   dict(equipo.desde_dict({}).atajos)), ({}, False, {}))
c("las acciones son las de equipo.ACCIONES_DE_ATAJO", a.ACCIONES, equipo.ACCIONES_DE_ATAJO)
c("la mitad que decide no carga tkinter", "tkinter" in sys.modules, False)

sys.exit(c.report())
