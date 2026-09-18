#!/usr/bin/env python3
"""
El código QR de emparejamiento: el codificador y lo que va dentro.

Un codificador de QR no se puede probar «a ojo»: o lo lee una cámara o no vale,
y aquí no hay cámara. Así que se comprueban tres cosas distintas, y las tres
hacen falta:

1. **Vectores conocidos**, los de la norma ISO/IEC 18004 y sus tablas
   publicadas: los polinomios generadores de Reed-Solomon expresados en
   exponentes de alfa, la información de formato y de versión, los centros de
   los patrones de alineación y —la más valiosa— las capacidades en modo byte,
   que dependen de las DOS tablas que están copiadas a mano en `ui/qr.py` y de
   la fórmula de los módulos de datos. Si alguna cifra de esas tablas estuviera
   mal, la capacidad de su versión no cuadraría.

2. **La vuelta entera**: se decodifica el dibujo. El decodificador está aquí y
   no en `ui/qr.py` porque el proyecto no necesita leer códigos QR —eso lo hace
   el móvil—, pero sí necesita saber que lo que dibuja se puede leer. Deshace
   la máscara, recorre el zigzag, deshace el intercalado de bloques y saca el
   mensaje. Lo único que toma prestado del codificador es el mapa de patrones de
   función, que va comprobado aparte en (3).

3. **La estructura**: los tres patrones de búsqueda, las líneas de
   temporización, el módulo oscuro y el tamaño.

Y encima de todo eso, el viaje que importa de verdad: de un dispositivo de
mentira a `pairing.construir()`, al QR, de vuelta, y a `profile.loads()`, que es
lo que leerá el móvil. Ese es el que impide que el formato de `common/pairing.py`
y el de `install/profile.py` se separen.
"""

import sys

from _harness import Checks, tmpdir

from common import pairing
from common.model import ConfigError
from install import profile
from ui import qr

c = Checks("código QR de emparejamiento")


# ---------------------------------------------------------------------------
# 1. Vectores conocidos
# ---------------------------------------------------------------------------

def _exponentes(coeficientes):
    """Los coeficientes de un polinomio como exponentes de alfa, que es como los
    publica la tabla de la norma."""
    log = [0] * 256
    x = 1
    for i in range(255):
        log[x] = i
        x = (x << 1) ^ (0x11D if x & 0x80 else 0)
    return [log[coef] for coef in coeficientes]


# Los generadores de Reed-Solomon, tal y como salen tabulados.
c("generador de grado 7", _exponentes(qr._divisor(7)),
  [87, 229, 146, 149, 238, 102, 21])
c("generador de grado 10", _exponentes(qr._divisor(10)),
  [251, 67, 46, 61, 118, 70, 64, 94, 32, 45])
c("generador de grado 13", _exponentes(qr._divisor(13)),
  [74, 152, 176, 100, 86, 100, 106, 104, 130, 218, 206, 140, 78])

# Las capacidades en modo byte. Es la comprobación que cubre las dos tablas
# copiadas a mano y la fórmula de los módulos de datos a la vez.
CAPACIDADES = {
    1: (17, 14, 11, 7),
    2: (32, 26, 20, 14),
    10: (271, 213, 151, 119),
    40: (2953, 2331, 1663, 1273),
}
for version, esperadas in CAPACIDADES.items():
    c(f"capacidad en bytes de la versión {version}",
      tuple(qr.capacidad(version, n) for n in "LMQH"), esperadas)

# Los centros de los patrones de alineación. La 32 es la que la norma tabula
# aparte, así que es justo la que hay que mirar.
c("alineación de la versión 1", qr._alineaciones(1), [])
c("alineación de la versión 2", qr._alineaciones(2), [6, 18])
c("alineación de la versión 7", qr._alineaciones(7), [6, 22, 38])
c("alineación de la versión 32", qr._alineaciones(32), [6, 34, 60, 86, 112, 138])
c("alineación de la versión 40", qr._alineaciones(40),
  [6, 30, 58, 86, 114, 142, 170])

# El tamaño: 21 módulos la versión 1, y cuatro más por versión.
c("tamaño de la versión 1", qr.tamano(1), 21)
c("tamaño de la versión 40", qr.tamano(40), 177)


# ---------------------------------------------------------------------------
# 2. El decodificador
# ---------------------------------------------------------------------------

def _mapa_de_funciones(version: int):
    """Qué módulos son de función. Lo único prestado del codificador.

    Se puede prestar porque lo que dibuja está comprobado aparte, en el bloque
    de estructura: si un patrón estuviera en el sitio equivocado, aquello
    fallaría antes de que esto llegara a leer nada."""
    lienzo = qr._Lienzo(version)
    lienzo.dibujar_funciones("L")
    return lienzo.funcion


