#!/usr/bin/env python3
"""Lo que decide gestionar el servidor desde el explorador «Servidor…», sin Tk, sin disco y sin red.

Lo que se comprueba es lo que, si falla, deja a un dispositivo sin su carpeta o sin su
catálogo: que un nombre no vale si lleva `/`, está vacío o ya existe (sin mirar mayúsculas),
que un pegado no pisa ni se mete dentro de sí mismo, qué rutas salen y cuáles llegan en cada
acción, qué se bloquea (raíz de una pareja, catálogo, llegar a una `up-mirror`) y qué avisa
la próxima pasada de cada pareja.
"""

import sys

from _harness import Checks, mkcfg

from common import rcd
from ui import gestion, transferencia

c = Checks("gestión del servidor: qué se puede tocar y qué dirá cada pareja")

E = transferencia.Elemento
Op = gestion.Operacion

# --- constantes ------------------------------------------------------------------------
c("los tipos", (gestion.BORRAR, gestion.RENOMBRAR, gestion.MOVER, gestion.NUEVA),
  ("borrar", "renombrar", "mover", "nueva"))
c("Operacion está congelada y sus extras valen None",
  (Op(gestion.BORRAR, "nas", "/").destino, Op(gestion.BORRAR, "nas", "/").nombre,
   Op(gestion.BORRAR, "nas", "/").elementos), (None, None, ()))
try:
    Op(gestion.BORRAR, "nas", "/").nombre = "x"
    c("Operacion no se puede mutar", "mutó", "FrozenInstanceError")
except Exception as exc:
    c("Operacion no se puede mutar", type(exc).__name__, "FrozenInstanceError")

# --- validar_nombre --------------------------------------------------------------------
c("nombre vacío", gestion.validar_nombre("", []), "Escribe un nombre.")
c("nombre de espacios", gestion.validar_nombre("   ", []), "Escribe un nombre.")
c("con barra", gestion.validar_nombre("a/b", []), "Un nombre no puede llevar «/».")
c("punto", gestion.validar_nombre(".", []), "Ese nombre no vale.")
c("dos puntos", gestion.validar_nombre("..", []), "Ese nombre no vale.")
c("ya hay uno igual salvo mayúsculas", gestion.validar_nombre("Fotos", ["fotos"]),
  "Ya hay algo que se llama «Fotos» en esta carpeta.")
c("ya hay uno exacto", gestion.validar_nombre("fotos", ["fotos", "otro"]),
  "Ya hay algo que se llama «fotos» en esta carpeta.")
c("un nombre libre vale", gestion.validar_nombre("nuevo", ["fotos"]), None)
c("el mismo nombre que el actual no es un rechazo (quien llama no hace nada)",
  gestion.validar_nombre("foto.jpg", ["foto.jpg"], actual="foto.jpg"), None)
c("cambiar solo las mayúsculas del propio nombre vale",
  gestion.validar_nombre("Foto.jpg", ["foto.jpg"], actual="foto.jpg"), None)
c("pero no sobre otro que solo se diferencia en mayúsculas",
  gestion.validar_nombre("FOTO.JPG", ["foto.jpg", "Foto.jpg"], actual="foto.jpg"),
  "Ya hay algo que se llama «FOTO.JPG» en esta carpeta.")
c("un espacio al final se conserva", gestion.validar_nombre("nota ", ["otra"]), None)
c("renombrar sobre otro hermano", gestion.validar_nombre("b", ["a", "b"], actual="a"),
  "Ya hay algo que se llama «b» en esta carpeta.")
c("existentes puede ser un generador", gestion.validar_nombre("x", (n for n in ["X"])),
  "Ya hay algo que se llama «x» en esta carpeta.")

# --- validar_pegado --------------------------------------------------------------------
mover = Op(gestion.MOVER, "nas", "/a", (E("x", True), E("y.txt", False)), destino="/b")
c("pegado normal", gestion.validar_pegado(mover, []), None)
c("pegado en la misma carpeta",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/a", (E("x", True),), destino="/a"), []),
  "Ya están en esta carpeta.")
c("  aunque una ruta lleve barra final",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/a", (E("x", True),), destino="/a/"), []),
  "Ya están en esta carpeta.")
c("  y en la raíz",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/", (E("x", True),), destino="/"), []),
  "Ya están en esta carpeta.")
c("una carpeta dentro de sí misma",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/a", (E("x", True),), destino="/a/x/sub"), []),
  "No se puede mover una carpeta dentro de sí misma.")
c("una carpeta sobre sí misma",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/a", (E("x", True),), destino="/a/x"), []),
  "No se puede mover una carpeta dentro de sí misma.")
c("una carpeta desde la raíz dentro de sí misma",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/", (E("x", True),), destino="/x/y"), []),
  "No se puede mover una carpeta dentro de sí misma.")
c("un ARCHIVO no es una carpeta: no hay «dentro»",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/a", (E("x", False),), destino="/a/x/sub"), []),
  None)
c("una carpeta hermana con prefijo de texto no es «dentro»",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/a", (E("x", True),), destino="/a/xy"), []),
  None)
c("un archivo y un destino que empieza por su nombre",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/a", (E("x", False),), destino="/a/xy"), []),
  None)
c("un nombre ocupado, sin mirar mayúsculas",
  gestion.validar_pegado(Op(gestion.MOVER, "nas", "/a", (E("x.txt", False),), destino="/b"),
                         ["X.txt"]),
  "Ya hay «x.txt» en /b: renómbralo antes.")
