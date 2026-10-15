#!/usr/bin/env python3
"""Qué se puede hacer con una avería, sin Tkinter.

Mismo guion que `pair_editor` y `conflict_editor`, y por el mismo motivo: aquí
se piensa un plan y se enseñan sus consecuencias, y solo si la persona dice que
sí se toca el disco. Apartar un baseline es la operación que puede acabar en un
borrado masivo, así que no hay ninguna reparación que ocurra sola, ni al abrir
la pantalla ni después.

Qué está mal lo dice `common/revision.py`; aquí solo se contesta a «¿y qué hago
con esto?». Hay tres respuestas posibles:
- un plan (`plan_*`), que se confirma y se ejecuta;
- una orden para `sync.py` (`args_*`), que se lanza en la ventana de salida
  porque eso es una sincronización de verdad, con su registro y su log; algunas
  se confirman antes (`aviso_resync()`, `aviso_forzar()`);
- nada, que es el caso de la carpeta local que no está (ver `revision._local`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from common import bisync, frenos, model, revision, store
from common.model import Config, Pair
from common.revision import Hallazgo, aviso_carpeta_programa

from . import prefs


ETIQUETA_SIMULAR = "Ver qué se borraría"
"""El botón que lanza la simulación forzada; el plan de forzar lo nombra para recomendarla."""


class ReparacionImposible(Exception):
    """Lo que se pide no se puede hacer; el mensaje es para la persona."""


def borrar(ruta: Path) -> None:
    """Borra un fichero.

    Es de módulo para que un test lo haga fallar.
    """
    ruta.unlink()


def apartar(nombre: str) -> Path | None:
    """Aparta el baseline de esa pareja.

    Es de módulo para que un test lo haga fallar.
    """
    return bisync.shelve_baseline(nombre)


def sincronizacion_en_curso() -> str | None:
    """Devuelve quién está sincronizando ahora mismo, o `None` si nadie.

    Se mira antes de borrar un bloqueo, que es lo único de aquí que podría
    hacer daño en caliente: quitarle el lock a una pasada viva deja que empiece
    otra sobre los mismos ficheros. Ante la duda se dice que sí lo hay: un
    registro de OTRO equipo no se puede comprobar (`pid_alive` solo sabe de los
    procesos de esta máquina) y equivocarse hacia «no se puede borrar» no rompe
    nada, mientras que equivocarse hacia el otro lado sí. Uno de este equipo
    pero de antes de reiniciar sí se sabe que es un resto: su pid ya es de otro
    proceso.
    """
    info = store.read_json(model.daemon_lock())
    if not info:
        return None
    host = info.get("host")
    try:
        pid = int(info.get("pid", -1))
    except (TypeError, ValueError):
        pid = -1
    if host == prefs.HOST and not store.vivo_en_este_arranque(info, prefs.HOST):
        return None                     # rastro de un servicio que ya no está
    quien = "el servicio periódico" if host == prefs.HOST else f"el servicio de {host}"
    return f"{quien} (pid {pid})"


@dataclass
class RepairPlan:
    """Lo que se va a hacer, antes de hacerlo.

    Mismo contrato que `pair_editor.EditPlan`: `consequences` y `warnings` se
    enseñan en `tk_pairs.confirmar_plan()` y `execute()` solo se llama si la
    persona ha dicho que sí.

    Args:
        titulo: Cómo se llama la reparación.
        consequences: Una línea por consecuencia.
        warnings: Lo que conviene saber antes de confirmar.
        _hacer: Lo que toca el disco; devuelve qué ha hecho.
    """
    titulo: str
    consequences: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _hacer: Callable[[], list[str]] | None = None

    def execute(self) -> list[str]:
        """Hace la reparación y devuelve qué ha hecho, para poder contarlo."""
        return list(self._hacer()) if self._hacer is not None else []


def vigente(config: Config, hallazgo: Hallazgo) -> Hallazgo | None:
    """Vuelve a mirar el dispositivo y devuelve esa avería tal como está ahora.

    La pantalla puede haber pintado la lista desde una lectura anterior (la que
    hizo la ventana principal al abrirse), y entre aquella lectura y el clic
    puede haberse soltado un bloqueo, haberse apartado un baseline o haber
    empezado una pasada. Antes de pensar un plan se mira otra vez, y el plan se
    hace con lo que se encuentra ahora y no con lo que se vio. Es la misma
    avería si coinciden la clave y la pareja.

    Args:
        config: La configuración del dispositivo.
        hallazgo: La avería que la persona ha elegido en pantalla.

    Returns:
        La avería recién leída, o `None` si ya no está.

    Raises:
        Exception: Lo que lance `revision.revisar()`; quien llama decide qué
            decir, pero no debe hacer un plan sin haber podido mirar.
    """
    for fresco in revision.revisar(config):
        if (fresco.clave, fresco.pareja) == (hallazgo.clave, hallazgo.pareja):
            return fresco
    return None


def _ocupado(quien: str) -> ReparacionImposible:
    """Devuelve el error de «hay una pasada en marcha» para quien esté sincronizando."""
    return ReparacionImposible(
        f"Ahora mismo está sincronizando {quien}. Un bloqueo solo se borra "
        "cuando no hay ninguna pasada en marcha: espera a que termine.")


def _pareja(config: Config, nombre: str | None) -> Pair:
    """Devuelve la pareja de ese nombre.

    Raises:
        ReparacionImposible: Si ya no está en la configuración.
    """
    pair = next((p for p in config.pairs if p.name == nombre), None)
    if pair is None:
        raise ReparacionImposible(
            f"La pareja «{nombre}» ya no está en la configuración: vuelve a abrir "
            "la pantalla para ver cómo está ahora.")
    return pair


def plan_apartar(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan de apartar el baseline de una pareja.

    Es para rehacerlo con un `--resync`. Se APARTA, no se borra: el directorio
    se renombra a `state/<pareja>.old-…` y queda inerte, por si hiciera falta
    volver a mirarlo. Y no se reaprovecha bajo el nombre nuevo, que es la
    tentación: eso le diría a bisync que el listado del destino viejo describe
    el nuevo y todo lo que no estuviera en el nuevo se leería como borrado.

    Raises:
        ReparacionImposible: Si la pareja o su baseline ya no están.
    """
    pair = _pareja(config, hallazgo.pareja)
    estado = bisync.pair_state(pair)
    if not estado.has_baseline:
        raise ReparacionImposible(
            f"«{pair.name}» ya no tiene baseline que apartar. Vuelve a abrir la "
            "pantalla para ver cómo está ahora.")

    def hacer() -> list[str]:
        """Aparta el baseline y dice dónde ha quedado.

        Vuelve a mirar que el baseline siga ahí: entre el plan y el «sí» ha
        podido apartarlo otra pantalla, y apartar lo que ya no está no es lo
        que se confirmó.
        """
        if not bisync.pair_state(pair).has_baseline:
            raise ReparacionImposible(
                f"«{pair.name}» ya no tiene baseline que apartar. Vuelve a abrir la "
                "pantalla para ver cómo está ahora.")
        destino = apartar(pair.name)
        if destino is None:
            raise ReparacionImposible(
                f"No he encontrado el baseline de «{pair.name}» para apartarlo.")
        return [f"El baseline de «{pair.name}» está ahora en {destino.name}"]

    return RepairPlan(
        f"Apartar el baseline de «{pair.name}»",
        [f"El contenido de state/{pair.name}/ se mueve a state/{pair.name}.old-<fecha>/",
         f"«{pair.name}» queda como si nunca se hubiera sincronizado",
         "No se borra nada: el baseline apartado se queda ahí, inerte"],
        ["Hasta que hagas el --resync, esa pareja se salta en cada pasada.",
         "El --resync vuelve a comparar los dos lados enteros y puede tardar."],
        hacer)


