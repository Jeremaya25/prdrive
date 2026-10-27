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

sys.exit(c.report())