c("dos ocupados",
  gestion.validar_pegado(
      Op(gestion.MOVER, "nas", "/a", (E("p", True), E("q", False), E("r", False)), destino="/b"),
      ["Q", "R", "otro"]),
  "Ya hay «q» y 1 más en /b: renómbralos antes.")
c("tres ocupados",
  gestion.validar_pegado(
      Op(gestion.MOVER, "nas", "/a", (E("p", True), E("q", False), E("r", False)), destino="/b"),
      ["P", "Q", "R"]),
  "Ya hay «p» y 2 más en /b: renómbralos antes.")
c("lo que hay en el destino y no se mueve no estorba", gestion.validar_pegado(mover, ["z"]), None)

# --- rutas_tocadas ---------------------------------------------------------------------
c("borrar: salen los elementos",
  gestion.rutas_tocadas(Op(gestion.BORRAR, "nas", "/datos", (E("a", False), E("b", True)))),
  (("/datos/a", "/datos/b"), ()))
c("borrar en la raíz: nunca «//»",
  gestion.rutas_tocadas(Op(gestion.BORRAR, "nas", "/", (E("x", True),))), (("/x",), ()))
c("renombrar: sale el viejo y llega el nuevo",
  gestion.rutas_tocadas(Op(gestion.RENOMBRAR, "nas", "/datos", (E("viejo", True),), nombre="nuevo")),
  (("/datos/viejo",), ("/datos/nuevo",)))
c("renombrar en la raíz",
  gestion.rutas_tocadas(Op(gestion.RENOMBRAR, "nas", "/", (E("a", False),), nombre="b")),
  (("/a",), ("/b",)))
c("mover: cada elemento sale de su carpeta y llega a la de destino",
  gestion.rutas_tocadas(Op(gestion.MOVER, "nas", "/a", (E("x", True), E("y", False)), destino="/b/c")),
  (("/a/x", "/a/y"), ("/b/c/x", "/b/c/y")))
c("mover desde la raíz a la raíz",
  gestion.rutas_tocadas(Op(gestion.MOVER, "nas", "/", (E("x", False),), destino="/")),
  (("/x",), ("/x",)))
c("mover a la raíz",
  gestion.rutas_tocadas(Op(gestion.MOVER, "nas", "/a", (E("x", False),), destino="/")),
  (("/a/x",), ("/x",)))
c("nueva carpeta: solo llega",
  gestion.rutas_tocadas(Op(gestion.NUEVA, "nas", "/datos", nombre="n")), ((), ("/datos/n",)))
c("nueva carpeta en la raíz",
  gestion.rutas_tocadas(Op(gestion.NUEVA, "nas", "/", nombre="n")), ((), ("/n",)))
c("una carpeta con barra final se normaliza",
  gestion.rutas_tocadas(Op(gestion.NUEVA, "nas", "/datos/", nombre="n")), ((), ("/datos/n",)))

# --- parejas ---------------------------------------------------------------------------
cfg = mkcfg((), pairs=[
    {"name": "Copia", "local": "sync-data/copia", "remote_path": "/datos/copia", "mode": "up-mirror"},
    {"name": "Notas", "local": "sync-data/notas", "remote_path": "/datos/notas", "mode": "bisync"},
    {"name": "Baja", "local": "sync-data/baja", "remote_path": "/datos/baja", "mode": "down"},
    {"name": "Espejo", "local": "sync-data/espejo", "remote_path": "/datos/espejo",
     "mode": "down-mirror"},
    {"name": "Sube", "local": "sync-data/sube", "remote_path": "/datos/sube", "mode": "up"},
    {"name": "Hondo", "local": "sync-data/hondo", "remote_path": "/datos/notas/hondo",
     "mode": "bisync"},
    {"name": "Ajena", "local": "sync-data/ajena", "remote_path": "/datos/copia", "mode": "bisync",
     "remote": "otro"},
])

c("parejas_que_contienen: la raíz exacta",
  transferencia.parejas_que_contienen(cfg, "nas", "/datos/notas"), {"Notas"})
c("  un ancestro",
  transferencia.parejas_que_contienen(cfg, "nas", "/datos/notas/a/b"), {"Notas"})
c("  la más honda gana",
  transferencia.parejas_que_contienen(cfg, "nas", "/datos/notas/hondo/a"), {"Hondo"})
c("  fuera de toda pareja", transferencia.parejas_que_contienen(cfg, "nas", "/datos"), set())
c("  un prefijo de texto no es un ancestro",
  transferencia.parejas_que_contienen(cfg, "nas", "/datos/notasx"), set())
c("  solo las del mismo remote",
  transferencia.parejas_que_contienen(cfg, "otro", "/datos/copia/x"), {"Ajena"})
c("  una ruta con barra final", transferencia.parejas_que_contienen(cfg, "nas", "/datos/notas/"),
  {"Notas"})
c("parejas_bajo: la propia carpeta", transferencia.parejas_bajo(cfg, "nas", "/datos/baja"), {"Baja"})
c("  una carpeta que contiene a otras",
  transferencia.parejas_bajo(cfg, "nas", "/datos/notas"), {"Notas", "Hondo"})
c("  la raíz las contiene todas (las del remote)",
  transferencia.parejas_bajo(cfg, "nas", "/"),
  {"Copia", "Notas", "Baja", "Espejo", "Sube", "Hondo"})
c("  una carpeta dentro de una pareja no es «bajo»",
  transferencia.parejas_bajo(cfg, "nas", "/datos/notas/a"), set())
c("  un prefijo de texto no cuenta", transferencia.parejas_bajo(cfg, "nas", "/datos/not"), set())
c("  solo las del mismo remote", transferencia.parejas_bajo(cfg, "otro", "/datos"), {"Ajena"})

