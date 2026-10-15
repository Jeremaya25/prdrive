#!/usr/bin/env python3
"""Las explicaciones de la guía de flags de rclone, escritas a mano y sin Tkinter.

Es el catálogo explicado de #126: datos del proyecto, no código. Cubre los flags que
prdrive ya pone o reserva (`model.BASE_FLAGS`, los de cada `Mode`, `FLAGS_RESERVADOS`,
`FLAGS_ESCRIBEN` y lo que `orden.flags_de_la_pasada()` añade) y los de borrado,
comparación, filtrado, tiempos y concurrencia. El resto de flags de la rclone fijada
sale en la guía con la ayuda corta de rclone, en inglés y marcada como tal
(`ui/flags_guia.py`).

**Aquí solo va lo que rclone no puede decir.** Quién pone un flag, con qué valor y con
qué motivo se lee del modelo (`flags_guia`), no se repite: un valor que cambia en
`model.py` cambia en la guía sin tocar este fichero, y un flag nuevo de prdrive sin
entrada aquí hace fallar `tests/test_flags_guia.py`. Lo que se afirma de rclone está
medido con la v1.75.2 sobre carpetas locales; si una versión nueva lo cambia, se
corrige aquí.

Los textos son para quien usa el dispositivo: sin jerga, de tú, con el efecto práctico.
Un flag nuevo se añade escribiéndolo en el TOML; esta guía ayuda y nunca restringe.
"""

from __future__ import annotations

from typing import NamedTuple

RIESGO_LEE = "lee"
"""Riesgo: no cambia ningún fichero por sí solo (ajusta cómo se mira, cuánto va a la vez…)."""
RIESGO_NOMBRES = "nombres"
"""Riesgo: cambia nombres de ficheros o los aparta con otro nombre."""
RIESGO_BORRA = "borra"
"""Riesgo: borra o reescribe ficheros, o es el freno que los protege."""
RIESGOS = (RIESGO_LEE, RIESGO_NOMBRES, RIESGO_BORRA)
"""Los riesgos, del menos al más serio."""

TEMA_PRDRIVE = "prdrive"
"""Tema: lo que prdrive pone o reserva en cada pasada."""
TEMA_BORRADO = "borrado"
"""Tema: borrados y sobrescrituras, y lo que las frena."""
TEMA_COMPARAR = "comparar"
"""Tema: cómo decide rclone qué ha cambiado."""
TEMA_FILTRADO = "filtrado"
"""Tema: qué ficheros entran en la pasada."""
TEMA_TIEMPOS = "tiempos"
"""Tema: esperas, reintentos y duración."""
TEMA_CONCURRENCIA = "concurrencia"
"""Tema: cuánto va a la vez y a qué velocidad."""
TEMA_OTROS = "otros"
"""Tema: los flags sin explicación propia (el resto del fichero generado)."""
TEMAS = (TEMA_PRDRIVE, TEMA_BORRADO, TEMA_COMPARAR, TEMA_FILTRADO, TEMA_TIEMPOS,
         TEMA_CONCURRENCIA, TEMA_OTROS)
"""Los temas, en el orden en que salen en la guía."""

TODOS = ("bisync", "up", "down", "up-mirror", "down-mirror")
"""Todos los modos de una pareja (`model.MODES`)."""
BISYNC = ("bisync",)
ESPEJO = ("up-mirror", "down-mirror")
SINCRONIZA = ("bisync", "up-mirror", "down-mirror")
SIN_BISYNC = ("up", "down", "up-mirror", "down-mirror")

_FILTRO_EN_BISYNC = (" En una pareja bisync no lo uses: bisync no vigila los cambios de este "
                     "flag entre una pasada y otra, y lo que deja de cumplirlo le parece "
                     "borrado (medido: lo cuenta como «File was deleted» y el resultado no "
                     "está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, "
                     "que prdrive sí vigila.")


class Entrada(NamedTuple):
    """La explicación de un flag.

    Args:
        nombre: Sin guiones y con `-` (`max-delete`), como lo ve rclone.
        tema: Uno de `TEMAS`. Lo que prdrive pone o reserva va en `TEMA_PRDRIVE` y solo eso.
        riesgo: Uno de `RIESGOS`.
        titulo: Una línea que dice de qué va, para la lista.
        para_que: Para qué sirve, en una frase.
        efecto: Qué hace en la práctica y qué cuidado pide.
        ejemplo: Cómo se escribe en el cuadro de flags (TOML, y tiene que valer ahí). En un
            flag que el config no admite no se escribe: dice qué usar en su lugar.
        modos: Los modos donde sirve de verdad (`TODOS`, `BISYNC`…), no solo donde rclone
            lo acepta.
        buscar: Palabras con las que una persona preguntaría por él («ignorar temporales»),
            para la búsqueda por efecto. Sin tildes da igual.
        prdrive: Solo cuando el valor de prdrive NO está en el modelo (`conflict-loser`,
            que se pone al guardar versiones). El resto se lee de `model`.
    """
    nombre: str
    tema: str
    riesgo: str
    titulo: str
    para_que: str
    efecto: str
    ejemplo: str
    modos: tuple[str, ...] = TODOS
    buscar: str = ""
    prdrive: str = ""


def _e(nombre: str, tema: str, riesgo: str, titulo: str, para_que: str, efecto: str,
       ejemplo: str, modos: tuple[str, ...] = TODOS, buscar: str = "",
       prdrive: str = "") -> Entrada:
    """Hace una `Entrada` con los campos en el orden en que se leen."""
    return Entrada(nombre, tema, riesgo, titulo, para_que, efecto, ejemplo, modos, buscar,
                   prdrive)


