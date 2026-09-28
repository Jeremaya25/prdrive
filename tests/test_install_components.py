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

    # Esto rebautiza `os.replace` del intérprete entero, no un alias local de
    # este módulo — pero cada bloque lo restaura en su `finally` y
    # `run_all.py` lanza cada fichero de test en su propio proceso, así que no
    # se escapa a ningún otro test. No mover esto a un proceso compartido.
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

    # --- el VeraCrypt de viaje (#50) ------------------------------------------
    #
    # Su carpeta vive en la raíz FÍSICA, junto al .hc, y se sustituye entera con
    # el mismo intercambio. Lo que se comprueba: que con sello se pone al día,
    # que en uso se pospone sin bajar nada, que uno SIN sello no se toca nunca
    # desde aquí —su vestíbulo solo sabe abrir esa disposición— y que si no cabe
    # no se toca nada.
    import shutil

    from _harness import falso_portatil
    from install import traveler, veracrypt_bin

    cache_vc = falso_portatil()
    reales_vc = (veracrypt_bin.ensure_veracrypt, components.veracrypt_en_uso,
                 traveler.espacio_libre)
    veracrypt_bin.ensure_veracrypt = lambda progreso=None, allow_download=True: (
        bajados.append("veracrypt") or cache_vc)
    components.veracrypt_en_uso = lambda carpeta: False

    def con_veracrypt(version=None, sello=True):
        """Un dispositivo (el contenedor montado) y su raíz física con VeraCrypt."""
        disp = dispositivo(rclone_version=pins.RCLONE_VERSION,
                           python_release=pins.PYTHON_RELEASE)
        for plat in (WIN, LIN):
            (platforms.runtime_dir(disp, plat) / comp.RUNTIME_STAMP).write_text(
                f"python = {pins.PYTHON_VERSION}\nrelease = {pins.PYTHON_RELEASE}\n",
                encoding="utf-8")
        fis = tmpdir("prdrive-comp-fisica-")
        shutil.copytree(falso_portatil(version), comp.veracrypt_dir(fis))
        if not sello:
            comp.veracrypt_stamp_path(fis).unlink()
        return disp, fis

    def lo_de(fis):
        carpeta = comp.veracrypt_dir(fis)
        return {p.name: p.read_bytes() for p in carpeta.iterdir()}

    try:
        disp, fis = con_veracrypt("1.26.7")
        pends = comp.pendientes(deploy.app_dir(disp), fis)
        c("un VeraCrypt de otra versión es lo único pendiente",
          [p.que for p in pends], [comp.VERACRYPT])
        bajados.clear()
        res = components.aplicar(disp, pends=pends)
        c("se pone al día", (res.hechos, res.pospuestos, res.fallidos),
          ([f"VeraCrypt de la unidad: 1.26.7 → {pins.VERACRYPT_VERSION}"], [], []))
        c("con el portable comprobado", bajados, ["veracrypt"])
        c("y ya no queda nada pendiente",
          comp.pendientes(deploy.app_dir(disp), fis), [])
        c("sin restos del intercambio en la raíz física",
          sorted(p.name for p in fis.iterdir()), [comp.veracrypt_dir(fis).name])

        # En uso: se pospone, sin bajar nada y sin tocar la carpeta.
        disp, fis = con_veracrypt("1.26.7")
        antes = lo_de(fis)
        components.veracrypt_en_uso = lambda carpeta: carpeta == comp.veracrypt_dir(fis)
        bajados.clear()
        res = components.aplicar(disp, pends=comp.pendientes(deploy.app_dir(disp), fis))
        c("en uso se pospone", len(res.pospuestos), 1)
        c.contains("diciendo por qué", res.pospuestos[0], "en uso")
        c("sin bajar nada", bajados, [])
        c("y sin tocar la carpeta", lo_de(fis), antes)
        components.veracrypt_en_uso = lambda carpeta: False

        # Sin sello (un dispositivo de antes): no se toca NUNCA desde aquí.
        disp, fis = con_veracrypt(sello=False)
        antes = lo_de(fis)
        bajados.clear()
        res = components.aplicar(disp, pends=comp.pendientes(deploy.app_dir(disp), fis))
        c("un VeraCrypt sin sello no se pone al día solo",
          (res.hechos, len(res.pospuestos), res.fallidos), ([], 1, []))
        c.contains("se remite a «Añadir plataformas…»", res.pospuestos[0],
                   "«Añadir plataformas…»")
        c.contains("que cambia también el vestíbulo", res.pospuestos[0], "vestíbulo")
        c("sin bajar nada", bajados, [])
        c("y sin tocar la carpeta", lo_de(fis), antes)

        # No cabe: un fallo que se dice, y la carpeta como estaba.
        disp, fis = con_veracrypt("1.26.7")
        antes = lo_de(fis)
        traveler.espacio_libre = lambda raiz: 1024
        res = components.aplicar(disp, pends=comp.pendientes(deploy.app_dir(disp), fis))
        traveler.espacio_libre = reales_vc[2]
        c("si no cabe, es un fallo", len(res.fallidos), 1)
        c.contains("que lo dice", res.fallidos[0], "No cabe VeraCrypt")
        c("y la carpeta sigue como estaba", lo_de(fis), antes)
        c("sin restos", sorted(p.name for p in fis.iterdir()),
          [comp.veracrypt_dir(fis).name])
    finally:
        (veracrypt_bin.ensure_veracrypt, components.veracrypt_en_uso,
         traveler.espacio_libre) = reales_vc

    # --- los restos de un runtime a medias se barren --------------------------
    #
    # Un `.windows-arm64.nuevo-27804` con 28 MB a medio extraer se quedó para
    # siempre en un dispositivo real: cada proceso solo limpiaba el suyo. Ahora
    # se barren los de procesos muertos, y solo esos.
    import contextlib
    import importlib.util
    import io
    import os
    import subprocess

    from common import update

    def pid_muerto() -> int:
        proc = subprocess.Popen([sys.executable, "-c", ""])
        proc.wait()
        return proc.pid

    muerto = pid_muerto()
    raiz = dispositivo()
    base = platforms.runtime_dir(raiz, WIN).parent
    restos = {n: base / n for n in (
        f".windows-arm64.nuevo-{muerto}", f".windows-x64.viejo-{muerto}",
        f".linux-x64.borrar-{muerto}", f".windows-x64.nuevo-{os.getpid()}",
        f".otra-cosa.nuevo-{muerto}", f"windows-arm64.nuevo-{muerto}")}
    for d in restos.values():
        (d / "Lib").mkdir(parents=True)
        (d / "Lib" / "algo.py").write_text("x", encoding="utf-8")
    barridos = deploy.barrer_restos_runtime(raiz)
    c("se barren los restos de procesos muertos",
      sorted(p.name for p in barridos),
      sorted([f".windows-arm64.nuevo-{muerto}", f".windows-x64.viejo-{muerto}",
              f".linux-x64.borrar-{muerto}"]))
    c("el de este mismo proceso no se toca",
      restos[f".windows-x64.nuevo-{os.getpid()}"].is_dir(), True)
    c("ni lo que no es de ninguna plataforma",
      restos[f".otra-cosa.nuevo-{muerto}"].is_dir(), True)
    c("ni lo que no lleva el punto delante",
      restos[f"windows-arm64.nuevo-{muerto}"].is_dir(), True)
    c("y los runtimes de verdad siguen ahí",
      (platforms.runtime_dir(raiz, WIN) / WIN.interprete).is_file(), True)

    # --- el relevo: el Python con el que está abierta la ventana -------------
    #
    # Desde la ventana, el runtime de esta plataforma no se podía cambiar nunca:
    # es el suyo, y Windows no deja apartar la carpeta de un pythonw.exe vivo. El
    # relevo lo cambia con la ventana cerrada, desde el temporal del equipo.
    raiz = dispositivo()
    components.runtime_en_uso = lambda carpeta: (
        carpeta == platforms.runtime_dir(raiz, WIN))
    c("se reconoce el Python propio entre los pendientes",
      components.runtime_propio(raiz, components.pendientes(raiz)).plataforma, WIN)
    components.runtime_en_uso = lambda carpeta: False
    c("y si no corre desde ninguno, no hay propio",
      components.runtime_propio(raiz, components.pendientes(raiz)), None)

    # La ventana hace la misma pregunta con `common.components.propio()`.
    c("corre_desde reconoce la carpeta de este intérprete",
      comp.corre_desde(Path(sys.executable).parent), True)
    c("y no una cualquiera", comp.corre_desde(tmpdir("prdrive-ajena-")), False)
    real_corre = comp.corre_desde
    app = deploy.app_dir(raiz)
    comp.corre_desde = lambda carpeta: carpeta == comp.runtime_dir(app, WIN)
    try:
        pends = comp.pendientes(app, None)
        c("propio() da el Python de la ventana", comp.propio(pends, app).plataforma, WIN)
        c("y nunca un rclone",
          comp.propio([p for p in pends if p.que == comp.RCLONE], app), None)
    finally:
        comp.corre_desde = real_corre

    # Preparar: un Python extraído y una copia del código, en el temporal.
    reales_rt = (runtime_bin.extract, runtime_bin.recorded_sha256)
    extraidos: list[tuple] = []

    def falso_extract(archivo, destino, plat, sha):
        extraidos.append((plat.clave, sha))
        (destino / plat.interprete).parent.mkdir(parents=True, exist_ok=True)
        (destino / plat.interprete).write_bytes(b"py NUEVO")
        return 1

    runtime_bin.extract = falso_extract
    runtime_bin.recorded_sha256 = lambda archivo: "sha-apuntada"
    codigo = tmpdir("prdrive-codigo-")
    (codigo / "prdrive-install.py").write_text("# el aplicador", encoding="utf-8")
    (codigo / "install").mkdir()
    (codigo / "install" / "__pycache__").mkdir()
    (codigo / "install" / "__pycache__" / "x.pyc").write_bytes(b"x")
    temporal = tmpdir("prdrive-temporal-")
    try:
        raiz = dispositivo()
        propio = components.pendientes(raiz)[1]       # el Python de Windows x64
        c("(el pendiente de la prueba es el Python de Windows x64)",
          (propio.que, propio.plataforma), (comp.PYTHON, WIN))
        orden, carpeta = components.preparar_relevo(
            raiz, propio, esperar=[111, 222], reabrir="py-del-dispositivo",
            decir=lambda m: None, codigo=codigo, base=temporal)
        c("en el temporal del equipo, nunca en el dispositivo",
          carpeta.parent, temporal)
        c("con el Python que se va a poner, extraído", extraidos, [("windows-x64", "sha-apuntada")])
        c("y lanzado con él, sin consola",
          orden[0], str(carpeta / "python" / WIN.interprete))
        c("desde la COPIA del código (el zip se borra enseguida)",
          orden[2], str(carpeta / "codigo" / "prdrive-install.py"))
        c("la copia no lleva cachés", (carpeta / "codigo" / "install" / "__pycache__").exists(),
          False)
        c("pone al día ese dispositivo",
          orden[3:5], ["--update-components", str(raiz)])
        c("esperando a la ventana y al aplicador, y reabriendo con el Python de siempre",
          orden[5:], ["--esperar", "111", "--esperar", "222",
                      "--reabrir", "py-del-dispositivo"])
        c("la carpeta dice de quién es",
          (carpeta / components.RELEVO_DUENNO).read_text(encoding="utf-8"), str(os.getpid()))
        c("y el dispositivo no se ha tocado",
          [p.que for p in components.pendientes(raiz) if p.plataforma == WIN],
          [comp.RCLONE, comp.PYTHON])

        # Si la extracción falla, no queda nada en el temporal.
        def extract_que_revienta(archivo, destino, plat, sha):
            destino.mkdir(parents=True)
            raise InstallError("el archivo no cuadra")

        runtime_bin.extract = extract_que_revienta
        antes = sorted(p.name for p in temporal.iterdir())
        try:
            components.preparar_relevo(raiz, propio, [1], None, lambda m: None,
                                       codigo=codigo, base=temporal)
            c("un relevo que no se puede preparar se cuenta", "siguió", "InstallError")
        except InstallError:
            c("un relevo que no se puede preparar se cuenta", "InstallError", "InstallError")
        c("sin dejar su carpeta a medias", sorted(p.name for p in temporal.iterdir()), antes)
        runtime_bin.extract = falso_extract

        # Las carpetas de relevos muertos las barre el siguiente.
        viejos = tmpdir("prdrive-relevos-")
        for nombre, duenno in (("a", str(pid_muerto())), ("b", str(os.getpid())),
                               ("c", None)):
            d = viejos / (components.RELEVO_PREFIJO + nombre)
            d.mkdir()
            if duenno:
                (d / components.RELEVO_DUENNO).write_text(duenno, encoding="utf-8")
        c("se barren las de relevos muertos o sin dueño",
          components.barrer_relevos(viejos), 2)
        c("y se queda la de uno vivo",
          sorted(p.name for p in viejos.iterdir()), [components.RELEVO_PREFIJO + "b"])

        # --- la orden, con --relevo, dentro de este proceso ------------------
        entrada = Path(__file__).resolve().parent.parent / "prdrive-install.py"

        def cargar(ruta: Path):
            spec = importlib.util.spec_from_file_location("prdrive_install", ruta)
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)
            return modulo

        instalador = cargar(entrada)
        reales_relevo = (components.lanzar_suelto, components.esperar_a,
                         components.preparar_relevo)
        lanzados: list[list[str]] = []
        components.lanzar_suelto = lambda orden: lanzados.append(orden) or 4242
        preparar_real = components.preparar_relevo
        components.preparar_relevo = (
            lambda *a, **k: preparar_real(*a, codigo=codigo, base=temporal, **k))
        try:
            raiz = dispositivo()
            components.runtime_en_uso = lambda carpeta: (
                carpeta == platforms.runtime_dir(raiz, WIN))
            bajados.clear()
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                rc = instalador.cmd_update_components(str(raiz), relevo=999)
            texto = salida.getvalue()
            c("con el Python de la ventana pendiente sale con CODIGO_RELEVO",
              rc, update.CODIGO_RELEVO)
            c("lo demás se pone al día igual",
              [p.describe() for p in components.pendientes(raiz)],
              [p.describe() for p in components.pendientes(raiz)
               if p.plataforma == WIN and p.que == comp.PYTHON])
            c("ése se consigue una sola vez: para el relevo, no para el dispositivo",
              bajados.count("python windows-x64"), 1)
            c("y el del dispositivo sigue siendo el de antes",
              (platforms.runtime_dir(raiz, WIN) / WIN.interprete).read_bytes(),
              b"py viejo")
            c("se lanza un relevo, uno", len(lanzados), 1)
            c.contains("esperando a la ventana", " ".join(lanzados[0]), "--esperar 999")
            c.contains("y a este proceso", " ".join(lanzados[0]), f"--esperar {os.getpid()}")
            c.contains("reabriendo con el mismo Python", " ".join(lanzados[0]),
                       f"--reabrir {sys.executable}")
            c.contains("y se dice que se hará después", texto, "DESPUÉS")
            c("sin darlo por pospuesto", "POSPUESTO" in texto, False)
            carpeta = Path(lanzados[0][0]).parent.parent
            c("la carpeta pasa a ser del relevo",
              (carpeta / components.RELEVO_DUENNO).read_text(encoding="utf-8"), "4242")

            # Sin --relevo (a mano, desde la consola) se pospone como siempre.
            raiz = dispositivo()
            lanzados.clear()
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                rc = instalador.cmd_update_components(str(raiz))
            c("sin --relevo no se lanza nada", (rc, lanzados), (0, []))
            c.contains("y se pospone con su motivo", salida.getvalue(), "POSPUESTO")
            c.contains("que remite al botón de la ventana", salida.getvalue(),
                       "«Actualizar…»")
            components.runtime_en_uso = lambda carpeta: False

            # --- el relevo en sí ---------------------------------------------
            # Se carga desde una copia en su carpeta, como en la vida real: el
            # registro va al lado del código, no al checkout.
            relevo = tmpdir("prdrive-relevo-prueba-")
            (relevo / "codigo").mkdir()
            (relevo / "codigo" / "prdrive-install.py").write_bytes(entrada.read_bytes())
            copia = cargar(relevo / "codigo" / "prdrive-install.py")

            raiz = dispositivo()
            lanzados.clear()
            components.esperar_a = lambda pids, limite=0: True
            stdout_antes = sys.stdout
            rc = copia.cmd_relevo(str(raiz), [999], "py-del-dispositivo")
            c("el relevo pone al día todo, el Python de la ventana incluido",
              (rc, components.pendientes(raiz)), (0, []))
            c("devuelve la salida a su sitio", sys.stdout is stdout_antes, True)
            c("y reabre la ventana con el Python del dispositivo",
              lanzados, [["py-del-dispositivo",
                          str(deploy.app_dir(raiz) / "runsync.py")]])
            c.contains("dejando su registro", (relevo / components.RELEVO_LOG).read_text(
                encoding="utf-8"), "Hecho")

            # La ventana no se cierra: no se toca nada ni se reabre otra.
            raiz = dispositivo()
            lanzados.clear()
            components.esperar_a = lambda pids, limite=0: False
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                rc = copia.cmd_relevo(str(raiz), [999], "py-del-dispositivo")
            c("si la ventana no se cierra, no hace nada", (rc, lanzados), (1, []))
            c("y el dispositivo sigue como estaba", len(components.pendientes(raiz)), 4)
            c.contains("y lo cuenta", salida.getvalue(), "sigue abierto")

            # Un fallo al poner al día: reabre igual, y lo cuenta.
            raiz = dispositivo()
            lanzados.clear()
            components.esperar_a = lambda pids, limite=0: True
            runtime_bin.ensure_runtime = runtime_que_revienta
            salida = io.StringIO()
            with contextlib.redirect_stdout(salida):
                rc = copia.cmd_relevo(str(raiz), [999], "py-del-dispositivo")
            runtime_bin.ensure_runtime = falso_runtime
            c("un fallo sale con 1", rc, 1)
            c("pero la ventana se reabre igual", len(lanzados), 1)
            c.contains("y se enseña el registro", salida.getvalue(), "no cuadra con su suma")
        finally:
            (components.lanzar_suelto, components.esperar_a,
             components.preparar_relevo) = reales_relevo
    finally:
        runtime_bin.extract, runtime_bin.recorded_sha256 = reales_rt

    # --- la orden de consola --------------------------------------------------
    #
    # Se lanza un proceso de VERDAD, así que solo se prueban los dos caminos que
    # no llegan a descargar nada: el que no es un dispositivo y el que ya está al
    # día. En cuanto hubiera algo pendiente, el descargador real saldría a
    # Internet, y en este proyecto ningún test habla con la red.
    import subprocess

    entrada = Path(__file__).resolve().parent.parent / "prdrive-install.py"

    vacio = tmpdir("prdrive-sin-nada-")
    hecho = subprocess.run([sys.executable, str(entrada),
                            "--update-components", str(vacio)],
                           capture_output=True, text=True)
    c("sobre algo que no es un dispositivo se sale con 1", hecho.returncode, 1)
    c.contains("nombrando la carpeta que falta", hecho.stdout + hecho.stderr,
               ".prdrive")

    # Uno con los componentes ya fijados: se dice y se sale con 0, sin red.
    aldia = dispositivo(rclone_version=pins.RCLONE_VERSION,
                        python_release=pins.PYTHON_RELEASE)
    for plat in (WIN, LIN):
        d = platforms.runtime_dir(aldia, plat)
        (d / comp.RUNTIME_STAMP).write_text(
            f"python = {pins.PYTHON_VERSION}\nrelease = {pins.PYTHON_RELEASE}\n"
            f"triple = {plat.triple}\nsha256 = x\n", encoding="utf-8")
    c("un dispositivo al día no tiene nada pendiente",
      components.pendientes(aldia), [])
    # `c()` solo apunta el fallo y sigue: si esta invariante se rompiera, el
    # subprocess de abajo lanzaría el descargador de verdad contra la red. En
    # este proyecto ningún test habla con la red, así que aquí hace falta un
    # assert de verdad que pare el script.
    assert not components.pendientes(aldia)
    resto = platforms.runtime_dir(aldia, WIN).parent / f".windows-arm64.nuevo-{pid_muerto()}"
    (resto / "Lib").mkdir(parents=True)
    hecho = subprocess.run([sys.executable, str(entrada),
                            "--update-components", str(aldia)],
                           capture_output=True, text=True)
    c("y la orden lo dice y sale con 0", hecho.returncode, 0)
    c.contains("sin haber tocado nada", hecho.stdout, "nada que hacer")
    c("pero barriendo el resto de un intento anterior", resto.exists(), False)
    c.contains("y diciéndolo", hecho.stdout, "resto de un intento anterior")
finally:
    (rclone_bin.pinned_rclone, runtime_bin.ensure_runtime, deploy.install_runtime,
     components.rclone_en_uso, components.runtime_en_uso) = reales

sys.exit(c.report())
