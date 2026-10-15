#!/usr/bin/env python3
"""Qué está mal en este dispositivo, como datos.

Es el diagnóstico de `sync.py --doctor` convertido en datos: para que la
interfaz pueda poner un botón al lado de cada avería hace falta que la avería
sea un dato y no una línea impresa.

Vive en `common/` y no en `ui/` porque `sync.py` no importa `ui/`: si el
diagnóstico viviera del lado de la ventana habría dos (el que enseña la
pantalla y el que imprime el subcomando) y se separarían a la primera. Aquí
solo hay uno: `--doctor` imprime `informe()` y la pantalla dibuja `revisar()`.

No toca nada y no decide nada: mira el estado y cuenta lo que ve. Qué se puede
hacer con cada avería, y cómo, es de `ui/repair.py`, que es quien sabe pedir
confirmación antes de mover un baseline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import bisync, conflicts, frenos, historial, model, results, store, vestibulo
from .model import Config, Pair

GRAVE = "grave"
"""Gravedad: no se puede sincronizar, o hacerlo arriesga datos.

Las tres gravedades no son tres colores: son tres respuestas distintas a
«¿puedo seguir usando esto?».
"""
AVISO = "aviso"
"""Gravedad: hay algo que hacer, pero nada está en peligro."""
NOTA = "nota"
"""Gravedad: informativa; normalmente se arregla sola."""


@dataclass(frozen=True)
class Hallazgo:
    """Una avería concreta.

    `clave` es lo que mira quien repara para saber de qué habla; el texto es
    para quien lo lee. `dato` lleva lo que la reparación necesita y el
    diagnóstico ya ha averiguado (las rutas de los locks, por ejemplo), para no
    recorrer el disco dos veces.

    Args:
        clave: Tipo de avería: `local`, `prefijo`, `resync`, `lock`, `espacio`,
            `conflicto`, `fallo`, `freno`, `listados`, `catalogo`.
        titulo: Frase corta.
        detalle: Explicación completa.
        pareja: La pareja afectada, o `None` si es del dispositivo.
        gravedad: `GRAVE`, `AVISO` o `NOTA`.
        dato: Lo que necesita la reparación.
    """
    clave: str
    titulo: str
    detalle: str
    pareja: str | None = None
    gravedad: str = AVISO
    dato: tuple = field(default_factory=tuple)


def _local(pair: Pair, estado: bisync.PairState) -> Hallazgo | None:
    """Devuelve la avería de una carpeta local que no está.

    Es la única de la lista que NO se repara desde aquí, a propósito: crearla
    es exactamente lo que `sync._bisync_preflight()` se niega a hacer cuando
    hay baseline, porque un lado local vacío se lee como «se ha borrado todo» y
    eso se propaga al remoto. Lo que hay que arreglar está fuera del programa
    (el volumen no está montado donde se cree, o la carpeta se movió), así que
    aquí solo se dice.
    """
    if pair.local_abs.exists():
        return None
    if pair.is_bisync and estado.has_baseline:
        return Hallazgo(
            "local", f"{nombre_visible(pair.name)}: la carpeta local no está",
            f"{pair.local_endpoint} no existe, y esta pareja ya tiene baseline. "
            "La sincronización se parará en vez de crearla: un lado vacío se lee "
            "como «se ha borrado todo». Comprueba que el volumen esté montado "
            "donde toca y que la carpeta no se haya movido; no lo arregles "
            "creándola vacía.",
            pair.name, GRAVE)
    return Hallazgo(
        "local", f"{nombre_visible(pair.name)}: la carpeta local aún no está",
        f"{pair.local_endpoint} no existe. Como esta pareja no tiene baseline "
        "que proteger, la próxima pasada la crea.",
        pair.name, NOTA)


def _prefijo(pair: Pair, estado: bisync.PairState) -> Hallazgo | None:
    """Devuelve la avería de un baseline guardado con el prefijo de OTRO destino.

    Si el prefijo esperado no es de fiar (un alias que no se puede resolver,
    `bisync.prefijo_comprobable()`) no dice nada: acusar de grave a un baseline
    que quizá es bueno, y ofrecer apartarlo, es peor que callar.
    """
    esperado = bisync.expected_prefix(pair)
    if not estado.prefix or estado.prefix == esperado:
        return None
    if not bisync.prefijo_comprobable(pair):
        return None
    return Hallazgo(
        "prefijo", f"{nombre_visible(pair.name)}: el baseline no es de esta pareja",
        f"Está guardado como «{estado.prefix}» y esta pareja espera "
        f"«{esperado}», así que rclone no lo va a encontrar. Pasa cuando cambia "
        "un extremo (la carpeta local, el remoto o su ruta). Se aparta y se "
        "rehace con un --resync.",
        pair.name, GRAVE, (estado.prefix, esperado))


def carpeta_programa_en_remoto(pair: Pair) -> str | None:
    """Devuelve dónde quedó en el remoto el programa que subió una pareja de la raíz.

    Es la decisión de «hay que avisar de que se borre a mano» y la comparten el
    hallazgo `resync`, la pregunta de la ventana y la de `sync.py`: tiene que
    dar la misma respuesta en los tres, y tiene que darse ANTES del `--resync`,
    porque después el listado nuevo ya no enseña la carpeta. La ruta se arma con
    `remote_name` y `remote_path` tal como están: `remote_path = ""` es
    relativa al origen del remote (`nas:.prdrive/`) y `"/"` absoluta
    (`nas:/.prdrive/`), y no son lo mismo en SFTP.

    Returns:
        La carpeta (`nas:R/p/.prdrive/`), o `None` si la pareja no es de la raíz
        entera o su listado no la trae.
    """
    if not (pair.es_raiz and bisync.programa_en_listado(pair)):
        return None
    base = pair.remote_path.rstrip("/") or pair.remote_path[:1]
    if base and not base.endswith("/"):
        base += "/"
    return f"{pair.remote_name}:{base}{model.APP_DIR.name}/"


def aviso_carpeta_programa(carpeta: str) -> str:
    """Devuelve la frase que dice dónde borrar a mano la copia del programa.

    El `--resync` deja de subir la carpeta del programa pero no la borra del
    remoto: el código no borra nada ahí, y esa copia lleva la clave.
    """
    return ("El resync deja de subir la carpeta del programa, pero no la borra del "
            f"remoto: bórrala tú de {carpeta}, que lleva la clave.")


def dato_resync(pair: Pair) -> tuple:
    """Devuelve el `dato` de un hallazgo `resync` de esa pareja.

    Es dónde está en el remoto la copia del programa que subió una pareja de la
    raíz entera (`carpeta_programa_en_remoto()`), para que la confirmación del
    resync (`ui/repair.aviso_resync()`) lo diga; va en una tupla porque
    `Hallazgo` es inmutable. Lo arman con esta misma función el diagnóstico
    (`_resync()`) y el resync que pide la persona sin que el diagnóstico lo
    vea (`ui/repair.hallazgo_resync()`), así que el aviso es el mismo vengan de
    donde vengan.

    Returns:
        `(carpeta,)`, o `()` si no hay copia que decir.
    """
    carpeta = carpeta_programa_en_remoto(pair)
    return (carpeta,) if carpeta is not None else ()


def _resync(pair: Pair, estado: bisync.PairState) -> Hallazgo | None:
    """Devuelve la avería de una pareja que pide `--resync` y nadie lo ha hecho.

    La del llavero no la tiene: se resincroniza sola en su próxima pasada
    (`sync._bisync_preflight()`).

    Si es una pareja de la raíz entera que subió la carpeta del programa, el
    `dato` es dónde está esa copia en el remoto (`dato_resync()`); si no, va
    vacío.
    """
    if pair.llavero:
        return None
    razones = bisync.resync_reasons(pair, estado)
    if not razones:
        return None
    detalle = ("; ".join(razones) + ". Hasta que se haga, esta pareja se salta en "
               "cada pasada: el servicio no resincroniza solo, nunca.")
    dato = dato_resync(pair)
    if dato:
        detalle += (" Hasta ahora subía la carpeta del programa (con su clave y "
                    "rclone.conf) al remoto.")
    return Hallazgo(
        "resync", f"{nombre_visible(pair.name)} necesita un --resync", detalle,
        pair.name, AVISO, dato)


def _locks(pair: Pair) -> Hallazgo | None:
    """Devuelve la avería de los locks de bisync que han quedado sueltos."""
    try:
        sueltos = sorted(pair.workdir.glob("*.lck"))
    except OSError:
        return None
    if not sueltos:
        return None
    return Hallazgo(
        "lock", f"{nombre_visible(pair.name)}: hay {len(sueltos)} bloqueo(s) sin dueño",
        "Los deja una pasada que se cortó a medias, y mientras estén ahí bisync "
        "se niega a empezar. Solo se pueden borrar si no hay ninguna "
        "sincronización en curso.",
        pair.name, AVISO, tuple(sueltos))


def nombre_visible(pareja: str) -> str:
    """Devuelve cómo se nombra una pareja en un título: «notas», o «El llavero».

    La del llavero no se nombra por su pareja (`keychain`): la pone prdrive, no
    la persona.
    """
    return "El llavero" if pareja == model.LLAVERO else f"«{pareja}»"


def _conflictos(config: Config) -> list[Hallazgo]:
    """Devuelve las averías de ficheros que cambiaron en los dos lados.

    Se lee lo apuntado y no se recorre el disco: lo llama la ventana al
    pintarse.
    """
    try:
        cuentas = conflicts.contar(conflicts.cargar(config))
    except Exception:                                   # noqa: BLE001
        return []
    return [Hallazgo(
        "conflicto", *_frases_conflicto(nombre, n), nombre, AVISO, (n,))
        for nombre, n in cuentas.items() if n]


def _frases_conflicto(nombre: str, n: int) -> tuple[str, str]:
    """Devuelve el título y la explicación de los conflictos de una pareja.

    La del llavero no se nombra por su pareja (`keychain`, que la persona no ha
    puesto) y no se elige: se combina.
    """
    if nombre == model.LLAVERO:
        return ("El llavero: la base tiene copias de conflicto",
                "Dos dispositivos la cambiaron sin sincronizar en medio. «Combinar» junta "
                "lo de las dos sin perder nada; «Abrir llavero» lo ofrece antes de abrir.")
    return (f"«{nombre}»: {n} fichero(s) en conflicto" if n > 1
            else f"«{nombre}»: 1 fichero en conflicto",
            "Cambiaron en los dos lados entre dos pasadas, así que hay dos versiones "
            "y se van separando. Hay que elegir con cuál te quedas.")


def _dia(sello: str) -> str:
    """Devuelve la fecha como «12/09», o «12/09/2025» si no es de este año."""
    cuando = datetime.strptime(sello, store.FORMATO)
    return f"{cuando:%d/%m}" if cuando.year == datetime.now().year else f"{cuando:%d/%m/%Y}"


def _frase_racha(racha: historial.Racha) -> str:
    """Resume en una frase desde cuándo falla y cuántas pasadas recientes fueron bien.

    Por ejemplo: «Falla desde el 12/09 · 0 de las últimas 14 bien.» Dice «al
    menos» cuando el diario no ve dónde empezó la racha (todas las que constan
    fallaron): puede que fallara desde antes de que el diario existiera, y una
    fecha que parece exacta y no lo es haría buscar la causa en el día
    equivocado.
    """
    desde = ("Falla desde el " if racha.exacta else "Falla al menos desde el ")
    cuenta = ("es la única pasada que consta" if racha.pasadas == 1
              else f"{racha.buenas} de las últimas {racha.pasadas} bien")
    return f"{desde}{_dia(racha.desde)} · {cuenta}."


def _freno(fallo: results.Fallo, pair: Pair | None) -> frenos.Freno | None:
    """Devuelve el freno de borrados que paró esa pasada, o `None` si falló por otra cosa.

    Lo dice el log de la pasada (`frenos.detectar()`, el mismo reconocimiento que
    usa la consola de `sync.py`). Sin log, o sin poder leerlo, no hay nada que
    reconocer y la avería sigue siendo un fallo cualquiera.
    """
    if fallo.log is None or pair is None:
        return None
    try:
        return frenos.detectar_en(fallo.log, pair)
    except OSError:
        return None


def _frase_freno(pair: Pair, freno: frenos.Freno) -> tuple[str, str]:
    """Devuelve el título y lo que pasó, en la unidad de ese freno.

    El de bisync es un porcentaje del listado anterior y el de un espejo una
    cuenta de ficheros (AGENTS.md, «Safety invariants»): cada texto habla solo
    de la suya.
    """
    nombres = [frenos.nombre_lado(lado) for lado in freno.lados]
    if freno.tipo == frenos.CAMBIADOS:
        donde = " y ".join(nombres) or "un lado"
        a_donde = (f" {frenos.hacia(frenos.otro_lado(freno.lados[0]))}"
                   if len(freno.lados) == 1 else "")
        return ("el freno de seguridad ha parado la sincronización",
                f"Desde la última sincronización han cambiado todos los ficheros en {donde} "
                "(pasa, por ejemplo, con un cambio de hora o al tocar toda la carpeta). "
                f"bisync se paró para no copiarlo todo de nuevo{a_donde}.")
    if freno.tipo == frenos.ESPEJO:
        destino = frenos.nombre_lado(freno.lados[0])
        origen = frenos.nombre_lado(frenos.otro_lado(freno.lados[0]))
        hecho = (f"Ya ha borrado {freno.borrados} ficheros en {destino}, que es lo máximo que "
                 "permite su freno (una cuenta de ficheros), y se paró"
                 if freno.borrados else
                 f"Se paró en el freno de borrados de {destino} (una cuenta de ficheros)")
        faltan = (f": faltan {freno.pendientes} por borrar" if freno.pendientes else "")
        return ("el freno de borrados ha parado el espejo",
                f"Esta pareja es un espejo: deja {destino} igual que {origen}, borrando lo que "
                f"sobra. {hecho}{faltan}. Lo ya borrado no vuelve solo.")
    lado = nombres[0] if nombres else None
    if freno.borrados is None or lado is None:
        return ("el freno de borrados ha parado la sincronización",
                "Se habían borrado demasiados ficheros respecto a la última sincronización y "
                "bisync se paró para no copiar ese borrado al otro lado.")
    return ("el freno de borrados ha parado la sincronización",
            f"Se han borrado {freno.borrados} de {freno.total} ficheros ({freno.porcentaje} %) "
            f"en {lado} desde la última sincronización, y el freno de bisync salta por encima "
            f"del {freno.tope} %. La pasada se paró para no copiar ese borrado "
            f"{frenos.hacia(frenos.otro_lado(freno.lados[0]))}.")


def _como_argumento(nombre: str) -> str:
    """Devuelve el nombre de una pareja tal como se escribe en una línea de órdenes.

    Con comillas dobles si lleva algo más que letras, cifras, `_`, `.` o `-`
    («Mis fotos»): valen en `cmd`, en PowerShell y en un intérprete POSIX.
    """
    return nombre if re.fullmatch(r"[\w.-]+", nombre) else f'"{nombre}"'


def _hallazgo_freno(pair: Pair, freno: frenos.Freno, log: Path | None,
                    racha: historial.Racha | None) -> Hallazgo:
    """Devuelve el hallazgo del freno que paró la última pasada de esa pareja.

    Sustituye al `fallo` de la pareja, nunca va además. El `dato` lleva el log y el
    freno con sus cifras, que es lo que necesita `ui/repair.py` para el plan.
    """
    titulo, que = _frase_freno(pair, freno)
    if pair.llavero:
        # Sus bases son contraseñas: no se ofrece forzar, ni se dice «si es lo que querías».
        # Lo que se puede hacer lo dice `frenos`, igual que la consola.
        detalle = f"{que} {frenos.salida_llavero(freno.tipo)}"
        if racha is not None:
            detalle += f" {_frase_racha(racha)}"
        return Hallazgo("freno", f"{nombre_visible(pair.name)}: {titulo}", detalle,
                        pair.name, AVISO, (log, freno))
    if freno.tipo == frenos.ESPEJO:
        riesgo = ("Si el origen está vacío o desmontado, lo borrado es un error: "
                  "compruébalo antes de seguir.")
    elif freno.tipo == frenos.CAMBIADOS:
        riesgo = ("Si no lo esperabas, mira qué ha tocado esos ficheros antes de seguir: "
                  "copiarlo todo de nuevo pisa lo que haya al otro lado.")
    else:
        riesgo = ("Puede ser lo que querías o un error (el dispositivo sin montar donde "
                  "toca, la carpeta equivocada): mira ese lado antes de seguir.")
    detalle = f"{que} {riesgo}"
    if racha is not None:
        detalle += f" {_frase_racha(racha)}"
    detalle += (" Mientras no se resuelva, eso no está sincronizado. Si es lo que querías, se "
                f"puede forzar UNA pasada: `python sync.py {_como_argumento(pair.name)} --force`.")
    return Hallazgo("freno", f"{nombre_visible(pair.name)}: {titulo}", detalle,
                    pair.name, AVISO, (log, freno))


def _fallos(config: Config) -> list[Hallazgo]:
    """Devuelve las averías de las parejas cuya última pasada falló.

    Las que paró un freno de borrados (`frenos.detectar()`) son un hallazgo
    propio, con cifras y sin ser además un fallo. El resto no tiene reparación:
    son un informe, y lo que se ofrece es el log que lo explica. Del diario de
    pasadas sale desde cuándo falla, que distingue un tropiezo de una avería; sin
    diario (un dispositivo recién actualizado o que no se deja leer) la avería se
    cuenta igual, sin esa frase.

    El llavero no está en `Config.names`, pero si un freno lo para (tras la repetición
    que ya hace `sync.repetir_sin_freno()`) entra aquí, con su nombre y sin que se
    ofrezca forzarlo (#115). Un fallo suyo que no es un freno (sin red) sigue sin
    hallazgo: ya lo dice la línea del llavero y se reintenta solo.
    """
    try:
        fallos = results.fallos(config)
        if config.pareja_llavero is not None:
            fallos += results.fallos_de([model.LLAVERO])
    except Exception:                                   # noqa: BLE001
        return []
    try:
        rachas = historial.rachas(f.pareja for f in fallos)
    except Exception:                                   # noqa: BLE001
        rachas = {}
    parejas = {p.name: p for p in config.pairs}
    hallazgos = []
    for f in fallos:
        racha = rachas.get(f.pareja)
        freno = _freno(f, parejas.get(f.pareja))
        if freno is None and f.pareja == model.LLAVERO:
            continue
        if freno is not None:
            hallazgos.append(_hallazgo_freno(parejas[f.pareja], freno, f.log, racha))
            continue
        hallazgos.append(Hallazgo(
            "fallo", f"{nombre_visible(f.pareja)}: la última pasada falló",
            f"Acabó con código {f.codigo}" + (f" el {f.cuando}" if f.cuando else "") +
            (". El log lo explica." if f.log else ". No queda log de aquella pasada.") +
            (f" {_frase_racha(racha)}" if racha is not None else "") +
            " Mientras no se arregle, eso no está sincronizado.",
            f.pareja, AVISO, (f.log,)))
    return hallazgos


def _listados_sueltos() -> Hallazgo | None:
    """Devuelve la avería de los listados sueltos en la raíz de `state/`.

    Son del layout de una sola carpeta.
    """
    try:
        sueltos = sorted(model.STATE_DIR.glob("*.lst")) if model.STATE_DIR.exists() else []
    except OSError:
        return None
    if not sueltos:
        return None
    return Hallazgo(
        "listados", f"{len(sueltos)} listado(s) sueltos en state/",
        "Son del reparto antiguo, cuando todas las parejas compartían carpeta. "
        "Se reparten solos en la próxima pasada de cada pareja.",
        None, NOTA, tuple(sueltos))


def _espacio(fisica: Path | None | object = vestibulo.BUSCAR) -> Hallazgo | None:
    """Devuelve la avería de un contenedor dinámico al que se acaba el sitio fuera.

    Un contenedor dinámico (disperso) crece a medida que se escribe dentro, así
    que su sitio libre de verdad es el de la unidad física. Cuando se acaba, el
    volumen de dentro da errores de E/S en mitad de lo que esté escribiendo (un
    bisync, por ejemplo) y rclone no puede explicar por qué: desde dentro el
    disco no está lleno. No tiene botón: la salida es liberar sitio fuera del
    contenedor.

    `fleet` se importa dentro: es el que sabe leer el id del fichero de control
    y arrastra el catálogo, que el resto de este módulo no necesita. Solo se
    importa y se pregunta si hay que buscar la raíz física.

    Args:
        fisica: La raíz física si quien llama ya la tiene (`None` es «no vive en
            un contenedor»); con `vestibulo.BUSCAR` se busca por el id del
            dispositivo.
    """
    try:
        if fisica is vestibulo.BUSCAR:
            from . import fleet
            falta = vestibulo.sin_sitio_fuera(fleet.device_id())
        else:
            falta = vestibulo.sin_sitio_fuera("", fisica)
    except Exception:                                # noqa: BLE001
        return None
    if falta is None:
        return None
    fisica, libre = falta
    return Hallazgo(
        "espacio", "El contenedor se queda sin sitio fuera",
        f"{vestibulo.CONTENEDOR} es dinámico: crece a medida que se escribe "
        f"dentro, y en {fisica} quedan {libre / 1024 ** 2:.0f} MB libres. Si se "
        "llena, lo de dentro empieza a dar errores de escritura en mitad de una "
        "sincronización. Libera sitio en la unidad, fuera del contenedor.",
        None, AVISO, (str(fisica), libre))


def _catalogo_duplicado() -> Hallazgo | None:
    """Devuelve la avería de un remoto con los dos nombres del catálogo a la vez.

    Sale de lo que se apuntó la última vez que alguien miró la carpeta del
    catálogo (`catalog.duplicado()`), sin red. Pasa si una subida a
    `pairs.toml` se cruza con el renombrado a `remote.toml`: vale
    `remote.toml`, el que se busca primero, y lo que llevara el otro no cuenta.
    No tiene botón aquí porque es una operación en el remoto: la hace
    «Renombrar el catálogo…», en «Ajustes».

    `catalog` se importa dentro, como `fleet` en `_espacio()`.
    """
    try:
        from . import catalog
        apuntado = catalog.duplicado()
    except Exception:                                # noqa: BLE001
        return None
    if apuntado is None:
        return None
    sobra, visto = apuntado
    carpeta = catalog.partir(sobra)[0]
    cuando = f" (visto el {visto})" if visto else ""
    return Hallazgo(
        "catalogo", "En el remoto hay dos catálogos",
        f"En {carpeta} están {catalog.FICHERO} y {catalog.FICHERO_ANTERIOR}{cuando}. "
        f"Vale {catalog.FICHERO}, que es el que buscan primero todos los "
        f"dispositivos; {catalog.FICHERO_ANTERIOR} lo dejó una subida que se cruzó "
        f"con el renombrado, y el cambio que llevara no cuenta. Mira en «Parejas» "
        f"si falta algo y, si falta, repítelo allí. Después, en «Ajustes» → "
        f"«Renombrar el catálogo…», aparta el {catalog.FICHERO_ANTERIOR} que sobra.",
        None, AVISO, (sobra,))


def revisar(config: Config, *,
            fisica: Path | None | object = vestibulo.BUSCAR) -> list[Hallazgo]:
    """Devuelve todo lo que está mal ahora mismo, lo más grave primero.

    No habla con el remoto ni lanza rclone: lee el dispositivo, lo que permite
    llamarlo mientras se pinta una ventana. Lo único que puede escribir es
    `filters/<pareja>.txt`, y no es cosa suya: lo regenera
    `bisync.resync_reasons()` cuando el contenido ha cambiado, que es justo lo
    que hace falta saber para decir si la pareja pide un resync.

    Args:
        config: La configuración a revisar.
        fisica: La raíz física del contenedor, si quien llama ya la ha buscado
            (`ui/instantanea.py` la busca una vez para todas sus lecturas);
            `None` es «no vive en un contenedor». Por defecto se busca.
    """
    hallazgos: list[Hallazgo] = []
    for pair in config.pairs:
        estado = (bisync.pair_state(pair) if pair.is_bisync
                  else bisync.PairState("fresh", "no es bisync", None))
        for hallazgo in (_local(pair, estado), _prefijo(pair, estado),
                         _resync(pair, estado), _locks(pair)):
            if hallazgo is not None:
                hallazgos.append(hallazgo)
    hallazgos += _conflictos(config)
    hallazgos += _fallos(config)
    for hallazgo in (_listados_sueltos(), _espacio(fisica), _catalogo_duplicado()):
        if hallazgo is not None:
            hallazgos.append(hallazgo)

    orden = {GRAVE: 0, AVISO: 1, NOTA: 2}
    return sorted(hallazgos, key=lambda h: orden.get(h.gravedad, 9))


def cuenta(hallazgos: list[Hallazgo]) -> int:
    """Devuelve cuántas cosas hay que mirar.

    Las notas no cuentan: se arreglan solas, y un aviso que no pide nada de
    nadie es ruido en la ventana principal.
    """
    return sum(1 for h in hallazgos if h.gravedad in (GRAVE, AVISO))


def _informe_pareja(pair: Pair) -> list[str]:
    """Devuelve las líneas del informe de una pareja.

    Con una línea en blanco al final.
    """
    lineas = [f"[{pair.name}] {pair.mode.name}",
              f"  local : {pair.local_endpoint} "
              f"{'(OK)' if pair.local_abs.exists() else '(NO EXISTE)'}",
              f"  remoto: {pair.remote_endpoint}"]
    if not pair.is_bisync:
        return lineas + [""]

    estado = bisync.pair_state(pair)
    sin_fiar = ("" if bisync.prefijo_comprobable(pair) else
                " (no se puede comprobar: un alias del rclone.conf no se puede resolver)")
    lineas += [f"  estado: {estado.status} — {estado.detail}",
               f"  prefijo esperado: {bisync.expected_prefix(pair)}{sin_fiar}"]
    if bisync.referencia_vacia(pair, estado):
        lineas.append("  referencia: vacía — la próxima pasada la rehace con --resync "
                      "(no hay nada que proteger)")
    filtros = bisync.filters_state(bisync.filters_file_for(pair))
    lineas.append(f"  filtros: {filtros.status} — {filtros.detail}")

    if pair.workdir.exists():
        for f in sorted(pair.workdir.iterdir()):
            if f.is_file():
                cuando = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                lineas.append(f"    {f.name:<62} {cuando}")
    return lineas + [""]


def informe(config: Config) -> list[str]:
    """Devuelve el informe completo, línea a línea, para quien no tiene pantalla.

    Lleva más que `revisar()` (las rutas resueltas, el entorno del combine, los
    ficheros del workdir con su fecha) porque eso es lo que se pega en un
    mensaje cuando algo no cuadra. Las averías son las mismas: salen de
    `revisar()`, así que el subcomando y la pantalla no pueden discrepar.
    """
    lineas = [f"Dispositivo detectado en: {model.DEVICE_ROOT}",
              f"Workdir de estado: {model.STATE_DIR}"]
    lineas += [f"  {clave}={valor}" for clave, valor in config.pen_environment().items()]
    lineas.append("")
    for pair in config.pairs:
        lineas += _informe_pareja(pair)

    hallazgos = revisar(config)
    if not hallazgos:
        lineas.append("Sin incidencias.")
        return lineas
    lineas.append(f"{len(hallazgos)} cosa(s) que revisar:")
    for h in hallazgos:
        lineas.append(f"  {h.gravedad.upper():<6} {h.titulo}")
        lineas.append(f"         {h.detalle}")
    return lineas