def _leer_formato(modulos) -> tuple[str, int]:
    """El nivel de corrección y la máscara, leídos de la copia de la esquina."""
    bits = 0
    posiciones = ([(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)]
                  + [(14 - i, 8) for i in range(9, 15)])
    for i, (x, y) in enumerate(posiciones):
        if modulos[y][x]:
            bits |= 1 << i
    bits ^= qr._MASCARA_FORMATO
    datos = bits >> 10
    nivel = next(n for n, v in qr.NIVELES.items() if v == datos >> 3)
    return nivel, datos & 0b111


def _flujo(modulos, funcion) -> bytes:
    """Los codewords, recorriendo el zigzag de dos columnas de derecha a
    izquierda, arriba y abajo alternando, saltando la columna 6."""
    lado = len(modulos)
    bits: list[int] = []
    derecha = lado - 1
    while derecha >= 1:
        if derecha == 6:
            derecha = 5
        for vertical in range(lado):
            for j in range(2):
                x = derecha - j
                hacia_arriba = (derecha + 1) & 2 == 0
                y = (lado - 1 - vertical) if hacia_arriba else vertical
                if not funcion[y][x]:
                    bits.append(1 if modulos[y][x] else 0)
        derecha -= 2
    # Los módulos que sobran al final no forman un codeword entero: se tiran.
    return bytes(int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits) // 8 * 8, 8))


def _desintercalar(flujo: bytes, version: int, nivel: str) -> bytes:
    """Deshace el troceado en bloques y se queda solo con los datos.

    Escrito del revés a partir de la descripción de la norma, no copiando el
    bucle del codificador: el hueco del codeword que les falta a los bloques
    cortos es la única irregularidad, y es exactamente donde se equivoca uno."""
    por_bloque = qr._CORRECCION_POR_BLOQUE[nivel][version]
    cuantos = qr._BLOQUES[nivel][version]
    total = qr._modulos_de_datos(version) // 8
    cortos = cuantos - total % cuantos
    largo_corto = total // cuantos
    largos = [largo_corto + (0 if j < cortos else 1) for j in range(cuantos)]

    bloques: list[list[int]] = [[] for _ in range(cuantos)]
    k = 0
    for i in range(largo_corto + 1):
        for j in range(cuantos):
            if i == largo_corto - por_bloque and j < cortos:
                continue                    # el hueco del bloque corto
            if i < largos[j]:
                bloques[j].append(flujo[k])
                k += 1

    datos = bytearray()
    for j, bloque in enumerate(bloques):
        datos += bytes(bloque[:largos[j] - por_bloque])
    return bytes(datos)


def decodificar(codigo: qr.Codigo) -> bytes:
    """El mensaje que lleva dentro un `Codigo`, leído del dibujo."""
    version = codigo.version
    nivel, mascara = _leer_formato(codigo.modulos)
    funcion = _mapa_de_funciones(version)
    formula = qr._MASCARAS[mascara]

    # Quitar la máscara es volver a aplicarla: es un XOR.
    lado = codigo.tamano
    modulos = [list(fila) for fila in codigo.modulos]
    for y in range(lado):
        for x in range(lado):
            if not funcion[y][x] and formula(x, y):
                modulos[y][x] = not modulos[y][x]

    datos = _desintercalar(_flujo(modulos, funcion), version, nivel)
    modo = datos[0] >> 4
    if modo != qr._MODO_BYTE:
        raise AssertionError(f"modo {modo:04b}, se esperaba byte")
    if version <= 9:
        largo = (datos[0] & 0x0F) << 4 | datos[1] >> 4
        cuerpo = bytes(((datos[i] & 0x0F) << 4) | (datos[i + 1] >> 4)
                       for i in range(1, 1 + largo))
    else:
        largo = ((datos[0] & 0x0F) << 12 | datos[1] << 4 | datos[2] >> 4)
        cuerpo = bytes(((datos[i] & 0x0F) << 4) | (datos[i + 1] >> 4)
                       for i in range(2, 2 + largo))
    return cuerpo


# ---------------------------------------------------------------------------
# 3. La estructura del dibujo
# ---------------------------------------------------------------------------

