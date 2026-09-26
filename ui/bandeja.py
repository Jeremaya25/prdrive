#!/usr/bin/env python3
"""
bandeja.py — Qué enseña la bandeja del agente: su icono, su texto y su menú.

Es la mitad que DECIDE, y es pura: recibe el resumen del agente
(`Agente.resumen()`, lo mismo que va a `estado.json`) y devuelve una `Vista`
—uno de los cinco iconos de `icons.BANDEJA_ESTADOS`, la línea que sale al pasar
el ratón y el árbol del menú—. Cada entrada del menú lleva las peticiones que
hace al elegirla, con la misma forma que el buzón (`equipo.pedir()`), así que el
agente las atiende por un solo camino venga de donde vengan.

La mitad que DIBUJA es de cada sistema: `ui/bandeja_windows.py` (fase 4) con
`Shell_NotifyIconW`, y `ui/bandeja_linux.py` (fase 6) con StatusNotifierItem y
dbusmenu. Ninguna de las dos decide nada, y ninguna importa tkinter: el agente
no carga Tk nunca.

Lo que ofrece el menú (sección 5 del diseño, y «Una unidad nueva» de la 3):

  * el estado, en gris, y debajo hasta `MAX_AVISOS` avisos;
  * **Abrir** la raíz de este equipo (con ella bloqueada, desbloquea antes) y
    cada unidad conectada que está en la lista; nunca una que no lo está, que
    sería ejecutar su código sin el sí;
  * **Desbloquear / Bloquear** la raíz cifrada, y la casilla de
    `pedir_al_iniciar`;
  * «PRDRIVE-2, conectada · **Atender…**» para una unidad a la que se dijo
    «Ahora no» (o se le está preguntando) mientras siga enchufada;
  * **Sincronizar ahora**, **Pausar** / **Reanudar** y **Cerrar el agente**.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from common import APP_NAME, equipo
from ui import icons

# En qué está una raíz de este equipo (`Agente._estado_raiz()`).
ABIERTA = "abierta"
BLOQUEADA = "bloqueada"
DESBLOQUEANDO = "desbloqueando"
BLOQUEANDO = "bloqueando"
FANTASMA = "fantasma"
AUSENTE = "ausente"
BUSCANDO = "buscando"       # sin cifrar y todavía no vista: el agente acaba de arrancar

MAX_AVISOS = 3              # las líneas de aviso bajo el estado; el resto, «y N más»
MAX_TIP = 127               # `szTip` de NOTIFYICONDATAW: 128 con el nulo


@dataclass(frozen=True)
class Entrada:
    """Una línea del menú. Sin texto es un separador.

    `pide` son las peticiones al agente (dicts del buzón); `marcada` no None la
    hace casilla; `defecto` es la que hace el doble clic en el icono; con
    `hijos` es un submenú."""
    texto: str = ""
    pide: tuple[Mapping[str, Any], ...] = ()
    activa: bool = True
    marcada: bool | None = None
    defecto: bool = False
    hijos: tuple["Entrada", ...] = ()

    @property
    def separador(self) -> bool:
        return not self.texto


SEPARADOR = Entrada()


@dataclass(frozen=True)
class Vista:
    icono: str                          # uno de icons.BANDEJA_ESTADOS
    tip: str
    menu: tuple[Entrada, ...]
    frase: str = ""                     # el estado sin el nombre delante (Linux)

    def defecto(self) -> Entrada | None:
        """La entrada del doble clic, si hay una."""
        return next((e for e in _todas(self.menu) if e.defecto and e.activa), None)


def _todas(entradas):
    for e in entradas:
        yield e
        yield from _todas(e.hijos)


# ---------------------------------------------------------------------------
# El estado
# ---------------------------------------------------------------------------

def avisos(resumen: Mapping[str, Any]) -> list[str]:
    """Lo que va mal y merece que el icono lo diga, en frases cortas."""
    lineas: list[str] = []
    for u in resumen.get("unidades") or []:
        for pareja in u.get("fallando") or []:
            lineas.append(f"{u.get('nombre')}: falla {pareja}")
        if u.get("error"):
            lineas.append(f"{u.get('nombre')}: {u['error']}")
    for linea in resumen.get("sin_conexion") or []:
        lineas.append(f"Sin conexión: {linea}")
    for ruta in resumen.get("ausentes") or []:
        lineas.append(f"Falta la raíz de este equipo: {ruta}")
    for ruta in resumen.get("fantasmas") or []:
        lineas.append(f"Volumen fantasma en {ruta}: bloquéala y vuelve a desbloquearla")
    return lineas


def estado(resumen: Mapping[str, Any]) -> tuple[str, str]:
    """(icono, frase) del agente, en este orden de prioridad:

    la pausa pedida (lo ha decidido alguien) > una pasada en marcha > los avisos
    > lo que retiene sin ser pausa (batería, red de uso medido) > la raíz
    cifrada bloqueada > bien. Bloqueada no es un aviso: es lo normal con el
    contenedor cerrado, y el icono lo enseña sin alarmar."""
    if resumen.get("pausado"):
        return icons.PAUSA, "en pausa"
    pasada = resumen.get("pasada")
    if pasada:
        que = pasada.get("pareja") or "comprobando la conexión"
        return icons.SINCRONIZANDO, f"sincronizando {pasada.get('unidad')} · {que}"
    hay = avisos(resumen)
    if hay:
        return icons.AVISO, hay[0] if len(hay) == 1 else f"{len(hay)} avisos"
    if resumen.get("retenido"):
        return icons.PAUSA, f"esperando: {resumen['retenido']}"
    raices = resumen.get("equipo") or []
    for estado_, frase in ((DESBLOQUEANDO, "desbloqueando"), (BLOQUEANDO, "bloqueando"),
                           (BLOQUEADA, "bloqueada")):
        for r in raices:
            if r.get("estado") == estado_:
                return icons.BLOQUEADO, f"{r.get('nombre')} {frase}"
    if not raices and not resumen.get("unidades"):
        return icons.BIEN, "esperando unidades"
    return icons.BIEN, "al día"


def aviso_de_estado(resumen: Mapping[str, Any]) -> tuple[str, str]:
    """(título, texto) del aviso con el que el acceso «prdrive» del menú dice
    cómo va el agente donde no hay bandeja que lo enseñe (fase 6): lo mismo
    que su icono y la cabecera de su menú."""
    _icono, frase = estado(resumen)
    lineas = avisos(resumen)
    texto = lineas[:MAX_AVISOS]
    if len(lineas) > MAX_AVISOS:
        texto.append(f"y {len(lineas) - MAX_AVISOS} más")
    if not texto:
        atendidas = [str(u.get("nombre")) for u in resumen.get("unidades") or []
                     if u.get("atendida")]
        texto = [f"Atiende: {', '.join(atendidas)}." if atendidas
                 else "No hay ninguna unidad conectada que atender."]
    if resumen.get("pausado"):
        texto.append("Para que siga: python agente.py sigue")
    return f"{APP_NAME}: {frase}", "\n".join(texto)


def tip(frase: str) -> str:
    texto = f"{APP_NAME} — {frase}"
    return texto if len(texto) <= MAX_TIP else texto[:MAX_TIP - 1] + "…"


# ---------------------------------------------------------------------------
# El menú
# ---------------------------------------------------------------------------

def _pide(que: str, **campos) -> tuple[dict, ...]:
    return ({"pide": que, **campos},)


def _raices_del_equipo(resumen: Mapping[str, Any]) -> list[Entrada]:
    entradas: list[Entrada] = []
    raices = resumen.get("equipo") or []
    for i, r in enumerate(raices):
        uid, nombre, est = r.get("id", ""), r.get("nombre") or APP_NAME, r.get("estado")
        if est == AUSENTE:
            entradas.append(Entrada(f"{nombre}: no está en su sitio", activa=False))
            continue
        if est == BUSCANDO:
            entradas.append(Entrada(f"{nombre}: buscándola…", activa=False))
            continue
        cerrada = est in (BLOQUEADA, DESBLOQUEANDO)
        entradas.append(Entrada(f"Abrir {nombre}" + ("…" if cerrada else ""),
                                _pide(equipo.PIDE_ABRIR, id=uid),
                                activa=est in (ABIERTA, BLOQUEADA, DESBLOQUEANDO),
                                defecto=i == 0))
        if not r.get("cifrada"):
            continue
        if est == BLOQUEADA:
            entradas.append(Entrada(f"Desbloquear {nombre}…",
                                    _pide(equipo.PIDE_DESBLOQUEAR, id=uid)))
        elif est == DESBLOQUEANDO:
            entradas.append(Entrada(f"Desbloqueando {nombre}: la contraseña la pide "
                                    f"VeraCrypt", activa=False))
        elif est == BLOQUEANDO:
            entradas.append(Entrada(f"Bloqueando {nombre}…", activa=False))
        else:                               # abierta, o un fantasma: bloquear lo arregla
            entradas.append(Entrada(f"Bloquear {nombre}",
                                    _pide(equipo.PIDE_BLOQUEAR, id=uid)))
    if any(r.get("cifrada") for r in raices):
        pedir = bool(resumen.get("pedir_al_iniciar", True))
        entradas.append(Entrada("Pedir la contraseña al iniciar sesión",
                                _pide(equipo.PIDE_AJUSTE, clave="pedir_al_iniciar",
                                      valor=not pedir),
                                marcada=pedir))
    return entradas


def _unidades(resumen: Mapping[str, Any]) -> list[Entrada]:
    entradas: list[Entrada] = []
    for u in resumen.get("unidades") or []:
        if u.get("del_equipo"):
            continue
        uid, nombre = u.get("id", ""), u.get("nombre")
        if u.get("en_lista"):
            entradas.append(Entrada(f"Abrir {nombre}", _pide(equipo.PIDE_ABRIR, id=uid)))
        elif u.get("ahora_no") or u.get("preguntando"):
            entradas.append(Entrada(f"{nombre}, conectada · Atender…",
                                    _pide(equipo.PIDE_ATENDER, id=uid)))
    return entradas


def _sincronizar(resumen: Mapping[str, Any]) -> Entrada:
    atendidas = [u for u in resumen.get("unidades") or [] if u.get("atendida")]
    if not atendidas:
        return Entrada("Sincronizar ahora", activa=False)
    if len(atendidas) == 1:
        return Entrada("Sincronizar ahora",
                       _pide(equipo.PIDE_PASADA, id=atendidas[0].get("id"), parejas=[]))
    todas = tuple(p for u in atendidas
                  for p in _pide(equipo.PIDE_PASADA, id=u.get("id"), parejas=[]))
    return Entrada("Sincronizar ahora", hijos=(
        Entrada("Todas", todas), SEPARADOR,
        *(Entrada(str(u.get("nombre")),
                  _pide(equipo.PIDE_PASADA, id=u.get("id"), parejas=[]))
          for u in atendidas)))


def _actualizar(resumen: Mapping[str, Any]) -> list[Entrada]:
    """«Actualizar» cuando el agente sabe de una versión más nueva que la suya
    (sección 8 del diseño). Mientras se actualiza, dicho y apagado."""
    nueva = resumen.get("nueva")
    if not nueva:
        return []
    if resumen.get("actualizando"):
        return [Entrada(f"Actualizando a la {nueva}…", activa=False)]
    return [Entrada(f"Actualizar a la {nueva}", _pide(equipo.PIDE_ACTUALIZAR))]


def _bloques(*bloques: list[Entrada]) -> tuple[Entrada, ...]:
    """Los bloques no vacíos, con un separador entre cada dos."""
    salida: list[Entrada] = []
    for bloque in bloques:
        if bloque:
            if salida:
                salida.append(SEPARADOR)
            salida += bloque
    return tuple(salida)


def vista(resumen: Mapping[str, Any]) -> Vista:
    """Todo lo que enseña la bandeja, a partir del resumen del agente."""
    icono, frase = estado(resumen)
    cabecera = [Entrada(frase[:1].upper() + frase[1:], activa=False)]
    hay = avisos(resumen)
    if len(hay) > 1 or (hay and hay[0] != frase):
        cabecera += [Entrada(f"  {a}", activa=False) for a in hay[:MAX_AVISOS]]
        if len(hay) > MAX_AVISOS:
            cabecera.append(Entrada(f"  y {len(hay) - MAX_AVISOS} más", activa=False))
    pausado = bool(resumen.get("pausado"))
    menu = _bloques(cabecera, _raices_del_equipo(resumen), _unidades(resumen),
                    [_sincronizar(resumen),
                     Entrada("Reanudar", _pide(equipo.PIDE_SIGUE)) if pausado
                     else Entrada("Pausar", _pide(equipo.PIDE_PAUSA))],
                    [*_actualizar(resumen),
                     Entrada("Cerrar el agente", _pide(equipo.PIDE_PARAR))])
    return Vista(icono, tip(frase), menu, frase[:1].upper() + frase[1:])
