#!/usr/bin/env python3
"""
qr.py — Un codificador de códigos QR, escrito aquí por la misma razón que
`ui/icons.py` dibuja sus iconos: el proyecto no admite dependencias.

Lo que hace falta es enseñar en pantalla la conexión con el remoto para que un
móvil la lea, y eso son unos 800 bytes: demasiados para un código pequeño y
muy pocos para justificar traerse una librería. Así que se codifica.

**Solo modo byte.** El QR tiene cuatro modos (numérico, alfanumérico, byte,
kanji) y los tres que no son byte existen para apretar textos de un alfabeto
concreto. Lo que aquí se codifica es UTF-8 con base64 dentro, o sea el caso
peor de todos ellos: elegir modo por tramos no ahorraría un solo módulo y sí
multiplicaría por tres el código que hay que mantener.

Todo lo demás sí está entero: las 40 versiones, los cuatro niveles de
corrección, el troceado en bloques con su Reed-Solomon intercalado, las ocho
máscaras y la puntuación que elige la mejor. Recortar ahí no es simplificar:
un lector que no es nuestro es el que decide si el código vale, y todo esto es
justo lo que mira.

Las referencias son a la norma **ISO/IEC 18004**, y se citan igual que
`common/bisync.py` cita el fuente de rclone: cuando una constante o un número
mágico sale de una tabla de la norma, se dice de cuál. Las tablas que no se
pueden deducir —cuántos codewords de corrección lleva cada versión y en cuántos
bloques se parte— están abajo, copiadas literalmente.

    >>> codigo = codificar("hola")
    >>> codigo.version, codigo.tamano
    (1, 21)
    >>> codigo.modulos[0][0]        # la esquina del patrón de búsqueda
    True

`codificar()` no dibuja nada: devuelve módulos, que es lo que entiende
`icons.matriz()`. Aquí no se importa Tk ni se sabe de colores, y por eso se
puede probar sin pantalla.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Los niveles de corrección
#
# El número NO es el orden de menos a más corrección: es lo que va escrito en la
# información de formato del propio código (ISO/IEC 18004, tabla 12), y ahí L y
# M están cambiados respecto al orden intuitivo. Guardarlo ya en ese orden
# evita una traducción más adelante, que es donde se cuela el error.
# ---------------------------------------------------------------------------

NIVELES: dict[str, int] = {"L": 1, "M": 0, "Q": 3, "H": 2}

# El de por defecto. M recupera un 15 % del código, que en una pantalla —sin
# arrugas, sin reflejos, sin impresora— sobra, y a cambio deja el dibujo bastante
# más pequeño que Q. L sería aún menor, pero el emparejamiento se hace una vez y
# con la cámara a pulso: no es el sitio donde apurar.
NIVEL_POR_DEFECTO = "M"


# ---------------------------------------------------------------------------
# Las dos tablas que no se deducen (ISO/IEC 18004, tabla 9)
#
# Todo lo demás del formato se calcula: cuántos módulos tiene una versión, dónde
# van los patrones de alineación, la información de formato y de versión. Esto
# no: cuántos codewords de corrección lleva cada bloque y en cuántos bloques se
# parte el mensaje son decisiones de la norma, y van copiadas.
#
# Índice 0 sin usar, para poder indexar por versión directamente y no restar uno
# en cada sitio.
# ---------------------------------------------------------------------------

_CORRECCION_POR_BLOQUE: dict[str, tuple[int, ...]] = {
    "L": (0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28,
          30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30,
          30, 30, 30, 30, 30, 30),
    "M": (0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28,
          26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28,
          28, 28, 28, 28, 28, 28),
    "Q": (0, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28,
          28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30,
          30, 30, 30, 30, 30, 30),
    "H": (0, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28,
          28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30,
          30, 30, 30, 30, 30, 30),
}

_BLOQUES: dict[str, tuple[int, ...]] = {
    "L": (0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9,
          9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    "M": (0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
          17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43,
          45, 47, 49),
    "Q": (0, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21,
          20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56,
          59, 62, 65, 68),
    "H": (0, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25,
          25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66,
          70, 74, 77, 81),
}

MIN_VERSION, MAX_VERSION = 1, 40

# El indicador de modo byte, 4 bits (ISO/IEC 18004, tabla 2).
_MODO_BYTE = 0b0100

# Los polinomios generadores de los tres códigos que usa el QR, y que son la
# razón de que aquí no haya ninguna constante «mágica» suelta:
#   * 0x11D  el campo de Galois GF(2^8) de Reed-Solomon (x^8+x^4+x^3+x^2+1)
#   * 0x537  el BCH (15,5) de la información de formato
#   * 0x1F25 el BCH (18,6) de la información de versión
_GF = 0x11D
_BCH_FORMATO = 0x537
_BCH_VERSION = 0x1F25

# La máscara que se le aplica a la información de formato para que un código con
# los 15 bits a cero no exista (ISO/IEC 18004, 8.9).
_MASCARA_FORMATO = 0b101010000010010

# Los pesos de las cuatro reglas de penalización (ISO/IEC 18004, tabla 11).
_N1, _N2, _N3, _N4 = 3, 3, 40, 10


class QRError(ValueError):
    """Lo que se quiere codificar no cabe, o el nivel no existe.

    Hereda de `ValueError` y no de `model.ConfigError` a propósito: esto no es
    un problema de configuración del usuario sino de quien llama, y la ventana
    que lo enseña ya sabe traducirlo a una frase."""


@dataclass(frozen=True)
class Codigo:
    """Un QR ya resuelto: qué versión salió, con qué máscara, y los módulos.

    `modulos[fila][columna]`, True = oscuro. **Sin zona de silencio**: el borde
    blanco de cuatro módulos que exige la norma es cosa de quien lo pinta, que
    es el único que sabe sobre qué fondo cae. `icons.matriz()` lo pone."""
    version: int
    nivel: str
    mascara: int
    modulos: tuple[tuple[bool, ...], ...]

    @property
    def tamano(self) -> int:
        return len(self.modulos)


# ---------------------------------------------------------------------------
# Aritmética de Reed-Solomon sobre GF(2^8)
# ---------------------------------------------------------------------------

def _multiplicar(x: int, y: int) -> int:
    """El producto de dos elementos del campo, sin tablas.

    Multiplicación rusa reduciendo por el polinomio del campo en cada paso. Se
    hace así y no con tablas de logaritmos porque son 256 entradas que habría
    que construir al importar el módulo para ahorrar unos microsegundos en algo
    que se ejecuta cuando alguien abre una ventana."""
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * _GF)
        z ^= ((y >> i) & 1) * x
    return z


def _divisor(grado: int) -> list[int]:
    """El polinomio generador de grado `grado`: (x-r^0)(x-r^1)…(x-r^(g-1)).

    Se devuelve sin el coeficiente principal, que siempre es 1, porque así es
    como lo quiere la división de abajo."""
    if not 1 <= grado <= 255:
        raise QRError(f"grado {grado} fuera de rango para Reed-Solomon")
    resultado = [0] * (grado - 1) + [1]
    raiz = 1
    for _ in range(grado):
        for j in range(grado):
            resultado[j] = _multiplicar(resultado[j], raiz)
            if j + 1 < grado:
                resultado[j] ^= resultado[j + 1]
        raiz = _multiplicar(raiz, 0x02)
    return resultado


def _resto(datos: bytes | list[int], divisor: list[int]) -> list[int]:
    """Los codewords de corrección de un bloque: el resto de la división."""
    resultado = [0] * len(divisor)
    for b in datos:
        factor = b ^ resultado.pop(0)
        resultado.append(0)
        for i, coef in enumerate(divisor):
            resultado[i] ^= _multiplicar(coef, factor)
    return resultado


# ---------------------------------------------------------------------------
# Geometría de una versión
# ---------------------------------------------------------------------------

def tamano(version: int) -> int:
    """El lado en módulos. La versión 1 mide 21 y cada una suma 4."""
    return version * 4 + 17


def _modulos_de_datos(version: int) -> int:
    """Cuántos módulos quedan para datos y corrección en esta versión.

    Es el total menos lo que ocupan los patrones de función, y se calcula en vez
    de tabularse porque la norma da la fórmula (ISO/IEC 18004, anexo D): del
    cuadrado se descuentan los tres patrones de búsqueda con su separador y sus
    franjas de formato (64 módulos), las dos líneas de temporización, cada
    patrón de alineación (25 módulos, menos los solapes con la temporización) y,
    desde la versión 7, los dos bloques de información de versión."""
    resultado = (16 * version + 128) * version + 64
    if version >= 2:
        alineaciones = version // 7 + 2
        resultado -= (25 * alineaciones - 10) * alineaciones - 55
        if version >= 7:
            resultado -= 36
    return resultado


def _codewords_de_datos(version: int, nivel: str) -> int:
    """Cuántos bytes de mensaje caben de verdad, ya descontada la corrección."""
    return (_modulos_de_datos(version) // 8
            - _CORRECCION_POR_BLOQUE[nivel][version] * _BLOQUES[nivel][version])


def capacidad(version: int, nivel: str = NIVEL_POR_DEFECTO) -> int:
    """Cuántos bytes de contenido admite esta versión y este nivel.

    Es `_codewords_de_datos` menos la cabecera: 4 bits de modo más el contador
    de caracteres, que mide 8 bits hasta la versión 9 y 16 de la 10 en adelante
    (ISO/IEC 18004, tabla 3)."""
    _comprobar(version, nivel)
    bits_cabecera = 4 + (8 if version <= 9 else 16)
    return _codewords_de_datos(version, nivel) - (bits_cabecera + 7) // 8


def _comprobar(version: int, nivel: str) -> None:
    if nivel not in NIVELES:
        raise QRError(f"nivel de corrección desconocido: {nivel!r}; "
                      f"los que hay son {', '.join(NIVELES)}.")
    if not MIN_VERSION <= version <= MAX_VERSION:
        raise QRError(f"la versión {version} no existe: van de {MIN_VERSION} "
                      f"a {MAX_VERSION}.")


def _alineaciones(version: int) -> list[int]:
    """Los centros de los patrones de alineación, en fila y en columna.

    Se calculan (ISO/IEC 18004, anexo E da la tabla equivalente): el primero
    siempre en 6, el último a 7 del borde, y el resto repartidos con un paso
    par. La versión 32 es la excepción que la propia norma tabula a mano."""
    if version == 1:
        return []
    cuantos = version // 7 + 2
    paso = 26 if version == 32 else (version * 4 + cuantos * 2 + 1) // (cuantos * 2 - 2) * 2
    centros = [tamano(version) - 7 - i * paso for i in range(cuantos - 1)] + [6]
    centros.reverse()
    return centros


# ---------------------------------------------------------------------------
# El mensaje: de bytes a codewords con su corrección intercalada
# ---------------------------------------------------------------------------

def _elegir_version(cuantos: int, nivel: str) -> int:
    """La versión más pequeña en la que caben `cuantos` bytes."""
    for version in range(MIN_VERSION, MAX_VERSION + 1):
        if capacidad(version, nivel) >= cuantos:
            return version
    mayor = capacidad(MAX_VERSION, nivel)
    raise QRError(
        f"{cuantos} bytes no caben en ningún código QR con corrección {nivel}: "
        f"el mayor admite {mayor}.")


def _bits(datos: bytes, version: int, nivel: str) -> list[int]:
    """La secuencia de bits del mensaje, ya rellenada hasta llenar la versión.

    El relleno tiene tres tramos y los tres son de la norma (ISO/IEC 18004,
    8.4.9): hasta cuatro ceros de terminador, los que hagan falta para cerrar el
    byte, y luego 0xEC y 0x11 alternándose hasta el final. Los dos bytes de
    relleno no son arbitrarios: están elegidos para no formar patrones que se
    parezcan a los de búsqueda."""
    contador = 8 if version <= 9 else 16
    bits: list[int] = []

    def meter(valor: int, cuantos: int) -> None:
        bits.extend((valor >> i) & 1 for i in reversed(range(cuantos)))

    meter(_MODO_BYTE, 4)
    meter(len(datos), contador)
    for b in datos:
        meter(b, 8)

    capacidad_bits = _codewords_de_datos(version, nivel) * 8
    bits.extend([0] * min(4, capacidad_bits - len(bits)))       # terminador
    bits.extend([0] * (-len(bits) % 8))                         # cierra el byte
    for i in range((capacidad_bits - len(bits)) // 8):
        meter(0xEC if i % 2 == 0 else 0x11, 8)
    return bits


def _bloques(datos: bytes, version: int, nivel: str) -> bytes:
    """Los codewords de datos y de corrección, troceados e intercalados.

    El QR no guarda «primero todos los datos y luego toda la corrección»: parte
    el mensaje en bloques, calcula el Reed-Solomon de cada uno y luego los lee
    **en columnas** —el primer byte de cada bloque, el segundo de cada bloque…—
    para que un borrón que se coma una zona del dibujo reparta el daño entre
    todos los bloques en vez de destrozar uno entero (ISO/IEC 18004, 8.6).

    Los bloques no miden todos igual: los `cortos` primeros llevan un codeword
    menos, y el hueco que dejan al intercalar hay que saltarlo."""
    por_bloque = _CORRECCION_POR_BLOQUE[nivel][version]
    cuantos = _BLOQUES[nivel][version]
    total = _modulos_de_datos(version) // 8
    cortos = cuantos - total % cuantos
    largo_corto = total // cuantos

    divisor = _divisor(por_bloque)
    trozos: list[list[int]] = []
    k = 0
    for i in range(cuantos):
        largo = largo_corto - por_bloque + (0 if i < cortos else 1)
        datos_bloque = datos[k:k + largo]
        k += largo
        # A los bloques cortos se les mete un byte de mentira en el hueco que
        # les falta, para que TODOS midan lo mismo y el intercalado de abajo sea
        # un recorrido rectangular. Ese byte no se escribe nunca: se salta al
        # intercalar, y va después de los datos y antes de la corrección para
        # caer justo en el índice que se salta.
        relleno = [0] if i < cortos else []
        trozos.append(list(datos_bloque) + relleno + _resto(datos_bloque, divisor))

    salida = bytearray()
    for i in range(largo_corto + 1):
        for j, trozo in enumerate(trozos):
            # El codeword que falta en los bloques cortos: su hueco se salta,
            # no se rellena. Es la única irregularidad del intercalado.
            if i != largo_corto - por_bloque or j >= cortos:
                salida.append(trozo[i])
    return bytes(salida)


# ---------------------------------------------------------------------------
# El dibujo
# ---------------------------------------------------------------------------

class _Lienzo:
    """La rejilla mientras se construye: módulos y qué casillas son de función.

    Las dos matrices van juntas porque casi todo lo que se hace aquí —colocar
    los datos, aplicar la máscara, puntuarla— necesita saber si una casilla es
    de función, y esa pregunta se hace una vez por módulo y por máscara."""

    def __init__(self, version: int) -> None:
        self.version = version
        self.lado = tamano(version)
        self.modulos = [[False] * self.lado for _ in range(self.lado)]
        self.funcion = [[False] * self.lado for _ in range(self.lado)]

    def poner(self, x: int, y: int, oscuro: bool) -> None:
        self.modulos[y][x] = oscuro
        self.funcion[y][x] = True

    # --- patrones de función ------------------------------------------------

    def dibujar_funciones(self, nivel: str) -> None:
        """Todo lo que no depende del mensaje: búsqueda, temporización,
        alineación y el hueco reservado de formato y versión."""
        for i in range(self.lado):
            self.poner(6, i, i % 2 == 0)
            self.poner(i, 6, i % 2 == 0)

        for cx, cy in ((3, 3), (self.lado - 4, 3), (3, self.lado - 4)):
            self._busqueda(cx, cy)

        centros = _alineaciones(self.version)
        ultimo = len(centros) - 1
        for i, cy in enumerate(centros):
            for j, cx in enumerate(centros):
                # Las tres esquinas donde ya hay un patrón de búsqueda.
                if (i, j) not in ((0, 0), (0, ultimo), (ultimo, 0)):
                    self._alineacion(cx, cy)

        # El formato se dibuja ya, con una máscara cualquiera: hay que reservar
        # su sitio antes de colocar los datos. Se reescribe al final, cuando se
        # sepa qué máscara ganó.
        self.dibujar_formato(nivel, 0)
        self._version_info()

    def _busqueda(self, cx: int, cy: int) -> None:
        """El ojo de buey de 7x7 y su separador blanco alrededor."""
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < self.lado and 0 <= y < self.lado:
                    lejos = max(abs(dx), abs(dy))
                    self.poner(x, y, lejos != 2 and lejos != 4)

    def _alineacion(self, cx: int, cy: int) -> None:
        """El cuadrado de 5x5 con su centro: anillo blanco a distancia 1."""
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self.poner(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    def dibujar_formato(self, nivel: str, mascara: int) -> None:
        """Los 15 bits de formato, dos veces, y el módulo oscuro.

        Van duplicados —junto al patrón de búsqueda de arriba a la izquierda y
        repartidos entre los otros dos— para que un código al que le falte una
        esquina siga diciendo con qué máscara está hecho. El bit menos
        significativo va primero (ISO/IEC 18004, 8.9)."""
        datos = NIVELES[nivel] << 3 | mascara
        resto = datos
        for _ in range(10):
            resto = (resto << 1) ^ ((resto >> 9) * _BCH_FORMATO)
        bits = (datos << 10 | resto) ^ _MASCARA_FORMATO

        def bit(i: int) -> bool:
            return (bits >> i) & 1 != 0

        # La copia de arriba a la izquierda, saltando la línea de temporización.
        for i in range(0, 6):
            self.poner(8, i, bit(i))
        self.poner(8, 7, bit(6))
        self.poner(8, 8, bit(7))
        self.poner(7, 8, bit(8))
        for i in range(9, 15):
            self.poner(14 - i, 8, bit(i))

        # La segunda copia, partida entre las otras dos esquinas.
        for i in range(0, 8):
            self.poner(self.lado - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.poner(8, self.lado - 15 + i, bit(i))

        # El módulo oscuro: siempre negro, en todas las versiones.
        self.poner(8, self.lado - 8, True)

    def _version_info(self) -> None:
        """Los 18 bits de versión, en dos bloques de 3x6. Solo desde la 7.

        Antes de la versión 7 no existen: el lector deduce la versión del
        tamaño, que hasta ahí es suficiente."""
        if self.version < 7:
            return
        resto = self.version
        for _ in range(12):
            resto = (resto << 1) ^ ((resto >> 11) * _BCH_VERSION)
        bits = self.version << 12 | resto

        for i in range(18):
            oscuro = (bits >> i) & 1 != 0
            a, b = self.lado - 11 + i % 3, i // 3
            self.poner(a, b, oscuro)
            self.poner(b, a, oscuro)

    # --- los datos ----------------------------------------------------------

    def dibujar_datos(self, datos: bytes) -> None:
        """Los codewords, en zigzag de dos columnas de derecha a izquierda.

        El recorrido sube y baja alternando por pares de columnas, saltándose la
        columna 6 —la de temporización, que no lleva datos— y todo lo que sea de
        función. Si sobran módulos al final se quedan en claro: la norma los
        llama «restantes» y el lector los ignora."""
        i = 0
        derecha = self.lado - 1
        while derecha >= 1:
            if derecha == 6:
                derecha = 5
            for vertical in range(self.lado):
                for j in range(2):
                    x = derecha - j
                    hacia_arriba = (derecha + 1) & 2 == 0
                    y = (self.lado - 1 - vertical) if hacia_arriba else vertical
                    if not self.funcion[y][x] and i < len(datos) * 8:
                        self.modulos[y][x] = (datos[i >> 3] >> (7 - (i & 7))) & 1 != 0
                        i += 1
            derecha -= 2

    def aplicar(self, mascara: int) -> None:
        """Aplica (o quita: es un XOR) una de las ocho máscaras.

        Enmascarar no protege nada, sirve para que el dibujo no salga con
        manchas grandes ni con algo que se parezca a un patrón de búsqueda, que
        es lo que despista al lector (ISO/IEC 18004, tabla 10)."""
        formula = _MASCARAS[mascara]
        for y in range(self.lado):
            for x in range(self.lado):
                if not self.funcion[y][x] and formula(x, y):
                    self.modulos[y][x] = not self.modulos[y][x]

    # --- la puntuación ------------------------------------------------------

    def penalizacion(self) -> int:
        """Lo malo que es este dibujo para un lector. Menos es mejor.

        Son las cuatro reglas de la norma (ISO/IEC 18004, 8.8.2): rachas largas
        del mismo color, bloques de 2x2, cosas que se parecen a un patrón de
        búsqueda, y un reparto de claro y oscuro que se aleje del 50 %."""
        total = 0
        lado = self.lado
        modulos = self.modulos

        for y in range(lado):
            total += self._linea([modulos[y][x] for x in range(lado)])
        for x in range(lado):
            total += self._linea([modulos[y][x] for y in range(lado)])

        for y in range(lado - 1):
            for x in range(lado - 1):
                if (modulos[y][x] == modulos[y][x + 1]
                        == modulos[y + 1][x] == modulos[y + 1][x + 1]):
                    total += _N2

        oscuros = sum(fila.count(True) for fila in modulos)
        celdas = lado * lado
        # Cuánto se desvía del 50 %, en pasos del 5 %.
        k = (abs(oscuros * 20 - celdas * 10) + celdas - 1) // celdas - 1
        return total + k * _N4

    def _linea(self, celdas: list[bool]) -> int:
        """Las reglas 1 y 3 sobre una fila o una columna.

        La 3 no busca el patrón 1:1:3:1:1 a pelo sino que lleva un historial de
        las últimas siete rachas, porque lo que penaliza la norma es ese patrón
        **con cuatro módulos claros a un lado**, y eso incluye el borde del
        código: por eso al empezar y al terminar la línea se le suma un tramo
        claro del tamaño del lado."""
        total = 0
        historial = [0] * 7
        color = False
        racha = 0

        for celda in celdas:
            if celda == color:
                racha += 1
                if racha == 5:
                    total += _N1
                elif racha > 5:
                    total += 1
            else:
                self._apuntar(racha, historial)
                if not color:
                    total += self._buscar_falsos(historial) * _N3
                color = celda
                racha = 1

        if color:                       # una racha oscura al final no cuenta
            self._apuntar(racha, historial)
            racha = 0
        racha += self.lado              # el blanco de fuera del código
        self._apuntar(racha, historial)
        return total + self._buscar_falsos(historial) * _N3

    def _apuntar(self, racha: int, historial: list[int]) -> None:
        if historial[0] == 0:
            racha += self.lado          # el blanco de antes de empezar
        historial.pop()
        historial.insert(0, racha)

    @staticmethod
    def _buscar_falsos(historial: list[int]) -> int:
        """Cuántos patrones 1:1:3:1:1 con su margen hay en el historial."""
        n = historial[1]
        nucleo = (n > 0 and historial[2] == historial[4] == historial[5] == n
                  and historial[3] == n * 3)
        return ((1 if nucleo and historial[0] >= n * 4 and historial[6] >= n else 0)
                + (1 if nucleo and historial[6] >= n * 4 and historial[0] >= n else 0))


# Las ocho máscaras (ISO/IEC 18004, tabla 10). x es la columna, y la fila.
_MASCARAS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (y // 2 + x // 3) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


# ---------------------------------------------------------------------------
# La cara pública
# ---------------------------------------------------------------------------

def codificar(contenido: bytes | str, nivel: str = NIVEL_POR_DEFECTO,
              version: int | None = None) -> Codigo:
    """El código QR de `contenido`, en la versión más pequeña donde quepa.

    El texto se codifica en UTF-8, que es lo que espera cualquier lector de hoy
    ante el modo byte. `version` fuerza un tamaño concreto —lo usan los tests
    para medir una versión determinada—; lo normal es dejar que lo elija.

    Lanza `QRError` si el nivel no existe, si la versión forzada no vale o si el
    contenido no cabe ni en la versión 40."""
    datos = contenido.encode("utf-8") if isinstance(contenido, str) else bytes(contenido)
    if nivel not in NIVELES:
        raise QRError(f"nivel de corrección desconocido: {nivel!r}; "
                      f"los que hay son {', '.join(NIVELES)}.")
    if version is None:
        version = _elegir_version(len(datos), nivel)
    else:
        _comprobar(version, nivel)
        if len(datos) > capacidad(version, nivel):
            raise QRError(
                f"{len(datos)} bytes no caben en la versión {version} con "
                f"corrección {nivel}: admite {capacidad(version, nivel)}.")

    lienzo = _Lienzo(version)
    lienzo.dibujar_funciones(nivel)
    lienzo.dibujar_datos(_bloques(_empaquetar(_bits(datos, version, nivel)),
                                  version, nivel))

    # Se prueban las ocho y gana la de menos penalización. Probarlas todas es lo
    # que manda la norma y cuesta ocho recorridos de una rejilla que como mucho
    # mide 177x177: nada al lado de abrir la ventana que lo va a enseñar.
    mejor, mejor_puntos = 0, None
    for mascara in range(8):
        lienzo.aplicar(mascara)
        lienzo.dibujar_formato(nivel, mascara)
        puntos = lienzo.penalizacion()
        if mejor_puntos is None or puntos < mejor_puntos:
            mejor, mejor_puntos = mascara, puntos
        lienzo.aplicar(mascara)         # deshacer: la máscara es un XOR
    lienzo.aplicar(mejor)
    lienzo.dibujar_formato(nivel, mejor)

    return Codigo(version=version, nivel=nivel, mascara=mejor,
                  modulos=tuple(tuple(fila) for fila in lienzo.modulos))


def _empaquetar(bits: list[int]) -> bytes:
    """Los bits en grupos de ocho. La cuenta ya viene cuadrada de `_bits()`."""
    return bytes(int("".join(str(b) for b in bits[i:i + 8]), 2)
                 for i in range(0, len(bits), 8))
