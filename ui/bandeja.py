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

  * arriba, solo si algo va mal, hasta `MAX_AVISOS` avisos, y cada uno lleva a
    donde se arregla: «PRUEBA-G: falla docs · Abrir…» abre su ventana (y en ella
    «Reparación»), un remoto sin conexión se vuelve a probar, un volumen
    fantasma se bloquea. Sin nada que decir no hay cabecera: una línea gris con
    «al día» encima de todo no servía para nada (tercera pasada en real, B5). El
    estado va en el texto del ratón, que dice cuándo se sincronizó por última
    vez;
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

import time
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

MAX_AVISOS = 3              # las líneas de aviso del menú; el resto, «y N más»
MAX_TIP = 127               # `szTip` de NOTIFYICONDATAW: 128 con el nulo

# Los iconos de las entradas del menú, por nombre de `icons.GLIFOS`: lo que
# significa la entrada, no cómo se pinta. Windows pinta ese glifo
# (`ui/bandeja_windows.py`); Linux pide al tema del escritorio el suyo
# (`ui/bandeja_linux.ICONOS_DEL_TEMA`), que sigue su color y su modo oscuro.
I_ABRIR = "carpeta"
I_SINCRONIZAR = "sync"
I_PAUSAR = "pausa"
I_REANUDAR = "play"
I_BLOQUEAR = "candado"
I_DESBLOQUEAR = "candado_abierto"
I_ATENDER = "plus"
I_ACTUALIZAR = "down"
I_CERRAR = "arranque"
I_AVISO = "warn"
I_REINTENTAR = "reload"
ICONOS = (I_ABRIR, I_SINCRONIZAR, I_PAUSAR, I_REANUDAR, I_BLOQUEAR, I_DESBLOQUEAR,
          I_ATENDER, I_ACTUALIZAR, I_CERRAR, I_AVISO, I_REINTENTAR)


@dataclass(frozen=True)
class Entrada:
    """Una línea del menú. Sin texto es un separador.

    `pide` son las peticiones al agente (dicts del buzón); `marcada` no None la
    hace casilla; `defecto` es la que hace el doble clic en el icono; con
    `hijos` es un submenú; `icono`, uno de `ICONOS` o nada."""
    texto: str = ""
    pide: tuple[Mapping[str, Any], ...] = ()
    activa: bool = True
    marcada: bool | None = None
    defecto: bool = False
    hijos: tuple["Entrada", ...] = ()
    icono: str = ""

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

def _avisos(resumen: Mapping[str, Any]) -> list[tuple[str, Entrada]]:
    """Lo que va mal: cada cosa con su frase corta (la del icono y los avisos)
    y su entrada del menú, que lleva a donde se arregla. Lo que no tiene
    arreglo desde aquí —una raíz que no está en su sitio— queda apagado."""
    salida: list[tuple[str, Entrada]] = []
    for u in resumen.get("unidades") or []:
        nombre = u.get("nombre")
        abrir = _pide(equipo.PIDE_ABRIR, id=u.get("id", ""))
        for pareja in u.get("fallando") or []:
            frase = f"{nombre}: falla {pareja}"
            salida.append((frase, Entrada(f"{frase} · Abrir…", abrir, icono=I_AVISO)))
        if u.get("error"):
            frase = f"{nombre}: {u['error']}"
            salida.append((frase, Entrada(f"{frase} · Abrir…", abrir, icono=I_AVISO)))
    for linea in resumen.get("sin_conexion") or []:
        frase = f"Sin conexión: {linea}"
        salida.append((frase, Entrada(f"{frase} · Probar ahora",
                                      _pide(equipo.PIDE_SONDEAR), icono=I_REINTENTAR)))
    for ruta in resumen.get("ausentes") or []:
        frase = f"Falta la raíz de este equipo: {ruta}"
        salida.append((frase, Entrada(frase, activa=False, icono=I_AVISO)))
    fantasmas = {r.get("ruta"): r.get("id", "") for r in resumen.get("equipo") or []
                 if r.get("estado") == FANTASMA}
    for ruta in resumen.get("fantasmas") or []:
        frase = f"Volumen fantasma en {ruta}: bloquéala y vuelve a desbloquearla"
        if ruta in fantasmas:
            salida.append((frase, Entrada(f"Volumen fantasma en {ruta} · Bloquear",
                                          _pide(equipo.PIDE_BLOQUEAR, id=fantasmas[ruta]),
                                          icono=I_BLOQUEAR)))
        else:
            salida.append((frase, Entrada(frase, activa=False, icono=I_AVISO)))
    return salida


