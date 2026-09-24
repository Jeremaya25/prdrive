#!/usr/bin/env python3
"""
El VeraCrypt que viaja en el dispositivo (Traveler's Disk).

Sin esto, un dispositivo cifrado con VeraCrypt solo sirve en equipos que ya lo
tengan instalado, justo lo contrario de lo que hace el resto del proyecto. Y no
hay CLI para prepararlo: el diálogo de VeraCrypt extrae los binarios de su propio
`VeraCrypt Setup.exe`. Lo que sí es exacto —y es lo que se prueba aquí— es que
`DriverLoad()` carga de la carpeta del ejecutable un `.sys` con la arquitectura
en el nombre, y que el instalador de VeraCrypt lo deja como `veracrypt.sys`:
copiar la carpeta basta, pero renombrando el driver según su cabecera PE.

Todo sobre árboles falsos: ni se copia un VeraCrypt de verdad ni se toca ninguna
unidad. Lo que se comprueba es lo que decide —qué se copia, para qué
arquitectura, y qué se dice de ello—, más la trampa de integración que estaría
callada hasta el segundo uso del dispositivo: la carpeta nueva tiene que estar en
`device.RUIDO`.
"""

from _harness import Checks, tmpdir

from install import device, traveler

c = Checks("Traveler's Disk: VeraCrypt dentro del dispositivo")


def pe(maquina: int | None) -> bytes:
    """Lo justo de un binario de Windows para que se lea su CPU.

    Cabecera DOS con `e_lfanew` = 0x40, la firma `PE\\0\\0` ahí, y detrás el
    `Machine` de `IMAGE_FILE_HEADER`. None da algo que no es un PE."""
    if maquina is None:
        return b"esto no es un ejecutable"
    cabecera = bytearray(0x40)
    cabecera[0:2] = b"MZ"
    cabecera[0x3C:0x40] = (0x40).to_bytes(4, "little")
    return bytes(cabecera) + b"PE\0\0" + maquina.to_bytes(2, "little") + bytes(16)


X64, ARM64, X86 = 0x8664, 0xAA64, 0x014C


def falso_veracrypt(drivers=None, con_expander=True):
    """Una carpeta con la pinta de un VeraCrypt instalado.

    `drivers` es {nombre: máquina}. Por defecto, lo que deja el instalador de
    VeraCrypt en un x64: `veracrypt.sys` a secas, con cabecera x64."""
    carpeta = tmpdir("prdrive-vc-origen-")
    ficheros = ["VeraCrypt.exe", "VeraCrypt Format.exe", "License.txt"]
    if con_expander:
        ficheros.append("VeraCryptExpander.exe")
    for nombre in ficheros:
        (carpeta / nombre).write_text(nombre, encoding="utf-8")
    for nombre, maquina in (drivers or {"veracrypt.sys": X64}).items():
        (carpeta / nombre).write_bytes(pe(maquina))
    # Lo que NO debe viajar: el instalador pesa lo que pesa y no sirve de nada
    # en el dispositivo.
    (carpeta / "VeraCrypt Setup.exe").write_text("x", encoding="utf-8")
    return {"mount": str(carpeta / "VeraCrypt.exe"),
            "format": str(carpeta / "VeraCrypt Format.exe")}


def destinos(vc, raiz):
    return sorted(destino.name for _, destino in traveler.plan(vc, raiz))


