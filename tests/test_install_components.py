#!/usr/bin/env python3
"""
Sustituir el rclone y el Python de un dispositivo (install/components.py).

Nada de esto habla con la red ni toca un dispositivo real: `pinned_rclone()` y
`ensure_runtime()` se sustituyen enteros, y las dos preguntas sobre el sistema
—¿está ese rclone en marcha?, ¿corre este proceso desde ese runtime?— son
funciones de módulo justo para poder contestarlas a mano aquí.

Lo que se comprueba es lo que puede hacer daño:

  * que el intercambio no pase nunca por «medio rclone en bin/», porque es el
    único que el dispositivo tiene;
  * que lo que está en uso se POSPONGA con su motivo en vez de forzarse, y sin
    haberse bajado nada;
  * que un fallo de verificación deje el binario de antes exactamente como
    estaba;
  * y que después de una pasada buena el dispositivo ya no tenga nada pendiente,
    que es lo que apaga el recuadro ámbar.
"""

import sys
from pathlib import Path
from urllib.error import URLError

from _harness import Checks, tmpdir

from common import components as comp
from common import pins
from install import InstallError, components, deploy, platforms, rclone_bin
from install import runtime_bin

c = Checks("actualizar componentes (install/components.py)")

WIN = pins.plataforma("windows-x64")
LIN = pins.plataforma("linux-x64")


def dispositivo(rclone_version="v0.0.1", python_release="20200101") -> Path:
    """Un dispositivo de mentira con componentes viejos de dos plataformas."""
    raiz = tmpdir("prdrive-comp-disp-")
    app = deploy.app_dir(raiz)
    for plat in (WIN, LIN):
        binario = platforms.rclone_path(raiz, plat)
        binario.parent.mkdir(parents=True, exist_ok=True)
        binario.write_bytes(b"rclone viejo")
        deploy.write_rclone_stamp(binario, plat, rclone_version)
        d = platforms.runtime_dir(raiz, plat)
        (d / plat.interprete).parent.mkdir(parents=True, exist_ok=True)
        (d / plat.interprete).write_bytes(b"py viejo")
        (d / comp.RUNTIME_STAMP).write_text(
            f"python = 3.13.0\nrelease = {python_release}\n"
            f"triple = {plat.triple}\nsha256 = viejo\n", encoding="utf-8")
    assert app.is_dir()
    return raiz


# Lo que devolverían los descargadores de verdad, ya comprobado.
nuevo_rclone = tmpdir("prdrive-comp-bin-") / "rclone.exe"
nuevo_rclone.write_bytes(b"rclone NUEVO")

bajados: list[str] = []
reales = (rclone_bin.pinned_rclone, runtime_bin.ensure_runtime,
          deploy.install_runtime, components.rclone_en_uso,
          components.runtime_en_uso)


def falso_runtime(plat, progreso=None, allow_download=True):
    bajados.append("python " + plat.clave)
    return Path("archivo-de-mentira")


def falso_install_runtime(device_root, plat, archivo):
    """Se comporta como el de verdad: escribe el sello con los pines de ahora."""
    d = platforms.runtime_dir(device_root, plat)
    d.mkdir(parents=True, exist_ok=True)
    (d / plat.interprete).parent.mkdir(parents=True, exist_ok=True)
    (d / plat.interprete).write_bytes(b"py NUEVO")
    (d / comp.RUNTIME_STAMP).write_text(
        f"python = {pins.PYTHON_VERSION}\nrelease = {pins.PYTHON_RELEASE}\n"
        f"triple = {plat.triple}\nsha256 = nuevo\n", encoding="utf-8")
    return d


rclone_bin.pinned_rclone = lambda plat, progreso=None: (
    bajados.append("rclone " + plat.clave) or nuevo_rclone)
runtime_bin.ensure_runtime = falso_runtime
deploy.install_runtime = falso_install_runtime
components.rclone_en_uso = lambda ruta: False
components.runtime_en_uso = lambda carpeta: False

