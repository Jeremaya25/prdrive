#!/usr/bin/env python3
"""Lo que `icons` pinta sin Tk (los `.ico`, la bandeja, la marca) no cambia ni un byte.

Los `.ico` de la unidad y del instalador, los iconos de la bandeja y los PNG de
dbusmenu no pasan por Tk: los pinta `icons` en Python puro, y lo que se haga con
el pintor de Tk (SVG, cachés, `_png` memoizado) no puede cambiarlos. Aquí se
fijan los SHA-256 de 25 salidas:

- **Veintitrés no llevan zlib** (DIB, píxeles de menú, pixmaps de la bandeja):
  se fijan enteros.
- **Dos llevan PNG** (`ico()` con sus 128 y 256 px, y `png_marca(32)`) y su flujo
  comprimido lo decide la versión de zlib: el Python oficial de Windows 3.14
  trae zlib-ng, que a igual nivel escribe otro flujo (con el paquete
  `zlib-ng`, `ico()` sale 7 bytes más corto). Esas dos se fijan por su contenido descomprimido, que es lo que
  `_png` decide, y además `_png` se compara con una copia sencilla (abajo)
  corrida con el MISMO zlib: así vale en cualquier sistema y sigue vigilando el
  nivel de compresión.

Los números salen del rasterizador (`_capas_rgba`), que usa `math.sin/cos/atan2`
(del libm de cada sistema) y `math.hypot` (el de CPython desde 3.10, igual en
3.11–3.14). Las salidas aguantan un ulp de error en `sin/cos/atan2`, pero cuatro
(`pixeles_menu(pausa…)` y las `ico_bandeja` de sincronizando, aviso, pausa y
bloqueado, con trazos rectos) tienen píxeles con alfa·255 = n + 0,5 exacto, y de
qué lado redondea lo decide el último bit de `hypot`. Si otra arquitectura las
cambiara, es el rasterizador y no `_png`.

No usa Tk: corre en cualquier equipo.
"""

from __future__ import annotations

import hashlib
import struct
import sys
import time
import zlib

from _harness import Checks

from ui import icons

c = Checks("iconos: lo que no pasa por Tk sale byte a byte igual")

FIRMA_PNG = b"\x89PNG\r\n\x1a\n"


def sha(datos: bytes) -> str:
    """Devuelve el SHA-256 de `datos` en hexadecimal."""
    return hashlib.sha256(datos).hexdigest()


def png_descomprimido(datos: bytes) -> bytes:
    """Devuelve un PNG como su IHDR y sus píxeles sin comprimir: lo que no depende de zlib."""
    assert datos.startswith(FIRMA_PNG)
    pos, ihdr, idat = 8, b"", b""
    while pos < len(datos):
        largo, = struct.unpack(">I", datos[pos:pos + 4])
        tipo, cuerpo = datos[pos + 4:pos + 8], datos[pos + 8:pos + 8 + largo]
        if tipo == b"IHDR":
            ihdr = cuerpo
        elif tipo == b"IDAT":
            idat += cuerpo
        pos += 12 + largo
    return ihdr + zlib.decompress(idat)


def canonico(datos: bytes) -> bytes:
    """Devuelve la salida con sus PNG descomprimidos y sin las longitudes que dependen de zlib.

    Para un PNG suelto es su IHDR y sus píxeles. Para un `.ico`, cada entrada
    (tamaño, planos, bits) seguida de su imagen: un DIB tal cual y un PNG
    descomprimido. La longitud y el desplazamiento de las entradas se dejan
    fuera: cambian con el flujo comprimido.
    """
    if datos.startswith(FIRMA_PNG):
        return png_descomprimido(datos)
    cuantas, = struct.unpack_from("<H", datos, 4)
    salida = bytearray(datos[:6])
    for i in range(cuantas):
        ancho, alto, _c, _r, planos, bits, largo, desde = struct.unpack_from(
            "<BBBBHHII", datos, 6 + 16 * i)
        img = datos[desde:desde + largo]
        salida += struct.pack("<BBHH", ancho, alto, planos, bits)
        salida += png_descomprimido(img) if img.startswith(FIRMA_PNG) else img
    return bytes(salida)


# las 25 salidas: función y argumentos
SALIDAS = {
    "ico()": lambda: icons.ico(),
    **{f"ico(campo={k}) (16,32)": (lambda k=k: icons.ico((16, 32), icons.CAMPOS[k]))
       for k in ("azul", "verde", "granate", "morado", "grafito")},
    **{f"ico_bandeja({e})": (lambda e=e: icons.ico_bandeja(e))
       for e in ("bien", "sincronizando", "aviso", "pausa", "bloqueado")},
    **{f"pixmap_bandeja({e},24)": (lambda e=e: icons.pixmap_bandeja(e, 24))
       for e in ("bien", "sincronizando", "aviso", "pausa", "bloqueado")},
    "png_marca(32)": lambda: icons.png_marca(32),
    "pixeles_marca(16)": lambda: icons.pixeles_marca(16),
    **{f"pixeles_menu({n},16,#000000)": (lambda n=n: icons.pixeles_menu(n, 16, "#000000"))
       for n in ("pausa", "play", "candado", "carpeta", "ok", "expulsar", "llave")},
}

