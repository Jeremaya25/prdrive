#!/usr/bin/env python3
"""
VeraCrypt: cuánto tarda crear el contenedor, cómo se monta y qué se recuerda.

Crear el contenedor en un disco externo tardaba media hora, y la causa no era el
cifrado: con `/quick`, VeraCrypt preasigna el fichero y después escribe un sector
cada 128 MiB *a propósito* para forzar a Windows a materializar cada tramo, así
que NTFS acaba rellenando de ceros el contenedor entero. La salida es `/dynamic`,
que **solo vale si el anfitrión admite ficheros dispersos**: si no, VeraCrypt
aborta con ERR_DYNAMIC_NOT_SUPPORTED. Esa decisión —la que convierte media hora
en segundos, o la instalación en un error— es lo que se comprueba aquí.

Nada de esto lanza VeraCrypt ni toca una unidad: se sustituyen las sondas de
módulo (`soporta_dispersos`, `medir_escritura`, `volume_guid_path`, `_run`,
`_volumenes_con_control`), que para eso son funciones de módulo.
"""

from pathlib import PurePosixPath

from _harness import Checks, tmpdir

from install import crypto

c = Checks("VeraCrypt: creación, montaje y favorito")

VC = {"mount": "VeraCrypt.exe", "format": "VeraCrypt Format.exe"}
CONT = crypto.Path("P:/PRDRIVE.hc")

win_original = crypto.IS_WIN
path_original = crypto.Path
sondas = {n: getattr(crypto, n) for n in
          ("soporta_dispersos", "medir_escritura", "volume_guid_path", "en_uso",
           "_run", "_volumenes_con_control", "veracrypt_config_dir", "Path")}
