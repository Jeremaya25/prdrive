#!/usr/bin/env python3
"""Qué enseña la bandeja del agente: su icono, su texto y su menú.

Es la mitad que DECIDE y es pura: recibe el resumen del agente
(`Agente.resumen()`, lo mismo que va a `estado.json`) y devuelve una `Vista`:
uno de los cinco iconos de `icons.BANDEJA_ESTADOS`, la línea que sale al pasar
el ratón y el árbol del menú. Cada entrada del menú lleva las peticiones que
hace al elegirla, con la misma forma que el buzón (`equipo.pedir()`), así que
el agente las atiende por un solo camino venga de donde vengan.

La mitad que DIBUJA es de cada sistema: `ui/bandeja_windows.py` con
`Shell_NotifyIconW` y `ui/bandeja_linux.py` con StatusNotifierItem y dbusmenu.
Ninguna decide nada y ninguna importa tkinter: el agente no carga Tk nunca.

Lo que ofrece el menú (sección 5 del diseño, «Una unidad nueva» de la 3 y el
#68):
- Arriba, solo si algo va mal, hasta `MAX_AVISOS` avisos, y cada uno lleva a
  donde se arregla: «PRUEBA-G: falla docs · Abrir…» abre su ventana (y en ella
  «Reparación»), un remoto sin conexión se vuelve a probar, un volumen fantasma
  se bloquea. Sin nada que decir no hay cabecera: una línea gris con «al día»
  encima de todo no servía para nada (tercera pasada en real, B5). El estado va
  en el texto del ratón, que dice cuándo se sincronizó por última vez.
- **Un desplegable por dispositivo** (las raíces de este equipo y luego las
  unidades conectadas), con SU icono (`Emblema`) y todo lo suyo dentro, sin
  repetir su nombre: «Configurar» (su ventana de runsync), «Abrir en
  explorador» (su carpeta), «Sincronizar ahora» (solo él), en una unidad
  extraíble de la lista «Expulsar» (la suelta para poder quitarla) y, en una
  raíz cifrada, «Bloquear» / «Desbloquear…» y la casilla de `pedir_al_iniciar`. A
  una unidad que no está en la lista no se le ofrece nada de eso, que sería
  ejecutar su código sin el sí: su desplegable dice «(sin atender)» y lleva
  «Atender…». Lo que no está bien lo dice el rótulo entre paréntesis
  («bloqueada», «por actualizar»…). Si su programa es anterior al del
  agente, «Actualizar a la vX» lo pone al día con la versión del agente.
  Abajo del todo, apagada, la versión de su programa, si se sabe.
- Fuera, lo del agente entero: **Sincronizar todo ahora** (solo con dos o más
  dispositivos que sincronizar), **Pausar** / **Reanudar**, **Actualizar**
  (o **Buscar actualizaciones**, si no se sabe de ninguna) y **Cerrar el
  agente**; y la última línea, apagada, la versión del agente.

«Configurar» es la entrada por defecto de cada desplegable: en Windows sale en
negrita y es lo que hace el doble clic sobre el propio desplegable
(`ui/bandeja_windows.py`); dbusmenu no tiene nada parecido y en Linux es solo
la primera entrada.
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

# Iconos de las entradas del menú, por nombre de `icons.GLIFOS`: lo que
# significa la entrada, no cómo se pinta. Windows pinta ese glifo
# (`ui/bandeja_windows.py`); Linux pide al tema del escritorio el suyo
# (`ui/bandeja_linux.ICONOS_DEL_TEMA`), que sigue su color y su modo oscuro.
I_CONFIGURAR = "gear"
I_EXPLORAR = "carpeta"
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
I_LLAVERO = "llave"
I_EXPULSAR = "expulsar"
ICONOS = (I_CONFIGURAR, I_EXPLORAR, I_SINCRONIZAR, I_PAUSAR, I_REANUDAR, I_BLOQUEAR,
          I_DESBLOQUEAR, I_ATENDER, I_ACTUALIZAR, I_CERRAR, I_AVISO, I_REINTENTAR,
          I_LLAVERO, I_EXPULSAR)
"""Todos los iconos que puede llevar una entrada."""


@dataclass(frozen=True)
class Emblema:
    """El icono a color de un dispositivo en el menú: el suyo o la marca de prdrive.

    No es un glifo de `ICONOS`: es lo que se le puso en «Nombre e icono de la
    unidad…» (su `autorun.inf`). Lo averigua el agente (`volumen.emblema()`),
    y solo de una raíz de su lista, conectada y abierta; de cualquier otra se
    pinta la marca de prdrive. Cada sistema lo pinta a su manera
    (`bandeja_windows.pixeles_emblema()`, `bandeja_linux.png_emblema()`) y
    nunca falla por él: lo que no se pueda leer o pintar es la marca.

    Args:
        campo: El color del campo de la marca (uno de `icons.CAMPOS`).
        ico: El `.ico` propio de la unidad, o nada. Si no se puede leer o no se
            entiende, se pinta la marca con `campo`.
    """
    campo: str = icons.CAMPO
    ico: str = ""


MARCA = Emblema()
"""El icono de un dispositivo sin uno suyo que enseñar: la marca de prdrive."""

TOPE_CACHE = 64
"""Cuántos iconos pintados guarda como mucho cada caché de la bandeja.

