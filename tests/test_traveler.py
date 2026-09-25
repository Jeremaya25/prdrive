#!/usr/bin/env python3
"""
El VeraCrypt que viaja en el dispositivo (Traveler's Disk).

Sin esto, un dispositivo cifrado con VeraCrypt solo sirve en equipos que ya lo
tengan instalado, justo lo contrario de lo que hace el resto del proyecto. Lo que
viaja es el VeraCrypt Portable oficial, con sus dos arquitecturas y sus nombres
—`DriverLoad()` carga de la carpeta del ejecutable un `.sys` con la arquitectura
en el nombre—, y es un componente: lleva sello, se sustituye entero y nunca se
copia encima. Sin red, la copia del VeraCrypt instalado en el equipo, con los
nombres del portable leídos de la cabecera PE.

Todo sobre árboles falsos: ni se baja ni se copia un VeraCrypt de verdad
(`veracrypt_bin.ensure_veracrypt` se sustituye por una carpeta de mentira con su
sello) ni se toca ninguna unidad. Y la trampa de integración que estaría callada
hasta el segundo uso del dispositivo: la carpeta —y lo que deja a medias un
intercambio— tiene que contar como ruido para `device`.
"""

from _harness import Checks, falso_portatil, pe, tmpdir

from common import autorun, components, pins
from install import InstallError, device, traveler, veracrypt_bin

c = Checks("Traveler's Disk: VeraCrypt dentro del dispositivo")

X64, ARM64, X86 = 0x8664, 0xAA64, 0x014C


def falso_veracrypt(drivers=None, con_expander=True, exe=X64):
    """Una carpeta con la pinta de un VeraCrypt instalado.

    `drivers` es {nombre: máquina}. Por defecto, lo que deja el instalador de
    VeraCrypt en un x64: `veracrypt.sys` a secas, con cabecera x64, y los
    ejecutables sin la arquitectura en el nombre."""
    carpeta = tmpdir("prdrive-vc-origen-")
    ejecutables = ["VeraCrypt.exe", "VeraCrypt Format.exe"]
    if con_expander:
        ejecutables.append("VeraCryptExpander.exe")
    for nombre in ejecutables:
        (carpeta / nombre).write_bytes(pe(exe, nombre.encode()))
    (carpeta / "License.txt").write_text("licencia", encoding="utf-8")
    for nombre, maquina in (drivers or {"veracrypt.sys": X64}).items():
        (carpeta / nombre).write_bytes(pe(maquina))
    # Lo que NO debe viajar: el instalador pesa lo que pesa y no sirve de nada
    # en el dispositivo.
    (carpeta / "VeraCrypt Setup.exe").write_text("x", encoding="utf-8")
    return {"mount": str(carpeta / "VeraCrypt.exe"),
            "format": str(carpeta / "VeraCrypt Format.exe")}


def destinos(vc, raiz):
    return sorted(destino.name for _, destino in traveler.plan(vc, raiz))


def lo_que_hay(raiz):
    return sorted(p.name for p in (raiz / traveler.CARPETA).iterdir())


def fallo_de(funcion, *args):
    try:
        funcion(*args)
        return None
    except InstallError as e:
        return str(e)


PORTABLE = sorted([*veracrypt_bin.LICENCIAS, *(
    n for a in veracrypt_bin.ARQUITECTURAS
    for n in (veracrypt_bin.montar(a), veracrypt_bin.formatear(a),
              veracrypt_bin.expander(a), veracrypt_bin.driver(a)))])

reales = {"IS_WIN": traveler.IS_WIN, "ensure": veracrypt_bin.ensure_veracrypt,
          "libre": traveler.espacio_libre}
cache = falso_portatil()
bajadas: list[str] = []


def desde_cache(progreso=None, allow_download=True):
    bajadas.append("portable")
    return cache