try:
    # --- 1. /dynamic solo cuando se pide, y nunca a ciegas -------------------
    #
    # Pasárselo sobre exFAT no es «una opción que no hace nada»: VeraCrypt
    # aborta, y la instalación se cae en el primer paso que escribe algo.
    crypto.IS_WIN = True
    sin = crypto.create_command(VC, CONT, 1024, "s3cr3t", "exFAT")
    con = crypto.create_command(VC, CONT, 1024, "s3cr3t", "NTFS", dinamico=True)
    c("sin dinámico no aparece /dynamic", "/dynamic" in sin, False)
    c("con dinámico sí", "/dynamic" in con, True)
    c("y /quick sigue estando, que /dynamic lo exige", "/quick" in con, True)

    # En POSIX no existe el conmutador: pedirlo no puede colarlo en la orden.
    crypto.IS_WIN = False
    posix = crypto.create_command(VC, CONT, 1024, "s3cr3t", "exFAT", dinamico=True)
    c("en POSIX no hay /dynamic que valga", any("dynamic" in a for a in posix), False)
    c("y la contraseña va por stdin, no en la orden", "s3cr3t" in posix, False)

    # --- 2. el montaje, como medio extraíble --------------------------------
    #
    # Sin `/m rm`, Windows crea `System Volume Information` y `$RECYCLE.BIN`
    # DENTRO del contenedor, o sea dentro de lo que mira rclone.
    crypto.IS_WIN = True
    cmd = crypto.mount_command(VC, CONT, "s3cr3t", "P", etiqueta="PRDRIVE")
    c("monta como medio extraíble", cmd[cmd.index("/m") + 1], "rm")
    c("y con etiqueta para el Explorador", "label=PRDRIVE" in cmd, True)
    c("sin etiqueta no se emite un /m vacío",
      [a for a in crypto.mount_command(VC, CONT, "x", "P") if a.startswith("label=")], [])

    # La contraseña sigue tapándose con los flags nuevos delante y detrás.
    c("redact tapa la contraseña", crypto.PASSWORD_MARK in crypto.redact(cmd, "s3cr3t"),
      True)
    c("y no deja ni un rastro", "s3cr3t" in crypto.redact(cmd, "s3cr3t"), False)

    # --- 3. el tamaño propuesto deja de ser una espera de horas -------------
    #
    # Antes se proponía «libre − 1 GiB» siempre, y en un disco de 1 TB eso son
    # gigas que hay que ESCRIBIR antes de poder seguir instalando.
    TERA = 1024 ** 4
    c("con dinámico el tamaño deja de importar", crypto.suggested_size(TERA, True), "max")
    c("sin dinámico se pone tope", crypto.suggested_size(TERA, False), "64G")
    c("y en un disco pequeño se respeta el hueco",
      crypto.suggested_size(9 * 1024 ** 3, False), "8G")
    c("nunca se propone cero", crypto.suggested_size(0, False), "1G")

    # --- 4. la espera se mide, no se adivina --------------------------------
    crypto.medir_escritura = lambda root, muestra=0: 10 * 1024 ** 2   # 10 MB/s
    c("un giga a 10 MB/s son ~102 s",
      round(crypto.estimar_creacion("P:/", 1024 ** 3)), 102)
    c("y se dice en minutos", crypto.describir_espera(600), "unos 10 min")
    c("las esperas cortas se dicen así", crypto.describir_espera(30),
      "menos de dos minutos")
    crypto.medir_escritura = lambda root, muestra=0: None
    c("si no se ha podido medir, se dice; no se inventa un número",
      crypto.estimar_creacion("P:/", 1024 ** 3), None)
    c("y el texto lo reconoce",
      crypto.describir_espera(None), "no he podido medir la velocidad de la unidad")

    # --- 5. el favorito sobrevive a un cambio de letra ----------------------
    #
    # `P:\PRDRIVE.hc` deja de valer en cuanto la unidad coge otra letra en otro
    # equipo, que en un dispositivo portátil es lo normal.
    crypto.volume_guid_path = lambda root: "\\\\?\\Volume{1234-5678}\\"
    c("el contenedor se guarda por GUID de volumen",
      crypto.ruta_favorita(CONT), "\\\\?\\Volume{1234-5678}\\PRDRIVE.hc")
    crypto.volume_guid_path = lambda root: None
    c("y si Windows no lo da, se queda la ruta de siempre",
      crypto.ruta_favorita(CONT), str(CONT))

    config = tmpdir("prdrive-vc-")
    (config / "Configuration.xml").write_text("<VeraCrypt/>", encoding="utf-8")
    crypto.veracrypt_config_dir = lambda: config
    crypto.volume_guid_path = lambda root: "\\\\?\\Volume{1234-5678}\\"
    crypto.write_favorite(CONT, "P", label="PRDRIVE")
    xml = (config / "Favorite Volumes.xml").read_text(encoding="utf-8")
    c.contains("el favorito monta como extraíble", xml, 'removable="1"')
    c.contains("y enseña la etiqueta en el Explorador", xml, 'useLabelInExplorer="1"')
    c.contains("y guarda la ruta independiente de la letra", xml, "Volume{1234-5678}")
    c.contains("sigue montando al conectar", xml, 'mountOnArrival="1"')

    # --- 6. no montar dos veces lo que ya está montado ----------------------
    #
    # En POSIX se lo preguntamos a VeraCrypt. En Windows no hay listado por CLI
    # y se mira por el otro lado: una unidad con el fichero de control es este
    # dispositivo... pero solo si hay UNA. Con dos prdrive enchufados, adivinar
    # cuál es sería peor que no saberlo.
    #
    # Los listados se escriben a mano, carácter a carácter como los escribe
    # `UserInterface::ListMountedVolumes()` —el '-' de «sin montar» lleva un
    # espacio detrás—: generarlos con `crypto._entre_comillas()` daría por
    # bueno cualquier formato. `PurePosixPath` y no `Path`: son rutas de Linux
    # y esto tiene que pasar también en Windows.
    crypto.IS_WIN = False
    crypto.Path = PurePosixPath

    def montado(listado, ruta):
        crypto._run = lambda cmd, password="", timeout=None: type(
            "R", (), {"stdout": listado, "stderr": "", "returncode": 0})()
        punto = crypto.mounted_container(VC, PurePosixPath(ruta))
        return None if punto is None else str(punto)

    listado = ("1: /media/usb/PRDRIVE.hc /dev/mapper/veracrypt1 /media/veracrypt1\n"
               "2: /otro/cosa.hc /dev/mapper/veracrypt2 - \n")
    c("POSIX: lo encuentra por la ruta del anfitrión",
      montado(listado, "/media/usb/PRDRIVE.hc"), "/media/veracrypt1")
    c("y un volumen sin punto de montaje no cuenta",
      montado(listado, "/otro/cosa.hc"), None)
    c("ni uno que no está en la lista", montado(listado, "/nada.hc"), None)

    # udisks monta en /media/<usuario>/<ETIQUETA>, y «USB DISK» es una etiqueta
    # de lo más corriente. VeraCrypt entrecomilla con simples cada ruta que
    # lleva un espacio (`QuoteSpaces`); trocear la línea por espacios no la
    # reconocía nunca, y el instalador intentaba montar por segunda vez lo que
    # ya estaba montado —al volver atrás en el asistente, por ejemplo—.
    c("con espacios en la ruta del anfitrión y en el punto de montaje",
      montado("1: '/media/ana/USB DISK/PRDRIVE.hc' /dev/mapper/veracrypt1 "
              "'/media/ana/PRDRIVE 1'\n", "/media/ana/USB DISK/PRDRIVE.hc"),
      "/media/ana/PRDRIVE 1")
    c("una ruta que solo empieza igual es otra",
      montado("2: '/media/ana/USB DISK/PRDRIVE.hc.viejo' /dev/mapper/veracrypt2 "
              "/media/veracrypt2\n", "/media/ana/USB DISK/PRDRIVE.hc"), None)
    c("una comilla de dentro va doblada, y se deshace",
      montado("3: '/media/ana/O''Neil USB/PRDRIVE.hc' /dev/mapper/veracrypt3 "
              "'/mnt/it''s mine'\n", "/media/ana/O'Neil USB/PRDRIVE.hc"),
      "/mnt/it's mine")
    c("sin espacios no hay comillas, aunque la ruta lleve una",
      montado("4: /media/ana/O'Neil/PRDRIVE.hc /dev/mapper/veracrypt4 "
              "/media/veracrypt4\n", "/media/ana/O'Neil/PRDRIVE.hc"),
      "/media/veracrypt4")
    c("sin dispositivo, el '-' deja dos espacios y el punto sigue leyéndose",
      montado("5: '/media/ana/USB DISK/PRDRIVE.hc' -  '/media/ana/PRDRIVE 1'\n",
              "/media/ana/USB DISK/PRDRIVE.hc"), "/media/ana/PRDRIVE 1")
    c("y entre comillas el '-' sigue siendo «sin montar»",
      montado("6: '/media/ana/USB DISK/PRDRIVE.hc' /dev/mapper/veracrypt6 - \n",
              "/media/ana/USB DISK/PRDRIVE.hc"), None)

    # Lo único que QuoteSpaces no escapa es el salto de línea: parte el
    # registro, y leerlo tal cual daría una carpeta que no es. No se adivina.
    c("un salto de línea en una ruta invalida el listado",
      montado("1: /media/usb/PRDRIVE.hc /dev/mapper/veracrypt1 /media/vera\ncrypt1\n",
              "/media/usb/PRDRIVE.hc"), None)
    c("y un registro que no llega entero, también",
      montado("1: /media/usb/PRDRIVE.hc /dev/mapper/veracrypt1 /media/vera",
              "/media/usb/PRDRIVE.hc"), None)
    crypto.Path = sondas["Path"]

    crypto.IS_WIN = True
    raiz = crypto.Path("Q:/")
    crypto._volumenes_con_control = lambda: [raiz]
    crypto.en_uso = lambda container: True
    c("Windows: abierto y una sola candidata es la respuesta",
      crypto.mounted_container(VC, CONT), raiz)
    # El falso positivo que importa: OTRO prdrive enchufado a la vez lleva su
    # fichero de control, y sin la condición de «el contenedor está abierto» se
    # leería como que el nuestro está montado ahí. El instalador seguiría
    # adelante sobre el dispositivo equivocado.
    crypto.en_uso = lambda container: False
    c("pero si el contenedor no está abierto, no está montado: no se adivina",
      crypto.mounted_container(VC, CONT), None)
    crypto.en_uso = lambda container: True
    crypto._volumenes_con_control = lambda: [raiz, crypto.Path("R:/")]
    c("con dos candidatas, tampoco", crypto.mounted_container(VC, CONT), None)
    crypto._volumenes_con_control = lambda: []
    c("y con ninguna, tampoco", crypto.mounted_container(VC, CONT), None)

    # --- 7. por qué ha fallado, sin inventárselo ---------------------------
    def salida(texto):
        return type("R", (), {"stdout": texto, "stderr": "", "returncode": 1})()

    crypto.IS_WIN = False
    c("una contraseña mala se reconoce",
      crypto.explicar_montaje(salida("Error: Incorrect password or not a VeraCrypt volume."),
                              CONT),
      dict(crypto.FALLOS_MONTAJE)["incorrect password"])
    c("y la falta de permisos también",
      crypto.explicar_montaje(salida("Failed to obtain administrator privileges"), CONT),
      dict(crypto.FALLOS_MONTAJE)["administrator privileges"])
    generico = crypto.explicar_montaje(salida("algo que no dice nada"), CONT)
    c.contains("y si no casa ninguna, se dice «lo más habitual», no una causa",
               generico, "Lo más habitual")
finally:
    crypto.IS_WIN = win_original
    crypto.Path = path_original
    for nombre, funcion in sondas.items():
        setattr(crypto, nombre, funcion)

raise SystemExit(c.report())