# --- bloqueo ---------------------------------------------------------------------------
RAIZ = "Ahí está la carpeta de la pareja «{p}»: tocarla desde aquí rompería la pareja."
CATALOGO = ("Ahí está el catálogo de las parejas: tocarlo desde aquí dejaría a los dispositivos "
            "sin él.")
LLEGAR = ("«Copia» deja el servidor igual que el dispositivo: lo que pongas aquí lo borraría su "
          "próxima pasada.")
CAT = ("nas", "/prdrive-catalog/")
B = gestion.BORRAR

c("borrar la raíz de una pareja",
  gestion.bloqueo(Op(B, "nas", "/datos", (E("notas", True),)), cfg, None), RAIZ.format(p="Notas"))
c("borrar una carpeta que contiene raíces de pareja",
  gestion.bloqueo(Op(B, "nas", "/", (E("datos", True),)), cfg, None), RAIZ.format(p="Copia"))
c("borrar la carpeta que contiene una pareja anidada",
  gestion.bloqueo(Op(B, "nas", "/datos", (E("notas", True),)), cfg, None), RAIZ.format(p="Notas"))
c("renombrar otra carpeta al nombre de la raíz de una pareja",
  gestion.bloqueo(Op(gestion.RENOMBRAR, "nas", "/datos", (E("viejo", True),), nombre="espejo"),
                  cfg, None), RAIZ.format(p="Espejo"))
c("renombrar la raíz de una pareja",
  gestion.bloqueo(Op(gestion.RENOMBRAR, "nas", "/datos", (E("baja", True),), nombre="otra"),
                  cfg, None), RAIZ.format(p="Baja"))
c("mover una carpeta que contiene una pareja",
  gestion.bloqueo(Op(gestion.MOVER, "nas", "/datos", (E("sube", True),), destino="/tmp"),
                  cfg, None), RAIZ.format(p="Sube"))
c("mover algo encima del nombre de una raíz",
  gestion.bloqueo(Op(gestion.MOVER, "nas", "/tmp", (E("baja", True),), destino="/datos"),
                  cfg, None), RAIZ.format(p="Baja"))
c("crear la carpeta que será la raíz de una pareja (aún no existe)",
  gestion.bloqueo(Op(gestion.NUEVA, "nas", "/datos", nombre="baja"), cfg, None),
  RAIZ.format(p="Baja"))
c("borrar un archivo dentro de una pareja no bloquea",
  gestion.bloqueo(Op(B, "nas", "/datos/notas", (E("a.txt", False),)), cfg, None), None)
c("borrar una carpeta dentro de una pareja no bloquea",
  gestion.bloqueo(Op(B, "nas", "/datos/notas", (E("sub", True),)), cfg, None), None)
c("fuera de toda pareja no bloquea",
  gestion.bloqueo(Op(B, "nas", "/otro", (E("a", True),)), cfg, None), None)
c("las parejas de otro remote no bloquean",
  gestion.bloqueo(Op(B, "b2", "/datos", (E("notas", True),)), cfg, None), None)
c("  pero sí en su propio remote",
  gestion.bloqueo(Op(B, "otro", "/datos", (E("copia", True),)), cfg, None), RAIZ.format(p="Ajena"))
c("  y solo la suya",
  gestion.bloqueo(Op(B, "otro", "/datos", (E("notas", True),)), cfg, None), None)

c("borrar la carpeta del catálogo",
  gestion.bloqueo(Op(B, "nas", "/", (E("prdrive-catalog", True),)), cfg, CAT), CATALOGO)
c("borrar el remote.toml",
  gestion.bloqueo(Op(B, "nas", "/prdrive-catalog", (E("remote.toml", False),)), cfg, CAT), CATALOGO)
c("borrar el keychain/ del llavero",
  gestion.bloqueo(Op(B, "nas", "/prdrive-catalog", (E("keychain", True),)), cfg, CAT), CATALOGO)
c("borrar algo dentro del catálogo",
  gestion.bloqueo(Op(B, "nas", "/prdrive-catalog/keychain", (E("a.kdbx", False),)), cfg, CAT),
  CATALOGO)
c("borrar una carpeta que contiene el catálogo (la raíz de todo)",
  gestion.bloqueo(Op(B, "nas", "/", (E("prdrive-catalog", True), E("x", False))), cfg, CAT), CATALOGO)
c("renombrar otra carpeta al nombre del catálogo",
  gestion.bloqueo(Op(gestion.RENOMBRAR, "nas", "/", (E("viejo", True),), nombre="prdrive-catalog"),
                  cfg, CAT), CATALOGO)
c("crear dentro del catálogo",
  gestion.bloqueo(Op(gestion.NUEVA, "nas", "/prdrive-catalog", nombre="n"), cfg, CAT), CATALOGO)
c("una carpeta con prefijo de texto no es el catálogo",
  gestion.bloqueo(Op(B, "nas", "/", (E("prdrive-catalog-viejo", True),)), cfg, CAT), None)
c("otro remote no es el catálogo",
  gestion.bloqueo(Op(B, "b2", "/", (E("prdrive-catalog", True),)), cfg, CAT), None)
c("sin catálogo conocido no bloquea por él",
  gestion.bloqueo(Op(B, "nas", "/", (E("prdrive-catalog", True),)), cfg, None), None)
c("una pareja gana al catálogo (manda la primera regla)",
  gestion.bloqueo(Op(B, "nas", "/", (E("datos", True),)), cfg, ("nas", "/datos/")),
  RAIZ.format(p="Copia"))

