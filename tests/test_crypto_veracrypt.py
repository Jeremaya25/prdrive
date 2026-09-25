#!/usr/bin/env python3
"""
VeraCrypt: cuánto tarda crear el contenedor, cómo se monta y qué se revisa antes.

Crear el contenedor en un disco externo tardaba media hora, y la causa no era el
cifrado: con `/quick`, VeraCrypt preasigna el fichero y después escribe un sector
cada 128 MiB *a propósito* para forzar a Windows a materializar cada tramo, así
que NTFS acaba rellenando de ceros el contenedor entero. La salida es `/dynamic`,
que **solo vale si el anfitrión admite ficheros dispersos**: si no, VeraCrypt
aborta con ERR_DYNAMIC_NOT_SUPPORTED. Esa decisión —la que convierte media hora
en segundos, o la instalación en un error— es lo que se comprueba aquí.

Nada de esto lanza VeraCrypt ni toca una unidad: se sustituyen las sondas de
módulo (`soporta_dispersos`, `medir_escritura`, `sistema_de_ficheros`, `_run`,
`_volumenes_con_control`), que para eso son funciones de módulo.
"""

from pathlib import PurePosixPath

from _harness import Checks, tmpdir

from common import pins
from install import crypto, device

c = Checks("VeraCrypt: creación, montaje y lo que se revisa antes")

VC = {"mount": "VeraCrypt.exe", "format": "VeraCrypt Format.exe"}
CONT = crypto.Path("P:/PRDRIVE.hc")