Cada guardado de «Nombre e icono…» da un `.ico` con otro nombre (la ruta es la
clave) y sin tope no se soltaría ninguno mientras el agente viva.
"""


class CacheAcotada(dict):
    """Un diccionario que, al llenarse, suelta la entrada que lleva más tiempo dentro.

    Es la caché de los iconos ya pintados de `bandeja_windows` y
    `bandeja_linux`: una clave nueva con la caché llena saca la más antigua
    (la primera que entró), no la menos usada; con un tope de decenas de
    entradas, volver a pintar un icono es lo bastante barato.

    Args:
        tope: Cuántas entradas caben como mucho.
    """

    def __init__(self, tope: int = TOPE_CACHE) -> None:
        """Crea la caché vacía."""
        super().__init__()
        self.tope = tope

    def __setitem__(self, clave: Any, valor: Any) -> None:
        """Guarda la entrada; si la clave es nueva y no cabe, saca la más antigua."""
        if clave not in self and len(self) >= self.tope:
            del self[next(iter(self))]
        super().__setitem__(clave, valor)


@dataclass(frozen=True)
class Entrada:
    """Una línea del menú; sin texto es un separador.

    Args:
        texto: Lo que dice.
        pide: Las peticiones al agente que hace al elegirla (dicts del buzón).
        activa: Si se puede elegir.
        marcada: Si no es `None`, la entrada es una casilla y esto dice si está
            marcada.
        defecto: Si es la entrada por defecto de su menú: en Windows va en
            negrita y la elige el doble clic en el desplegable que la contiene.
        hijos: Si no está vacío, la entrada es un submenú.
        icono: Uno de `ICONOS`, o nada.
        emblema: El icono a color de un dispositivo; con él, `icono` no cuenta.
    """
    texto: str = ""
    pide: tuple[Mapping[str, Any], ...] = ()
    activa: bool = True
    marcada: bool | None = None
    defecto: bool = False
    hijos: tuple["Entrada", ...] = ()
    icono: str = ""
    emblema: Emblema | None = None

    @property
    def separador(self) -> bool:
        """Indica si la entrada es un separador."""
        return not self.texto


SEPARADOR = Entrada()
"""La entrada que hace de separador."""


@dataclass(frozen=True)
class Vista:
    """Todo lo que enseña la bandeja.

    Args:
        icono: Uno de `icons.BANDEJA_ESTADOS`.
        tip: La línea que sale al pasar el ratón.
        menu: El árbol del menú.
        frase: El estado sin el nombre delante (Linux).
    """
    icono: str
    tip: str
    menu: tuple[Entrada, ...]
    frase: str = ""

    def defecto(self) -> Entrada | None:
        """Devuelve la primera entrada por defecto que se puede elegir, si hay una.

        Es el «Configurar» del primer dispositivo (la raíz de este equipo, si
        la hay): lo que hace `Activate` en Linux, con los anfitriones que lo
        llaman al pinchar en el icono.
        """
        return next((e for e in _todas(self.menu) if e.defecto and e.activa), None)


def _todas(entradas):
    """Recorre las entradas y sus hijos, en orden."""
    for e in entradas:
        yield e
        yield from _todas(e.hijos)


def _avisos(resumen: Mapping[str, Any]) -> list[tuple[str, Entrada]]:
    """Devuelve lo que va mal, cada cosa con su frase corta y su entrada del menú.

    La frase es la del icono y de los avisos; la entrada lleva a donde se
    arregla. Lo que no tiene arreglo desde aquí (una raíz que no está en su
    sitio) queda apagado.
    """
    salida: list[tuple[str, Entrada]] = []
    for u in resumen.get("unidades") or []:
        nombre = u.get("nombre")
        abrir = _pide(equipo.PIDE_ABRIR, id=u.get("id", ""))
        for pareja in u.get("fallando") or []:
            frase = f"{nombre}: falla {pareja}"
            salida.append((frase, Entrada(f"{frase} · Abrir…", abrir, icono=I_AVISO)))
        for pareja in u.get("saltadas") or []:
            frase = f"{nombre}: {pareja} necesita --resync"
            salida.append((frase, Entrada(f"{frase} · Abrir…", abrir, icono=I_AVISO)))
        if u.get("error"):
            frase = f"{nombre}: {u['error']}"
            salida.append((frase, Entrada(f"{frase} · Abrir…", abrir, icono=I_AVISO)))
        if u.get("llavero_conflicto"):
            # Se arregla combinando: «Abrir llavero» lo ofrece, y donde no se
            # abre, su ventana lo enseña en «Reparación».
            frase = f"{nombre}: el llavero tiene dos versiones"
            salida.append((frase, Entrada(f"{frase} · Combinar…", _pide(
                equipo.PIDE_LLAVERO, id=u.get("id", "")), icono=I_LLAVERO)
                if _con_llavero(resumen, u) else
                Entrada(f"{frase} · Abrir…", abrir, icono=I_AVISO)))
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
    """Devuelve lo que va mal y merece que el icono lo diga, en frases cortas."""
    return [frase for frase, _entrada in _avisos(resumen)]


def hace(segundos: float, cuando: float) -> str:
    """Devuelve cuándo fue algo, dicho corto.

    Son «hace un momento», «hace 5 min», «a las 11:55» (hoy, hace más de una
    hora) o «el 29/09 a las 11:55».
    """
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
    """Devuelve el icono y la frase del agente.

    El orden de prioridad es: la pausa pedida (lo ha decidido alguien) > una
    pasada en marcha > los avisos > lo que retiene sin ser pausa (batería, red
    de uso medido) > una raíz en el «Pausar» de su ventana > la raíz cifrada
    bloqueada > bien. Bloqueada no es un aviso: es lo normal con el contenedor
    cerrado y el icono lo enseña sin alarmar. La raíz pausada tampoco: lo ha
    decidido alguien, y el icono de pausa y su nombre bastan para saber por qué
    no se sincroniza.

    Cuando va bien, la frase dice cuándo acabó bien la última pasada
    (`ultima_pasada`, segundos de época): «al día» a secas no decía nada que el
    icono no dijera ya.

    Args:
        resumen: El resumen del agente.
        ahora: El reloj; por defecto, el del sistema.
    """
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
    pausadas = [str(u.get("nombre")) for u in resumen.get("unidades") or []
                if u.get("pausada")]
    if pausadas:
        return icons.PAUSA, f"{', '.join(pausadas)} en pausa"
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
    """Devuelve el título y el texto del aviso que dice cómo va el agente.

    Es con el que el acceso «prdrive» del menú lo dice donde no hay bandeja que
    lo enseñe: lo mismo que su icono, su texto y los avisos de su menú.
    """
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
    """Devuelve el texto del ratón, recortado a lo que cabe en `MAX_TIP`."""
    texto = f"{APP_NAME} · {frase}"
    return texto if len(texto) <= MAX_TIP else texto[:MAX_TIP - 1] + "…"


def _pide(que: str, **campos) -> tuple[dict, ...]:
    """Devuelve la petición del buzón que hace una entrada."""
    return ({"pide": que, **campos},)


EN_PAUSA = "en pausa"
"""Lo que dice el desplegable de un dispositivo pausado desde su ventana (#64)."""
POR_ACTUALIZAR = "por actualizar"
"""Lo que dice el desplegable de un dispositivo que no se atiende hasta ponerlo al día.

Su programa es anterior a la versión mínima del agente, o una actualización
suya no acabó bien.
"""

ESTADO_DE_RAIZ = {BLOQUEADA: "bloqueada", DESBLOQUEANDO: "desbloqueando…",
                  BLOQUEANDO: "bloqueando…", FANTASMA: "no responde",
                  AUSENTE: "no está en su sitio", BUSCANDO: "buscándola…"}
"""Lo que dice el rótulo de una raíz de este equipo entre paréntesis; abierta, nada."""


def _emblema(u: Mapping[str, Any] | None) -> Emblema:
    """Devuelve el icono de un dispositivo a partir de su fila del resumen.

    Solo cuenta el de una unidad de la lista (`en_lista`): de las demás no se
    enseña nada suyo, tampoco el icono. Lo que no se entienda es la marca.
    """
    if not u or not u.get("en_lista"):
        return MARCA
    dato = u.get("emblema")
    if not isinstance(dato, Mapping):
        return MARCA
    ico = dato.get("ico")
    if isinstance(ico, str) and ico:
        return Emblema(ico=ico)
    clave = dato.get("marca")
    if isinstance(clave, str) and clave in icons.CAMPOS:
        return Emblema(campo=icons.CAMPOS[clave])
    return MARCA


def _version(fila: Mapping[str, Any] | None) -> list[Entrada]:
    """Devuelve la línea con la versión de un dispositivo, para el pie de su desplegable.

    Va apagada, que no se elige, y separada de lo que sí. Sin fila (una raíz
    cerrada no se puede leer) o sin versión que decir, nada.
    """
    version = fila.get("version") if fila else None
    if not isinstance(version, str) or not version:
        return []
    return [SEPARADOR, Entrada(f"Versión {version}", activa=False)]


def _por_actualizar(fila: Mapping[str, Any] | None) -> bool:
    """Indica si de ese dispositivo no se ejecuta nada hasta ponerlo al día."""
    return bool(fila) and (fila.get("vieja") is not None or bool(fila.get("a_medias")))


def _poner_al_dia(fila: Mapping[str, Any] | None, version: Any) -> list[Entrada]:
    """Devuelve la entrada que pone al día un dispositivo con la versión del agente.

    Es «Actualizar a la vX» si el agente dice que se puede (`actualizable`), y
    «Actualizando a la vX…» apagada mientras lo hace. A uno que no se atiende
    hasta ponerlo al día y no se puede desde aquí, la frase apagada de siempre.

    Args:
        fila: Su fila del resumen; sin ella (una raíz cerrada), nada.
        version: La versión del agente (`resumen["version"]`).
    """
    if not fila:
        return []
    uid = fila.get("id", "")
    if fila.get("actualizando"):
        return [Entrada(f"Actualizando a la v{version}…", activa=False)]
    if fila.get("actualizable") and isinstance(version, str) and version:
        return [Entrada(f"Actualizar a la v{version}",
                        _pide(equipo.PIDE_ACTUALIZAR_UNIDAD, id=uid), icono=I_ACTUALIZAR)]
    if _por_actualizar(fila):
        return [Entrada("Actualízala para que la atienda", activa=False)]
    return []


def _expulsar(fila: Mapping[str, Any] | None) -> list[Entrada]:
    """Devuelve el «Expulsar» de una unidad, con su separador, para su desplegable.

    Solo la ofrece el agente de un volumen compatible (`expulsable`, en
    `common/expulsar.py`): de las demás unidades y de las raíces de este
    equipo no hay entrada, ni apagada. Mientras lo hace, «Expulsando…» apagada.

    Args:
        fila: Su fila del resumen; sin ella, nada.
    """
    if not fila:
        return []
    if fila.get("expulsando"):
        return [SEPARADOR, Entrada("Expulsando…", activa=False, icono=I_EXPULSAR)]
    if fila.get("expulsable"):
        return [SEPARADOR, Entrada("Expulsar", _pide(equipo.PIDE_EXPULSAR,
                                                     id=fila.get("id", "")),
                                   icono=I_EXPULSAR)]
    return []


def _acciones(uid: str, abrir: bool, cerrada: bool, sincronizar: bool,
              llavero: bool = False) -> list[Entrada]:
    """Devuelve «Configurar», «Abrir en explorador», «Abrir llavero» y «Sincronizar ahora».

    Args:
        uid: El id del dispositivo.
        abrir: Si se puede abrir su ventana y su carpeta.
        cerrada: Si es una raíz cifrada bloqueada: abrirla la desbloquea antes,
            y los puntos suspensivos dicen que antes sale la contraseña.
        sincronizar: Si el agente la está atendiendo y se le puede pedir una
            pasada.
        llavero: Si lleva llavero y este equipo lo abre: entonces va «Abrir
            llavero», que se puede cuando se puede abrir su ventana.
    """
    puntos = "…" if cerrada else ""
    entradas = [Entrada(f"Configurar{puntos}", _pide(equipo.PIDE_ABRIR, id=uid),
                        activa=abrir, defecto=abrir, icono=I_CONFIGURAR),
                Entrada(f"Abrir en explorador{puntos}", _pide(equipo.PIDE_EXPLORAR, id=uid),
                        activa=abrir, icono=I_EXPLORAR)]
    if llavero:
        entradas.append(Entrada("Abrir llavero", _pide(equipo.PIDE_LLAVERO, id=uid),
                                activa=abrir and not cerrada, icono=I_LLAVERO))
    entradas.append(Entrada("Sincronizar ahora", _pide(equipo.PIDE_PASADA, id=uid, parejas=[]),
                            activa=sincronizar, icono=I_SINCRONIZAR))
    return entradas


def _con_llavero(resumen: Mapping[str, Any], fila: Mapping[str, Any] | None) -> bool:
    """Indica si un dispositivo lleva llavero y este equipo lo abre (de momento, Windows)."""
    return bool(resumen.get("abre_llavero") and fila and fila.get("llavero"))


def _pedir_al_iniciar(resumen: Mapping[str, Any], varias: bool) -> Entrada:
    """Devuelve la casilla de `pedir_al_iniciar`, que pide lo contrario de lo que hay.

    El ajuste es del agente y vale para todas sus raíces cifradas: con una
    sola va en su desplegable y se lee como suyo; con varias va fuera, y lo
    dice.
    """
    pedir = bool(resumen.get("pedir_al_iniciar", True))
    texto = ("Pedir la contraseña de cada raíz cifrada al iniciar sesión" if varias
             else "Pedir la contraseña al iniciar sesión")
    return Entrada(texto, _pide(equipo.PIDE_AJUSTE, clave="pedir_al_iniciar",
                                valor=not pedir), marcada=pedir)


def _cerrojo(uid: str, est: str | None) -> Entrada:
    """Devuelve la entrada de bloquear o desbloquear una raíz cifrada, según su estado."""
    if est == BLOQUEADA:
        return Entrada("Desbloquear…", _pide(equipo.PIDE_DESBLOQUEAR, id=uid),
                       icono=I_DESBLOQUEAR)
    if est == DESBLOQUEANDO:
        return Entrada("Desbloqueando: la contraseña la pide VeraCrypt", activa=False)
    if est == BLOQUEANDO:
        return Entrada("Bloqueando…", activa=False)
    if est in (ABIERTA, FANTASMA):                  # a un fantasma, bloquear lo arregla
        return Entrada("Bloquear", _pide(equipo.PIDE_BLOQUEAR, id=uid), icono=I_BLOQUEAR)
    return Entrada("Desbloquear…", activa=False, icono=I_DESBLOQUEAR)


def _raices_del_equipo(resumen: Mapping[str, Any]) -> list[Entrada]:
    """Devuelve el desplegable de cada raíz de este equipo.

    Con una sola raíz cifrada, la casilla de `pedir_al_iniciar` va en el suyo.
    Una raíz abierta cuyo programa es anterior a la versión mínima del agente
    (o que una actualización dejó a medias) se dice «por actualizar» y no deja
    abrir nada suyo, como una unidad: el agente lo rechazaría en silencio
    (`Agente._abrir()`). Si es anterior a la del agente, se ofrece ponerla al
    día.
    """
    filas = {u.get("id"): u for u in resumen.get("unidades") or []}
    raices = resumen.get("equipo") or []
    una_cifrada = sum(bool(r.get("cifrada")) for r in raices) == 1
    entradas: list[Entrada] = []
    for r in raices:
        uid, nombre, est = r.get("id", ""), r.get("nombre") or APP_NAME, r.get("estado")
        fila = filas.get(uid) if est == ABIERTA else None
        vieja = _por_actualizar(fila)
        quieta = not vieja and not (fila and fila.get("actualizando"))
        hijos = _acciones(uid, abrir=quieta and est in (ABIERTA, BLOQUEADA, DESBLOQUEANDO),
                          cerrada=est in (BLOQUEADA, DESBLOQUEANDO),
                          sincronizar=not vieja and bool(fila and fila.get("atendida")),
                          llavero=_con_llavero(resumen, fila))
        hijos += _poner_al_dia(fila, resumen.get("version"))
        if r.get("cifrada"):
            hijos += [SEPARADOR, _cerrojo(uid, est)]
            if una_cifrada:
                hijos.append(_pedir_al_iniciar(resumen, varias=False))
        hijos += _version(fila)
        que = POR_ACTUALIZAR if vieja else (
            ESTADO_DE_RAIZ.get(est) or (EN_PAUSA if fila and fila.get("pausada") else None))
        entradas.append(Entrada(f"{nombre} ({que})" if que else nombre, hijos=tuple(hijos),
                                emblema=_emblema(fila)))
    return entradas


def _unidades(resumen: Mapping[str, Any]) -> list[Entrada]:
    """Devuelve el desplegable de cada unidad conectada.

    Una que no está en la lista (o cuyo código ha cambiado, o anterior a la
    versión mínima del agente) solo lleva lo que se puede hacer con ella sin
    ejecutar nada suyo, y la marca de prdrive por icono. A una de la lista con
    un programa anterior al del agente se le ofrece ponerla al día.
    """
    version = resumen.get("version")
    entradas: list[Entrada] = []
    for u in resumen.get("unidades") or []:
        if u.get("del_equipo"):
            continue
        uid, nombre = u.get("id", ""), str(u.get("nombre") or APP_NAME)
        if _por_actualizar(u):
            # No hay nada que pedirle hasta que se actualice, y se dice.
            entradas.append(Entrada(f"{nombre} ({POR_ACTUALIZAR})", hijos=(
                *_poner_al_dia(u, version), *_version(u)), emblema=MARCA))
        elif u.get("en_lista"):
            # La pausa de su ventana (#64) se dice: si no, el desplegable
            # parecería atendido y no lo está.
            entradas.append(Entrada(
                f"{nombre} ({EN_PAUSA})" if u.get("pausada") else nombre,
                hijos=(*_acciones(uid, abrir=not (u.get("actualizando") or u.get("expulsando")),
                                  cerrada=False, sincronizar=bool(u.get("atendida")),
                                  llavero=_con_llavero(resumen, u)),
                       *_poner_al_dia(u, version), *_expulsar(u), *_version(u)),
                emblema=_emblema(u)))
        elif u.get("ahora_no") or u.get("preguntando"):
            # Con otro código que el aceptado (`agente.huella()`), se dice: el
            # sí de ahora es a ese código.
            cambiada = bool(u.get("cambiada"))
            entradas.append(Entrada(
                f"{nombre} ({'código cambiado' if cambiada else 'sin atender'})",
                hijos=(Entrada("Atender con su código nuevo…" if cambiada else "Atender…",
                               _pide(equipo.PIDE_ATENDER, id=uid), icono=I_ATENDER),
                       *_version(u)),
                emblema=MARCA))
    return entradas


def _del_agente(resumen: Mapping[str, Any]) -> list[Entrada]:
    """Devuelve lo que es del agente entero y no de un dispositivo.

    «Sincronizar todo ahora» solo con dos o más dispositivos atendidos: con
    uno, repetiría su «Sincronizar ahora». Con varias raíces cifradas, la
    casilla de `pedir_al_iniciar`, que vale para todas.
    """
    entradas: list[Entrada] = []
    atendidas = [u for u in resumen.get("unidades") or [] if u.get("atendida")]
    if len(atendidas) >= 2:
        entradas.append(Entrada("Sincronizar todo ahora", tuple(
            p for u in atendidas
            for p in _pide(equipo.PIDE_PASADA, id=u.get("id"), parejas=[])),
            icono=I_SINCRONIZAR))
    if resumen.get("pausado"):
        entradas.append(Entrada("Reanudar", _pide(equipo.PIDE_SIGUE), icono=I_REANUDAR))
    else:
        entradas.append(Entrada("Pausar", _pide(equipo.PIDE_PAUSA), icono=I_PAUSAR))
    if sum(bool(r.get("cifrada")) for r in resumen.get("equipo") or []) > 1:
        entradas.append(_pedir_al_iniciar(resumen, varias=True))
    return entradas


def _actualizar(resumen: Mapping[str, Any]) -> list[Entrada]:
    """Devuelve la entrada «Actualizar», o «Buscar actualizaciones» si no se sabe de ninguna.

    Es la sección 8 del diseño. Mientras se actualiza o se busca, se dice y
    queda apagada.
    """
    nueva = resumen.get("nueva")
    if not nueva:
        if resumen.get("buscando"):
            return [Entrada("Buscando actualizaciones…", activa=False)]
        return [Entrada("Buscar actualizaciones", _pide(equipo.PIDE_BUSCAR_VERSION),
                        icono=I_REINTENTAR)]
    if resumen.get("actualizando"):
        return [Entrada(f"Actualizando a la {nueva}…", activa=False)]
    return [Entrada(f"Actualizar a la {nueva}", _pide(equipo.PIDE_ACTUALIZAR),
                    icono=I_ACTUALIZAR)]


def _version_del_agente(resumen: Mapping[str, Any]) -> list[Entrada]:
    """Devuelve la última línea del menú: «Agente X», la versión del agente, apagada.

    Es la del programa que lleva este equipo, la que «Actualizar» sustituye.
    Sin `VERSION` que leer, nada.
    """
    version = resumen.get("version")
    if not isinstance(version, str) or not version:
        return []
    # «Agente», y no el nombre del programa: en este menú, el programa ES el
    # agente, y la versión de cada unidad va dentro de la suya.
    return [Entrada(f"Agente {version}", activa=False)]


def _bloques(*bloques: list[Entrada]) -> tuple[Entrada, ...]:
    """Devuelve los bloques no vacíos, con un separador entre cada dos."""
    salida: list[Entrada] = []
    for bloque in bloques:
        if bloque:
            if salida:
                salida.append(SEPARADOR)
            salida += bloque
    return tuple(salida)


def vista(resumen: Mapping[str, Any], ahora: float | None = None) -> Vista:
    """Devuelve todo lo que enseña la bandeja, a partir del resumen del agente.

    Args:
        resumen: El resumen del agente.
        ahora: Para el «hace N min» del texto; por defecto, el reloj.
    """
    icono, frase = estado(resumen, ahora)
    hay = [entrada for _frase, entrada in _avisos(resumen)]
    cabecera = hay[:MAX_AVISOS]
    if len(hay) > MAX_AVISOS:
        cabecera.append(Entrada(f"y {len(hay) - MAX_AVISOS} más", activa=False))
    menu = _bloques(cabecera, _raices_del_equipo(resumen) + _unidades(resumen),
                    _del_agente(resumen),
                    [*_actualizar(resumen),
                     Entrada("Cerrar el agente", _pide(equipo.PIDE_PARAR), icono=I_CERRAR)],
                    _version_del_agente(resumen))
    return Vista(icono, tip(frase), menu, frase[:1].upper() + frase[1:])