try:
    # --- la pasada buena -----------------------------------------------------
    raiz = dispositivo()
    c("se ve lo que hay que poner al día", len(components.pendientes(raiz)), 4)
    bajados.clear()
    res = components.aplicar(raiz)
    c("no queda nada pospuesto", res.pospuestos, [])
    c("ni fallido", res.fallidos, [])
    c("se cuentan los cuatro componentes", len(res.hechos), 4)
    c("y la pasada cuenta como buena", res.ok, True)
    c("y el dispositivo ya está al día", components.pendientes(raiz), [])
    c("el rclone es el nuevo",
      platforms.rclone_path(raiz, WIN).read_bytes(), b"rclone NUEVO")
    c("con su sello puesto al día",
      comp.leer_sello(comp._texto(
          comp.rclone_stamp_path(deploy.app_dir(raiz), WIN))).get("rclone"),
      pins.RCLONE_VERSION)
    c("y no quedan restos del intercambio",
      sorted(p.name for p in platforms.rclone_path(raiz, WIN).parent.iterdir()),
      sorted([WIN.rclone_exe, WIN.rclone_exe + comp.RCLONE_STAMP_SUFIJO,
              LIN.rclone_exe, LIN.rclone_exe + comp.RCLONE_STAMP_SUFIJO]))

    # Otra pasada no hace nada: ya no hay nada pendiente.
    bajados.clear()
    res = components.aplicar(raiz)
    c("una segunda pasada no baja nada", bajados, [])
    c("ni dice haber hecho nada", res.hechos, [])

    # --- lo que está en uso se pospone, y sin bajar nada ---------------------
    #
    # Postergar es una decisión: en Windows el renombrado colaría igual, pero
    # cambiarle el binario a una sincronización a media pasada no puede ocurrir
    # sin que nadie lo haya pedido.
    raiz = dispositivo()
    components.rclone_en_uso = lambda ruta: ruta == platforms.rclone_path(raiz, WIN)
    bajados.clear()
    res = components.aplicar(raiz)
    c("el que está en uso se pospone", len(res.pospuestos), 1)
    c.contains("diciendo cuál", res.pospuestos[0], "rclone de Windows x64")
    c.contains("y por qué", res.pospuestos[0], "en uso")
    c("no se ha bajado su binario", "rclone windows-x64" in bajados, False)
    c("el de antes sigue intacto",
      platforms.rclone_path(raiz, WIN).read_bytes(), b"rclone viejo")
    c("y sigue saliendo como pendiente",
      [p.que for p in components.pendientes(raiz) if p.plataforma == WIN],
      [comp.RCLONE])
    c("lo demás sí se ha hecho", len(res.hechos), 3)
    c("y posponer no hace fallar la pasada", res.ok, True)
    components.rclone_en_uso = lambda ruta: False

    # El Python desde el que corre este mismo programa: en Windows no se puede
    # renombrar la carpeta de un pythonw.exe vivo, así que ni se intenta.
    raiz = dispositivo()
    components.runtime_en_uso = lambda carpeta: (
        carpeta == platforms.runtime_dir(raiz, WIN))
    bajados.clear()
    res = components.aplicar(raiz)
    c("el runtime en uso se pospone", len(res.pospuestos), 1)
    c.contains("explicando que es el que está corriendo",
               res.pospuestos[0], "corriendo")
    c("y no se ha bajado", "python windows-x64" in bajados, False)
    components.runtime_en_uso = lambda carpeta: False

    # --- un fallo de verificación no toca nada -------------------------------
    raiz = dispositivo()

    def revienta(plat, progreso=None):
        raise InstallError("lo descargado no es lo que rclone publica")

    rclone_bin.pinned_rclone = revienta
    res = components.aplicar(raiz)
    c("un fallo de descarga es un fallo, no una posposición",
      len(res.fallidos), 2)
    c.contains("y se cuenta qué pasó", res.fallidos[0], "no es lo que rclone publica")
    c("el binario de antes sigue donde estaba",
      platforms.rclone_path(raiz, WIN).read_bytes(), b"rclone viejo")
    c("y con su sello de antes",
      comp.leer_sello(comp._texto(
          comp.rclone_stamp_path(deploy.app_dir(raiz), WIN))).get("rclone"),
      "v0.0.1")
    c("una pasada con fallos no está ok", res.ok, False)
    rclone_bin.pinned_rclone = lambda plat, progreso=None: (
        bajados.append("rclone " + plat.clave) or nuevo_rclone)

    # --- y lo que falla del lado del Python se cuenta igual ------------------
    raiz = dispositivo()

    def runtime_que_revienta(plat, progreso=None, allow_download=True):
        raise InstallError("el archivo descargado no cuadra con su suma")

    runtime_bin.ensure_runtime = runtime_que_revienta
    res = components.aplicar(raiz)
    c("un Python que no se puede poner también es un fallo", len(res.fallidos), 2)
    c.contains("diciendo cuál", res.fallidos[0], "Python de Windows x64")
    c.contains("y qué pasó", res.fallidos[0], "no cuadra con su suma")
    c("los rclone de esa misma pasada sí se han puesto", len(res.hechos), 2)
    runtime_bin.ensure_runtime = falso_runtime

    # --- sin red no hay ni InstallError --------------------------------------
    #
    # `urllib.error.URLError` ES un OSError, y sale crudo de `published_sha256()`
    # nada más ir a leer el SHA256SUMS —el primer sitio al que va una descarga—,
    # así que quedarse sin red, un proxy o un tiempo de espera llegan por ahí. Si
    # se escapara, se perdería el parte entero de una pasada que a lo mejor ya
    # había puesto al día media docena de componentes.
    raiz = dispositivo()

    def sin_red(plat, progreso=None):
        if plat == WIN:
            raise URLError("getaddrinfo failed")
        return bajados.append("rclone " + plat.clave) or nuevo_rclone

    rclone_bin.pinned_rclone = sin_red
    res = components.aplicar(raiz)
    c("quedarse sin red es un fallo de ese componente, no de la pasada",
      len(res.fallidos), 1)
    c.contains("y se cuenta lo que dijo la red",
               res.fallidos[0], "getaddrinfo failed")
    c("los demás componentes se ponen igual", len(res.hechos), 3)
    c("aunque la pasada no salga ok", res.ok, False)
    c("y el que no se pudo bajar sigue pendiente",
      [p.que for p in components.pendientes(raiz) if p.plataforma == WIN],
      [comp.RCLONE])
    rclone_bin.pinned_rclone = lambda plat, progreso=None: (
        bajados.append("rclone " + plat.clave) or nuevo_rclone)

    # --- el intercambio no pasa por «medio rclone» ---------------------------
    #
    # Si el renombrado final falla, el de antes vuelve a su sitio: nunca queda
    # `bin/` sin rclone, que es el estado en el que el dispositivo no sincroniza
    # en ningún equipo.
    raiz = dispositivo()
    destino = platforms.rclone_path(raiz, WIN)
    reemplazar = components.os.replace
    llamadas = {"n": 0}

    def replace_que_falla(a, b):
        llamadas["n"] += 1
        if llamadas["n"] == 2:        # la 1ª aparta el viejo; la 2ª coloca
            raise PermissionError("justo ahora no")
        return reemplazar(a, b)

    components.os.replace = replace_que_falla
    try:
        components.swap_rclone(destino, nuevo_rclone)
        c("un intercambio cortado se cuenta", "siguió", "InstallError")
    except InstallError as e:
        c("un intercambio cortado se cuenta", "InstallError", "InstallError")
        c.contains("diciendo dónde", str(e), str(destino))
    finally:
        components.os.replace = reemplazar
    c("y el rclone de antes sigue ahí", destino.read_bytes(), b"rclone viejo")
    c("sin restos a medias",
      [p.name for p in destino.parent.glob(".*")], [])

    # Los otros dos puntos por donde el intercambio se puede cortar, porque lo
    # que hay que barrer es distinto en cada uno: lo que se limpia tiene que ser
    # lo que este intercambio llegó a escribir, ni más ni menos. Borrar de más
    # aquí sería borrar el único rclone del dispositivo por un fallo que ocurrió
    # antes de tocarlo.
    #
    # Si falla la copia, lo único que existía era el `.nuevo`.
    raiz = dispositivo()
    destino = platforms.rclone_path(raiz, WIN)
    try:
        components.swap_rclone(destino, destino.with_name("no-existe"))
        c("una copia que no llega se cuenta", "siguió", "InstallError")
    except InstallError:
        c("una copia que no llega se cuenta", "InstallError", "InstallError")
    c("sin haber tocado el de antes", destino.read_bytes(), b"rclone viejo")
    c("ni dejar un .nuevo por ahí",
      [p.name for p in destino.parent.glob(".*")], [])

    # Si falla apartar el de antes, tampoco se ha tocado: el destino sigue
    # siendo el de siempre, y del intercambio solo hay que retirar el `.nuevo`.
    raiz = dispositivo()
    destino = platforms.rclone_path(raiz, WIN)

    def replace_que_no_va(a, b):
        raise PermissionError("ocupado")

    components.os.replace = replace_que_no_va
    try:
        components.swap_rclone(destino, nuevo_rclone)
        c("apartar el de antes tampoco se deja a medias", "siguió", "InstallError")
    except InstallError:
        c("apartar el de antes tampoco se deja a medias",
          "InstallError", "InstallError")
    finally:
        components.os.replace = reemplazar
    c("el de antes sigue siendo el de antes",
      destino.read_bytes(), b"rclone viejo")
    c("y el .nuevo se ha retirado",
      [p.name for p in destino.parent.glob(".*")], [])

    # Y si encima falla devolver el de antes a su sitio, el dispositivo se queda
    # sin rclone de verdad. Eso tiene que salir como InstallError y diciendo por
    # dónde se sale: un OSError crudo abortaría la pasada entera de `aplicar()`
    # —que solo recoge InstallError— y se perdería el parte; y una plataforma sin
    # binario ya no vuelve a salir como pendiente, así que nadie más lo contaría.
    raiz = dispositivo()
    destino = platforms.rclone_path(raiz, WIN)
    llamadas = {"n": 0}

    def replace_que_falla_siempre_menos_la_primera(a, b):
        llamadas["n"] += 1
        if llamadas["n"] >= 2:    # la 1ª aparta; fallan colocar y devolver
            raise PermissionError("justo ahora no")
        return reemplazar(a, b)

    components.os.replace = replace_que_falla_siempre_menos_la_primera
    try:
        components.swap_rclone(destino, nuevo_rclone)
        c("quedarse sin rclone se cuenta", "siguió", "InstallError")
    except InstallError as e:
        c("quedarse sin rclone se cuenta", "InstallError", "InstallError")
        c.contains("diciendo en qué estado queda", str(e), "sin rclone")
        c.contains("y por dónde se sale", str(e), "Añadir plataformas")
    except OSError:
        c("quedarse sin rclone se cuenta", "OSError crudo", "InstallError")
    finally:
        components.os.replace = reemplazar
    c("sin dejar el .nuevo por ahí",
      [p.name for p in destino.parent.glob(".*.nuevo-*")], [])
    c("y con el binario de antes apartado, no destruido",
      [p.read_bytes() for p in destino.parent.glob(".*.viejo-*")],
      [b"rclone viejo"])

    # --- los restos de un intento anterior se barren -------------------------
    raiz = dispositivo()
    destino = platforms.rclone_path(raiz, WIN)
    resto = destino.with_name(f".{destino.name}.viejo-4242")
    resto.write_bytes(b"de la vez pasada")
    components.aplicar(raiz)
    c("un resto de un intercambio anterior se barre", resto.exists(), False)

    # Y uno atascado no puede llevarse por delante el barrido de los que van
    # detrás: el que falla es justo el esperado —un `.viejo` que sujeta un rclone
    # en marcha— y los `.viejo-*` van primero, así que los `.nuevo-*` se
    # quedarían sin barrer para siempre. Aquí se atasca con un directorio, que
    # `unlink()` rechaza en los dos sistemas.
    raiz = dispositivo()
    destino = platforms.rclone_path(raiz, WIN)
    atascado = destino.with_name(f".{destino.name}.viejo-1")
    atascado.mkdir()
    (atascado / "dentro").write_bytes(b"no se deja borrar")
    detras = destino.with_name(f".{destino.name}.nuevo-2")
    detras.write_bytes(b"de un intento a medias")
    components.aplicar(raiz)
    c("un resto atascado no para el barrido de los siguientes",
      detras.exists(), False)
    c("y él se queda para la próxima vez", atascado.is_dir(), True)

    # --- lo que se va contando mientras tanto --------------------------------
    #
    # Es lo que imprime la orden de consola, así que se mira como lo leería
    # alguien: «consiguiendo la v1.75.1» sería un artículo sin nombre detrás.
    raiz = dispositivo()
    dicho: list[str] = []
    components.aplicar(raiz, dicho.append)
    c("se cuenta lo que se consigue, uno por componente",
      len([m for m in dicho if "consiguiendo" in m]), 4)
    c.contains("nombrando la versión, no dejando el artículo suelto",
               dicho[0], "consiguiendo la versión ")
    c.contains("y se dice también lo que se sustituye",
               "\n".join(dicho), "sustituyendo")
finally:
    (rclone_bin.pinned_rclone, runtime_bin.ensure_runtime, deploy.install_runtime,
     components.rclone_en_uso, components.runtime_en_uso) = reales

sys.exit(c.report())