def avisos(resumen: Mapping[str, Any]) -> list[str]:
    """Lo que va mal y merece que el icono lo diga, en frases cortas."""
    return [frase for frase, _entrada in _avisos(resumen)]


def hace(segundos: float, cuando: float) -> str:
    """Cuándo fue algo, dicho corto: «hace un momento», «hace 5 min», «a las
    11:55» (hoy, hace más de una hora) o «el 29/09 a las 11:55»."""
    if segundos < 60:
        return "hace un momento"
    if segundos < 3600:
        return f"hace {int(segundos // 60)} min"
    fecha = time.localtime(cuando)
    hora = time.strftime("%H:%M", fecha)
    if time.localtime(cuando + segundos)[:3] == fecha[:3]:
        return f"a las {hora}"
    return f"el {time.strftime('%d/%m', fecha)} a las {hora}"


def estado(resumen: Mapping[str, Any], ahora: float | None = None) -> tuple[str, str]:
    """(icono, frase) del agente, en este orden de prioridad:

    la pausa pedida (lo ha decidido alguien) > una pasada en marcha > los avisos
    > lo que retiene sin ser pausa (batería, red de uso medido) > la raíz
    cifrada bloqueada > bien. Bloqueada no es un aviso: es lo normal con el
    contenedor cerrado, y el icono lo enseña sin alarmar.

    Bien, la frase dice cuándo acabó bien la última pasada (`ultima_pasada`,
    segundos de época; `ahora`, por defecto el reloj): «al día» a secas no
    decía nada que el icono no dijera ya."""
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
    ultima = resumen.get("ultima_pasada")
    if isinstance(ultima, (int, float)):
        ahora = time.time() if ahora is None else ahora
        return icons.BIEN, f"sincronizado {hace(max(0.0, ahora - ultima), ultima)}"
    if any(u.get("atendida") for u in resumen.get("unidades") or []):
        return icons.BIEN, "esperando la primera pasada"
    return icons.BIEN, "sin nada que sincronizar ahora"


def aviso_de_estado(resumen: Mapping[str, Any]) -> tuple[str, str]:
    """(título, texto) del aviso con el que el acceso «prdrive» del menú dice
    cómo va el agente donde no hay bandeja que lo enseñe (fase 6): lo mismo
    que su icono, su texto y los avisos de su menú."""
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
    texto = f"{APP_NAME} · {frase}"
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
                                defecto=i == 0, icono=I_ABRIR))
        if not r.get("cifrada"):
            continue
        if est == BLOQUEADA:
            entradas.append(Entrada(f"Desbloquear {nombre}…",
                                    _pide(equipo.PIDE_DESBLOQUEAR, id=uid),
                                    icono=I_DESBLOQUEAR))
        elif est == DESBLOQUEANDO:
            entradas.append(Entrada(f"Desbloqueando {nombre}: la contraseña la pide "
                                    f"VeraCrypt", activa=False))
        elif est == BLOQUEANDO:
            entradas.append(Entrada(f"Bloqueando {nombre}…", activa=False))
        else:                               # abierta, o un fantasma: bloquear lo arregla
            entradas.append(Entrada(f"Bloquear {nombre}",
                                    _pide(equipo.PIDE_BLOQUEAR, id=uid), icono=I_BLOQUEAR))
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
        if u.get("vieja") is not None:
            # Anterior a la versión mínima del agente: no hay nada que pedirle
            # hasta que se actualice, y se dice en el propio menú.
            entradas.append(Entrada(f"{nombre}: actualízala para que la atienda",
                                    activa=False))
        elif u.get("en_lista"):
            entradas.append(Entrada(f"Abrir {nombre}", _pide(equipo.PIDE_ABRIR, id=uid),
                                    icono=I_ABRIR))
        elif u.get("ahora_no") or u.get("preguntando"):
            # Con otro código que el aceptado (`agente.huella()`), se dice: el
            # sí de ahora es a ese código.
            que = "código cambiado" if u.get("cambiada") else "conectada"
            entradas.append(Entrada(f"{nombre}, {que} · Atender…",
                                    _pide(equipo.PIDE_ATENDER, id=uid), icono=I_ATENDER))
    return entradas