win_original = traveler.IS_WIN
try:
    # --- 1. qué se copia, sin copiar nada -----------------------------------
    vc = falso_veracrypt()
    raiz = tmpdir("prdrive-volumen-")
    nombres = destinos(vc, raiz)
    c("viaja el ejecutable", "VeraCrypt.exe" in nombres, True)
    c("viaja el Expander, que es lo que agranda el contenedor luego",
      "VeraCryptExpander.exe" in nombres, True)
    c("viaja la licencia, que estamos copiando su programa",
      "License.txt" in nombres, True)
    c("NO viaja el instalador", "VeraCrypt Setup.exe" in nombres, False)
    c("y todo va a la subcarpeta VeraCrypt/",
      {d.parent.name for _, d in traveler.plan(vc, raiz)}, {traveler.CARPETA})
    c("sin VeraCrypt de dónde copiar, no hay plan", traveler.plan(None, raiz), [])

    # --- 2. el driver viaja con el nombre que VeraCrypt portátil busca ------
    #
    # El instalador de VeraCrypt lo deja como `veracrypt.sys` (Setup.c) y
    # `DriverLoad()` busca `veracrypt-x64.sys` o `veracrypt-arm64.sys`
    # (Dlgcode.c). Copiarlo tal cual era un traveler que no cargaba el driver
    # nunca. La arquitectura se lee de su cabecera, no se supone.
    c("la cabecera PE dice x64", traveler.maquina_pe(
        traveler.origen(vc) / "veracrypt.sys"), "x64")
    c("el veracrypt.sys de una instalación x64 viaja como veracrypt-x64.sys",
      [n for n in nombres if n.endswith(".sys")], ["veracrypt-x64.sys"])
    c("el de un Windows ARM, como veracrypt-arm64.sys",
      [n for n in destinos(falso_veracrypt({"veracrypt.sys": ARM64}), raiz)
       if n.endswith(".sys")], ["veracrypt-arm64.sys"])
    c("una carpeta portátil, que ya los trae con nombre, viaja tal cual",
      [n for n in destinos(falso_veracrypt({"veracrypt-x64.sys": X64,
                                            "veracrypt-arm64.sys": ARM64}), raiz)
       if n.endswith(".sys")], ["veracrypt-arm64.sys", "veracrypt-x64.sys"])
    doble = falso_veracrypt({"veracrypt.sys": X64, "veracrypt-x64.sys": X64})
    c("con los dos de la misma CPU gana el que ya tiene el nombre bueno",
      [(o.name, d.name) for o, d in traveler.plan(doble, raiz)
       if d.name.endswith(".sys")], [("veracrypt-x64.sys", "veracrypt-x64.sys")])
    c("un driver x86 no viaja: DriverLoad() no lo busca",
      [n for n in destinos(falso_veracrypt({"veracrypt.sys": X86}), raiz)
       if n.endswith(".sys")], [])
    c("ni uno cuya cabecera no se entiende",
      [n for n in destinos(falso_veracrypt({"veracrypt.sys": None}), raiz)
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
    c("y esos sí se reconocen",
      traveler.arquitecturas(traveler.origen(falso_veracrypt(
          {"veracrypt-x64.sys": X64, "veracrypt-arm64.sys": ARM64}))),
      ["arm64", "x64"])

    # --- 3. la copia, y que se pueda repetir para poner al día -------------
    traveler.IS_WIN = True
    escritos = traveler.instalar(vc, raiz)
    c("se ha copiado algo", len(escritos) >= 5, True)
    c("y el ejecutable está donde lo va a buscar el usuario",
      traveler.exe_portatil(raiz).is_file(), True)
    c("el volumen ya lleva VeraCrypt", traveler.instalado(raiz), True)
    # Idempotente a propósito: es también el botón «poner al día».
    traveler.instalar(vc, raiz)
    c("repetirlo no falla", traveler.instalado(raiz), True)

    pelado = falso_veracrypt()
    (traveler.origen(pelado) / "VeraCrypt.exe").unlink()
    try:
        traveler.instalar(pelado, tmpdir("prdrive-volumen-"))
        fallo = "no ha protestado"
    except Exception as e:                                   # noqa: BLE001
        fallo = type(e).__name__
    c("sin el ejecutable se protesta en vez de dejar una carpeta inútil",
      fallo, "InstallError")

    try:
        traveler.instalar(falso_veracrypt({"veracrypt.sys": None}),
                          tmpdir("prdrive-volumen-"))
        fallo = "no ha protestado"
    except Exception as e:                                   # noqa: BLE001
        fallo = type(e).__name__
    c("sin un driver que VeraCrypt portátil pueda cargar, también",
      fallo, "InstallError")

    # --- 4. el autorun.inf --------------------------------------------------
    #
    # No ejecuta nada al conectar —AutoRun lleva desactivado para extraíbles
    # desde Windows 7—, pero la etiqueta y el icono sí los lee el Explorador.
    texto = traveler.autorun_texto("PRDRIVE")
    c.contains("pone nombre a la unidad", texto, "label=PRDRIVE")
    c.contains("y su icono", texto, "icon=VeraCrypt\\VeraCrypt.exe")
    c.contains("«Montar» dice QUÉ montar, como el autorun del propio VeraCrypt",
               texto, '/q /m rm /v "PRDRIVE.hc"')
    c.contains("y desmontar usa /dismount, que aceptan todas las versiones",
               texto, "/q /dismount")
    c("y no /u, que no existe antes de la 1.26.24", "/u\n" in texto, False)
    destino = traveler.write_autorun(raiz, "PRDRIVE")
    c("se escribe en la raíz física, junto al .hc", destino.parent, raiz)
    c("en UTF-16, que es lo que lee el Explorador",
      destino.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff"), True)

    # --- 5. lo que se le cuenta al usuario ---------------------------------
    #
    # Cada arquitectura vale SOLO en la suya: IsARM() pregunta por la máquina
    # nativa, así que un VeraCrypt x64 emulado en un Windows ARM busca el driver
    # arm64, y un driver no se emula nunca.
    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(raiz)}
    c("dice que lleva VeraCrypt", etiquetas["VeraCrypt portátil"].ok, True)
    c("dice para qué arquitectura",
      etiquetas["Driver de VeraCrypt"].detalle.startswith("x64"), True)
    c("y que en un Windows ARM no monta",
      "Windows ARM no monta" in etiquetas["Driver de VeraCrypt"].detalle, True)
    c("y que se podrá agrandar el contenedor",
      etiquetas["VeraCrypt Expander"].ok, True)

    solo_arm = tmpdir("prdrive-volumen-")
    traveler.instalar(falso_veracrypt({"veracrypt.sys": ARM64}, con_expander=False),
                      solo_arm)
    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(solo_arm)}
    c("un traveler solo de ARM se avisa: no vale en un x64",
      "Windows x64 no monta" in etiquetas["Driver de VeraCrypt"].detalle, True)
    c("y sin Expander se dice, no se calla",
      etiquetas["VeraCrypt Expander"].ok, False)

    los_dos = tmpdir("prdrive-volumen-")
    traveler.instalar(falso_veracrypt({"veracrypt-x64.sys": X64,
                                       "veracrypt-arm64.sys": ARM64}), los_dos)
    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(los_dos)}
    c("con los dos, los dos", etiquetas["Driver de VeraCrypt"].detalle, "arm64, x64")

    # El traveler que dejaban las versiones anteriores: el ejecutable y un
    # `veracrypt.sys` que VeraCrypt portátil no busca. Está, pero no sirve, y
    # hay que decirlo con la salida en la mano.
    viejo = tmpdir("prdrive-volumen-")
    (viejo / traveler.CARPETA).mkdir()
    (viejo / traveler.CARPETA / "VeraCrypt.exe").write_text("x", encoding="utf-8")
    (viejo / traveler.CARPETA / "veracrypt.sys").write_bytes(pe(X64))
    etiquetas = {chk.etiqueta: chk for chk in traveler.comprobar(viejo)}
    c("un traveler viejo no se da por bueno", etiquetas["Driver de VeraCrypt"].ok, False)
    c.contains("y se dice por qué y qué pulsar", etiquetas["Driver de VeraCrypt"].detalle,
               "Llevar VeraCrypt en el dispositivo")
    c("ni cuenta como instalado", traveler.instalado(viejo), False)
    traveler.instalar(vc, viejo)
    c("volver a llevarlo lo arregla", traveler.instalado(viejo), True)

    vacio = tmpdir("prdrive-volumen-")
    c("y sin nada, la lista es de una fila y roja",
      [(k.etiqueta, k.ok) for k in traveler.comprobar(vacio)],
      [("VeraCrypt portátil", False)])

    # --- 6. la trampa de integración ---------------------------------------
    #
    # Con contenedor, la raíz FÍSICA lleva el .hc, el autorun.inf y ahora la
    # carpeta VeraCrypt/. Si esa carpeta no está en RUIDO, la siguiente vez que
    # se enchufe el dispositivo el asistente lo lee como «aquí hay cosas de
    # otro» y esconde el recorrido corto. Es el mismo fallo contra el que avisa
    # el comentario de `device.RUIDO`, una carpeta más tarde.
    c("la carpeta de VeraCrypt no cuenta como contenido ajeno",
      traveler.CARPETA.lower() in device.RUIDO, True)
    fisica = tmpdir("prdrive-fisica-")
    (fisica / "PRDRIVE.hc").write_text("x", encoding="utf-8")
    (fisica / traveler.CARPETA).mkdir()
    (fisica / "autorun.inf").write_text("x", encoding="utf-8")
    estado, _ = device.install_target(fisica)
    c("y la raíz de un dispositivo VeraCrypt no se lee como ajena",
      estado, device.VACIO)
finally:
    traveler.IS_WIN = win_original

raise SystemExit(c.report())