RAIZ_CAT = ("nas", "")
c("catálogo en la raíz: borrar remote.toml",
  gestion.bloqueo(Op(B, "nas", "/", (E("remote.toml", False),)), cfg, RAIZ_CAT), CATALOGO)
c("catálogo en la raíz: borrar pairs.toml",
  gestion.bloqueo(Op(B, "nas", "/", (E("pairs.toml", False),)), cfg, RAIZ_CAT), CATALOGO)
c("catálogo en la raíz: otro archivo no bloquea",
  gestion.bloqueo(Op(B, "nas", "/", (E("otra.txt", False),)), cfg, RAIZ_CAT), None)
c("catálogo en la raíz: una carpeta cualquiera no bloquea",
  gestion.bloqueo(Op(B, "nas", "/", (E("fotos", True),)), cfg, RAIZ_CAT), None)
c("catálogo en la raíz: un remote.toml en otra carpeta no es el catálogo",
  gestion.bloqueo(Op(B, "nas", "/fotos", (E("remote.toml", False),)), cfg, RAIZ_CAT), None)
c("catálogo en la raíz: renombrar algo a remote.toml",
  gestion.bloqueo(Op(gestion.RENOMBRAR, "nas", "/", (E("a.txt", False),), nombre="remote.toml"),
                  cfg, RAIZ_CAT), CATALOGO)

RAIZ_ABS = ("nas", "/")
c("catálogo en la raíz escrito con «/»: borrar remote.toml",
  gestion.bloqueo(Op(B, "nas", "/", (E("remote.toml", False),)), cfg, RAIZ_ABS), CATALOGO)
c("catálogo en la raíz escrito con «/»: borrar pairs.toml",
  gestion.bloqueo(Op(B, "nas", "/", (E("pairs.toml", False),)), cfg, RAIZ_ABS), CATALOGO)
c("catálogo en la raíz escrito con «/»: otro archivo no bloquea",
  gestion.bloqueo(Op(B, "nas", "/", (E("otra.txt", False),)), cfg, RAIZ_ABS), None)
c("catálogo en la raíz escrito con «/»: una carpeta cualquiera no bloquea",
  gestion.bloqueo(Op(B, "nas", "/", (E("fotos", True),)), cfg, RAIZ_ABS), None)
c("catálogo en la raíz escrito con «/»: renombrar algo a remote.toml",
  gestion.bloqueo(Op(gestion.RENOMBRAR, "nas", "/", (E("a.txt", False),), nombre="remote.toml"),
                  cfg, RAIZ_ABS), CATALOGO)

c("mover dentro de una up-mirror",
  gestion.bloqueo(Op(gestion.MOVER, "nas", "/tmp", (E("a.txt", False),), destino="/datos/copia/sub"),
                  cfg, None), LLEGAR)
c("mover a la raíz de una up-mirror",
  gestion.bloqueo(Op(gestion.MOVER, "nas", "/tmp", (E("a.txt", False),), destino="/datos/copia"),
                  cfg, None), LLEGAR)
c("crear una carpeta en una up-mirror",
  gestion.bloqueo(Op(gestion.NUEVA, "nas", "/datos/copia", nombre="n"), cfg, None), LLEGAR)
c("renombrar dentro de una up-mirror (llega ahí)",
  gestion.bloqueo(Op(gestion.RENOMBRAR, "nas", "/datos/copia", (E("a", False),), nombre="b"),
                  cfg, None), LLEGAR)
c("borrar dentro de una up-mirror no bloquea (salir es un aviso)",
  gestion.bloqueo(Op(B, "nas", "/datos/copia", (E("a.txt", False),)), cfg, None), None)
c("mover FUERA de una up-mirror no bloquea",
  gestion.bloqueo(Op(gestion.MOVER, "nas", "/datos/copia", (E("a.txt", False),), destino="/tmp"),
                  cfg, None), None)
c("llegar a una pareja anidada dentro de una up-mirror manda la más honda",
  gestion.bloqueo(
      Op(gestion.NUEVA, "nas", "/x/y", nombre="n"),
      mkcfg((), pairs=[
          {"name": "Copia", "local": "sync-data/c", "remote_path": "/x", "mode": "up-mirror"},
          {"name": "Dentro", "local": "sync-data/d", "remote_path": "/x/y", "mode": "bisync"},
      ]), None), None)
c("mover a una bisync no bloquea",
  gestion.bloqueo(Op(gestion.MOVER, "nas", "/tmp", (E("a", False),), destino="/datos/notas/s"),
                  cfg, None), None)
c("mover a otra up-mirror del mismo remote bloquea con su nombre",
  gestion.bloqueo(
      Op(gestion.NUEVA, "nas", "/z", nombre="n"),
      mkcfg((), pairs=[
          {"name": "Z", "local": "sync-data/z", "remote_path": "/z", "mode": "up-mirror"},
      ]), None),
  "«Z» deja el servidor igual que el dispositivo: lo que pongas aquí lo borraría su próxima "
  "pasada.")

# --- avisos ----------------------------------------------------------------------------
QUITA = "La próxima pasada de «{p}» lo quitará también del dispositivo."
CONSERVA = "El dispositivo conserva su copia: «{p}» no borra."
SUBE_DE_NUEVO = "La próxima pasada de «{p}» lo volverá a subir desde el dispositivo."
COPIA_AL_DISP = "La próxima pasada de «{p}» lo copiará al dispositivo."
NO_RECIBE = "El dispositivo no lo recibirá: «{p}» solo sube."

c("borrar en una bisync",
  gestion.avisos(Op(B, "nas", "/datos/notas", (E("a.txt", False),)), cfg), (QUITA.format(p="Notas"),))