# SHA-256 de la salida entera: las que no llevan zlib (23)
ENTEROS = {
    "ico(campo=azul) (16,32)": "13a1446aed9353f9379b139ad1cc581fa2634f27b1d9a2864e538fea6c26b1d4",
    "ico(campo=verde) (16,32)": "f90fc72c4c8683949127c94054e202d5a00cfc0eee656284f87f5f42657a51e3",
    "ico(campo=granate) (16,32)": "e8bf93767893d3e10f75018b9acbdab7b780f418b8216a14642cfeb885444091",
    "ico(campo=morado) (16,32)": "a04849bbba3b020af06a54d92aab0571534608659c987756f22cec414504110f",
    "ico(campo=grafito) (16,32)": "e01ac70ba4b94baa7be0ab82fb44ae63bc381f5beed97117a323651cd25431b0",
    "ico_bandeja(bien)": "e6ce7f2ed319d1b931a942fafd72cfa5375f82955f785a9af433bb3d9e50b1ca",
    "pixmap_bandeja(bien,24)": "653521473918149506cda147f71122f442a30af09f7cec16032093078b9dac6e",
    "ico_bandeja(sincronizando)": "6124005f1ba6c49665ec1dee4de3c5fe055c30d3875d29191a7ba5e8581a20af",
    "pixmap_bandeja(sincronizando,24)": "d0cdb85178841113877cb4801802c02384ec099b86d0ebb5217be6d302d194bf",
    "ico_bandeja(aviso)": "b42754ed66e40fa2bfa43146c5fbb368eb174056b7ed935111e9e01d5835f98e",
    "pixmap_bandeja(aviso,24)": "b84b49938efbf8b8f2c29e13c7dc52f018127a8970ff1aceac27f1c4472a2813",
    "ico_bandeja(pausa)": "4769770fd3e84724cb78cb72a8dc77e7bad622d061d46a3d7db2e4193a207350",
    "pixmap_bandeja(pausa,24)": "3ac1b1f65aeb7686a015725ee9b9cdd5de1c6b16d42970a2876e5b1681bc48a0",
    "ico_bandeja(bloqueado)": "a2469ce313fc6debbd55b0d5b45047610b6e8388b1233e6cb2d0eda57a183573",
    "pixmap_bandeja(bloqueado,24)": "2aea3962dfe38e5598af9b15ddf72789edb5b9ee3a63f736d4fedfe4d3675ef0",
    "pixeles_marca(16)": "161dfbcfbb5cb646418f1086711a016f72cf4903f39d63a09be486041de8f212",
    "pixeles_menu(pausa,16,#000000)": "90a4e63bcc1601dfd75438bf1fada36c854d7d7ad7a3f23d4669febce2f32bbb",
    "pixeles_menu(play,16,#000000)": "dcecbec06e1371631d3501e9919f3cb53c88a3321c25a4486e3d1c5d7d8b13d6",
    "pixeles_menu(candado,16,#000000)": "8488701d4ce138f95eef39523620e66d58fd129ac3eeea58f0cd9b1e12b37191",
    "pixeles_menu(carpeta,16,#000000)": "f88b28b7088d013f354cdaf709aa6152689a1ec4f1aaa37097c89548674aaf24",
    "pixeles_menu(ok,16,#000000)": "8bf83582927ed06fd2d6c417bcbfcaec19634f9c62934dc786a9b951c2540a15",
    "pixeles_menu(expulsar,16,#000000)": "7da4765bcc9b84ac6abcfdeca95a099f9d97e2db52cd48e644b6cfda7626b468",
    "pixeles_menu(llave,16,#000000)": "ebf9e7f284e8501e8b94f312177751e9fb6d464bb80422a691acb4c474188183",
}

# SHA-256 del contenido descomprimido (`canonico()`): las dos con PNG
DESCOMPRIMIDOS = {
    "ico()": "bf2cd2af8c0b6d1448eeffb35a827bd06e078dae9672bae409fbaf2afd2771f0",
    "png_marca(32)": "ca1089bb5a7e3c6bd06a870dd82184ab5a92de9f2dc748455c4898c840d27e50",
}

c("las 25 salidas están todas en la tabla",
  sorted(SALIDAS), sorted([*ENTEROS, *DESCOMPRIMIDOS]))

generado = {nombre: f() for nombre, f in SALIDAS.items()}

c("las que no llevan zlib salen byte a byte iguales a los fijados",
  sorted(n for n, h in ENTEROS.items() if sha(generado[n]) != h), [])