def revisar_estructura(codigo: qr.Codigo, etiqueta: str) -> None:
    modulos, lado = codigo.modulos, codigo.tamano
    c(f"{etiqueta}: el lado cuadra con la versión", lado, qr.tamano(codigo.version))
    c(f"{etiqueta}: la matriz es cuadrada",
      all(len(fila) == lado for fila in modulos), True)

    # Los tres patrones de búsqueda: anillo oscuro, anillo claro, centro oscuro.
    esquinas = ((0, 0), (lado - 7, 0), (0, lado - 7))
    bien = True
    for x0, y0 in esquinas:
        for dy in range(7):
            for dx in range(7):
                lejos = max(abs(dx - 3), abs(dy - 3))
                if modulos[y0 + dy][x0 + dx] != (lejos != 2):
                    bien = False
    c(f"{etiqueta}: los tres patrones de búsqueda están enteros", bien, True)

    # El separador blanco: la fila y la columna que rodean al de la esquina.
    c(f"{etiqueta}: el separador del patrón de arriba a la izquierda",
      any(modulos[7][x] for x in range(8)) or any(modulos[y][7] for y in range(8)),
      False)

    # Las líneas de temporización alternan empezando en oscuro.
    c(f"{etiqueta}: la temporización horizontal alterna",
      [modulos[6][x] for x in range(8, lado - 8)],
      [x % 2 == 0 for x in range(8, lado - 8)])
    c(f"{etiqueta}: la temporización vertical alterna",
      [modulos[y][6] for y in range(8, lado - 8)],
      [y % 2 == 0 for y in range(8, lado - 8)])

    c(f"{etiqueta}: el módulo oscuro está puesto", modulos[lado - 8][8], True)
    c(f"{etiqueta}: la máscara elegida es una de las ocho",
      0 <= codigo.mascara <= 7, True)


# ---------------------------------------------------------------------------
# La vuelta entera, en varios tamaños
# ---------------------------------------------------------------------------

MENSAJES = [
    ("una letra", "a"),
    ("acentos y eñes", "Canción de otoño en primavera — ¡qué más da!"),
    ("el salto a contador de 16 bits", "x" * 400),
    ("una carga del tamaño del emparejamiento", "K" * 900),
    ("bytes crudos", bytes(range(256)) * 3),
]

for etiqueta, mensaje in MENSAJES:
    for nivel in "LMQH":
        codigo = qr.codificar(mensaje, nivel)
        esperado = mensaje.encode("utf-8") if isinstance(mensaje, str) else mensaje
        c(f"{etiqueta} ({nivel}): vuelve entero", decodificar(codigo), esperado)
        c(f"{etiqueta} ({nivel}): el nivel leído es el pedido",
          _leer_formato(codigo.modulos)[0], nivel)
    revisar_estructura(qr.codificar(mensaje), etiqueta)

# Una versión de cada tramo, forzada, para tocar los tres tamaños de patrón de
# alineación y los dos del contador de caracteres. La 7 es la primera que lleva
# información de versión, y la 40 la mayor que existe.
for version in (1, 6, 7, 14, 27, 40):
    contenido = b"z" * min(200, qr.capacidad(version, "L"))
    codigo = qr.codificar(contenido, "L", version=version)
    c(f"versión {version} forzada: vuelve entera", decodificar(codigo), contenido)
    revisar_estructura(codigo, f"versión {version}")

# El límite: lo que no cabe se dice, no se recorta.
try:
    qr.codificar(b"x" * (qr.capacidad(40, "H") + 1), "H")
    c("lo que no cabe en ninguna versión se rechaza", "no lanzó", "QRError")
except qr.QRError as e:
    c("lo que no cabe en ninguna versión se rechaza", "QRError" in type(e).__name__, True)

try:
    qr.codificar("hola", "Z")
    c("un nivel inventado se rechaza", "no lanzó", "QRError")
except qr.QRError:
    c("un nivel inventado se rechaza", True, True)

try:
    qr.codificar(b"x" * 100, "H", version=1)
    c("una versión forzada demasiado pequeña se rechaza", "no lanzó", "QRError")
except qr.QRError:
    c("una versión forzada demasiado pequeña se rechaza", True, True)

# La versión se elige, y es la más pequeña que sirve.
c("17 bytes caben en la versión 1 con corrección L",
  qr.codificar(b"x" * 17, "L").version, 1)
c("18 bytes ya piden la versión 2", qr.codificar(b"x" * 18, "L").version, 2)


# ---------------------------------------------------------------------------
# El viaje de verdad: dispositivo -> QR -> perfil
# ---------------------------------------------------------------------------

CLAVE = (b"-----BEGIN OPENSSH PRIVATE KEY-----\n"
         + b"b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gt\n" * 5
         + b"-----END OPENSSH PRIVATE KEY-----\n")
KNOWN = "nas.example.org ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKfalsa\n"

disp = tmpdir("prdrive-qr-")
app = disp / ".prdrive"
(app / "keys").mkdir(parents=True)
(app / "keys" / "id_ed25519").write_bytes(CLAVE)
(app / "keys" / "known_hosts").write_text(KNOWN, encoding="utf-8")
(app / "rclone.conf").write_text(
    "[nas]\n"
    "type = sftp\n"
    "host = nas.example.org\n"
    "port = 22\n"
    "user = pere\n"
    "disable_hashcheck = true\n"
    "shell_type = none\n"
    "key_file = keys/id_ed25519\n"
    "known_hosts_file = keys/known_hosts\n",
    encoding="utf-8")