c("borrar en la pareja anidada: solo la más honda",
  gestion.avisos(Op(B, "nas", "/datos/notas/hondo", (E("a.txt", False),)), cfg),
  (QUITA.format(p="Hondo"),))
c("borrar en una down-mirror",
  gestion.avisos(Op(B, "nas", "/datos/espejo", (E("a", True),)), cfg), (QUITA.format(p="Espejo"),))
c("borrar en una down",
  gestion.avisos(Op(B, "nas", "/datos/baja", (E("a", True),)), cfg), (CONSERVA.format(p="Baja"),))
c("borrar en una up",
  gestion.avisos(Op(B, "nas", "/datos/sube", (E("a", True),)), cfg),
  (SUBE_DE_NUEVO.format(p="Sube"),))
c("borrar en una up-mirror",
  gestion.avisos(Op(B, "nas", "/datos/copia", (E("a", True),)), cfg),
  (SUBE_DE_NUEVO.format(p="Copia"),))
c("borrar varios elementos de una misma pareja: una línea",
  gestion.avisos(Op(B, "nas", "/datos/notas", (E("a", False), E("b", True), E("c", False))), cfg),
  (QUITA.format(p="Notas"),))
c("mover de Baja a Notas: sale de una y llega a otra",
  gestion.avisos(Op(gestion.MOVER, "nas", "/datos/baja", (E("a", False),), destino="/datos/notas"), cfg),
  (CONSERVA.format(p="Baja"), COPIA_AL_DISP.format(p="Notas")))
c("mover dentro de la misma pareja: sale y llega",
  gestion.avisos(Op(gestion.MOVER, "nas", "/datos/notas", (E("a", False),), destino="/datos/notas/s"),
                 cfg),
  (QUITA.format(p="Notas"), COPIA_AL_DISP.format(p="Notas")))
c("nueva carpeta en una up: el dispositivo no la recibe",
  gestion.avisos(Op(gestion.NUEVA, "nas", "/datos/sube", nombre="n"), cfg),
  (NO_RECIBE.format(p="Sube"),))
c("nueva carpeta en una down",
  gestion.avisos(Op(gestion.NUEVA, "nas", "/datos/baja", nombre="n"), cfg),
  (COPIA_AL_DISP.format(p="Baja"),))
c("nueva carpeta en una bisync",
  gestion.avisos(Op(gestion.NUEVA, "nas", "/datos/notas", nombre="n"), cfg),
  (COPIA_AL_DISP.format(p="Notas"),))
c("renombrar dentro de una down-mirror: salen y llegan",
  gestion.avisos(Op(gestion.RENOMBRAR, "nas", "/datos/espejo", (E("a", False),), nombre="b"), cfg),
  (QUITA.format(p="Espejo"), COPIA_AL_DISP.format(p="Espejo")))
c("renombrar dentro de una bisync",
  gestion.avisos(Op(gestion.RENOMBRAR, "nas", "/datos/notas", (E("a", False),), nombre="b"), cfg),
  (QUITA.format(p="Notas"), COPIA_AL_DISP.format(p="Notas")))
c("llegar a una up-mirror no tiene aviso (lo bloquea otra regla)",
  gestion.avisos(Op(gestion.NUEVA, "nas", "/datos/copia", nombre="n"), cfg), ())
c("fuera de toda pareja no hay aviso",
  gestion.avisos(Op(B, "nas", "/otro", (E("a", False),)), cfg), ())
c("las parejas de otro remote no avisan",
  gestion.avisos(Op(B, "b2", "/datos/notas", (E("a", False),)), cfg), ())
c("  pero sí en el suyo",
  gestion.avisos(Op(B, "otro", "/datos/copia", (E("a", False),)), cfg), (QUITA.format(p="Ajena"),))
c("sin duplicados: dos elementos que salen del mismo sitio y llegan al mismo",
  gestion.avisos(
      Op(gestion.MOVER, "nas", "/datos/baja", (E("a", False), E("b", False)), destino="/datos/baja/s"),
      cfg),
  (CONSERVA.format(p="Baja"), COPIA_AL_DISP.format(p="Baja")))
cfg_dos = mkcfg((), pairs=[
    {"name": "Uno", "local": "sync-data/uno", "remote_path": "/m", "mode": "bisync"},
    {"name": "Dos", "local": "sync-data/dos", "remote_path": "/m", "mode": "down"},
])
c("dos parejas en la misma carpeta: una línea por cada una, en el orden de la configuración",
  gestion.avisos(Op(B, "nas", "/m", (E("a", False),)), cfg_dos),
  (QUITA.format(p="Uno"), CONSERVA.format(p="Dos")))

# --- ordenes_de ------------------------------------------------------------------------
RARO = ("con espacio", "100%", "a#b?", "*[x]{y}")
c("borrar una carpeta: purge, la ruta sin la barra del principio",
  gestion.ordenes_de(Op(gestion.BORRAR, "nas", "/datos", (E("viejo", True),))),
  [{"_path": "operations/purge", "fs": "nas:/", "remote": "datos/viejo"}])
c("borrar un archivo: deletefile",
  gestion.ordenes_de(Op(gestion.BORRAR, "nas", "/datos", (E("a.txt", False),))),
  [{"_path": "operations/deletefile", "fs": "nas:/", "remote": "datos/a.txt"}])
c("borrar en la raíz: sin barra y sin «//»",
  gestion.ordenes_de(Op(gestion.BORRAR, "nas", "/", (E("x", True), E("y", False)))),
  [{"_path": "operations/purge", "fs": "nas:/", "remote": "x"},
   {"_path": "operations/deletefile", "fs": "nas:/", "remote": "y"}])