try:
    traveler.IS_WIN = True
    veracrypt_bin.ensure_veracrypt = desde_cache

    # --- 1. el portable: lo que viaja, tal cual y con su sello -------------------
    raiz = tmpdir("prdrive-volumen-")
    puesto = traveler.instalar(None, raiz)
    c("viaja el portable entero, con sus nombres y su sello",
      lo_que_hay(raiz), sorted([*PORTABLE, components.VERACRYPT_STAMP]))
    c("las dos arquitecturas", traveler.arquitecturas(raiz / traveler.CARPETA),
      ["arm64", "x64"])
    c("sin renombrar nada: son los bytes de la caché",
      (raiz / traveler.CARPETA / "VeraCrypt-arm64.exe").read_bytes(),
      (cache / "VeraCrypt-arm64.exe").read_bytes())
    c("es el portable", (puesto.portatil, puesto.aviso), (True, ""))
    c("y dice lo que ha escrito", len(puesto.ficheros), len(PORTABLE) + 1)
    c("el sello dice la versión fijada", traveler.version_puesta(raiz),
      pins.VERACRYPT_VERSION)
    c("el volumen ya lleva VeraCrypt", traveler.instalado(raiz), True)
    c("sin restos del intercambio en la raíz",
      sorted(p.name for p in raiz.iterdir()), [traveler.CARPETA])

    # Idempotente: «Añadir plataformas…» sobre un dispositivo al día no copia nada.
    otra_vez = traveler.instalar(None, raiz)
    c("repetirlo con lo mismo no toca nada", (otra_vez.al_dia, otra_vez.ficheros),
      (True, []))
    (raiz / traveler.CARPETA / "veracrypt-x64.sys").write_bytes(b"estropeado")
    c("pero si un fichero ya no es el que dice el sello, se vuelve a poner",
      traveler.instalar(None, raiz).al_dia, False)
    c("y queda bien", (raiz / traveler.CARPETA / "veracrypt-x64.sys").read_bytes(),
      (cache / "veracrypt-x64.sys").read_bytes())

    # --- 2. sustituir, nunca copiar encima -----------------------------------------
    #
    # Un dispositivo de antes: la copia de una instalación, con `VeraCrypt.exe`.
    # Lo nuevo no se mezcla con lo viejo: la carpeta se cambia entera.
    viejo = tmpdir("prdrive-volumen-")
    (viejo / traveler.CARPETA).mkdir()
    (viejo / traveler.CARPETA / "VeraCrypt.exe").write_bytes(pe(X64))
    (viejo / traveler.CARPETA / "veracrypt-x64.sys").write_bytes(pe(X64))
    traveler.instalar(None, viejo)
    c("la carpeta de antes se sustituye entera: nada de VeraCrypt.exe suelto",
      lo_que_hay(viejo), sorted([*PORTABLE, components.VERACRYPT_STAMP]))

    # No cabe: no se toca nada, y se dice cuánto hace falta.
    lleno = tmpdir("prdrive-volumen-")
    (lleno / traveler.CARPETA).mkdir()
    (lleno / traveler.CARPETA / "VeraCrypt.exe").write_bytes(pe(X64))
    traveler.espacio_libre = lambda r: 1024      # los de mentira ocupan unos KB
    fallo = fallo_de(traveler.instalar, None, lleno)
    traveler.espacio_libre = reales["libre"]
    c.contains("si no cabe se dice", fallo or "", "No cabe VeraCrypt")
    c.contains("y que no se ha tocado nada", fallo or "", "No se ha tocado nada")
    c("y es verdad", (sorted(p.name for p in lleno.iterdir()), lo_que_hay(lleno)),
      ([traveler.CARPETA], ["VeraCrypt.exe"]))

    # Si la carpeta de antes no se puede apartar (Windows: un ejecutable en
    # marcha), la nueva se retira y la de antes sigue en su sitio.
    reemplazar = traveler.os.replace

    def no_se_aparta(a, b):
        if str(a).endswith(traveler.CARPETA):
            raise PermissionError("en uso")
        return reemplazar(a, b)

    traveler.os.replace = no_se_aparta
    try:
        fallo = fallo_de(traveler.sustituir, lleno,
                         traveler.plan_portatil(cache, lleno),
                         (cache / components.VERACRYPT_STAMP).read_text("utf-8"))
    finally:
        traveler.os.replace = reemplazar
    c.contains("apartar la de antes que está en uso se dice", fallo or "",
               "sigue en su sitio")
    c("sin dejar la nueva a medio poner",
      (sorted(p.name for p in lleno.iterdir()), lo_que_hay(lleno)),
      ([traveler.CARPETA], ["VeraCrypt.exe"]))

    # Los restos de un intercambio que no se pudo terminar se barren la próxima vez.
    resto = raiz / f".{traveler.CARPETA}.viejo-4242"
    resto.mkdir()
    (resto / "VeraCrypt-x64.exe").write_bytes(b"de la vez pasada")
    (raiz / traveler.CARPETA / "LICENSE").unlink()
    traveler.instalar(None, raiz)
    c("un resto de la vez pasada se barre", resto.exists(), False)

    # --- 3. sin red: la copia de la instalación, sin sello ---------------------------
    #
    # El instalador de VeraCrypt deja `VeraCrypt.exe` y `veracrypt.sys` (Setup.c)
    # y `DriverLoad()` busca `veracrypt-<arq>.sys`: se renombra según la cabecera,
    # como hace el propio diálogo de VeraCrypt con una instalación MSI.
    def sin_red(progreso=None, allow_download=True):
        raise veracrypt_bin.SinRed("No he podido descargar VeraCrypt: sin red")

    veracrypt_bin.ensure_veracrypt = sin_red
    vc = falso_veracrypt()
    nombres = destinos(vc, tmpdir())
    c("de una instalación x64 viajan los nombres del portable",
      nombres, sorted(["License.txt", "VeraCrypt-x64.exe", "VeraCrypt Format-x64.exe",
                       "VeraCryptExpander-x64.exe", "veracrypt-x64.sys"]))
    c("NO viaja el instalador", "VeraCrypt Setup.exe" in nombres, False)
    c("y todo va a la subcarpeta VeraCrypt/",
      {d.parent.name for _, d in traveler.plan(vc, tmpdir())}, {traveler.CARPETA})
    c("sin VeraCrypt de dónde copiar, no hay plan", traveler.plan(None, tmpdir()), [])
    c("la cabecera PE dice x64",
      traveler.maquina_pe(traveler.origen(vc) / "veracrypt.sys"), "x64")
    c("de un Windows ARM, los de arm64",
      destinos(falso_veracrypt({"veracrypt.sys": ARM64}, exe=ARM64), tmpdir()),
      sorted(["License.txt", "VeraCrypt-arm64.exe", "VeraCrypt Format-arm64.exe",
              "VeraCryptExpander-arm64.exe", "veracrypt-arm64.sys"]))
    c("una carpeta portátil, que ya los trae con nombre, viaja tal cual",
      [n for n in destinos({"mount": str(cache / "VeraCrypt-x64.exe")}, tmpdir())
       if n.endswith(".sys")], ["veracrypt-arm64.sys", "veracrypt-x64.sys"])
    doble = falso_veracrypt({"veracrypt.sys": X64, "veracrypt-x64.sys": X64})
    c("con los dos drivers de la misma CPU gana el que ya tiene el nombre bueno",
      [(o.name, d.name) for o, d in traveler.plan(doble, tmpdir())
       if d.name.endswith(".sys")], [("veracrypt-x64.sys", "veracrypt-x64.sys")])
    c("un driver x86 no viaja: DriverLoad() no lo busca",
      [n for n in destinos(falso_veracrypt({"veracrypt.sys": X86}), tmpdir())
       if n.endswith(".sys")], [])
    c("ni uno cuya cabecera no se entiende",
      [n for n in destinos(falso_veracrypt({"veracrypt.sys": None}), tmpdir())
       if n.endswith(".sys")], [])

    carpeta_pe = tmpdir("prdrive-pe-")
    for nombre, contenido in (("corto", b"MZ"), ("sin_pe", pe(X64)[:0x40]),
                              ("lejos", pe(X64)[:0x3C] + (10_000).to_bytes(4, "little"))):
        (carpeta_pe / nombre).write_bytes(contenido)
        c(f"una cabecera que no llega ({nombre}) no es ninguna CPU",
          traveler.maquina_pe(carpeta_pe / nombre), None)
    c("y un fichero que no existe, tampoco",
      traveler.maquina_pe(carpeta_pe / "no-existe"), None)
    c("arquitecturas() solo cuenta los nombres que VeraCrypt busca",
      traveler.arquitecturas(traveler.origen(vc)), [])

    sin_nada = tmpdir("prdrive-volumen-")
    puesto = traveler.instalar(vc, sin_nada)
    c("sin red y con VeraCrypt instalado, se copia el de este equipo",
      lo_que_hay(sin_nada), sorted(["License.txt", "VeraCrypt-x64.exe",
                                    "VeraCrypt Format-x64.exe",
                                    "VeraCryptExpander-x64.exe", "veracrypt-x64.sys"]))
    c("sin sello: no se sabe qué versión es", traveler.version_puesta(sin_nada), "")
    c("y se dice", puesto.portatil, False)
    c.contains("por qué", puesto.aviso, "No he podido bajar")
    c.contains("qué arquitectura lleva", puesto.aviso, "X64")
    c.contains("y cómo se arregla", puesto.aviso, "Añadir plataformas")

    fallo = fallo_de(traveler.instalar, None, tmpdir("prdrive-volumen-"))
    c.contains("sin red y sin VeraCrypt en el equipo, se dice las dos cosas",
               fallo or "", "no tiene un VeraCrypt instalado")
    fallo = fallo_de(traveler.instalar, falso_veracrypt({"veracrypt.sys": None}),
                     tmpdir("prdrive-volumen-"))
    c.contains("sin un driver que VeraCrypt portátil pueda cargar, también",
               fallo or "", "No sé con qué nombre")
    # Lo que ya lleva el portable comprobado no se cambia por una copia de una
    # sola arquitectura sin comprobar.
    fallo = fallo_de(traveler.instalar, vc, raiz)
    c.contains("con el portable ya puesto, sin red no se toca", fallo or "",
               "se queda como está")
    c("y sigue siendo el portable", traveler.version_puesta(raiz),
      pins.VERACRYPT_VERSION)

    # Un paquete que se baja y no cuadra NO cae en la copia: se dice.
    def no_cuadra(progreso=None, allow_download=True):
        raise InstallError("Lo descargado no es el paquete de VeraCrypt fijado.")

    veracrypt_bin.ensure_veracrypt = no_cuadra
    fallo = fallo_de(traveler.instalar, vc, tmpdir("prdrive-volumen-"))
    c.contains("un paquete que no cuadra no se esconde detrás de la copia",
               fallo or "", "no es el paquete")
    veracrypt_bin.ensure_veracrypt = desde_cache

    # --- 4. el autorun.inf: se edita, no se reescribe --------------------------------
    #
    # No ejecuta nada al conectar —AutoRun lleva desactivado para extraíbles
    # desde Windows 7—, pero la etiqueta y el icono sí los lee el Explorador. Las
    # órdenes `shell\…` Windows no las enseña en un extraíble (M2), y las de las
    # versiones anteriores apuntaban a un VeraCrypt.exe que el portable no trae.
    texto = traveler.autorun_texto("PRDRIVE")
    c("pone nombre a la unidad y su icono, y nada más",
      autorun.claves(texto), {"label": "PRDRIVE", "icon": autorun.ICONO_VERACRYPT})
    c("el icono es un ejecutable del portable",
      autorun.ICONO_VERACRYPT, "VeraCrypt\\VeraCrypt-x64.exe")
    destino = traveler.write_autorun(raiz, "PRDRIVE")
    c("se escribe en la raíz física, junto al .hc", destino.parent, raiz)
    c("en UTF-16, que es lo que lee el Explorador",
      destino.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff"), True)

    # El de un dispositivo de antes: sus órdenes, con algo de otro al lado.
    DE_ANTES = ("; mío\n[autorun]\nlabel=Pendrive de Pere\n"
                "icon=VeraCrypt\\VeraCrypt.exe\n"
                "action=Montar el volumen PRDRIVE\n"
                "shell\\montar=Montar el volumen PRDRIVE\n"
                'shell\\montar\\command=VeraCrypt\\VeraCrypt.exe /q /m rm /v "PRDRIVE.hc"\n'
                "shell\\desmontar=Desmontar todos los volúmenes\n"
                "shell\\desmontar\\command=VeraCrypt\\VeraCrypt.exe /q /dismount\n"
                "open=otra-cosa.exe\n[Content]\nMusicFiles=false\n")
    autorun.escribir(raiz, DE_ANTES)
    traveler.write_autorun(raiz)
    puesto_ahora = autorun.leer(raiz)
    c("las órdenes de antes se retiran",
      "shell" in puesto_ahora.texto or "action=" in puesto_ahora.texto, False)
    c("el nombre elegido se queda", puesto_ahora.etiqueta, "Pendrive de Pere")
    c("el icono de VeraCrypt pasa al ejecutable que lleva ahora",
      puesto_ahora.icono, "VeraCrypt\\VeraCrypt-x64.exe")
    c.contains("lo que no es de prdrive se queda", puesto_ahora.texto, "open=otra-cosa.exe")
    c.contains("las otras secciones también", puesto_ahora.texto, "[Content]")
    c.contains("y los comentarios", puesto_ahora.texto, "; mío")

    autorun.escribir(raiz, "[autorun]\nlabel=A\nicon=.prdrive-icono-verde.ico\n")
    traveler.write_autorun(raiz)
    c("un icono elegido que no es el de VeraCrypt se respeta",
      (autorun.leer(raiz).etiqueta, autorun.leer(raiz).icono),
      ("A", ".prdrive-icono-verde.ico"))

    solo_arm = tmpdir("prdrive-volumen-")
    (solo_arm / traveler.CARPETA).mkdir()
    (solo_arm / traveler.CARPETA / "VeraCrypt-arm64.exe").write_bytes(pe(ARM64))
    traveler.write_autorun(solo_arm)
    c("sin x64, el icono es el que haya", autorun.leer(solo_arm).icono,
      "VeraCrypt\\VeraCrypt-arm64.exe")

    # --- 5. lo que se le cuenta al usuario -------------------------------------------
    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(raiz)}
    c("dice que lleva VeraCrypt", etiquetas["VeraCrypt portátil"].ok, True)
    c("con las dos arquitecturas", etiquetas["Driver de VeraCrypt"].detalle, "arm64, x64")
    c("y la versión del portable",
      (etiquetas["Versión de VeraCrypt"].ok,
       pins.VERACRYPT_VERSION in etiquetas["Versión de VeraCrypt"].detalle), (True, True))
    c("y que se podrá agrandar el contenedor", etiquetas["VeraCrypt Expander"].ok, True)

    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(sin_nada)}
    c("la copia sin red: una sola arquitectura, y se avisa",
      etiquetas["Driver de VeraCrypt"].detalle.startswith("x64"), True)
    c("y que en un Windows ARM no monta",
      "Windows ARM no monta" in etiquetas["Driver de VeraCrypt"].detalle, True)
    c("sin sello, en rojo, diciendo cómo se arregla",
      (etiquetas["Versión de VeraCrypt"].ok,
       "Añadir plataformas" in etiquetas["Versión de VeraCrypt"].detalle), (False, True))

    # El traveler que dejaban las primeras versiones: el ejecutable y un
    # `veracrypt.sys` que VeraCrypt portátil no busca. Está, pero no sirve.
    muy_viejo = tmpdir("prdrive-volumen-")
    (muy_viejo / traveler.CARPETA).mkdir()
    (muy_viejo / traveler.CARPETA / "VeraCrypt.exe").write_text("x", encoding="utf-8")
    (muy_viejo / traveler.CARPETA / "veracrypt.sys").write_bytes(pe(X64))
    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(muy_viejo)}
    c("un traveler viejo no se da por bueno", etiquetas["Driver de VeraCrypt"].ok, False)
    c.contains("y se dice por qué y qué pulsar", etiquetas["Driver de VeraCrypt"].detalle,
               "Llevar VeraCrypt en el dispositivo")
    c("ni cuenta como instalado", traveler.instalado(muy_viejo), False)
    c.contains("«Añadir plataformas…» dice que lo cambia por el portable",
               traveler.lo_que_hara(muy_viejo), "VeraCrypt Portable oficial")
    traveler.instalar(None, muy_viejo)
    c("volver a llevarlo lo arregla", traveler.instalado(muy_viejo), True)
    c.contains("y ya no hay nada que cambiar", traveler.lo_que_hara(muy_viejo),
               "se queda como está")

    vacio = tmpdir("prdrive-volumen-")
    c("y sin nada, la lista es de una fila y roja",
      [(k.etiqueta, k.ok) for k in traveler.comprobar(vacio)],
      [("VeraCrypt portátil", False)])
    c("y no hay nada que decir de él", traveler.lo_que_hara(vacio), "")

    # --- 6. fuera de Windows no hay traveler -----------------------------------------
    traveler.IS_WIN = False
    c.contains("en Linux no se lleva", fallo_de(traveler.instalar, None, tmpdir()) or "",
               "cosa de Windows")
    traveler.IS_WIN = True