def _sincronizar(resumen: Mapping[str, Any]) -> Entrada:
    atendidas = [u for u in resumen.get("unidades") or [] if u.get("atendida")]
    if not atendidas:
        return Entrada("Sincronizar ahora", activa=False, icono=I_SINCRONIZAR)
    if len(atendidas) == 1:
        return Entrada("Sincronizar ahora",
                       _pide(equipo.PIDE_PASADA, id=atendidas[0].get("id"), parejas=[]),
                       icono=I_SINCRONIZAR)
    todas = tuple(p for u in atendidas
                  for p in _pide(equipo.PIDE_PASADA, id=u.get("id"), parejas=[]))
    return Entrada("Sincronizar ahora", hijos=(
        Entrada("Todas", todas), SEPARADOR,
        *(Entrada(str(u.get("nombre")),
                  _pide(equipo.PIDE_PASADA, id=u.get("id"), parejas=[]))
          for u in atendidas)), icono=I_SINCRONIZAR)


def _actualizar(resumen: Mapping[str, Any]) -> list[Entrada]:
    """«Actualizar» cuando el agente sabe de una versión más nueva que la suya
    (sección 8 del diseño). Mientras se actualiza, dicho y apagado."""
    nueva = resumen.get("nueva")
    if not nueva:
        return []
    if resumen.get("actualizando"):
        return [Entrada(f"Actualizando a la {nueva}…", activa=False)]
    return [Entrada(f"Actualizar a la {nueva}", _pide(equipo.PIDE_ACTUALIZAR),
                    icono=I_ACTUALIZAR)]


def _bloques(*bloques: list[Entrada]) -> tuple[Entrada, ...]:
    """Los bloques no vacíos, con un separador entre cada dos."""
    salida: list[Entrada] = []
    for bloque in bloques:
        if bloque:
            if salida:
                salida.append(SEPARADOR)
            salida += bloque
    return tuple(salida)


def vista(resumen: Mapping[str, Any], ahora: float | None = None) -> Vista:
    """Todo lo que enseña la bandeja, a partir del resumen del agente. `ahora`
    es para el «hace N min» del texto (por defecto, el reloj)."""
    icono, frase = estado(resumen, ahora)
    hay = [entrada for _frase, entrada in _avisos(resumen)]
    cabecera = hay[:MAX_AVISOS]
    if len(hay) > MAX_AVISOS:
        cabecera.append(Entrada(f"y {len(hay) - MAX_AVISOS} más", activa=False))
    pausado = bool(resumen.get("pausado"))
    menu = _bloques(cabecera, _raices_del_equipo(resumen), _unidades(resumen),
                    [_sincronizar(resumen),
                     Entrada("Reanudar", _pide(equipo.PIDE_SIGUE), icono=I_REANUDAR)
                     if pausado
                     else Entrada("Pausar", _pide(equipo.PIDE_PAUSA), icono=I_PAUSAR)],
                    [*_actualizar(resumen),
                     Entrada("Cerrar el agente", _pide(equipo.PIDE_PARAR), icono=I_CERRAR)])
    return Vista(icono, tip(frase), menu, frase[:1].upper() + frase[1:])