c("una orden por elemento y en su orden",
  [o["remote"] for o in gestion.ordenes_de(
      Op(gestion.BORRAR, "nas", "/d", tuple(E(n, False) for n in RARO)))],
  ["d/" + n for n in RARO])
c("los nombres raros van tal cual, sin escapar (mover una carpeta)",
  gestion.ordenes_de(Op(gestion.MOVER, "nas", "/a", tuple(E(n, True) for n in RARO), destino="/b")),
  [{"_path": "sync/move", "srcFs": "nas:/a/" + n, "dstFs": "nas:/b/" + n,
    "deleteEmptySrcDirs": True} for n in RARO])
c("mover un archivo: movefile con el remote entero",
  gestion.ordenes_de(Op(gestion.MOVER, "nas", "/a", (E("x y.txt", False),), destino="/b/c")),
  [{"_path": "operations/movefile", "srcFs": "nas:/", "srcRemote": "a/x y.txt",
    "dstFs": "nas:/", "dstRemote": "b/c/x y.txt"}])
c("mover desde la raíz: la carpeta es «nas:/x»",
  gestion.ordenes_de(Op(gestion.MOVER, "nas", "/", (E("x", True),), destino="/b")),
  [{"_path": "sync/move", "srcFs": "nas:/x", "dstFs": "nas:/b/x", "deleteEmptySrcDirs": True}])
c("mover a la raíz",
  gestion.ordenes_de(Op(gestion.MOVER, "nas", "/a", (E("x", False),), destino="/")),
  [{"_path": "operations/movefile", "srcFs": "nas:/", "srcRemote": "a/x",
    "dstFs": "nas:/", "dstRemote": "x"}])
c("renombrar una carpeta: sync/move al nombre nuevo",
  gestion.ordenes_de(Op(gestion.RENOMBRAR, "nas", "/a", (E("v", True),), nombre="100%")),
  [{"_path": "sync/move", "srcFs": "nas:/a/v", "dstFs": "nas:/a/100%",
    "deleteEmptySrcDirs": True}])
c("renombrar un archivo en la raíz: movefile",
  gestion.ordenes_de(Op(gestion.RENOMBRAR, "nas", "/", (E("v.txt", False),), nombre="a#b?")),
  [{"_path": "operations/movefile", "srcFs": "nas:/", "srcRemote": "v.txt",
    "dstFs": "nas:/", "dstRemote": "a#b?"}])
c("nueva carpeta: mkdir, una sola orden",
  gestion.ordenes_de(Op(gestion.NUEVA, "nas", "/datos", nombre="*[x]{y}")),
  [{"_path": "operations/mkdir", "fs": "nas:/", "remote": "datos/*[x]{y}"}])
c("nueva carpeta en la raíz",
  gestion.ordenes_de(Op(gestion.NUEVA, "nas", "/", nombre="con espacio")),
  [{"_path": "operations/mkdir", "fs": "nas:/", "remote": "con espacio"}])
c("ninguna orden se sale de la lista cerrada de rcd",
  all(o["_path"] in rcd.ORDENES_PERMITIDAS
      for op in (Op(gestion.BORRAR, "n", "/", (E("a", True), E("b", False))),
                 Op(gestion.MOVER, "n", "/", (E("a", True), E("b", False)), destino="/z"),
                 Op(gestion.RENOMBRAR, "n", "/", (E("a", True),), nombre="q"),
                 Op(gestion.NUEVA, "n", "/", nombre="q"))
      for o in gestion.ordenes_de(op)), True)

# --- ordenes_de: ni un espacio ni una «\» del nombre se tocan ---------------------------
# `foo ` es otro elemento que `foo`: purgar «d/foo» borraría el equivocado, y sin remedio.
for raiz, base in (("en la raíz", "/"), ("en una subcarpeta", "/d")):
    pre = "" if base == "/" else "d/"
    for nom in ("foo ", " x", "a\\b"):
        c(f"borrar una carpeta {nom!r} {raiz}",
          gestion.ordenes_de(Op(gestion.BORRAR, "nas", base, (E(nom, True),))),
          [{"_path": "operations/purge", "fs": "nas:/", "remote": pre + nom}])
        c(f"borrar un archivo {nom!r} {raiz}",
          gestion.ordenes_de(Op(gestion.BORRAR, "nas", base, (E(nom, False),))),
          [{"_path": "operations/deletefile", "fs": "nas:/", "remote": pre + nom}])
        c(f"renombrar una carpeta desde y hacia {nom!r} {raiz}",
          gestion.ordenes_de(Op(gestion.RENOMBRAR, "nas", base, (E(nom, True),), nombre=nom + "2")),
          [{"_path": "sync/move", "srcFs": "nas:/" + pre + nom, "dstFs": "nas:/" + pre + nom + "2",
            "deleteEmptySrcDirs": True}])
        c(f"renombrar un archivo desde y hacia {nom!r} {raiz}",
          gestion.ordenes_de(Op(gestion.RENOMBRAR, "nas", base, (E("v", False),), nombre=nom)),
          [{"_path": "operations/movefile", "srcFs": "nas:/", "srcRemote": pre + "v",
            "dstFs": "nas:/", "dstRemote": pre + nom}])
        c(f"mover una carpeta {nom!r} {raiz}",
          gestion.ordenes_de(Op(gestion.MOVER, "nas", base, (E(nom, True),), destino="/z")),
          [{"_path": "sync/move", "srcFs": "nas:/" + pre + nom, "dstFs": "nas:/z/" + nom,
            "deleteEmptySrcDirs": True}])
        c(f"mover un archivo {nom!r} {raiz}",
          gestion.ordenes_de(Op(gestion.MOVER, "nas", base, (E(nom, False),), destino="/")),
          [{"_path": "operations/movefile", "srcFs": "nas:/", "srcRemote": pre + nom,
            "dstFs": "nas:/", "dstRemote": nom}])
        c(f"mover una carpeta {nom!r} hacia {raiz}",
          gestion.ordenes_de(Op(gestion.MOVER, "nas", "/o", (E(nom, True),), destino=base)),
          [{"_path": "sync/move", "srcFs": "nas:/o/" + nom, "dstFs": "nas:/" + pre + nom,
            "deleteEmptySrcDirs": True}])
        c(f"nueva carpeta {nom!r} {raiz}",
          gestion.ordenes_de(Op(gestion.NUEVA, "nas", base, nombre=nom)),
          [{"_path": "operations/mkdir", "fs": "nas:/", "remote": pre + nom}])