ENTRADAS: tuple[Entrada, ...] = (
    # ------------------------------------------------------------------ lo que pone prdrive
    _e("verbose", TEMA_PRDRIVE, RIESGO_LEE,
       "Cuánto cuenta rclone en el log de cada pasada",
       "Para que el log diga qué ha copiado, movido o borrado, fichero a fichero.",
       "Con él puedes ver después qué hizo una pasada y por qué. Quitarlo deja el log casi "
       "vacío: la pasada va igual, pero no sabrás qué tocó.",
       "verbose = false",
       buscar="log registro detalle contar ruido silencio mensajes salida"),
    _e("create-empty-src-dirs", TEMA_PRDRIVE, RIESGO_BORRA,
       "Si las carpetas vacías también se copian y se borran",
       "Para que una carpeta vacía creada o borrada en un lado se cree o se borre en "
       "el otro.",
       "Solo afecta a carpetas vacías, nunca a ficheros. Quitarlo hace que las carpetas "
       "vacías se queden como están; con --remove-empty-dirs no puede ir.",
       "create-empty-src-dirs = false",
       buscar="carpetas vacias directorios borrar crear"),
    _e("stats", TEMA_PRDRIVE, RIESGO_LEE,
       "Cada cuánto escribe rclone cuánto lleva",
       "Para que el log lleve una línea de progreso cada pocos segundos.",
       "De ahí saca prdrive el progreso en vivo de la ventana. Con \"0\" rclone no escribe "
       "progreso y la ventana no lo muestra; la pasada va igual.",
       'stats = "5s"',
       buscar="progreso tiempo intervalo cada cuanto lleva avance segundos"),
    _e("stats-one-line", TEMA_PRDRIVE, RIESGO_LEE,
       "Que el progreso ocupe una sola línea",
       "Para que cada aviso de progreso quepa en una línea que prdrive pueda leer.",
       "Sin él, rclone escribe un bloque de varias líneas y la ventana no puede resumir el "
       "progreso en una sola.",
       "stats-one-line = false",
       buscar="progreso linea avance"),
    _e("conflict-resolve", TEMA_PRDRIVE, RIESGO_NOMBRES,
       "Qué versión gana cuando un fichero cambia en los dos lados",
       "Decidir qué hacer cuando bisync encuentra el mismo fichero cambiado en "
       "el dispositivo y en el remoto.",
       "Con «newer» gana la versión más reciente y la otra se aparta con otro nombre (mira "
       "--conflict-suffix); con «none» no se resuelve solo y el fichero queda como conflicto.",
       'conflict-resolve = "larger"',
       modos=BISYNC,
       buscar="conflicto cambia fichero dos lados mismo tiempo gana version mas nueva "
              "reciente elegir cual se queda"),
    _e("conflict-suffix", TEMA_PRDRIVE, RIESGO_NOMBRES,
       "Cómo se llama la copia que pierde un conflicto",
       "Para que el nombre de la copia apartada diga de qué lado venía.",
       "Con dos textos separados por una coma, el primero es para el dispositivo y el "
       "segundo para el remoto. Cambiarlo no borra nada, pero los conflictos de antes "
       "conservan el nombre que tenían.",
       'conflict-suffix = "conflicto-dispositivo,conflicto-remoto"',
       modos=BISYNC,
       buscar="conflicto nombre copia renombrar sufijo apartar pierde"),
    _e("conflict-loser", TEMA_PRDRIVE, RIESGO_BORRA,
       "Qué pasa con la copia que pierde un conflicto",
       "Elegir si la copia perdedora se guarda con otro nombre («num», "
       "«pathname») o se borra («delete»).",
       "Con «delete» la copia perdedora no se queda en la carpeta: sale por las versiones "
       "anteriores si la pareja las guarda, y si no, se pierde. Con «num» se queda con un "
       "número.",
       'conflict-loser = "num"',
       modos=BISYNC,
       prdrive="«delete» cuando la pareja guarda versiones (la casilla «Guardar versiones»); "
               "si no, rclone usa «num».",
       buscar="conflicto perdedor borrar copia pierde versiones anteriores borrados"),
    _e("max-delete", TEMA_PRDRIVE, RIESGO_BORRA,
       "El freno de los borrados",
       "Para que una pasada se pare en vez de borrar de golpe lo que no debe, como "
       "cuando una carpeta aparece vacía porque la unidad no estaba montada.",
       "En bisync no es una cuenta de ficheros sino un porcentaje de lo que había en la "
       "pasada anterior; en los espejo sí es una cuenta de ficheros. Subirlo mucho o "
       "quitarlo deja que una pasada borre de golpe. Si el freno salta, la pasada se para "
       "y lo dice.",
       "max-delete = 10",
       modos=SINCRONIZA,
       buscar="borrados borrar freno limite proteger demasiados muchos seguridad parar "
              "unidad vacia desmontada"),
    _e("resilient", TEMA_PRDRIVE, RIESGO_LEE,
       "Reintentar tras un error pequeño sin rehacer la referencia",
       "Para que un error leve (un fichero que no se pudo leer) no obligue a "
       "resincronizar la pareja entera.",
       "Sin él, ese error pide un --resync en la pasada siguiente. Con él, la próxima "
       "pasada lo vuelve a intentar sola.",
       "resilient = false",
       modos=BISYNC,
       buscar="reintentar error resync referencia fallo leve"),
    _e("recover", TEMA_PRDRIVE, RIESGO_LEE,
       "Recuperarse solo de una pasada cortada",
       "Para que, si una pasada se interrumpe (se tira de la unidad, se apaga el "
       "equipo), la siguiente continúe sin pedir --resync.",
       "Quitarlo hace que una interrupción brusca pida resincronizar la pareja.",
       "recover = false",
       modos=BISYNC,
       buscar="interrumpir cortar apagar recuperar resync unidad quitada"),
    _e("max-lock", TEMA_PRDRIVE, RIESGO_LEE,
       "Cuándo caduca el candado de una pasada muerta",
       "Para que el candado que deja una pasada que murió a medias no bloquee las "
       "siguientes para siempre.",
       "Con «2m» un candado de más de dos minutos se da por caducado. El mínimo es 2m; "
       "con 0 el candado no caduca nunca.",
       'max-lock = "5m"',
       modos=BISYNC,
       buscar="candado bloqueo lock tiempo caduca bloqueada pasada muerta espera"),
    _e("config", TEMA_PRDRIVE, RIESGO_LEE,
       "El fichero de conexiones de rclone",
       "Para que rclone use el rclone.conf del dispositivo y no el del equipo donde "
       "esté enchufado.",
       "Lo pone prdrive en cada pasada y no se puede cambiar: cambiarlo sacaría a rclone "
       "de las conexiones del dispositivo.",
       "No se escribe: es el rclone.conf del dispositivo, el mismo para todas las parejas.",
       buscar="conexion remoto configuracion rclone.conf contrasenas"),
    _e("log-file", TEMA_PRDRIVE, RIESGO_LEE,
       "Dónde escribe rclone el log de la pasada",
       "Para que cada pasada deje su propio log, que luego se puede abrir y guardar.",
       "Lo pone prdrive y no se puede cambiar: es lo que hace que cada pasada tenga su log "
       "y que el progreso en vivo funcione.",
       "No se escribe. Los logs se abren desde «Abrir los logs».",
       buscar="log registro guardar fichero pasada"),
    _e("dry-run", TEMA_PRDRIVE, RIESGO_LEE,
       "Probar sin cambiar nada",
       "Ver qué haría una pasada sin copiar, mover ni borrar nada.",
       "Lo pone prdrive cuando usas «Simular», para que valga en todas las parejas y "
       "modos. Pruébalo siempre antes en una pareja *-mirror, que borra en el otro lado.",
       "No se escribe. Se usa con el botón «Simular» de la pantalla de parejas.",
       buscar="simular probar ensayo sin cambiar nada antes seguro prueba"),
    _e("workdir", TEMA_PRDRIVE, RIESGO_LEE,
       "Dónde guarda bisync su referencia",
       "Para que bisync guarde en state/<pareja>/ la lista de lo que había en la "
       "última pasada.",
       "Lo pone prdrive y no se puede cambiar: apuntarlo a otra carpeta haría que bisync "
       "comparase con una referencia que no es la de esta pareja.",
       "No se escribe.",
       modos=BISYNC,
       buscar="referencia baseline estado carpeta listas bisync"),
    _e("resync", TEMA_PRDRIVE, RIESGO_BORRA,
       "Rehacer la referencia de bisync",
       "Para que bisync empiece de cero: mira los dos lados, copia lo que falta en "
       "cada uno y apunta cómo están.",
       "Reescribe lo que sea distinto: gana un lado (por defecto el dispositivo). Lo "
       "pone prdrive solo cuando tú lo pides y te pregunta antes; escribirlo aquí lo "
       "forzaría en cada pasada.",
       "No se escribe. Se pide desde la ventana cuando una pareja lo necesita.",
       modos=BISYNC,
       buscar="resincronizar rehacer referencia empezar de cero reescribir"),
    _e("backup-dir", TEMA_PRDRIVE, RIESGO_NOMBRES,
       "Carpeta donde apartar lo que se cambia o borra",
       "Guardar en otra carpeta la versión anterior de lo que una pasada cambia "
       "o borra.",
       "En bisync prdrive no usa este flag sino --backup-dir1 y --backup-dir2, uno por "
       "lado, y solo con la casilla «Guardar versiones».",
       "No se escribe. Marca «Guardar versiones» en la pareja.",
       buscar="versiones anteriores copia seguridad apartar guardar recuperar borrados"),
    _e("backup-dir1", TEMA_PRDRIVE, RIESGO_NOMBRES,
       "Carpeta de versiones del lado del dispositivo",
       "Apartar en <pareja>/.prversions lo que bisync cambia o borra en el "
       "dispositivo.",
       "Lo pone prdrive cuando la pareja guarda versiones y no se puede cambiar.",
       "No se escribe. Marca «Guardar versiones» en la pareja.",
       modos=BISYNC,
       buscar="versiones anteriores copia seguridad apartar guardar recuperar borrados "
              "prversions"),
    _e("backup-dir2", TEMA_PRDRIVE, RIESGO_NOMBRES,
       "Carpeta de versiones del lado del remoto",
       "Apartar en <pareja>/.prversions lo que bisync cambia o borra en el "
       "remoto.",
       "Lo pone prdrive cuando la pareja guarda versiones y no se puede cambiar.",
       "No se escribe. Marca «Guardar versiones» en la pareja.",
       modos=BISYNC,
       buscar="versiones anteriores copia seguridad apartar guardar recuperar borrados "
              "prversions"),
    _e("suffix", TEMA_PRDRIVE, RIESGO_NOMBRES,
       "La marca de fecha de lo que se aparta",
       "Para que cada fichero apartado lleve la fecha y la hora de la pasada que lo "
       "apartó.",
       "Lo pone prdrive en cada pasada, porque cada una tiene la suya; no se puede "
       "escribir aquí.",
       "No se escribe.",
       buscar="versiones sufijo fecha hora marca apartar"),
    _e("suffix-keep-extension", TEMA_PRDRIVE, RIESGO_NOMBRES,
       "Que lo apartado conserve su extensión",
       "Para que una versión guardada siga acabando en .docx o .jpg, y se abra con "
       "su programa.",
       "Lo pone prdrive junto con la marca de fecha y no se puede cambiar.",
       "No se escribe.",
       buscar="versiones extension nombre apartar"),
    _e("filters-file", TEMA_PRDRIVE, RIESGO_LEE,
       "El fichero con los patrones de «Incluir» y «Excluir»",
       "Para que bisync lea de un fichero los patrones de la pareja y note si "
       "cambian.",
       "Lo hace prdrive a partir de los cuadros «Incluir» y «Excluir» de la pareja. "
       "Cambiar los patrones de una pareja bisync pide un --resync.",
       "No se escribe. Usa los cuadros «Incluir» y «Excluir» de la pareja.",
       modos=BISYNC,
       buscar="filtros patrones incluir excluir ignorar ficheros"),
    _e("filter", TEMA_PRDRIVE, RIESGO_LEE,
       "Una regla de filtrado suelta",
       "En rclone, añadir una regla «+» o «-» a mano.",
       "No se admite aquí: mezclada con los cuadros «Incluir» y «Excluir» rompe el filtrado "
       "de la pareja.",
       "No se escribe. Usa los cuadros «Incluir» y «Excluir» de la pareja.",
       buscar="filtros regla incluir excluir ignorar ficheros"),
    _e("filter-from", TEMA_PRDRIVE, RIESGO_LEE,
       "Leer las reglas de filtrado de un fichero",
       "En rclone, cargar reglas de filtrado de un fichero de texto.",
       "No se admite aquí: mezclado con los cuadros «Incluir» y «Excluir» rompe el "
       "filtrado de la pareja.",
       "No se escribe. Usa los cuadros «Incluir» y «Excluir» de la pareja.",
       buscar="filtros reglas fichero incluir excluir ignorar ficheros"),
    _e("include", TEMA_PRDRIVE, RIESGO_LEE,
       "Copiar solo los ficheros que encajen",
       "Para que la pareja copie únicamente lo que encaje con un patrón (por "
       "ejemplo *.docx).",
       "Lo pone prdrive a partir del cuadro «Incluir» de la pareja, y no se puede escribir "
       "aquí. Con «Incluir» lleno, todo lo demás se queda fuera.",
       "No se escribe. Pon el patrón en el cuadro «Incluir» de la pareja, como *.docx.",
       buscar="incluir solo copiar patron filtros ficheros elegir"),
    _e("exclude", TEMA_PRDRIVE, RIESGO_LEE,
       "Dejar fuera ficheros que encajen",
       "Ignorar ficheros por su nombre: los temporales, las cachés, lo que no "
       "quieres llevar.",
       "Lo pone prdrive a partir del cuadro «Excluir» de la pareja, y no se puede escribir "
       "aquí. Un patrón por línea; lo que encaja se queda fuera de la pasada.",
       "No se escribe. En el cuadro «Excluir» de la pareja, una línea por patrón: *.tmp, "
       "~$*, .~lock.*#, Thumbs.db.",
       buscar="ignorar ficheros temporales tmp omitir saltar excluir no copiar filtros "
              "cache papelera basura"),
    _e("cpuprofile", TEMA_PRDRIVE, RIESGO_BORRA,
       "Volcar un perfil del procesador a un fichero",
       "Guardar cuánto procesador gasta cada parte de rclone; es para quien depura rclone.",
       "No se admite en el config: escribe (o vacía) el fichero que se le diga, y el "
       "config viaja con el dispositivo a otros equipos.",
       "No se escribe.",
       buscar="perfil depurar escribir fichero equipo"),
    _e("memprofile", TEMA_PRDRIVE, RIESGO_BORRA,
       "Volcar un perfil de memoria a un fichero",
       "Guardar cuánta memoria gasta cada parte de rclone; es para quien depura rclone.",
       "No se admite en el config: escribe (o vacía) el fichero que se le diga, y el "
       "config viaja con el dispositivo a otros equipos.",
       "No se escribe.",
       buscar="perfil depurar memoria escribir fichero equipo"),
    _e("password-command", TEMA_PRDRIVE, RIESGO_LEE,
       "Un programa que da la contraseña de rclone",
       "En rclone, pedirle a un programa la contraseña del rclone.conf cifrado.",
       "No se admite en el config: haría correr ese programa en el equipo donde enchufes "
       "la unidad.",
       "No se escribe.",
       buscar="contrasena programa ejecutar comando seguridad"),
    _e("metadata-mapper", TEMA_PRDRIVE, RIESGO_LEE,
       "Un programa que transforma los metadatos al subir",
       "En rclone, pasar los metadatos de cada fichero por un programa antes de subirlos.",
       "No se admite en el config: haría correr ese programa en el equipo donde enchufes "
       "la unidad.",
       "No se escribe.",
       buscar="metadatos programa ejecutar comando seguridad"),

    # ------------------------------------------------------------------ borrados y sobrescrituras
    _e("delete-after", TEMA_BORRADO, RIESGO_BORRA,
       "Borrar del destino al acabar de copiar",
       "Para que, al sincronizar, lo que ya no está en el origen se borre del destino "
       "cuando todo lo demás ya se ha copiado.",
       "Es lo que hace rclone si no le dices otra cosa. Es lo más seguro de los tres "
       "--delete-*: si algo falla a medias, aún tienes todo en el destino. Solo vale donde "
       "se sincroniza (*-mirror). Pruébalo antes con «Simular».",
       "delete-after = true",
       modos=ESPEJO,
       buscar="borrados borrar eliminar quitar destino sobra espejo cuando orden "
              "al final despues"),
    _e("delete-before", TEMA_BORRADO, RIESGO_BORRA,
       "Borrar del destino antes de copiar",
       "Liberar sitio en el destino antes de empezar a copiar.",
       "Borra primero y copia después: si la copia falla, ya has perdido lo borrado. No se "
       "puede combinar con --delete-during ni --delete-after. Solo vale en *-mirror. "
       "Pruébalo antes con «Simular».",
       "delete-before = true",
       modos=ESPEJO,
       buscar="borrados borrar eliminar quitar destino sobra espejo antes primero "
              "liberar espacio sitio"),
    _e("delete-during", TEMA_BORRADO, RIESGO_BORRA,
       "Borrar del destino mientras se copia",
       "Ir borrando lo que sobra a la vez que se copia, en una sola vuelta.",
       "Es más rápido que los otros dos, pero mezcla borrar y copiar. No se puede combinar "
       "con --delete-before ni --delete-after. Solo vale en *-mirror. Pruébalo antes con "
       "«Simular».",
       "delete-during = true",
       modos=ESPEJO,
       buscar="borrados borrar eliminar quitar destino sobra espejo durante mientras "
              "rapido"),
    _e("delete-excluded", TEMA_BORRADO, RIESGO_BORRA,
       "Borrar también lo que los filtros dejan fuera",
       "Para que, al sincronizar, se borre del destino lo que tus patrones de "
       "«Excluir» dejan fuera.",
       "Sin él, lo excluido que ya está en el destino se queda ahí. Con él se borra: "
       "añadir un patrón de «Excluir» puede borrar muchos ficheros. Solo vale en "
       "*-mirror. Pruébalo antes con «Simular».",
       "delete-excluded = true",
       modos=ESPEJO,
       buscar="borrados borrar eliminar excluir excluidos filtros destino limpiar"),
    _e("max-delete-size", TEMA_BORRADO, RIESGO_BORRA,
       "El freno de los borrados, por tamaño",
       "Para que una pasada se pare si fuera a borrar más de un tamaño total.",
       "Es como --max-delete pero cuenta bytes, no ficheros: con «1G», una pasada que "
       "fuera a borrar más de 1 GB se para. Quitarlo (\"off\") deja el freno solo en "
       "--max-delete.",
       'max-delete-size = "5G"',
       modos=ESPEJO,
       buscar="borrados borrar freno limite tamano proteger demasiados seguridad parar "
              "gigas"),
    _e("ignore-errors", TEMA_BORRADO, RIESGO_BORRA,
       "Seguir borrando aunque haya errores de lectura",
       "Para que un espejo siga borrando del destino aunque no haya podido leer "
       "parte del origen.",
       "Es peligroso: un origen que no se ha leído entero parece vacío, y lo que no se "
       "ve se borra del destino. Por defecto rclone se niega a borrar si hubo errores. "
       "Solo vale en *-mirror.",
       "ignore-errors = true",
       modos=ESPEJO,
       buscar="borrados borrar errores lectura peligro seguir forzar"),
    _e("force", TEMA_BORRADO, RIESGO_BORRA,
       "Saltarse el freno de los borrados",
       "Para que bisync haga una pasada aunque vaya a borrar más de lo que permite "
       "--max-delete.",
       "Quita justo la protección que evita que una unidad vacía arrase el otro lado. "
       "Úsalo una sola vez, sabiendo qué se va a borrar, y no lo dejes puesto.",
       "force = true",
       modos=BISYNC,
       buscar="borrados borrar freno saltar forzar limite peligro seguridad"),
    _e("remove-empty-dirs", TEMA_BORRADO, RIESGO_BORRA,
       "Quitar todas las carpetas vacías al final",
       "Dejar limpias las carpetas que se quedan vacías tras la pasada.",
       "Borra cualquier carpeta vacía de los dos lados, también las que nunca tuvieron "
       "nada. No es compatible con --create-empty-src-dirs, que prdrive pone siempre.",
       "remove-empty-dirs = true",
       modos=BISYNC,
       buscar="borrados borrar carpetas vacias limpiar directorios"),
    _e("resync-mode", TEMA_BORRADO, RIESGO_BORRA,
       "Qué lado gana al rehacer la referencia",
       "Elegir qué versión se queda cuando un --resync encuentra el mismo "
       "fichero distinto en los dos lados.",
       "La otra versión se sobrescribe. Con «path1» gana el dispositivo, con «path2» el "
       "remoto; «newer», «older», «larger» y «smaller» deciden por fecha o tamaño. Solo "
       "se aplica cuando se pide un --resync desde la ventana.",
       'resync-mode = "newer"',
       modos=BISYNC,
       buscar="resync rehacer referencia gana lado sobrescribir reescribir elegir"),
    _e("track-renames", TEMA_BORRADO, RIESGO_NOMBRES,
       "Mover en lugar de copiar y borrar un fichero renombrado",
       "Para que renombrar un fichero en el origen lo mueva en el destino, sin "
       "volver a subirlo.",
       "Ahorra copiar ficheros grandes que solo han cambiado de nombre. Medido: sin él, un "
       "renombrado se copia entero con el nombre nuevo y se borra el viejo. Solo vale en "
       "*-mirror.",
       "track-renames = true",
       modos=ESPEJO,
       buscar="renombrar mover nombre cambiar nombre ahorrar subir copiar de nuevo "
              "ficheros grandes"),
    _e("fix-case", TEMA_BORRADO, RIESGO_NOMBRES,
       "Igualar las mayúsculas de los nombres del destino",
       "Corregir en el destino un nombre que solo se diferencia en mayúsculas "
       "y minúsculas.",
       "Renombra ficheros del destino para que se llamen igual que en el origen. Útil si "
       "el destino no distingue mayúsculas. Solo vale en *-mirror.",
       "fix-case = true",
       modos=ESPEJO,
       buscar="mayusculas minusculas nombre renombrar igualar"),
    _e("name-transform", TEMA_BORRADO, RIESGO_NOMBRES,
       "Cambiar los nombres de los ficheros al copiarlos",
       "Pasar los nombres a minúsculas, añadirles algo o limpiar caracteres "
       "al copiar.",
       "Es una transformación de una sola dirección: el fichero llega con otro nombre. "
       "Medido: «all,lowercase» pasa a minúsculas y «file,suffix=_copia» añade el texto "
       "tras la extensión. Se pueden poner varias.",
       'name-transform = ["all,lowercase"]',
       modos=SIN_BISYNC,
       buscar="nombre renombrar cambiar minusculas mayusculas transformar caracteres"),
    _e("inplace", TEMA_BORRADO, RIESGO_BORRA,
       "Escribir directamente sobre el fichero de destino",
       "No usar un fichero temporal al copiar, cuando el destino no deja "
       "renombrar.",
       "Si la copia se corta a mitad, el fichero de destino se queda a medias y el "
       "original que había se ha perdido. Sin él, rclone escribe un temporal y lo "
       "renombra al acabar.",
       "inplace = true",
       buscar="sobrescribir escribir encima temporal cortar a medias destino"),
    _e("immutable", TEMA_BORRADO, RIESGO_LEE,
       "No dejar que un fichero ya copiado cambie",
       "Proteger lo que ya está en el destino: si el origen es distinto, "
       "falla en vez de sobrescribir.",
       "Medido: con el fichero cambiado en el origen, rclone da error y deja intacto el "
       "del destino. Los ficheros nuevos se copian. Útil en una copia de seguridad que "
       "no debe cambiar.",
       "immutable = true",
       modos=SIN_BISYNC,
       buscar="proteger no sobrescribir cambiar modificado copia seguridad archivo "
              "intocable"),
    _e("no-check-dest", TEMA_BORRADO, RIESGO_BORRA,
       "Copiar sin mirar qué hay en el destino",
       "Saltarse la comparación y copiarlo todo.",
       "Sobrescribe lo que haya en el destino aunque sea igual, y copia siempre entero. "
       "Solo tiene sentido en una carpeta de destino vacía o nueva.",
       "no-check-dest = true",
       modos=SIN_BISYNC,
       buscar="sobrescribir copiar todo sin comparar destino"),
    _e("refresh-times", TEMA_BORRADO, RIESGO_BORRA,
       "Reescribir las fechas de los ficheros del remoto",
       "Poner la fecha de modificación correcta en ficheros del remoto que la "
       "tienen mal.",
       "Cambia metadatos del remoto sin copiar el contenido. Puede tardar si hay muchos "
       "ficheros y no todos los remotos lo admiten.",
       "refresh-times = true",
       modos=SIN_BISYNC,
       buscar="fechas modificacion reescribir remoto corregir"),
    _e("check-access", TEMA_BORRADO, RIESGO_LEE,
       "No sincronizar si falta un fichero de prueba",
       "Para que bisync se pare si en los dos lados no encuentra un fichero de "
       "prueba (RCLONE_TEST), como cuando una unidad no está montada.",
       "Medido: sin los ficheros de prueba, bisync aborta con «Access test failed» y pide "
       "--resync. Pon un fichero llamado RCLONE_TEST en cada lado (o cambia el nombre "
       "con --check-filename) antes de activarlo.",
       "check-access = true",
       modos=BISYNC,
       buscar="proteger seguridad unidad montada desmontada vacia fichero prueba borrados "
              "parar"),
    _e("check-filename", TEMA_BORRADO, RIESGO_LEE,
       "El nombre del fichero de prueba de --check-access",
       "Cambiar el nombre del fichero que bisync busca en los dos lados.",
       "Solo tiene efecto con --check-access. Por defecto el fichero se llama RCLONE_TEST.",
       'check-filename = ".prdrive-ok"',
       modos=BISYNC,
       buscar="proteger fichero prueba nombre unidad montada"),

    # ------------------------------------------------------------------ cómo decide qué ha cambiado
    _e("size-only", TEMA_COMPARAR, RIESGO_LEE,
       "Comparar solo por tamaño",
       "Decidir que un fichero ha cambiado solo si su tamaño es otro, sin mirar "
       "la fecha ni el contenido.",
       "Es más rápido, pero un fichero que cambia sin cambiar de tamaño no se copia. "
       "Medido: con el mismo tamaño y otro contenido, no se copia. Con --checksum se "
       "pisan: gana este.",
       "size-only = true",
       modos=SIN_BISYNC,
       buscar="comparar tamano rapido cambiado fecha ignorar"),
    _e("checksum", TEMA_COMPARAR, RIESGO_LEE,
       "Comparar por el contenido, no por la fecha",
       "Decidir qué ha cambiado mirando una firma del contenido (checksum), no "
       "la fecha.",
       "Es más seguro cuando las fechas no son fiables, pero tiene que leer los ficheros "
       "(o pedir la firma al remoto) y es más lento. Medido: copia un fichero de igual "
       "tamaño y distinto contenido.",
       "checksum = true",
       modos=SIN_BISYNC,
       buscar="comparar contenido firma hash lento seguro fechas fiables cambiado"),
    _e("ignore-times", TEMA_COMPARAR, RIESGO_BORRA,
       "Volver a copiar todo, aunque ya esté igual",
       "Forzar que todos los ficheros se copien de nuevo, sin comparar nada.",
       "Medido: reemplaza incluso lo que es idéntico. Tarda lo que tarde copiarlo todo. "
       "Con --ignore-existing se pisan: gana --ignore-existing y lo que ya existe no se "
       "toca.",
       "ignore-times = true",
       modos=SIN_BISYNC,
       buscar="copiar todo de nuevo forzar sobrescribir fechas comparar"),
    _e("update", TEMA_COMPARAR, RIESGO_LEE,
       "No pisar lo que es más nuevo en el destino",
       "Para que un fichero del origen no sobrescriba otro del destino que es más "
       "reciente.",
       "Medido: si el del destino tiene fecha más nueva, se deja. Protege cambios hechos "
       "directamente en el destino.",
       "update = true",
       modos=SIN_BISYNC,
       buscar="no sobrescribir mas nuevo reciente destino proteger fecha"),
    _e("ignore-existing", TEMA_COMPARAR, RIESGO_LEE,
       "No tocar lo que ya existe en el destino",
       "Copiar solo ficheros nuevos y no actualizar nunca los que ya están.",
       "Medido: un fichero cambiado en el origen no se copia si ya existe en el destino. "
       "Un archivo que solo debe crecer.",
       "ignore-existing = true",
       modos=SIN_BISYNC,
       buscar="solo nuevos no sobrescribir existente archivo no actualizar"),
    _e("ignore-size", TEMA_COMPARAR, RIESGO_LEE,
       "No mirar el tamaño al comparar",
       "Decidir qué ha cambiado solo por la fecha o la firma, sin el tamaño.",
       "Se usa con remotos que a veces dan mal el tamaño de un fichero. Un cambio de tamaño "
       "sin cambio de fecha ya no se nota.",
       "ignore-size = true",
       modos=SIN_BISYNC,
       buscar="comparar tamano ignorar cambiado fecha"),
    _e("ignore-checksum", TEMA_COMPARAR, RIESGO_LEE,
       "No comprobar la firma tras copiar",
       "Saltarse la verificación que rclone hace al terminar de copiar cada "
       "fichero.",
       "Ahorra tiempo, pero una copia corrupta ya no se detecta. Mejor déjalo como está "
       "salvo que un remoto dé firmas que no coinciden.",
       "ignore-checksum = true",
       modos=SIN_BISYNC,
       buscar="comprobar firma verificar copia corrupta saltar rapido"),
    _e("modify-window", TEMA_COMPARAR, RIESGO_LEE,
       "Cuánta diferencia de fecha se considera igual",
       "Para que dos fechas casi iguales se traten como la misma, en remotos o "
       "sistemas de ficheros que redondean.",
       "Algunos sistemas de ficheros (como FAT, que redondea a 2 segundos) y algunos remotos "
       "guardan las fechas redondeadas: con un margen (\"2s\") dejan de copiarse ficheros "
       "que solo difieren en eso. Por defecto el margen es de 1 nanosegundo. Lleva unidad "
       "obligatoria.",
       'modify-window = "2s"',
       buscar="fechas diferencia redondeo fat exfat igual tiempo margen comparar"),

    # ------------------------------------------------------------------ qué ficheros entran
    _e("exclude-from", TEMA_FILTRADO, RIESGO_LEE,
       "Dejar fuera lo que diga una lista de un fichero",
       "Ignorar ficheros con los patrones de un fichero de texto, uno por línea.",
       "Medido: con una línea «*.txt», no se copia ningún .txt. Útil para compartir la misma "
       "lista entre parejas. Una ruta relativa se cuenta desde la carpeta .prdrive del "
       "dispositivo." + _FILTRO_EN_BISYNC,
       'exclude-from = ["ignorar.txt"]',
       modos=SIN_BISYNC,
       buscar="ignorar ficheros temporales excluir lista fichero patrones omitir saltar"),
    _e("include-from", TEMA_FILTRADO, RIESGO_LEE,
       "Copiar solo lo que diga una lista de un fichero",
       "Copiar únicamente lo que encaje con los patrones de un fichero de texto.",
       "Medido: con una línea «a.txt», solo se copia a.txt. Todo lo demás se queda fuera. "
       "Una ruta relativa se cuenta desde la carpeta .prdrive del dispositivo."
       + _FILTRO_EN_BISYNC,
       'include-from = ["solo.txt"]',
       modos=SIN_BISYNC,
       buscar="incluir solo copiar lista fichero patrones elegir"),
    _e("files-from", TEMA_FILTRADO, RIESGO_LEE,
       "Copiar solo los ficheros de una lista exacta",
       "Copiar exactamente los ficheros que nombra un fichero de texto.",
       "Medido: copia solo los de la lista. Cada línea es una ruta, no un patrón. Una ruta "
       "relativa se cuenta desde la carpeta .prdrive del dispositivo." +
       _FILTRO_EN_BISYNC,
       'files-from = ["lista.txt"]',
       modos=SIN_BISYNC,
       buscar="solo copiar lista exacta fichero elegir nombrar"),
    _e("min-size", TEMA_FILTRADO, RIESGO_LEE,
       "Ignorar los ficheros pequeños",
       "Copiar solo los ficheros mayores de un tamaño.",
       "Medido: con «1k» solo pasan los de más de 1 KiB. Sin sufijo el número son KiB." +
       _FILTRO_EN_BISYNC,
       'min-size = "100k"',
       modos=SIN_BISYNC,
       buscar="ignorar ficheros pequenos tamano minimo chicos filtrar"),
    _e("max-size", TEMA_FILTRADO, RIESGO_LEE,
       "Ignorar los ficheros muy grandes",
       "No copiar los ficheros mayores de un tamaño.",
       "Medido: con «1k» solo pasan los de 1 KiB o menos. Sin sufijo el número son KiB. "
       "Útil para no llenar una unidad pequeña con vídeos u otros ficheros pesados." +
       _FILTRO_EN_BISYNC,
       'max-size = "500M"',
       modos=SIN_BISYNC,
       buscar="ignorar no copiar ficheros grandes muy pesados tamano maximo videos limite "
              "filtrar"),
    _e("min-age", TEMA_FILTRADO, RIESGO_LEE,
       "Ignorar los ficheros recién modificados",
       "Copiar solo ficheros más antiguos que un tiempo, y dejar los que se "
       "acaban de tocar.",
       "Medido: con «1d» solo pasan los modificados hace más de un día. Evita copiar un "
       "fichero que aún se está escribiendo." + _FILTRO_EN_BISYNC,
       'min-age = "1h"',
       modos=SIN_BISYNC,
       buscar="ignorar ficheros recientes nuevos antiguedad edad esperar modificado "
              "acabado de tocar filtrar"),
    _e("max-age", TEMA_FILTRADO, RIESGO_LEE,
       "Ignorar los ficheros antiguos",
       "Copiar solo ficheros modificados hace menos de un tiempo.",
       "Medido: con «1d» solo pasan los modificados en el último día. Lo antiguo se queda "
       "fuera." + _FILTRO_EN_BISYNC,
       'max-age = "30d"',
       modos=SIN_BISYNC,
       buscar="ignorar ficheros antiguos viejos edad antiguedad reciente dias filtrar"),
    _e("max-depth", TEMA_FILTRADO, RIESGO_LEE,
       "Limitar a cuántas carpetas de profundidad se baja",
       "No entrar en subcarpetas más allá de un nivel.",
       "Medido: con 1 solo pasan los ficheros de la carpeta de arriba, sin ninguna "
       "subcarpeta." + _FILTRO_EN_BISYNC,
       "max-depth = 2",
       modos=SIN_BISYNC,
       buscar="profundidad subcarpetas niveles limitar carpetas bajar"),
    _e("exclude-if-present", TEMA_FILTRADO, RIESGO_LEE,
       "Dejar fuera una carpeta si lleva un fichero marca",
       "Ignorar carpetas enteras con solo poner dentro un fichero (por ejemplo "
       ".nosync).",
       "Medido: una carpeta que contiene el fichero indicado no se copia. Cómodo para "
       "excluir una carpeta sin tocar los patrones." + _FILTRO_EN_BISYNC,
       'exclude-if-present = [".nosync"]',
       modos=SIN_BISYNC,
       buscar="ignorar carpetas excluir marca fichero nosync omitir saltar temporales "
              "proyecto"),
    _e("ignore-case", TEMA_FILTRADO, RIESGO_LEE,
       "No distinguir mayúsculas en los filtros",
       "Para que un patrón como *.tmp también encaje con MAYUS.TMP.",
       "Medido: con él, «*.tmp» excluye también MAYUS.TMP. Sin él, rclone distingue "
       "mayúsculas." + _FILTRO_EN_BISYNC,
       "ignore-case = true",
       modos=SIN_BISYNC,
       buscar="mayusculas minusculas filtros patrones ignorar"),

    # ------------------------------------------------------------------ esperas, reintentos y duración
    _e("timeout", TEMA_TIEMPOS, RIESGO_LEE,
       "Cuánto espera rclone sin recibir nada antes de rendirse",
       "Para que una conexión que se queda colgada acabe dando error en vez de "
       "esperar siempre.",
       "Por defecto son 5 minutos sin movimiento. En redes lentas o remotos que tardan, "
       "súbelo. Lleva unidad obligatoria: \"30\" a secas no vale, \"30s\" sí.",
       'timeout = "10m"',
       buscar="espera rendirse colgado conexion lenta red tiempo maximo esperar cuanto "
              "tarda"),
    _e("contimeout", TEMA_TIEMPOS, RIESGO_LEE,
       "Cuánto espera para conectar con el remoto",
       "Decidir cuánto tiempo se espera a que el remoto conteste al conectar.",
       "Por defecto 1 minuto. Con un remoto lejano o una red mala, súbelo. Lleva unidad "
       "obligatoria.",
       'contimeout = "2m"',
       buscar="conectar conexion espera tiempo remoto red lenta"),
    _e("retries", TEMA_TIEMPOS, RIESGO_LEE,
       "Cuántas veces repite una pasada que falla",
       "Para que rclone vuelva a intentar toda la operación si algo falla.",
       "Por defecto 3. Con 1 no reintenta nada. Cada reintento vuelve a mirar lo que "
       "falló, no repite lo que ya fue bien.",
       "retries = 5",
       buscar="reintentar repetir fallo intentos veces error volver a intentar"),
    _e("retries-sleep", TEMA_TIEMPOS, RIESGO_LEE,
       "Cuánto espera entre reintentos",
       "Dejar un respiro entre un intento y el siguiente.",
       "Por defecto no espera. Con un remoto que se satura, unos segundos ayudan. Lleva "
       "unidad obligatoria.",
       'retries-sleep = "10s"',
       buscar="reintentar esperar entre intentos pausa tiempo"),
    _e("low-level-retries", TEMA_TIEMPOS, RIESGO_LEE,
       "Cuántas veces repite una petición suelta que falla",
       "Para que un fallo pequeño de red no tire toda la operación.",
       "Por defecto 10. Es el nivel de abajo: reintenta cada petición, mientras que "
       "--retries reintenta toda la operación.",
       "low-level-retries = 20",
       buscar="reintentar repetir fallo red peticiones intentos veces error"),
    _e("max-duration", TEMA_TIEMPOS, RIESGO_LEE,
       "Cortar la pasada tras un tiempo",
       "Para que una pasada se pare sola pasado un tiempo, aunque quede trabajo.",
       "Lo que quede se hará en la siguiente. Útil para no ocupar la unidad ni la red más "
       "de la cuenta. Lleva unidad obligatoria; con 0 no corta.",
       'max-duration = "1h"',
       modos=SIN_BISYNC,
       buscar="cortar parar limitar tiempo duracion maximo horas pasada larga"),
    _e("no-update-modtime", TEMA_TIEMPOS, RIESGO_LEE,
       "No corregir la fecha del destino si el contenido es igual",
       "Evitar escrituras de fechas en remotos donde cambiarlas es lento.",
       "Si solo difiere la fecha y el contenido es igual, la deja como está. Por defecto "
       "rclone la actualiza.",
       "no-update-modtime = true",
       modos=SIN_BISYNC,
       buscar="fechas modificacion actualizar destino lento remoto"),
    _e("use-server-modtime", TEMA_TIEMPOS, RIESGO_LEE,
       "Usar la fecha que da el servidor",
       "Fiarse de la fecha del servidor en lugar de la que rclone guarda con "
       "cada fichero.",
       "Evita una petición por fichero en remotos que no guardan fechas propias, pero la "
       "fecha pasa a ser la de la subida.",
       "use-server-modtime = true",
       buscar="fechas modificacion servidor rapido remoto peticiones"),

    # ------------------------------------------------------------------ cuánto va a la vez
    _e("transfers", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Cuántos ficheros se copian a la vez",
       "Decidir cuántos ficheros viajan en paralelo.",
       "Por defecto 4. Más ficheros a la vez sacan partido a una buena conexión con muchos "
       "ficheros pequeños; en una unidad lenta o una conexión justa, menos va mejor.",
       "transfers = 8",
       buscar="a la vez paralelo velocidad rapido lento cuantos ficheros copiar cantidad "
              "simultaneos"),
    _e("checkers", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Cuántos ficheros se comparan a la vez",
       "Decidir cuántas comparaciones (¿ha cambiado este fichero?) corren en "
       "paralelo.",
       "Por defecto 8. Con miles de ficheros que apenas cambian, subirlo acelera el "
       "repaso; en una unidad lenta puede saturarla.",
       "checkers = 16",
       buscar="a la vez paralelo comparar comprobar velocidad rapido ficheros cuantos "
              "simultaneos"),
    _e("check-first", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Comparar todo antes de empezar a copiar",
       "Saber primero todo lo que hay que copiar y después copiarlo.",
       "Ayuda en unidades lentas, donde copiar estorba a comparar, y deja exacto el orden de "
       "--order-by. A cambio, empieza a copiar más tarde.",
       "check-first = true",
       buscar="comparar primero antes copiar total progreso orden"),
    _e("multi-thread-streams", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Cuántos trozos de un fichero grande se bajan a la vez",
       "Acelerar la descarga de un fichero grande troceándola.",
       "Por defecto 4. Solo se usa para ficheros mayores que --multi-thread-cutoff. Con 1 "
       "no trocea.",
       "multi-thread-streams = 2",
       modos=SIN_BISYNC,
       buscar="a la vez paralelo velocidad ficheros grandes descarga trozos hilos"),
    _e("buffer-size", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Cuánta memoria usa cada copia",
       "Decidir cuánta memoria reserva cada fichero que se copia.",
       "Por defecto 16 MiB por fichero que viaja. Bájalo en un equipo con poca memoria; "
       "subirlo ayuda con conexiones muy rápidas. Con --transfers 4 gasta 64 MiB.",
       'buffer-size = "8M"',
       buscar="memoria ram bajar equipo lento velocidad consumo"),
    _e("bwlimit", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Limitar la velocidad",
       "Para que rclone no ocupe toda tu conexión.",
       "El número son KiB por segundo; con sufijo, «1M» es 1 MiB/s. Admite horarios "
       "(\"08:00,512k 18:00,off\") para limitar de día y soltar de noche.",
       'bwlimit = "2M"',
       buscar="limitar velocidad ancho de banda subida bajada conexion internet ocupar "
              "lento red"),
    _e("bwlimit-file", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Limitar la velocidad de cada fichero",
       "Para que ningún fichero suelto se coma toda la velocidad.",
       "Cada fichero va como mucho a esa velocidad; con varios a la vez, el total puede "
       "ser mayor. Mismo formato que --bwlimit.",
       'bwlimit-file = "500k"',
       buscar="limitar velocidad ancho de banda fichero conexion"),
    _e("tpslimit", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Limitar las peticiones por segundo",
       "No saturar a un servidor que pone límite de peticiones.",
       "Útil si el remoto devuelve errores de «demasiadas peticiones». Un número bajo "
       "(5, 10) hace más lenta la pasada.",
       "tpslimit = 10",
       buscar="limitar peticiones segundo servidor saturar errores demasiadas velocidad"),
    _e("tpslimit-burst", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Cuántas peticiones seguidas se permiten de golpe",
       "Permitir pequeñas ráfagas aunque haya un --tpslimit.",
       "Por defecto 1. Solo tiene efecto junto a --tpslimit.",
       "tpslimit-burst = 5",
       buscar="limitar peticiones rafaga segundo servidor"),
    _e("max-connections", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Cuántas conexiones abre como mucho",
       "No abrir más conexiones simultáneas con el remoto de las que admite.",
       "Con 0 no hay límite. Algunos servidores (SFTP, NAS pequeños) se cierran si abres "
       "demasiadas.",
       "max-connections = 4",
       buscar="limitar conexiones a la vez servidor nas sftp cerrar abiertas"),
    _e("fast-list", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Listar de una vez en lugar de carpeta a carpeta",
       "Acelerar el repaso en remotos tipo nube (S3, Drive…) que pueden "
       "listar todo de golpe.",
       "Hace menos peticiones pero gasta más memoria. En remotos que no lo admiten no "
       "hace nada.",
       "fast-list = true",
       buscar="listar rapido velocidad peticiones nube memoria repaso"),
    _e("order-by", TEMA_CONCURRENCIA, RIESGO_LEE,
       "En qué orden se copian los ficheros",
       "Copiar primero lo pequeño, lo grande o lo más reciente.",
       "Se escribe «campo,sentido», como «size,descending» (los grandes primero) o "
       "«modtime,ascending» (los más antiguos primero). Útil con --max-duration o "
       "--max-transfer: lo más importante se copia antes de que la pasada corte.",
       'order-by = "size,ascending"',
       modos=SIN_BISYNC,
       buscar="orden primero pequenos grandes antiguos recientes prioridad copiar"),
    _e("max-transfer", TEMA_CONCURRENCIA, RIESGO_LEE,
       "Cortar la pasada tras copiar cierta cantidad",
       "Limitar cuánto se copia en una pasada, por ejemplo con una tarifa de "
       "datos limitada.",
       "Cuando se llega a esa cantidad, rclone se para y lo que queda se hará en la "
       "siguiente. Sin sufijo el número son KiB.",
       'max-transfer = "1G"',
       modos=SIN_BISYNC,
       buscar="limitar cortar cantidad gigas datos tarifa maximo copiar pasada"),
)
"""Los flags explicados a mano, en el orden en que salen dentro de su tema."""