RAW = {"defaults": {"remote": "nas", "catalog_path": "/prdrive-catalog/pairs.toml"},
       "pair": [{"name": "documentos", "local": "Documentos",
                 "remote_path": "/datos/documentos"}]}

carga_texto = pairing.construir(RAW, app_dir=app)
c("la carga es una sola pieza de texto", isinstance(carga_texto, str), True)
c("la clave privada va dentro", "private_key_b64" in carga_texto, True)
c("la ruta de la clave NO va dentro", "key_file" in carga_texto, False)
c("la ruta de los known_hosts NO va dentro", "known_hosts_file" in carga_texto, False)

# El tamaño es el que decide si esto cabe en un QR legible: se deja dicho.
codigo = qr.codificar(carga_texto)
print(f"  (carga de {len(carga_texto.encode('utf-8'))} bytes -> versión "
      f"{codigo.version}, {codigo.tamano}x{codigo.tamano} módulos)")
c("el código de emparejamiento no pasa de la versión 40",
  codigo.version <= 40, True)

leido = carga_texto.encode("utf-8")
c("la carga vuelve entera del QR", decodificar(codigo), leido)

carga = pairing.leer(decodificar(codigo).decode("utf-8"))
c("la clave sale igual que entró", carga.private_key, CLAVE)
c("los known_hosts salen igual", carga.known_hosts, KNOWN)
c("el nombre del remote viaja", carga.remote_name, "nas")

# Y lo que de verdad importa: que `install/profile.py` lo lea sin cambios.
perfil = profile.loads(carga.texto, private_key=carga.private_key,
                       known_hosts=carga.known_hosts, origen="del QR")
esperado = profile.from_rclone_conf(app / "rclone.conf", "nas")

c("el perfil reconstruido se llama igual", perfil.remote_name, esperado.remote_name)
c("y trae las mismas opciones", dict(perfil.options), dict(esperado.options))
c("y la misma clave", perfil.private_key, esperado.private_key)
c("y el mismo nombre de clave", perfil.key_name, esperado.key_name)
c("y los mismos known_hosts", perfil.known_hosts, esperado.known_hosts)
c("el perfil reconstruido está configurado", perfil.configured, True)
c("y sabe dónde está el catálogo", perfil.endpoint_catalog,
  "nas:/prdrive-catalog/pairs.toml")

# Un dispositivo sin clave —un backend que se autentica con contraseña— también
# se puede emparejar: lo que no puede es inventarse una.
(app / "rclone.conf").write_text(
    "[nas]\ntype = webdav\nurl = https://nas.example.org/dav\nuser = pere\n",
    encoding="utf-8")
sin_clave = pairing.leer(pairing.construir(RAW, app_dir=app))
c("sin clave no se inventa ninguna", sin_clave.private_key, None)
c("y el perfil sigue valiendo",
  profile.loads(sin_clave.texto).configured, True)

# Lo que no es nuestro se rechaza por la marca, no por el error de conectar.
for etiqueta, texto in (("un TOML de otro programa", 'nombre = "otra cosa"\n'),
                        ("algo que ni es TOML", "no soy toml <<<")):
    try:
        pairing.leer(texto)
        c(f"{etiqueta} se rechaza", "no lanzó", "PairingError")
    except pairing.PairingError:
        c(f"{etiqueta} se rechaza", True, True)

# Un remote que el rclone.conf no define: el mensaje dice cuál falta.
(app / "rclone.conf").write_text("[otro]\ntype = sftp\n", encoding="utf-8")
try:
    pairing.construir(RAW, app_dir=app)
    c("un remote que no está se rechaza", "no lanzó", "PairingError")
except pairing.PairingError as e:
    c("un remote que no está se rechaza", "'nas'" in str(e), True)

# Un checkout sin provisionar: no hay rclone.conf y eso no es una excepción
# cualquiera, es la que la ventana sabe enseñar sin romperse.
vacio = tmpdir("prdrive-qr-vacio-")
try:
    pairing.construir(RAW, app_dir=vacio)
    c("sin rclone.conf se dice, no se revienta", "no lanzó", "PairingError")
except pairing.PairingError:
    c("sin rclone.conf se dice, no se revienta", True, True)

# Y todo lo que lanza `construir()` lo caza la ventana, que solo espera
# `ConfigError`: si algún día saliera de ahí un OSError pelado, la ventana de
# emparejar se llevaría por delante a la principal.
c("PairingError es un ConfigError", issubclass(pairing.PairingError, ConfigError), True)

# Y el lector de rclone.conf es uno solo, no dos.
c("install/profile.py usa el lector de common/pairing.py",
  profile.parse_rclone_conf is pairing.parse_rclone_conf, True)

sys.exit(c.report())