finally:
    traveler.IS_WIN = reales["IS_WIN"]
    veracrypt_bin.ensure_veracrypt = reales["ensure"]
    traveler.espacio_libre = reales["libre"]

# --- 7. la trampa de integración -----------------------------------------------------
#
# Con contenedor, la raíz FÍSICA lleva el .hc, el autorun.inf y la carpeta
# VeraCrypt/. Si esa carpeta no está en RUIDO, la siguiente vez que se enchufe el
# dispositivo el asistente lo lee como «aquí hay cosas de otro» y esconde el
# recorrido corto. Lo mismo lo que deja a medias un intercambio que no se pudo
# terminar de barrer.
c("la carpeta de VeraCrypt no cuenta como contenido ajeno",
  traveler.CARPETA.lower() in device.RUIDO, True)
for resto in (".VeraCrypt.viejo-1234", ".VeraCrypt.nuevo-99"):
    c(f"«{resto}» tampoco", device.es_ruido(resto), True)
c("pero una carpeta que solo se parece, sí", device.es_ruido(".VeraCrypt.fotos"), False)
fisica = tmpdir("prdrive-fisica-")
(fisica / "PRDRIVE.hc").write_text("x", encoding="utf-8")
(fisica / traveler.CARPETA).mkdir()
(fisica / ".VeraCrypt.viejo-1234").mkdir()
(fisica / "autorun.inf").write_text("x", encoding="utf-8")
estado, _ = device.install_target(fisica)
c("y la raíz de un dispositivo VeraCrypt no se lee como ajena", estado, device.VACIO)

raise SystemExit(c.report())