c("la carpeta sí se normaliza (barra final, doble barra)",
  gestion.ordenes_de(Op(gestion.BORRAR, "nas", "//d//e/", (E("x ", False),))),
  [{"_path": "operations/deletefile", "fs": "nas:/", "remote": "d/e/x "}])


# --- plan_de ---------------------------------------------------------------------------
GRANDE = (1234, 3650722202)
b_grande = Op(gestion.BORRAR, "nas", "/d", (E("fotos", True),))
c("Plan está congelado y trae dos tuplas",
  gestion.plan_de(b_grande, {"fotos": GRANDE}, ()),
  gestion.Plan(("Se borrará para siempre «fotos», con 1234 archivos (3,4 GB).",), ()))
c("una carpeta de un archivo",
  gestion.plan_de(Op(gestion.BORRAR, "nas", "/d", (E("uno", True),)), {"uno": (1, 2048)}, ()
                  ).consequences,
  ("Se borrará para siempre «uno», con 1 archivo (2 KB).",))
c("una carpeta vacía",
  gestion.plan_de(Op(gestion.BORRAR, "nas", "/d", (E("hueca", True),)), {"hueca": (0, 0)}, ()
                  ).consequences,
  ("Se borrará para siempre «hueca», vacía.",))
c("un archivo",
  gestion.plan_de(Op(gestion.BORRAR, "nas", "/d", (E("a.txt", False),)), {"a.txt": (1, 1536)}, ()
                  ).consequences,
  ("Se borrará para siempre «a.txt» (1,5 KB).",))
c("una línea por elemento, en su orden",
  gestion.plan_de(Op(gestion.BORRAR, "nas", "/d", (E("hueca", True), E("a.txt", False))),
                  {"a.txt": (1, 1536), "hueca": (0, 0)}, ()).consequences,
  ("Se borrará para siempre «hueca», vacía.", "Se borrará para siempre «a.txt» (1,5 KB)."))
c("los avisos pasan tal cual como warnings",
  gestion.plan_de(b_grande, {"fotos": GRANDE}, ("uno", "dos")).warnings, ("uno", "dos"))
c("renombrar",
  gestion.plan_de(Op(gestion.RENOMBRAR, "nas", "/d", (E("a", True),), nombre="b"), {}, ()),
  gestion.Plan(("«a» pasará a llamarse «b».",), ()))
c("mover uno",
  gestion.plan_de(Op(gestion.MOVER, "nas", "/d", (E("a", True),), destino="/z/"), {}, ()
                  ).consequences,
  ("Se moverá «a» de /d a /z.",))
c("mover varios",
  gestion.plan_de(Op(gestion.MOVER, "nas", "/", (E("a", True), E("b", False), E("c", False)),
                     destino="/z"), {}, ("w",)),
  gestion.Plan(("Se moverán 3 elementos de / a /z.",), ("w",)))
c("nueva carpeta",
  gestion.plan_de(Op(gestion.NUEVA, "nas", "/d", nombre="n"), {}, ()).consequences,
  ("Se creará la carpeta «n» en /d.",))

# --- titulo_de, progreso_de y cancelando_de ---------------------------------------------
b3 = Op(gestion.BORRAR, "nas", "/datos", (E("a", True), E("b", False), E("c", False)))
m2 = Op(gestion.MOVER, "nas", "/datos", (E("a", True), E("b", False)), destino="/otra")
r1 = Op(gestion.RENOMBRAR, "nas", "/datos", (E("a", False),), nombre="b")
n1 = Op(gestion.NUEVA, "nas", "/datos", nombre="nueva")
c("título de borrar", gestion.titulo_de(b3), "Borrando en /datos")
c("título de mover", gestion.titulo_de(m2), "Moviendo a /otra")
c("título de renombrar", gestion.titulo_de(r1), "Renombrando «a» a «b»")
c("título de crear", gestion.titulo_de(n1), "Creando la carpeta «nueva»")
p0 = gestion.progreso_de(b3, {}, 1, 3)
c("progreso con stats vacías: no lanza", (p0.titulo, p0.archivo, p0.cuenta, p0.ritmo),
  ("Borrando en /datos", "", "1 de 3 elementos", ""))
c("  y la fracción es hechos/total", p0.fraccion, 1 / 3)
c("  es del tipo del panel de la pieza 2", isinstance(p0, transferencia.Progreso), True)
c("borrar cuenta los archivos que rclone borró",
  gestion.progreso_de(b3, {"deletes": 120}, 1, 3).cuenta, "1 de 3 elementos · 120 archivos borrados")