def plan_locks(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan de borrar los `.lck` que dejó una pasada cortada a medias.

    Lo único que hace falta saber para que esto sea seguro es que no haya nada
    sincronizando, y eso el programa sí lo sabe: el servicio se apunta en
    `state/daemon.lock.json` y la ventana, mientras hay una pasada en curso,
    apaga lo que toca el mismo estado.

    Raises:
        ReparacionImposible: Si hay una sincronización en marcha o los bloqueos
            ya no están.
    """
    pair = _pareja(config, hallazgo.pareja)
    ocupado = sincronizacion_en_curso()
    if ocupado:
        raise _ocupado(ocupado)

    sueltos = [Path(r) for r in hallazgo.dato if Path(r).exists()]
    if not sueltos:
        raise ReparacionImposible(
            f"Los bloqueos de «{pair.name}» ya no están: seguramente los ha "
            "soltado la pasada que los dejó.")

    def hacer() -> list[str]:
        """Borra los bloqueos sueltos y dice cuáles.

        Vuelve a mirar si alguien sincroniza: entre el plan y el «sí» ha podido
        empezar una pasada, y un bloqueo solo se borra si no hay ninguna.
        """
        ocupado = sincronizacion_en_curso()
        if ocupado:
            raise _ocupado(ocupado)
        hechos = []
        for ruta in sueltos:
            try:
                borrar(ruta)
                hechos.append(f"Borrado {ruta.name}")
            except FileNotFoundError:
                pass                      # ya no estaba: lo que se quería
            except OSError as e:
                raise ReparacionImposible(
                    f"No se ha podido borrar {ruta.name}:\n\n{e}") from e
        return hechos

    return RepairPlan(
        f"Borrar los bloqueos de «{pair.name}»",
        [f"Se borran {len(sueltos)} fichero(s) de bloqueo en state/{pair.name}/",
         "No se toca ningún fichero tuyo: un .lck solo dice «aquí hay una pasada»"],
        ["Si hubiera una sincronización en marcha que no consta, quedaría sin su "
         "bloqueo y otra podría empezar encima. Comprueba que no la haya."],
        hacer)


PLANES = {"prefijo": plan_apartar, "lock": plan_locks}
"""Qué plan resuelve cada clave de hallazgo."""


def plan_para(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan de esa avería.

    Raises:
        ReparacionImposible: Si no tiene.
    """
    fabricar = PLANES.get(hallazgo.clave)
    if fabricar is None:
        raise ReparacionImposible("Esta avería no se arregla desde aquí.")
    return fabricar(config, hallazgo)


def tiene_plan(hallazgo: Hallazgo) -> bool:
    """Indica si esa avería tiene un plan de reparación."""
    return hallazgo.clave in PLANES


def args_resync(hallazgo: Hallazgo) -> list[str]:
    """Devuelve los argumentos de `sync.py` para rehacer el baseline de esa pareja.

    Lleva `--yes` porque la pregunta ya se ha hecho: quien pulsa aquí acaba de
    leer en su confirmación qué es un resync. Sin él, `sync.py` la haría por
    stdin, que detrás de una ventana no existe, y la pareja se saltaría.
    """
    return [str(hallazgo.pareja), "--resync", "--yes"]


def args_simular(nombres: list[str]) -> list[str]:
    """Devuelve los argumentos de `sync.py` para una pasada de mentira de esas parejas.

    Sin `--yes`, a propósito y por lo mismo que en
    `pair_editor.simular_args()`: una pareja sin baseline tiene que volver
    «Saltada: requiere --resync», que es justo lo que interesa leer antes de
    aprobar nada.
    """
    return [*nombres, "--dry-run"]


def aviso_resync(hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan, sin disco, de confirmar un resync.

    No es un plan de disco (lo hace rclone), pero se confirma igual: es la
    operación que vuelve a comparar los dos lados enteros.

    Si el hallazgo trae la copia de la carpeta del programa que subió una pareja
    de la raíz entera (`dato`), lo avisa aquí y no después: el resync deja de
    subirla pero no la borra, y el listado nuevo ya no la enseñaría.
    """
    avisos = ["Puede tardar, según lo que haya que listar.",
              "Si la pareja guarda versiones, lo que el resync sobrescriba se guarda "
              "en .prversions/."]
    if hallazgo.dato:
        avisos.append(aviso_carpeta_programa(hallazgo.dato[0]))
    return RepairPlan(
        f"Resincronizar «{hallazgo.pareja}»",
        ["Se rehace el baseline de la pareja: rclone compara los dos lados "
         "enteros y se queda con lo que hay ahora en cada uno",
         "No se borra nada por estar en un solo lado: un resync junta, no iguala"],
        avisos)


def _freno_de(hallazgo: Hallazgo) -> frenos.Freno | None:
    """Devuelve el freno que explica un hallazgo `freno`, o `None` si no lo es o no lo trae."""
    if hallazgo.clave != "freno" or len(hallazgo.dato) < 2:
        return None
    return hallazgo.dato[1] if isinstance(hallazgo.dato[1], frenos.Freno) else None


def puede_forzar(hallazgo: Hallazgo) -> bool:
    """Indica si «Forzar sincronización…» se ofrece para ese hallazgo.

    Solo en un freno de borrados, y nunca en el del llavero: su salida es
    «Combinar», no saltarse el freno de unas bases de contraseñas.
    """
    return _freno_de(hallazgo) is not None and hallazgo.pareja != model.LLAVERO


def puede_simular_forzado(hallazgo: Hallazgo) -> bool:
    """Indica si se ofrece ver qué borraría la pasada forzada antes de forzarla.

    Donde hay borrados: el freno de bisync por borrados y el de un espejo. Cuando
    lo que paró bisync es que cambiaron todos los ficheros, la simulación no
    tiene borrados que enseñar.
    """
    freno = _freno_de(hallazgo)
    return puede_forzar(hallazgo) and freno.tipo in (frenos.BORRADOS, frenos.ESPEJO)


def args_forzar(hallazgo: Hallazgo, *, simular: bool = False) -> list[str]:
    """Devuelve los argumentos de `sync.py` para forzar UNA pasada de esa pareja.

    Lleva `--force`, que `sync.py` convierte en lo que salta el freno de cada modo
    (`orden.flags_de_la_pasada()`) y solo para esa ejecución. Sin `--yes` ni
    `--resync`: forzar no aprueba nada más, y una pareja que pidiera un resync se
    saltaría. Con `simular`, la misma pasada en `--dry-run`, que nombra lo que
    borraría sin tocar nada.

    Args:
        hallazgo: El freno que se fuerza.
        simular: Si es la pasada de prueba.
    """
    return [str(hallazgo.pareja), "--force", *(["--dry-run"] if simular else [])]


def _carpeta_vacia(ruta: Path) -> bool:
    """Indica si la carpeta existe y no tiene nada dentro (ante un error, que no)."""
    try:
        return next(ruta.iterdir(), None) is None
    except OSError:
        return False


def _tope(pair: Pair, freno: frenos.Freno) -> int | None:
    """Devuelve el tope que la pareja llevará en la próxima pasada (`max-delete`), o `None`."""
    valor = pair.flags.get("max-delete", freno.tope)
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _versiones(pair: Pair, que: str) -> str:
    """Devuelve la advertencia sobre si lo que se pise o borre al otro lado se puede recuperar.

    Args:
        pair: La pareja.
        que: Lo que le pasa a esos ficheros: «borre» o «pise».
    """
    if pair.versions:
        return (f"Esta pareja guarda versiones: lo que se {que} al otro lado queda en "
                f"{model.VERSIONS_DIR}/.")
    return (f"Esta pareja no guarda versiones: lo que se {que} al otro lado no se puede "
            "recuperar.")


def _forzar_borrados(pair: Pair, freno: frenos.Freno) -> tuple[list[str], list[str]]:
    """Devuelve las consecuencias y los avisos de forzar el freno de bisync por borrados."""
    lado = freno.lados[0] if freno.lados else None
    aqui = frenos.nombre_lado(lado) if lado else "un lado"
    alli = frenos.nombre_lado(frenos.otro_lado(lado)) if lado else "el otro"
    tope = _tope(pair, freno)
    cuantos = (f"Los {freno.borrados} ficheros que faltan en {aqui}"
               if freno.borrados is not None else f"Lo que falta en {aqui}")
    consecuencias = [
        f"Se lanza UNA pasada de «{pair.name}» con el freno de borrados de bisync saltado "
        "(--force).",
        f"{cuantos} se borrarán también en {alli}.",
        "Solo vale para esta pasada: la siguiente vuelve a llevar el freno"
        + (f" ({tope} %)." if tope is not None else ".")]
    avisos = [
        f"Si {aqui} está desmontado, vacío o es la carpeta equivocada, perderás esos "
        f"ficheros también en {alli}: el borrado se copia y ahí no vuelven.",
        *(["La carpeta local está vacía ahora mismo. Si no la has vaciado tú, lo normal es "
           "que el dispositivo no esté montado donde toca."]
          if _carpeta_vacia(pair.local_abs) else []),
        _versiones(pair, "borre"),
        f"Antes de forzar, pulsa «{ETIQUETA_SIMULAR}»: es esta misma pasada en simulacro y "
        "nombra los ficheros que borraría.",
        f"Salidas menos peligrosas: revisa primero {aqui} (¿está montado?, ¿es la carpeta "
        "de siempre?) y, si los ficheros se borraron por error, un --resync, que los "
        "recupera desde el otro lado: junta los dos lados sin borrar nada."]
    return consecuencias, avisos


def _forzar_cambiados(pair: Pair, freno: frenos.Freno) -> tuple[list[str], list[str]]:
    """Devuelve las consecuencias y los avisos de forzar el freno de «cambiaron todos»."""
    donde = " y ".join(frenos.nombre_lado(lado) for lado in freno.lados) or "un lado"
    hacia = (frenos.hacia(frenos.otro_lado(freno.lados[0])) if len(freno.lados) == 1
             else "al otro lado")
    consecuencias = [
        f"Se lanza UNA pasada de «{pair.name}» con el freno de bisync saltado (--force).",
        f"bisync copiará {hacia} lo que haya cambiado en {donde}, sobrescribiendo lo que "
        "tenga ahí.",
        "Solo vale para esta pasada: la siguiente vuelve a llevar el freno."]
    avisos = [
        "Si no esperabas que cambiaran todos (otro programa los ha tocado, es la carpeta "
        "equivocada), se copiará igual.",
        _versiones(pair, "pise"),
        f"Salida menos peligrosa: revisa primero qué ha tocado los ficheros de {donde}."]
    return consecuencias, avisos


def _forzar_espejo(pair: Pair, freno: frenos.Freno) -> tuple[list[str], list[str]]:
    """Devuelve las consecuencias y los avisos de forzar el freno de un espejo."""
    destino = frenos.nombre_lado(freno.lados[0])
    origen = frenos.nombre_lado(frenos.otro_lado(freno.lados[0]))
    tope = _tope(pair, freno)
    faltan = (f": quedan al menos {freno.pendientes} ficheros por borrar en {destino}"
              if freno.pendientes else "")
    consecuencias = [
        f"Se lanza UNA pasada de «{pair.name}» sin tope de borrados (--max-delete -1).",
        f"Se borrarán de {destino} todos los ficheros que no estén en {origen}{faltan}.",
        "Solo vale para esta pasada: la siguiente vuelve a llevar su tope"
        + (f" de {tope} ficheros." if tope is not None else ".")]
    avisos = [
        f"Si {origen} está vacío, desmontado o es la carpeta equivocada, {destino} se "
        "vaciará: esos borrados son un error y no se pueden deshacer.",
        *(["La carpeta local está vacía ahora mismo. Si no la has vaciado tú, lo normal es "
           "que el dispositivo no esté montado donde toca."]
          if pair.mode.source == "local" and _carpeta_vacia(pair.local_abs) else []),
        "Los espejos no guardan versiones: lo que se borre no se guarda en ninguna parte.",
        f"Antes de forzar, pulsa «{ETIQUETA_SIMULAR}»: es esta misma pasada en simulacro y "
        "nombra los ficheros que borraría.",
        f"Salida menos peligrosa: arregla el origen ({origen}: móntalo, o recupera la "
        "carpeta) y la siguiente pasada vuelve a copiar lo que falte; no hace falta forzar "
        "nada."]
    return consecuencias, avisos


def aviso_forzar(config: Config, hallazgo: Hallazgo) -> RepairPlan:
    """Devuelve el plan, sin disco, de confirmar que se fuerce UNA pasada.

    No es un plan de disco (lo hace rclone, en la ventana de salida, con `args_forzar()`)
    pero se confirma igual y con más motivo que un resync: salta justo el freno que
    protege de que un lado vacío, desmontado o equivocado se copie al otro. Por eso
    el plan dice de antemano qué se borrará y dónde, que si ese lado está mal se
    pierden datos, y recuerda las salidas menos peligrosas y la simulación que enseña
    qué ficheros borraría.

    Se niega, y no se ofrece: sin carpeta local (`sync._bisync_preflight()` aborta
    con 2 en ese caso; un lado local que falta se lee como «se ha borrado todo»),
    sin baseline en bisync (lo que hace falta es un `--resync`) y con el llavero.

    Args:
        config: La configuración del dispositivo.
        hallazgo: El freno, recién leído (`vigente()`).

    Raises:
        ReparacionImposible: Si no es un freno de borrados, la pareja ya no está o no
            se puede forzar.
    """
    freno = _freno_de(hallazgo)
    if freno is None:
        raise ReparacionImposible("Esto no es un freno de borrados: no hay nada que forzar.")
    pair = _pareja(config, hallazgo.pareja)
    if pair.llavero:
        raise ReparacionImposible(
            "El freno del llavero no se salta desde aquí: sus bases son tus contraseñas. "
            "Abre el llavero y, si hay copias de conflicto, usa «Combinar».")
    if not pair.local_abs.exists():
        raise ReparacionImposible(
            f"La carpeta local de «{pair.name}» ({pair.local_endpoint}) no existe. Con ese "
            "lado fuera de su sitio, forzar se leería como «se ha borrado todo» y se "
            "copiaría al otro: no se ofrece. Comprueba que el volumen esté montado donde "
            "toca y que la carpeta no se haya movido.")
    if pair.is_bisync and not bisync.pair_state(pair).has_baseline:
        raise ReparacionImposible(
            f"«{pair.name}» ya no tiene baseline, así que su freno de borrados ya no cuenta: "
            "lo que hace falta es un --resync. Vuelve a abrir la pantalla.")
    consecuencias, avisos = {frenos.BORRADOS: _forzar_borrados,
                             frenos.CAMBIADOS: _forzar_cambiados,
                             frenos.ESPEJO: _forzar_espejo}[freno.tipo](pair, freno)
    return RepairPlan(f"Forzar la sincronización de «{pair.name}»", consecuencias, avisos)


def hallazgos_reparables(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    """Devuelve los hallazgos que tienen algún botón.

    Es un plan o una pasada que lanzar.
    """
    return [h for h in hallazgos
            if tiene_plan(h) or h.clave in ("resync", "conflicto") or puede_forzar(h)]