win_original = crypto.IS_WIN
path_original = crypto.Path
sondas = {n: getattr(crypto, n) for n in
          ("soporta_dispersos", "medir_escritura", "sistema_de_ficheros", "en_uso",
           "_run", "_procesos", "_volumenes_con_control", "Path", "MOUNT_POLL")}
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

    # --- 5. FAT32: un fichero no llega a 4 GiB ------------------------------
    #
    # Casi todos los pendrives de 32 GB o menos vienen en FAT32, y el contenedor
    # es un fichero. Se proponía «el hueco, hasta 64G» y VeraCrypt fallaba al
    # crear sin decir esto. El tope es 4095 MiB y no 4 GiB − 1 porque VeraCrypt
    # redondea /size HACIA ARRIBA al tamaño de sector (Tcformat.c).
    MIB, GIB = 1024 ** 2, 1024 ** 3
    for nombre in ("FAT32", "FAT", "fat16", "vfat", "msdos"):
        c(f"{nombre} tiene tope", crypto.tope_contenedor(nombre), 4095 * MIB)
    for nombre in ("exFAT", "exfat", "NTFS", "ext4", ""):
        c(f"{nombre or 'sin nombre'} no (exFAT contiene «fat» y no es FAT)",
          crypto.tope_contenedor(nombre), None)
    c("el tope es múltiplo de cualquier sector", (4095 * MIB) % 4096, 0)
    c("y no llega a 4 GiB", 4095 * MIB < 4 * GIB, True)

    TOPE = crypto.TOPE_FAT
    c("en un pendrive FAT32 de 32 GB se propone el tope, en megas",
      crypto.suggested_size(30 * GIB, False, TOPE), "4095M")
    c("y si el hueco es menor, el hueco", crypto.suggested_size(3 * GIB, False, TOPE), "2G")
    c("'max' tampoco pasa del tope", crypto.size_to_bytes("max", 30 * GIB, TOPE), TOPE)
    c("sin tope, 'max' es el hueco menos el margen",
      crypto.size_to_bytes("max", 30 * GIB), 30 * GIB - crypto.MARGEN)
    c("un tamaño escrito a mano no se rebaja en silencio",
      crypto.size_to_bytes("8G", 30 * GIB, TOPE), 8 * GIB)

    lanzado = []
    crypto._run = lambda cmd, password="", timeout=None: lanzado.append(cmd)
    crypto.sistema_de_ficheros = lambda root: "FAT32"
    vacio = tmpdir("prdrive-fat-")
    try:
        crypto.create_container(VC, vacio / "PRDRIVE.hc", 8 * GIB, "x" * 20, "exFAT")
        fallo = "no ha protestado"
    except crypto.InstallError as e:
        fallo = str(e)
    c.contains("crear más grande que el tope se rechaza, diciendo el límite",
               fallo, "4095M")
    c.contains("y la salida", fallo, "exFAT o NTFS")
    c("sin llegar a lanzar VeraCrypt", lanzado, [])

    # --- 5b. la contraseña: lo que VeraCrypt diría sin /silent ---------------
    #
    # Con /silent, VeraCrypt Format se salta la pregunta de «contraseña corta»
    # (CheckPasswordLength con bSkipPasswordWarning = Silent). Nadie la hacía.
    # Se mide en bytes UTF-8, como mide VeraCrypt: una tilde cuenta dos.
    c("vacía, error", crypto.revisar_contrasena("")[0] is not None, True)
    c("19 bytes, aviso y no error",
      [x is not None for x in crypto.revisar_contrasena("a" * 19)], [False, True])
    c("20 bytes, nada", crypto.revisar_contrasena("a" * 20), (None, None))
    c("128 bytes, nada", crypto.revisar_contrasena("a" * 128), (None, None))
    c("129 bytes, error", crypto.revisar_contrasena("a" * 129)[0] is not None, True)
    c("diez eñes son veinte bytes: sin aviso", crypto.revisar_contrasena("ñ" * 10),
      (None, None))
    c("65 eñes son 130 bytes: error aunque sean 65 letras",
      crypto.revisar_contrasena("ñ" * 65)[0] is not None, True)

    # --- 5c. la instalación en claro que se queda al recifrar ----------------
    #
    # «Reinstalar desde cero» con VeraCrypt sobre un prdrive sin cifrar crea el
    # contenedor al lado: la instalación de antes, con la clave en claro, sigue
    # ahí. Se dice, y no se borra sola.
    fisica = tmpdir("prdrive-fisica-")
    (fisica / "PRDRIVE.hc").write_bytes(b"x")
    (fisica / "VeraCrypt").mkdir()
    c("una raíz de VeraCrypt sin restos no tiene nada que decir",
      crypto.restos_en_claro(fisica), [])
    c("ni fila en la verificación", crypto.comprobar_restos(fisica), [])
    (fisica / device.CONTROL_FILE).parent.mkdir()
    (fisica / device.CONTROL_FILE).write_text("id=viejo\n", encoding="utf-8")
    (fisica / "sync-data").mkdir()
    (fisica / "runsync.bat").write_text("x", encoding="utf-8")
    (fisica / "notas.txt").write_text("x", encoding="utf-8")
    c("con un prdrive en claro: el programa, y las carpetas de datos",
      crypto.restos_en_claro(fisica), [".prdrive/", "notas.txt", "sync-data/"])
    c.contains("el aviso nombra la clave", crypto.aviso_restos(
        crypto.restos_en_claro(fisica)), ".prdrive/keys/")
    c.contains("y dice que la borre a mano, no que se va a borrar",
               crypto.aviso_restos(crypto.restos_en_claro(fisica)), "bórrala a mano")
    fila = crypto.comprobar_restos(fisica)
    c("y la verificación lleva una fila roja",
      [(k.etiqueta, k.ok) for k in fila], [("Instalación sin cifrar", False)])
    c("una ruta que no existe no revienta",
      crypto.restos_en_claro(fisica / "no-existe"), [])

    # --- 5d. crear: no hay contenedor hasta que termina la copia elevada -----
    #
    # El VeraCrypt Format que viaja, sin administrador, se relanza elevado y el
    # proceso que lanzamos sale con 0 mientras la copia sigue escribiendo. Darlo
    # por creado ahí era montar un contenedor a medio hacer, que se quedaba sin
    # sistema de ficheros e inservible (H-4 en
    # docs/superpowers/pruebas/2026-09-24-veracrypt-unidad-g-resultados.md).
    crypto.IS_WIN = True
    crypto.sistema_de_ficheros = lambda root: "exFAT"
    crypto.MOUNT_POLL = 0
    hc = tmpdir("prdrive-crear-") / "PRDRIVE.hc"
    tabla = {111}                   # un VeraCrypt Format que ya estaba abierto
    vistas = []

    def lanzar(cmd, password="", timeout=None):
        hc.write_bytes(b"a medias")
        tabla.add(26060)            # la copia elevada, que sigue trabajando
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def procesos(nombre):
        vistas.append(nombre)
        if len(vistas) > 50:
            raise RuntimeError("esperando sin fin")
        if 26060 in tabla and len(vistas) > 3:      # termina a la cuarta mirada
            hc.write_bytes(b"entero")
            tabla.discard(26060)
        return set(tabla)

    crypto._run = lanzar
    crypto._procesos = procesos
    try:
        crypto.create_container(VC, hc, GIB, "x" * 20, "exFAT")
        fallo = None
    except (crypto.InstallError, RuntimeError) as e:
        fallo = str(e)
    c("crear no protesta", fallo, None)
    c("y no vuelve hasta que termina la copia elevada", hc.read_bytes(), b"entero")
    c("la busca por el nombre del Format que lanza", set(vistas),
      {"VeraCrypt Format.exe"})
    c("y el que ya estaba abierto no la hace esperar", len(vistas) < 50, True)

    tabla.clear()
    vistas.clear()
    crypto._run = lambda cmd, password="", timeout=None: type(
        "R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    try:
        crypto.create_container(VC, tmpdir("prdrive-crear-") / "PRDRIVE.hc", GIB,
                                "x" * 20, "exFAT")
        fallo = "no ha protestado"
    except crypto.InstallError as e:
        fallo = str(e)
    c.contains("si al terminar no hay contenedor, se dice", fallo,
               "no ha podido crear el contenedor")

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

    # --- 8. sin VeraCrypt instalado: el portable (#50, #38) ------------------
    #
    # El paquete portable no trae ningún `VeraCrypt.exe`: trae `VeraCrypt-x64.exe`,
    # `VeraCrypt Format-x64.exe` y los `-arm64`. Con una carpeta así, «dime dónde
    # está» no encontraba nada (#38). Y cuál de los dos usar lo dice la máquina
    # NATIVA, como a VeraCrypt (`IsARM()`), no lo que oye un instalador x64
    # emulado: la sonda del sistema se sustituye, como en tests/test_arch.py.
    from _harness import falso_portatil
    from common import model
    from install import veracrypt_bin

    crypto.IS_WIN = True
    sonda_original = model.maquina_nativa_windows
    cached_original = veracrypt_bin.cached
    candidatos_originales = crypto.WIN_CANDIDATES
    # El equipo que pasa la batería puede tener VeraCrypt instalado: aquí se
    # pregunta qué pasa sin él.
    crypto.WIN_CANDIDATES = {"mount": [], "format": []}
    try:
        portable = falso_portatil()
        veracrypt_bin.cached = lambda: None
        model.maquina_nativa_windows = lambda: 0x8664
        vc = crypto.find_veracrypt(portable)
        c("una carpeta del portable se reconoce (#38)",
          vc and (crypto.Path(vc["mount"]).name, crypto.Path(vc["format"]).name),
          ("VeraCrypt-x64.exe", "VeraCrypt Format-x64.exe"))
        c("y se sabe que es el portable (cada paso pedirá UAC)",
          crypto.portatil(vc), True)
        model.maquina_nativa_windows = lambda: 0xAA64
        vc = crypto.find_veracrypt(portable)
        c("en un Windows ARM, los de arm64, aunque el instalador sea x64 emulado",
          vc and crypto.Path(vc["mount"]).name, "VeraCrypt-arm64.exe")
        c("el Format que se lanza es el suyo",
          vc and crypto.Path(vc["format"]).name, "VeraCrypt Format-arm64.exe")

        instalacion = tmpdir("prdrive-vc-instalado-")
        for nombre in ("VeraCrypt.exe", "VeraCrypt Format.exe"):
            (instalacion / nombre).write_bytes(b"MZ")
        vc = crypto.find_veracrypt(instalacion)
        c("una carpeta con la disposición de una instalación sigue valiendo",
          vc and crypto.Path(vc["mount"]).name, "VeraCrypt.exe")
        c("y esa no es el portable", crypto.portatil(vc), False)
        media = tmpdir("prdrive-vc-medio-")
        (media / "VeraCrypt-arm64.exe").write_bytes(b"MZ")
        (media / "VeraCrypt Format.exe").write_bytes(b"MZ")
        c("montar de una y formatear de otra no se mezclan",
          crypto.find_veracrypt(media), None)

        # Sin carpeta que mirar y sin instalado: el portable de la caché, si
        # está y sigue siendo el comprobado. Bajarlo lo pide la pantalla.
        c("sin nada, None", crypto.find_veracrypt(), None)
        veracrypt_bin.cached = lambda: portable
        model.maquina_nativa_windows = lambda: 0x8664
        vc = crypto.find_veracrypt()
        c("con el portable en la caché, ese",
          vc and crypto.Path(vc["mount"]), portable / "VeraCrypt-x64.exe")

        # Crear con el portable: la copia elevada es `VeraCrypt Format-x64.exe`,
        # y es a esa a la que hay que esperar (H-4).
        vistas.clear()
        crypto._procesos = lambda nombre: vistas.append(nombre) or set()
        crypto._run = lambda cmd, password="", timeout=None: (
            hc2.write_bytes(b"x"), type("R", (), {"returncode": 0, "stdout": "",
                                                  "stderr": ""})())[1]
        hc2 = tmpdir("prdrive-crear-") / "PRDRIVE.hc"
        crypto.create_container(vc, hc2, GIB, "x" * 20, "exFAT")
        c("con el portable se espera a SU Format, por su nombre",
          set(vistas), {"VeraCrypt Format-x64.exe"})
    finally:
        model.maquina_nativa_windows = sonda_original
        veracrypt_bin.cached = cached_original
        crypto.WIN_CANDIDATES = candidatos_originales

    # --- 9. 'max' deja sitio para el VeraCrypt de viaje ------------------------
    #
    # Con 50 MiB libres fuera, un contenedor 'max' dejaba la unidad sin sitio
    # para poner al día el VeraCrypt que viaja: la carpeta nueva se copia al
    # lado de la vieja antes de cambiarlas.
    c("con VeraCrypt de viaje, 'max' deja la reserva",
      crypto.size_to_bytes("max", 30 * GIB, viajero=True),
      30 * GIB - crypto.RESERVA_VIAJERO)
    c("que es de 256 MiB", crypto.RESERVA_VIAJERO, 256 * MIB)
    c("y cabe dos veces lo que ocupa", crypto.RESERVA_VIAJERO > 2 * pins.MB_VERACRYPT * MIB,
      True)
    c("sin él, el margen de siempre", crypto.size_to_bytes("max", 30 * GIB),
      30 * GIB - crypto.MARGEN)
    c("el tope de FAT32 sigue mandando",
      crypto.size_to_bytes("max", 30 * GIB, TOPE, viajero=True), TOPE)
    c("y un tamaño escrito a mano no se toca",
      crypto.size_to_bytes("8G", 30 * GIB, viajero=True), 8 * GIB)
finally:
    crypto.IS_WIN = win_original
    crypto.Path = path_original
    for nombre, funcion in sondas.items():
        setattr(crypto, nombre, funcion)

raise SystemExit(c.report())