c("las dos con PNG salen igual una vez descomprimidas",
  sorted(n for n, h in DESCOMPRIMIDOS.items() if sha(canonico(generado[n])) != h), [])
c("  y el `.ico` de la marca lleva PNG en sus dos tamaños grandes (128 y 256)",
  sum(1 for i in range(7)
      if generado["ico()"][struct.unpack_from("<I", generado["ico()"], 6 + 16 * i + 12)[0]:][:8]
      == FIRMA_PNG), 2)


# `_png` contra la copia sencilla, con el mismo zlib en los dos
def png_sencillo(rgba) -> bytes:
    """El `_png` de referencia: un `bytes(...)` por píxel y sin memoria, el más simple."""
    crudo = bytearray()
    for fila in rgba:
        crudo.append(0)
        for r, g, b, a in fila:
            crudo += bytes((r, g, b, round(a * 255)))

    def trozo(nombre: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + nombre + datos
                + struct.pack(">I", zlib.crc32(nombre + datos) & 0xFFFFFFFF))

    return (FIRMA_PNG
            + trozo(b"IHDR", struct.pack(">IIBBBBB", len(rgba[0]), len(rgba), 8, 6, 0, 0, 0))
            + trozo(b"IDAT", zlib.compress(bytes(crudo), 9))
            + trozo(b"IEND", b""))


def pieza(borde: int = 3, ancho: int = 256, alto: int = 64):
    """Una pieza de `caja()` como la de un botón: dos capas y el centro ensanchado."""
    capas = [("#8C8678", 0.0, icons._forma(0, 0, 8, 8, 4, "1111")),
             ("#FFFFFF", 0.0, icons._forma(1, 1, 6, 6, 3, "1111"))]
    return icons._ensanchar(icons._capas_rgba(capas, 8.0, 8), borde, ancho, alto)


CASOS = {
    "pieza de botón (centro ensanchado a 256×64)": pieza(),
    "pieza sin ensanchar": icons._capas_rgba(
        [("#2F6FEB", 0.0, icons._forma(0, 0, 8, 8, 4, "1111"))], 8.0, 8),
    "casilla con hueco a la derecha": icons._con_hueco(
        icons._capas_rgba([("#8C8678", 0.0, [("rr", 0, 0, 16, 16, 2)])], 16.0, 16), 16,
        derecha=7),
    "glifo bajado y con altura": icons._con_hueco(
        icons._capas_rgba([("#000000", icons.TRAZO, icons.GLIFOS["ok"])], 16.0, 16), 16,
        bajar=2, alto=20),
    "la marca a 32 px": icons._capas_rgba(icons._capas_marca(32), 64.0, 32),
    "una imagen de 1×1": [[(1, 2, 3, 0.5)]],
    "alfa entero y flotante que valen lo mismo": [[(9, 9, 9, 1), (9, 9, 9, 1.0), (9, 9, 9, 0)]],
    "la misma fila repetida y alternada (A, B, A, A, B)": (
        lambda a, b: [a, b, a, a, b])([(0, 0, 0, 0.0), (255, 255, 255, 1.0)],
                                      [(255, 0, 0, 0.25), (0, 0, 255, 0.75)]),
    "filas distintas con los mismos píxeles": [[(5, 6, 7, 1.0)] * 3, [(5, 6, 7, 1.0)] * 3],
    "redondeo del alfa (0,5·255 = 127,5)": [[(0, 0, 0, 0.5), (0, 0, 0, 0.502), (0, 0, 0, 0.498)]],
}
for nombre, rgba in CASOS.items():
    c(f"_png = el de referencia: {nombre}", icons._png(rgba) == png_sencillo(rgba), True)
c("  y se acepta el `size` que algunas llamadas aún pasan",
  icons._png(CASOS["pieza sin ensanchar"], 8) == png_sencillo(CASOS["pieza sin ensanchar"]),
  True)

# sin estado entre llamadas: lo que una dejó en sus tablas no cuenta en la siguiente
a = [[(1, 1, 1, 1.0)]]
b = [[(1, 1, 1, 0.0)]]
c("dos llamadas seguidas no se contaminan",
  (icons._png(a) == png_sencillo(a), icons._png(b) == png_sencillo(b),
   icons._png(a) == png_sencillo(a)), (True, True, True))

# …y vale la pena: la memoria hace falta, no es un adorno (mejor de 5, relativo)
grande = pieza()


def mejor_de(f, veces: int = 5) -> float:
    """Devuelve lo que tarda `f` en su mejor vuelta."""
    mejor = float("inf")
    for _ in range(veces):
        t = time.perf_counter()
        f()
        mejor = min(mejor, time.perf_counter() - t)
    return mejor


c("_png de una pieza ensanchada tarda menos de la mitad que el de referencia",
  mejor_de(lambda: icons._png(grande)) * 2 < mejor_de(lambda: png_sencillo(grande)), True)

sys.exit(c.report())