c("  con deletes en 0 no lo dice", gestion.progreso_de(b3, {"deletes": 0}, 1, 3).cuenta,
  "1 de 3 elementos")
c("  ni si no es un número", gestion.progreso_de(b3, {"deletes": None}, 1, 3).cuenta,
  "1 de 3 elementos")
c("mover no cuenta archivos borrados",
  gestion.progreso_de(m2, {"deletes": 120}, 0, 2).cuenta, "0 de 2 elementos")
c("sin elementos que contar la barra es indeterminada", gestion.progreso_de(n1, {}, 0, 0).fraccion,
  None)
c("al acabar la fracción es 1", gestion.progreso_de(b3, {}, 3, 3).fraccion, 1.0)
c("cancelando nombra el elemento que va",
  (gestion.cancelando_de(b3, 0), gestion.cancelando_de(b3, 2)),
  ("Cancelando… se para al acabar «a».", "Cancelando… se para al acabar «c»."))
c("cancelando una carpeta nueva nombra la carpeta",
  gestion.cancelando_de(n1, 0), "Cancelando… se para al acabar «nueva».")

# --- resultado_de ----------------------------------------------------------------------
OK = {"success": True}


def mal(texto):
    return {"success": False, "error": texto}


def res(op, estados, cancelado=False):
    r = gestion.resultado_de(op, estados, {}, cancelado)
    return (r.texto, r.tono, r.reintentar)


b1 = Op(gestion.BORRAR, "nas", "/datos", (E("x", True),))
m1 = Op(gestion.MOVER, "nas", "/datos", (E("x", True),), destino="/otra")
c("borrar uno, bien", res(b1, [OK]), ("Borrado «x».", "ok", False))
c("borrar tres, bien", res(b3, [OK, OK, OK]), ("Borrados 3.", "ok", False))
c("mover uno, bien", res(m1, [OK]), ("Movido «x» a /otra.", "ok", False))
c("mover dos, bien", res(m2, [OK, OK]), ("Movidos 2 a /otra.", "ok", False))
c("renombrar, bien", res(r1, [OK]), ("Renombrado a «b».", "ok", False))
c("crear, bien", res(n1, [OK]), ("Creada «nueva».", "ok", False))
c("un fallo en medio por 404: se cuentan los que fueron bien",
  res(b3, [OK, mal("object not found"), OK]),
  ("Borrados 2 de 3: «b» no se pudo: ya no estaba", "aviso", False))
c("  el 404 también si el texto no trae código", res(b3, [mal("directory not found"), OK, OK])[0],
  "Borrados 2 de 3: «a» no se pudo: ya no estaba")
c("un fallo al mover varios",
  res(m2, [mal("boom"), OK]),
  ("Movidos 1 de 2: «a» no se pudo: rclone dice: boom", "aviso", False))
c("un permiso al borrar uno solo: la forma de un elemento",
  res(b1, [mal("permission denied")]),
  ("No se pudo borrar «x»: No tienes permiso para borrar en /datos.", "aviso", False))
c("un fallo al borrar uno solo, desconocido",
  res(b1, [mal("algo raro")])[0], "No se pudo borrar «x»: rclone dice: algo raro")
c("mover uno solo que falla",
  res(m1, [mal("object not found")])[0], "No se pudo mover «x»: ya no estaba")
c("  y por permisos (la carpeta es la de origen)",
  res(m1, [mal("SSH_FX_PERMISSION_DENIED")])[0],
  "No se pudo mover «x»: No tienes permiso para mover en /datos.")
c("renombrar con permisos denegados",
  res(r1, [mal("permission denied")])[0],
  "No se pudo renombrar «a»: No tienes permiso para renombrar en /datos.")
c("renombrar que falla",
  res(r1, [mal("boom")]), ("No se pudo renombrar «a»: rclone dice: boom", "aviso", False))
c("crear que falla por permisos",
  res(n1, [mal("permission denied")])[0],
  "No se pudo crear «nueva»: No tienes permiso para crear en /datos.")
c("un fallo sin texto se cita igual",
  res(b1, [{"success": False}])[0].startswith("No se pudo borrar «x»: "), True)
c("cancelado tras el primero de tres",
  res(b3, [OK], cancelado=True), ("Cancelado: borrados 1 de 3", "aviso", False))
c("cancelado al mover",
  res(m2, [OK], cancelado=True)[0], "Cancelado: movidos 1 de 2")
c("cancelado con el último lanzado en error: puede haber quedado a medias",
  res(b3, [OK, mal("context canceled")], cancelado=True)[0],
  "Cancelado: borrados 1 de 3 · «b» puede haber quedado a medias")
c("  el primero a medias",
  res(m2, [mal("context canceled")], cancelado=True)[0],
  "Cancelado: movidos 0 de 2 · «a» puede haber quedado a medias")
c("cancelado sin haber lanzado nada",
  res(b3, [], cancelado=True)[0], "Cancelado: borrados 0 de 3")
c("cancelar manda aunque el último fuera bien y no fueran todos",
  res(b3, [OK, OK], cancelado=True)[0], "Cancelado: borrados 2 de 3")
c("un renombrado que acabó antes de cancelar sigue siendo bien hecho",
  res(r1, [OK], cancelado=True), ("Renombrado a «b».", "ok", False))
c("nunca se ofrece Reintentar",
  any(res(op, st, cn)[2] for op, st, cn in (
      (b3, [OK, mal("x"), OK], False), (m2, [mal("x")], True), (r1, [mal("x")], False),
      (n1, [mal("x")], False), (b1, [mal("permission denied")], False))), False)


sys.exit(c.report())
