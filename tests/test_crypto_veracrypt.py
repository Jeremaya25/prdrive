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

El avance de una creación larga (#46) se prueba igual: `avance()` es pura y se le
dan secuencias de lecturas escritas a mano, y `bytes_escritos` se sustituye para
que `create_container()` lo lea sin que haya ninguna unidad detrás.
"""

import os
import sys
import time
from pathlib import PurePosixPath

from _harness import Checks, tmpdir

from install import crypto, device

c = Checks("VeraCrypt: creación, montaje y lo que se revisa antes")

VC = {"mount": "VeraCrypt.exe", "format": "VeraCrypt Format.exe"}
CONT = crypto.Path("P:/PRDRIVE.hc")

win_original = crypto.IS_WIN
path_original = crypto.Path
sondas = {n: getattr(crypto, n) for n in
          ("soporta_dispersos", "medir_escritura", "sistema_de_ficheros", "en_uso",
           "_run", "_procesos", "_volumenes_con_control", "Path", "MOUNT_POLL",
           "bytes_escritos", "SYS_DEV_BLOCK")}
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
    #
    # Y lo que se mide es la RÁFAGA: una sonda de 8 MiB no ve la caché de la
    # memoria USB llenarse. El caso de #46: más de 100 GB en exFAT, «unos 23
    # min» dichos y 40 cumplidos sin terminar. El número se da como mínimo, y
    # siempre al lado de por qué.
    crypto.medir_escritura = lambda root, muestra=0: 10 * 1024 ** 2   # 10 MB/s
    c("un giga a 10 MB/s son ~102 s",
      round(crypto.estimar_creacion("P:/", 1024 ** 3)), 102)
    c("el caso de #46 ya no promete 23 min: son un mínimo, y se dice por qué",
      crypto.describir_espera(23 * 60),
      "al menos unos 23 min; en memorias USB suele tardar bastante más, porque "
      "la velocidad baja cuando se llena su caché. Mientras se crea verás el "
      "avance real, si la unidad deja medirlo")
    c("en minutos, como mínimo", crypto.describir_espera(600).split(";")[0],
      "al menos unos 10 min")
    c("las esperas cortas tampoco prometen",
      crypto.describir_espera(30).split(";")[0], "en principio menos de dos minutos")
    c.contains("y llevan el mismo aviso", crypto.describir_espera(30),
               "cuando se llena su caché")
    c("hasta hora y media, en minutos", crypto.describir_espera(89 * 60).split(";")[0],
      "al menos unos 89 min")
    c("después, en horas y con coma", crypto.describir_espera(5400).split(";")[0],
      "al menos unas 1,5 h")
    c("sin un «,0» que nadie diría", crypto.describir_espera(7200).split(";")[0],
      "al menos unas 2 h")
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

    # --- 5e. el avance de una creación larga: la aritmética -----------------
    #
    # Con un contenedor fijo se escribe el volumen entero, y la ventana solo
    # tenía una barra que iba y venía. `avance()` convierte las lecturas del
    # contador de la unidad en «cuánto va» y «cuánto queda», y cuando el
    # contador no merece confianza no dice nada: mejor sin número que con uno
    # falso.
    MB = 1024 ** 2

    def serie(tramos, base=7 * GIB, t0=1000.0):
        """[(segundos, bytes por segundo), …] → una lectura por segundo, con la
        inicial delante (la de antes de lanzar VeraCrypt)."""
        muestras = [(t0, base)]
        t, b = t0, base
        for segundos, velocidad in tramos:
            for _ in range(int(segundos)):
                t, b = t + 1, b + velocidad
                muestras.append((t, b))
        return muestras

    def redondo(medida):
        return None if medida is None else (
            round(medida[0], 4), None if medida[1] is None else round(medida[1]))

    TAM = 6000 * MB
    c("a velocidad constante: lo escrito entre el tamaño, y lo que falta a esa "
      "velocidad", redondo(crypto.avance(serie([(120, 10 * MB)]), TAM)), (0.2, 480))
    c("los primeros segundos hay fracción, pero todavía no velocidad",
      redondo(crypto.avance(serie([(10, 10 * MB)]), TAM)), (round(100 / 6000, 4), None))
    c("sin haberse movido nunca no se sabe nada: el UAC, o un contador que no "
      "ve estas escrituras", crypto.avance(serie([(20, 0)]), TAM), None)

    # El UAC de la copia elevada fueron ~36 s en las pruebas en G: (sección 5
    # de los resultados). Esa espera no es lentitud de la unidad.
    tras_uac = serie([(40, 0), (40, 10 * MB)])
    c("tras la espera del UAC, la velocidad es la de la escritura, no la media "
      "con la espera", redondo(crypto.avance(tras_uac, TAM)), (round(400 / 6000, 4), 560))
    c("y hasta llevar un rato escribiendo no hay tiempo restante",
      crypto.avance(serie([(40, 0), (20, 10 * MB)]), TAM)[1], None)

    # El escalón de la caché SLC: rápido los primeros gigas, y de golpe a la
    # cuarta parte. El tiempo que queda tiene que SUBIR, que es justo lo que la
    # sonda de 8 MiB nunca podía saber.
    GRANDE = 60000 * MB
    antes_del_escalon = crypto.avance(serie([(120, 80 * MB)]), GRANDE)
    tras_el_escalon = crypto.avance(serie([(120, 80 * MB), (120, 20 * MB)]), GRANDE)
    c("escalón SLC: antes, lo que queda a 80 MB/s", round(antes_del_escalon[1]), 630)
    c("después, el tiempo restante crece aunque se haya escrito más",
      tras_el_escalon[1] > antes_del_escalon[1], True)
    c("y en cuanto la ventana entera es de después, es el de 20 MB/s",
      round(tras_el_escalon[1]), (60000 - 9600 - 2400) // 20)
    c("a medio escalón, entre lo de antes y lo de 20 MB/s",
      630 < crypto.avance(serie([(120, 80 * MB), (30, 20 * MB)]), GRANDE)[1]
      < (60000 - 9600 - 600) / 20, True)

    # Un contador que baja se ha reiniciado, o no cuenta lo que se creía: no
    # vale ni esa lectura ni ninguna de las siguientes.
    baja = serie([(90, 10 * MB)])
    baja.append((baja[-1][0] + 1, baja[-1][1] - 1))
    c("el contador baja: no se sabe", crypto.avance(baja, TAM), None)
    t, b = baja[-1]
    baja += [(t + i, b + i * 10 * MB) for i in range(1, 90)]
    c("y aunque vuelva a subir, ya no se le cree", crypto.avance(baja, TAM), None)

    c("parado más de PARADO_S: no se sabe",
      crypto.avance(serie([(90, 10 * MB), (crypto.PARADO_S + 1, 0)]), TAM), None)
    c("parado menos, todavía sí",
      crypto.avance(serie([(90, 10 * MB), (crypto.PARADO_S - 1, 0)]), TAM) is not None,
      True)
    c("y al volver a moverse, vuelve el número",
      crypto.avance(serie([(90, 10 * MB), (crypto.PARADO_S + 5, 0), (5, 10 * MB)]),
                    TAM) is not None, True)

    # El contador cuenta todo lo que se escriba en la unidad, no solo esto, y
    # después del relleno aún quedan la cabecera de respaldo y el formato.
    c("la fracción nunca pasa del 99 %",
      crypto.avance(serie([(120, 10 * MB)]), 100 * MB), (0.99, 0.0))
    c("ni con el contenedor justo escrito",
      crypto.avance(serie([(10, 10 * MB)]), 100 * MB)[0], 0.99)

    lecturas = serie([(60, 10 * MB)])
    c("sin la inicial no hay de dónde restar",
      crypto.avance([(lecturas[0][0], None)] + lecturas[1:], TAM), None)
    c("si falla la última lectura, no se sabe cómo va",
      crypto.avance(lecturas + [(lecturas[-1][0] + 1, None)], TAM), None)
    c("una que falla por en medio no estropea las demás",
      redondo(crypto.avance(lecturas[:30] + [(lecturas[30][0], None)] + lecturas[31:],
                            TAM)), redondo(crypto.avance(lecturas, TAM)))
    c("sin lecturas, nada", crypto.avance([], TAM), None)
    c("y con un tamaño que no es, tampoco", crypto.avance(lecturas, 0), None)

    # --- 5f. el avance, dicho --------------------------------------------------
    c("«43 % · quedan unos 25 min»", crypto.describir_avance(0.43, 25 * 60),
      "43 % · quedan unos 25 min")
    c("la cifra se trunca: el tope es 99 %, no 100 %",
      crypto.describir_avance(0.99, 30), "99 % · queda menos de un minuto")
    c("un minuto y algo", crypto.describir_avance(0.5, 75), "50 % · queda un minuto y pico")
    c("en horas, con coma", crypto.describir_avance(0.1, 9000),
      "10 % · quedan unas 2,5 h")
    c("sin velocidad todavía, se dice", crypto.describir_avance(0.02, None),
      "2 % · calculando cuánto queda")

    # --- 5g. el contador de la unidad ------------------------------------------
    #
    # Lo de verdad solo se puede leer con una unidad de verdad (pruebas P1–P7
    # de #46). Lo que sí se puede fijar aquí es cómo se lee: el campo, la
    # unidad, y la estructura de Windows byte a byte contra winioctl.h.
    c("IOCTL_DISK_PERFORMANCE es CTL_CODE(IOCTL_DISK_BASE, 8, BUFFERED, ANY)",
      crypto.IOCTL_DISK_PERFORMANCE, 0x00070020)
    import ctypes  # noqa: E402

    DP = crypto._disk_performance()
    c("DISK_PERFORMANCE mide 88 bytes, como en Windows", ctypes.sizeof(DP), 88)
    c("BytesWritten es el segundo LARGE_INTEGER", DP.BytesWritten.offset, 8)
    c("y detrás de los cuatro DWORD va QueryTime",
      (DP.QueryTime.offset, DP.StorageDeviceNumber.offset,
       DP.StorageManagerName.offset), (56, 64, 68))
    c("una ruta sin letra no tiene volumen que abrir",
      crypto._escritos_windows("\\\\servidor\\recurso"), None)

    if hasattr(os, "major"):
        # /sys/dev/block/<mayor>:<menor>/stat, falso: el séptimo campo son
        # sectores escritos, y un sector ahí es siempre de 512 bytes.
        sysfs = tmpdir("prdrive-sysfs-")
        raiz = tmpdir("prdrive-raiz-")
        st = os.stat(raiz)
        nodo = sysfs / f"{os.major(st.st_dev)}:{os.minor(st.st_dev)}"
        nodo.mkdir()
        (nodo / "stat").write_text(
            "    4262     1049   311426     1542    73113    41507  1234567    79440"
            "        0    67264    81958        0        0        0        0\n",
            encoding="ascii")
        crypto.SYS_DEV_BLOCK = sysfs
        crypto.IS_WIN = False
        c("Linux: los sectores escritos del dispositivo de la raíz, en bytes",
          crypto.bytes_escritos(raiz), 1234567 * 512)
        crypto.SYS_DEV_BLOCK = tmpdir("prdrive-sysfs-vacio-")
        c("sin dispositivo de bloques detrás (tmpfs…), None",
          crypto.bytes_escritos(raiz), None)
        (nodo / "stat").write_text("4262 1049\n", encoding="ascii")
        crypto.SYS_DEV_BLOCK = sysfs
        c("y un stat que no es el que se espera, también None",
          crypto.bytes_escritos(raiz), None)
        crypto.SYS_DEV_BLOCK = sondas["SYS_DEV_BLOCK"]
    if sys.platform != "win32":
        crypto.IS_WIN = True
        c("un fallo de ctypes es None, no una excepción",
          crypto.bytes_escritos("G:\\"), None)
        crypto.IS_WIN = False

    # --- 5h. crear, midiendo: el contador se apunta antes de lanzar ----------
    #
    # `create_container()` apunta la lectura inicial ANTES de lanzar VeraCrypt
    # —lo de antes no es de esta creación— y la va leyendo en otro hilo hasta
    # volver. Aquí VeraCrypt es un `_run` que escribe el fichero, y el contador
    # uno que crece un mega por lectura.
    crypto.IS_WIN = False
    contador = {"bytes": 5000, "lecturas": []}

    def escritos(root):
        contador["lecturas"].append(str(root))
        contador["bytes"] += MB
        return contador["bytes"]

    hc = tmpdir("prdrive-avance-") / "PRDRIVE.hc"
    al_lanzar = []

    def lanzar_escribiendo(cmd, password="", timeout=None):
        al_lanzar.append(len(contador["lecturas"]))
        time.sleep(0.3)                     # VeraCrypt escribiendo el volumen
        al_lanzar.append(len(contador["lecturas"]))
        hc.write_bytes(b"entero")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    crypto.bytes_escritos = escritos
    crypto._run = lanzar_escribiendo
    seguimiento = crypto.Seguimiento(cada=0.01)
    try:
        crypto.create_container(VC, hc, GIB, "x" * 20, "exFAT", seguimiento=seguimiento)
        fallo = None
    except crypto.InstallError as e:
        fallo = str(e)
    c("crear midiendo no cambia nada de crear", (fallo, hc.read_bytes()),
      (None, b"entero"))
    c("la lectura inicial va antes de lanzar VeraCrypt", al_lanzar[0] >= 1, True)
    c("y es la primera muestra", seguimiento.muestras[0][1], 5000 + MB)
    c("de la raíz física, la que lleva el contenedor", contador["lecturas"][0],
      str(hc.parent))
    c("mientras VeraCrypt escribe se sigue leyendo", al_lanzar[1] > al_lanzar[0], True)
    leidas = len(contador["lecturas"])
    time.sleep(0.1)
    c("y al volver se deja de leer", len(contador["lecturas"]), leidas)
    c("lo que ve la ventana: cuánto va, y que aún no hay velocidad",
      seguimiento.progreso()[1].endswith("calculando cuánto queda"), True)

    # Un contador que no se puede leer no puede impedir crear.
    crypto.bytes_escritos = lambda root: None
    hc = tmpdir("prdrive-avance-") / "PRDRIVE.hc"
    seguimiento = crypto.Seguimiento(cada=0.01)
    try:
        crypto.create_container(VC, hc, GIB, "x" * 20, "exFAT", seguimiento=seguimiento)
        fallo = None
    except crypto.InstallError as e:
        fallo = str(e)
    c("sin contador se crea igual", (fallo, hc.read_bytes()), (None, b"entero"))
    c("y la ventana no recibe ningún número", seguimiento.progreso(), None)

    # Si VeraCrypt no llega a lanzarse, el hilo no se queda leyendo.
    def no_lanza(cmd, password="", timeout=None):
        raise OSError("no existe")

    crypto._run = no_lanza
    seguimiento = crypto.Seguimiento(cada=0.01)
    try:
        crypto.create_container(VC, tmpdir("prdrive-avance-") / "PRDRIVE.hc", GIB,
                                "x" * 20, "exFAT", seguimiento=seguimiento)
    except crypto.InstallError:
        pass
    c("si VeraCrypt no se lanza, el hilo del avance para",
      seguimiento._hilo is not None and seguimiento._hilo.is_alive(), False)

    # Lo que ve la ventana caduca: si el hilo se queda colgado en una lectura,
    # el último número calculado no se sigue enseñando como si fuera de ahora.
    reloj = {"t": 0.0}
    crypto.bytes_escritos = escritos
    seguimiento = crypto.Seguimiento(cada=1000, reloj=lambda: reloj["t"])
    seguimiento.empezar(hc.parent, GIB)
    for _ in range(40):
        reloj["t"] += 1
        seguimiento._apuntar()
    c("con lecturas recientes hay número", seguimiento.leer() is not None, True)
    reloj["t"] += crypto.PARADO_S + 1
    c("sin lecturas en PARADO_S, deja de haberlo", seguimiento.leer(), None)
    seguimiento.parar()

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
