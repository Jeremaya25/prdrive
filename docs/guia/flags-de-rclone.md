[← Guías](README.md)

# Flags de rclone

<!-- Esta página la genera `python generar_guia_flags.py` a partir del catálogo de la guía (`ui/flags_catalogo.py`). No la edites a mano: `tests/test_flags_guia.py` falla si no coincide. -->

Qué hace cada flag de rclone que puedes poner en una pareja, explicado para quien usa el dispositivo. Es la misma guía que trae el programa, con búsqueda por texto y por efecto («qué hace con los borrados», «cómo ignoro ficheros temporales»): **Parejas → Modificar… → Avanzado → Editar flags… → «Guía de flags…»**.

Un flag se escribe en el TOML de la pareja, sin los guiones de delante (`transfers = 8`); cómo se funden las capas y qué no admite el config está en [Configuración](configuracion.md). Esta guía ayuda y no restringe: un flag que no aparece aquí se puede escribir igual, y rclone tiene la última palabra.

## Cómo leer cada ficha

**Riesgo**, de menos a más:

- **Solo lectura:** no cambia ningún fichero por sí solo: ajusta cómo se mira, cuánto va a la vez o qué se cuenta.
- **Cambia nombres:** cambia el nombre de ficheros, o los aparta con otro nombre.
- **Borra o reescribe:** borra o reescribe ficheros, o es el freno que los protege. Pruébalo antes con «Simular».

**Quién lo pone:**

- **No lo toca prdrive.** Lo que escribas va tal cual a rclone.
- **prdrive le da un valor, que puedes cambiar.** Lo pone prdrive con un valor de partida; puedes poner otro en la pareja.
- **Lo pone prdrive, no se puede cambiar.** Lo pone el script en cada pasada; escribirlo en una pareja se rechaza.
- **No se admite en el config.** Lanzaría un programa o escribiría un fichero de tu equipo, y el config viaja con el dispositivo: se rechaza.

**Modos donde sirve** son los de la pareja: `bisync`, `up`, `down`, `up-mirror` y `down-mirror`. Un flag que rclone acepta en una orden pero no hace nada ahí, o que solo vale en otra, no los incluye.

## Los que pone prdrive

prdrive pone estos flags en cada pasada o les da un valor de partida. Los marcados «Lo pone prdrive, no se puede cambiar» no se pueden escribir en una pareja; los que solo traen un valor se pueden cambiar. Aquí están también los que el config no admite, porque lanzarían un programa o escribirían un fichero de tu equipo.

### `--verbose`

**Cuánto cuenta rclone en el log de cada pasada**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que el log diga qué ha copiado, movido o borrado, fichero a fichero.
- **Qué hace en la práctica:** Con él puedes ver después qué hizo una pasada y por qué. Quitarlo deja el log casi vacío: la pasada va igual, pero no sabrás qué tocó.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** activado en todos los modos
- **Ejemplo:** `verbose = false`

### `--create-empty-src-dirs`

**Si las carpetas vacías también se copian y se borran**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que una carpeta vacía creada o borrada en un lado se cree o se borre en el otro.
- **Qué hace en la práctica:** Solo afecta a carpetas vacías, nunca a ficheros. Quitarlo hace que las carpetas vacías se queden como están; con --remove-empty-dirs no puede ir.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** activado en todos los modos
- **Ejemplo:** `create-empty-src-dirs = false`

### `--stats`

**Cada cuánto escribe rclone cuánto lleva**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que el log lleve una línea de progreso cada pocos segundos.
- **Qué hace en la práctica:** De ahí saca prdrive el progreso en vivo de la ventana. Con "0" rclone no escribe progreso y la ventana no lo muestra; la pasada va igual.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** 2s en todos los modos
- **Ejemplo:** `stats = "5s"`

### `--stats-one-line`

**Que el progreso ocupe una sola línea**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que cada aviso de progreso quepa en una línea que prdrive pueda leer.
- **Qué hace en la práctica:** Sin él, rclone escribe un bloque de varias líneas y la ventana no puede resumir el progreso en una sola.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** activado en todos los modos
- **Ejemplo:** `stats-one-line = false`

### `--conflict-resolve`

**Qué versión gana cuando un fichero cambia en los dos lados**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Decidir qué hacer cuando bisync encuentra el mismo fichero cambiado en el dispositivo y en el remoto.
- **Qué hace en la práctica:** Con «newer» gana la versión más reciente y la otra se aparta con otro nombre (mira --conflict-suffix); con «none» no se resuelve solo y el fichero queda como conflicto.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** newer en bisync
- **Ejemplo:** `conflict-resolve = "larger"`

### `--conflict-suffix`

**Cómo se llama la copia que pierde un conflicto**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que el nombre de la copia apartada diga de qué lado venía.
- **Qué hace en la práctica:** Con dos textos separados por una coma, el primero es para el dispositivo y el segundo para el remoto. Cambiarlo no borra nada, pero los conflictos de antes conservan el nombre que tenían.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** conflicto-dispositivo,conflicto-remoto en bisync
- **Ejemplo:** `conflict-suffix = "conflicto-dispositivo,conflicto-remoto"`

### `--conflict-loser`

**Qué pasa con la copia que pierde un conflicto**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Elegir si la copia perdedora se guarda con otro nombre («num», «pathname») o se borra («delete»).
- **Qué hace en la práctica:** Con «delete» la copia perdedora no se queda en la carpeta: sale por las versiones anteriores si la pareja las guarda, y si no, se pierde. Con «num» se queda con un número.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** «delete» cuando la pareja guarda versiones (la casilla «Guardar versiones»); si no, rclone usa «num».
- **Ejemplo:** `conflict-loser = "num"`

### `--max-delete`

**El freno de los borrados**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que una pasada se pare en vez de borrar de golpe lo que no debe, como cuando una carpeta aparece vacía porque la unidad no estaba montada.
- **Qué hace en la práctica:** En bisync no es una cuenta de ficheros sino un porcentaje de lo que había en la pasada anterior; en los espejo sí es una cuenta de ficheros. Subirlo mucho o quitarlo deja que una pasada borre de golpe. Si el freno salta, la pasada se para y lo dice.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** bisync, up-mirror, down-mirror
- **Lo que pone prdrive:** 25 en bisync · 50 en up-mirror y down-mirror
- **Ejemplo:** `max-delete = 10`

### `--resilient`

**Reintentar tras un error pequeño sin rehacer la referencia**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que un error leve (un fichero que no se pudo leer) no obligue a resincronizar la pareja entera.
- **Qué hace en la práctica:** Sin él, ese error pide un --resync en la pasada siguiente. Con él, la próxima pasada lo vuelve a intentar sola.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** activado en bisync
- **Ejemplo:** `resilient = false`

### `--recover`

**Recuperarse solo de una pasada cortada**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que, si una pasada se interrumpe (se tira de la unidad, se apaga el equipo), la siguiente continúe sin pedir --resync.
- **Qué hace en la práctica:** Quitarlo hace que una interrupción brusca pida resincronizar la pareja.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** activado en bisync
- **Ejemplo:** `recover = false`

### `--max-lock`

**Cuándo caduca el candado de una pasada muerta**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que el candado que deja una pasada que murió a medias no bloquee las siguientes para siempre.
- **Qué hace en la práctica:** Con «2m» un candado de más de dos minutos se da por caducado. El mínimo es 2m; con 0 el candado no caduca nunca.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** 2m en bisync
- **Ejemplo:** `max-lock = "5m"`

### `--config`

**El fichero de conexiones de rclone**

> **Lo pone prdrive, no se puede cambiar** (lo pone sync.py: es el rclone.conf del dispositivo)

- **Para qué sirve:** Para que rclone use el rclone.conf del dispositivo y no el del equipo donde esté enchufado.
- **Qué hace en la práctica:** Lo pone prdrive en cada pasada y no se puede cambiar: cambiarlo sacaría a rclone de las conexiones del dispositivo.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe: es el rclone.conf del dispositivo, el mismo para todas las parejas.

### `--log-file`

**Dónde escribe rclone el log de la pasada**

> **Lo pone prdrive, no se puede cambiar** (lo pone sync.py: cada pasada escribe en su propio log)

- **Para qué sirve:** Para que cada pasada deje su propio log, que luego se puede abrir y guardar.
- **Qué hace en la práctica:** Lo pone prdrive y no se puede cambiar: es lo que hace que cada pasada tenga su log y que el progreso en vivo funcione.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Los logs se abren desde «Abrir los logs».

### `--dry-run`

**Probar sin cambiar nada**

> **Lo pone prdrive, no se puede cambiar** (es --dry-run de sync.py, para que valga en todas las parejas)

- **Para qué sirve:** Ver qué haría una pasada sin copiar, mover ni borrar nada.
- **Qué hace en la práctica:** Lo pone prdrive cuando usas «Simular», para que valga en todas las parejas y modos. Pruébalo siempre antes en una pareja *-mirror, que borra en el otro lado.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Se usa con el botón «Simular» de la pantalla de parejas.

### `--workdir`

**Dónde guarda bisync su referencia**

> **Lo pone prdrive, no se puede cambiar** (lo pone sync.py: state/<pareja>/, y cambiarlo mueve el baseline)

- **Para qué sirve:** Para que bisync guarde en state/<pareja>/ la lista de lo que había en la última pasada.
- **Qué hace en la práctica:** Lo pone prdrive y no se puede cambiar: apuntarlo a otra carpeta haría que bisync comparase con una referencia que no es la de esta pareja.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe.

### `--resync`

**Rehacer la referencia de bisync**

> **Lo pone prdrive, no se puede cambiar** (es --resync de sync.py, que además pregunta antes)

- **Para qué sirve:** Para que bisync empiece de cero: mira los dos lados, copia lo que falta en cada uno y apunta cómo están.
- **Qué hace en la práctica:** Reescribe lo que sea distinto: gana un lado (por defecto el dispositivo). Lo pone prdrive solo cuando tú lo pides y te pregunta antes; escribirlo aquí lo forzaría en cada pasada.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Se pide desde la ventana cuando una pareja lo necesita.

### `--backup-dir`

**Carpeta donde apartar lo que se cambia o borra**

> **Lo pone prdrive, no se puede cambiar** (el versionado de bisync usa --backup-dir1/2, no este)

- **Para qué sirve:** Guardar en otra carpeta la versión anterior de lo que una pasada cambia o borra.
- **Qué hace en la práctica:** En bisync prdrive no usa este flag sino --backup-dir1 y --backup-dir2, uno por lado, y solo con la casilla «Guardar versiones».
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Marca «Guardar versiones» en la pareja.

### `--backup-dir1`

**Carpeta de versiones del lado del dispositivo**

> **Lo pone prdrive, no se puede cambiar** (sale de la casilla «Guardar versiones»: es <pareja>/.prversions)

- **Para qué sirve:** Apartar en <pareja>/.prversions lo que bisync cambia o borra en el dispositivo.
- **Qué hace en la práctica:** Lo pone prdrive cuando la pareja guarda versiones y no se puede cambiar.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Marca «Guardar versiones» en la pareja.

### `--backup-dir2`

**Carpeta de versiones del lado del remoto**

> **Lo pone prdrive, no se puede cambiar** (sale de la casilla «Guardar versiones»: es <pareja>/.prversions)

- **Para qué sirve:** Apartar en <pareja>/.prversions lo que bisync cambia o borra en el remoto.
- **Qué hace en la práctica:** Lo pone prdrive cuando la pareja guarda versiones y no se puede cambiar.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Marca «Guardar versiones» en la pareja.

### `--suffix`

**La marca de fecha de lo que se aparta**

> **Lo pone prdrive, no se puede cambiar** (lo pone sync.py: la marca de tiempo de ESTA pasada)

- **Para qué sirve:** Para que cada fichero apartado lleve la fecha y la hora de la pasada que lo apartó.
- **Qué hace en la práctica:** Lo pone prdrive en cada pasada, porque cada una tiene la suya; no se puede escribir aquí.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe.

### `--suffix-keep-extension`

**Que lo apartado conserve su extensión**

> **Lo pone prdrive, no se puede cambiar** (lo pone sync.py junto con --suffix)

- **Para qué sirve:** Para que una versión guardada siga acabando en .docx o .jpg, y se abra con su programa.
- **Qué hace en la práctica:** Lo pone prdrive junto con la marca de fecha y no se puede cambiar.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe.

### `--filters-file`

**El fichero con los patrones de «Incluir» y «Excluir»**

> **Lo pone prdrive, no se puede cambiar** (sale de los patrones incluir/excluir de la pareja)

- **Para qué sirve:** Para que bisync lea de un fichero los patrones de la pareja y note si cambian.
- **Qué hace en la práctica:** Lo hace prdrive a partir de los cuadros «Incluir» y «Excluir» de la pareja. Cambiar los patrones de una pareja bisync pide un --resync.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Usa los cuadros «Incluir» y «Excluir» de la pareja.

### `--filter`

**Una regla de filtrado suelta**

> **Lo pone prdrive, no se puede cambiar** (usa los patrones incluir/excluir; mezclarlos rompe el filtrado)

- **Para qué sirve:** En rclone, añadir una regla «+» o «-» a mano.
- **Qué hace en la práctica:** No se admite aquí: mezclada con los cuadros «Incluir» y «Excluir» rompe el filtrado de la pareja.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Usa los cuadros «Incluir» y «Excluir» de la pareja.

### `--filter-from`

**Leer las reglas de filtrado de un fichero**

> **Lo pone prdrive, no se puede cambiar** (usa los patrones incluir/excluir; mezclarlos rompe el filtrado)

- **Para qué sirve:** En rclone, cargar reglas de filtrado de un fichero de texto.
- **Qué hace en la práctica:** No se admite aquí: mezclado con los cuadros «Incluir» y «Excluir» rompe el filtrado de la pareja.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Usa los cuadros «Incluir» y «Excluir» de la pareja.

### `--include`

**Copiar solo los ficheros que encajen**

> **Lo pone prdrive, no se puede cambiar** (usa el cuadro «Incluir»)

- **Para qué sirve:** Para que la pareja copie únicamente lo que encaje con un patrón (por ejemplo *.docx).
- **Qué hace en la práctica:** Lo pone prdrive a partir del cuadro «Incluir» de la pareja, y no se puede escribir aquí. Con «Incluir» lleno, todo lo demás se queda fuera.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. Pon el patrón en el cuadro «Incluir» de la pareja, como *.docx.

### `--exclude`

**Dejar fuera ficheros que encajen**

> **Lo pone prdrive, no se puede cambiar** (usa el cuadro «Excluir»)

- **Para qué sirve:** Ignorar ficheros por su nombre: los temporales, las cachés, lo que no quieres llevar.
- **Qué hace en la práctica:** Lo pone prdrive a partir del cuadro «Excluir» de la pareja, y no se puede escribir aquí. Un patrón por línea; lo que encaja se queda fuera de la pasada.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** No se escribe. En el cuadro «Excluir» de la pareja, una línea por patrón: *.tmp, ~$*, .~lock.*#, Thumbs.db.

### `--cpuprofile`

**Volcar un perfil del procesador a un fichero**

> **No se admite en el config** (escribe (o trunca) en este equipo el fichero que se le diga, y el config viaja con el dispositivo)

- **Para qué sirve:** Guardar cuánto procesador gasta cada parte de rclone; es para quien depura rclone.
- **Qué hace en la práctica:** No se admite en el config: escribe (o vacía) el fichero que se le diga, y el config viaja con el dispositivo a otros equipos.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** No lo pone: el config lo rechaza.
- **En su lugar:** No se escribe.

### `--memprofile`

**Volcar un perfil de memoria a un fichero**

> **No se admite en el config** (escribe (o trunca) en este equipo el fichero que se le diga, y el config viaja con el dispositivo)

- **Para qué sirve:** Guardar cuánta memoria gasta cada parte de rclone; es para quien depura rclone.
- **Qué hace en la práctica:** No se admite en el config: escribe (o vacía) el fichero que se le diga, y el config viaja con el dispositivo a otros equipos.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** No lo pone: el config lo rechaza.
- **En su lugar:** No se escribe.

### `--password-command`

**Un programa que da la contraseña de rclone**

> **No se admite en el config** (lanza un programa en este equipo, y el config viaja con el dispositivo)

- **Para qué sirve:** En rclone, pedirle a un programa la contraseña del rclone.conf cifrado.
- **Qué hace en la práctica:** No se admite en el config: haría correr ese programa en el equipo donde enchufes la unidad.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** No lo pone: el config lo rechaza.
- **En su lugar:** No se escribe.

### `--metadata-mapper`

**Un programa que transforma los metadatos al subir**

> **No se admite en el config** (lanza un programa en este equipo, y el config viaja con el dispositivo)

- **Para qué sirve:** En rclone, pasar los metadatos de cada fichero por un programa antes de subirlos.
- **Qué hace en la práctica:** No se admite en el config: haría correr ese programa en el equipo donde enchufes la unidad.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** No lo pone: el config lo rechaza.
- **En su lugar:** No se escribe.

### `--force`

**Saltarse el freno de los borrados**

> **Lo pone prdrive, no se puede cambiar** (es --force de sync.py: salta el freno de borrados en UNA pasada y no puede quedar fijo en el config. Para saltarlo ahora, «Forzar sincronización…» en «Reparación» o `sync.py PAREJA --force`)

- **Para qué sirve:** Para que bisync haga una pasada aunque vaya a borrar más de lo que permite --max-delete.
- **Qué hace en la práctica:** Quita justo la protección que evita que una unidad vacía arrase el otro lado.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Lo pone el programa cuando toca, no la pareja; no se escribe.
- **En su lugar:** Para forzar una sola pasada, «Reparación» → «Forzar sincronización…»: pide confirmación y la pasada siguiente vuelve a frenar.

### `--modify-window`

**Cuánta diferencia de fecha se considera igual**

> **prdrive le da un valor, que puedes cambiar**

- **Para qué sirve:** Para que dos fechas casi iguales se traten como la misma, en remotos o sistemas de ficheros que redondean.
- **Qué hace en la práctica:** Algunos sistemas de ficheros (como FAT, que redondea a 2 segundos) y algunos remotos guardan las fechas redondeadas: con un margen ("2s") dejan de copiarse ficheros que solo difieren en eso. Lleva unidad obligatoria.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** 2s en todos los modos
- **Ejemplo:** `modify-window = "2s"`

## Borrados y sobrescrituras

Qué se borra del otro lado, cuándo, y lo que lo frena. Pruébalo todo antes con «Simular», sobre todo en una pareja *-mirror, que borra.

### `--delete-after`

**Borrar del destino al acabar de copiar**

- **Para qué sirve:** Para que, al sincronizar, lo que ya no está en el origen se borre del destino cuando todo lo demás ya se ha copiado.
- **Qué hace en la práctica:** Es lo que hace rclone si no le dices otra cosa. Es lo más seguro de los tres --delete-*: si algo falla a medias, aún tienes todo en el destino. Solo vale donde se sincroniza (*-mirror). Pruébalo antes con «Simular».
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `delete-after = true`

### `--delete-before`

**Borrar del destino antes de copiar**

- **Para qué sirve:** Liberar sitio en el destino antes de empezar a copiar.
- **Qué hace en la práctica:** Borra primero y copia después: si la copia falla, ya has perdido lo borrado. No se puede combinar con --delete-during ni --delete-after. Solo vale en *-mirror. Pruébalo antes con «Simular».
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `delete-before = true`

### `--delete-during`

**Borrar del destino mientras se copia**

- **Para qué sirve:** Ir borrando lo que sobra a la vez que se copia, en una sola vuelta.
- **Qué hace en la práctica:** Es más rápido que los otros dos, pero mezcla borrar y copiar. No se puede combinar con --delete-before ni --delete-after. Solo vale en *-mirror. Pruébalo antes con «Simular».
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `delete-during = true`

### `--delete-excluded`

**Borrar también lo que los filtros dejan fuera**

- **Para qué sirve:** Para que, al sincronizar, se borre del destino lo que tus patrones de «Excluir» dejan fuera.
- **Qué hace en la práctica:** Sin él, lo excluido que ya está en el destino se queda ahí. Con él se borra: añadir un patrón de «Excluir» puede borrar muchos ficheros. Solo vale en *-mirror. Pruébalo antes con «Simular».
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `delete-excluded = true`

### `--max-delete-size`

**El freno de los borrados, por tamaño**

- **Para qué sirve:** Para que una pasada se pare si fuera a borrar más de un tamaño total.
- **Qué hace en la práctica:** Es como --max-delete pero cuenta bytes, no ficheros: con «1G», una pasada que fuera a borrar más de 1 GB se para. Quitarlo ("off") deja el freno solo en --max-delete.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa off).
- **Ejemplo:** `max-delete-size = "5G"`

### `--ignore-errors`

**Seguir borrando aunque haya errores de lectura**

- **Para qué sirve:** Para que un espejo siga borrando del destino aunque no haya podido leer parte del origen.
- **Qué hace en la práctica:** Un origen que no se ha leído entero parece vacío, y lo que no se ve se borra del destino. Por defecto rclone se niega a borrar si hubo errores. Solo vale en *-mirror.
- **Ojo:** No lo pongas en una pareja: lo que se escribe aquí vale para todas las pasadas, también las que nadie vigila, y una con errores de lectura borraría del destino lo que no ha podido ver.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.

### `--remove-empty-dirs`

**Quitar todas las carpetas vacías al final**

- **Para qué sirve:** Dejar limpias las carpetas que se quedan vacías tras la pasada.
- **Qué hace en la práctica:** Borra cualquier carpeta vacía de los dos lados, también las que nunca tuvieron nada. No es compatible con --create-empty-src-dirs, que prdrive pone siempre.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `remove-empty-dirs = true`

### `--resync-mode`

**Qué lado gana al rehacer la referencia**

- **Para qué sirve:** Elegir qué versión se queda cuando un --resync encuentra el mismo fichero distinto en los dos lados.
- **Qué hace en la práctica:** La otra versión se sobrescribe. Con «path1» gana el dispositivo, con «path2» el remoto; «newer», «older», «larger» y «smaller» deciden por fecha o tamaño. Solo se aplica cuando se pide un --resync desde la ventana.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa none).
- **Ejemplo:** `resync-mode = "newer"`

### `--track-renames`

**Mover en lugar de copiar y borrar un fichero renombrado**

- **Para qué sirve:** Para que renombrar un fichero en el origen lo mueva en el destino, sin volver a subirlo.
- **Qué hace en la práctica:** Ahorra copiar ficheros grandes que solo han cambiado de nombre. Medido: sin él, un renombrado se copia entero con el nombre nuevo y se borra el viejo. Solo vale en *-mirror.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `track-renames = true`

### `--fix-case`

**Igualar las mayúsculas de los nombres del destino**

- **Para qué sirve:** Corregir en el destino un nombre que solo se diferencia en mayúsculas y minúsculas.
- **Qué hace en la práctica:** Renombra ficheros del destino para que se llamen igual que en el origen. Útil si el destino no distingue mayúsculas. Solo vale en *-mirror.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `fix-case = true`

### `--name-transform`

**Cambiar los nombres de los ficheros al copiarlos**

- **Para qué sirve:** Pasar los nombres a minúsculas, añadirles algo o limpiar caracteres al copiar.
- **Qué hace en la práctica:** Es una transformación de una sola dirección: el fichero llega con otro nombre. Medido: «all,lowercase» pasa a minúsculas y «file,suffix=_copia» añade el texto tras la extensión. Se pueden poner varias.
- **Riesgo:** Cambia nombres
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `name-transform = ["all,lowercase"]`

### `--inplace`

**Escribir directamente sobre el fichero de destino**

- **Para qué sirve:** No usar un fichero temporal al copiar, cuando el destino no deja renombrar.
- **Qué hace en la práctica:** Si la copia se corta a mitad, el fichero de destino se queda a medias y el original que había se ha perdido. Sin él, rclone escribe un temporal y lo renombra al acabar.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `inplace = true`

### `--immutable`

**No dejar que un fichero ya copiado cambie**

- **Para qué sirve:** Proteger lo que ya está en el destino: si el origen es distinto, falla en vez de sobrescribir.
- **Qué hace en la práctica:** Medido: con el fichero cambiado en el origen, rclone da error y deja intacto el del destino. Los ficheros nuevos se copian. Útil en una copia de seguridad que no debe cambiar.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `immutable = true`

### `--no-check-dest`

**Copiar sin mirar qué hay en el destino**

- **Para qué sirve:** Saltarse la comparación y copiarlo todo.
- **Qué hace en la práctica:** Sobrescribe lo que haya en el destino aunque sea igual, y copia siempre entero. Solo tiene sentido en una carpeta de destino vacía o nueva.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `no-check-dest = true`

### `--refresh-times`

**Reescribir las fechas de los ficheros del remoto**

- **Para qué sirve:** Poner la fecha de modificación correcta en ficheros del remoto que la tienen mal.
- **Qué hace en la práctica:** Cambia metadatos del remoto sin copiar el contenido. Puede tardar si hay muchos ficheros y no todos los remotos lo admiten.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `refresh-times = true`

### `--check-access`

**No sincronizar si falta un fichero de prueba**

- **Para qué sirve:** Para que bisync se pare si en los dos lados no encuentra un fichero de prueba (RCLONE_TEST), como cuando una unidad no está montada.
- **Qué hace en la práctica:** Medido: sin los ficheros de prueba, bisync aborta con «Access test failed» y pide --resync. Pon un fichero llamado RCLONE_TEST en cada lado (o cambia el nombre con --check-filename) antes de activarlo.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `check-access = true`

### `--check-filename`

**El nombre del fichero de prueba de --check-access**

- **Para qué sirve:** Cambiar el nombre del fichero que bisync busca en los dos lados.
- **Qué hace en la práctica:** Solo tiene efecto con --check-access. Por defecto el fichero se llama RCLONE_TEST.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** bisync
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `check-filename = ".prdrive-ok"`

## Cómo decide qué ha cambiado

Cómo decide rclone que un fichero ya está al día o que hay que copiarlo.

### `--size-only`

**Comparar solo por tamaño**

- **Para qué sirve:** Decidir que un fichero ha cambiado solo si su tamaño es otro, sin mirar la fecha ni el contenido.
- **Qué hace en la práctica:** Es más rápido, pero un fichero que cambia sin cambiar de tamaño no se copia. Medido: con el mismo tamaño y otro contenido, no se copia. Con --checksum se pisan: gana este.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `size-only = true`

### `--checksum`

**Comparar por el contenido, no por la fecha**

- **Para qué sirve:** Decidir qué ha cambiado mirando una firma del contenido (checksum), no la fecha.
- **Qué hace en la práctica:** Es más seguro cuando las fechas no son fiables, pero tiene que leer los ficheros (o pedir la firma al remoto) y es más lento. Medido: copia un fichero de igual tamaño y distinto contenido.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `checksum = true`

### `--ignore-times`

**Volver a copiar todo, aunque ya esté igual**

- **Para qué sirve:** Forzar que todos los ficheros se copien de nuevo, sin comparar nada.
- **Qué hace en la práctica:** Medido: reemplaza incluso lo que es idéntico. Tarda lo que tarde copiarlo todo. Con --ignore-existing se pisan: gana --ignore-existing y lo que ya existe no se toca.
- **Riesgo:** Borra o reescribe
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `ignore-times = true`

### `--update`

**No pisar lo que es más nuevo en el destino**

- **Para qué sirve:** Para que un fichero del origen no sobrescriba otro del destino que es más reciente.
- **Qué hace en la práctica:** Medido: si el del destino tiene fecha más nueva, se deja. Protege cambios hechos directamente en el destino.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `update = true`

### `--ignore-existing`

**No tocar lo que ya existe en el destino**

- **Para qué sirve:** Copiar solo ficheros nuevos y no actualizar nunca los que ya están.
- **Qué hace en la práctica:** Medido: un fichero cambiado en el origen no se copia si ya existe en el destino. Un archivo que solo debe crecer.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `ignore-existing = true`

### `--ignore-size`

**No mirar el tamaño al comparar**

- **Para qué sirve:** Decidir qué ha cambiado solo por la fecha o la firma, sin el tamaño.
- **Qué hace en la práctica:** Se usa con remotos que a veces dan mal el tamaño de un fichero. Un cambio de tamaño sin cambio de fecha ya no se nota.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `ignore-size = true`

### `--ignore-checksum`

**No comprobar la firma tras copiar**

- **Para qué sirve:** Saltarse la verificación que rclone hace al terminar de copiar cada fichero.
- **Qué hace en la práctica:** Ahorra tiempo, pero una copia corrupta ya no se detecta. Mejor déjalo como está salvo que un remoto dé firmas que no coinciden.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `ignore-checksum = true`

## Qué ficheros entran

Qué ficheros se dejan fuera o se eligen. Para ignorar ficheros por su nombre, lo normal es el cuadro «Excluir» de la pareja.

### `--exclude-from`

**Dejar fuera lo que diga una lista de un fichero**

- **Para qué sirve:** Ignorar ficheros con los patrones de un fichero de texto, uno por línea.
- **Qué hace en la práctica:** Medido: con una línea «*.txt», no se copia ningún .txt. Útil para compartir la misma lista entre parejas. Una ruta relativa se cuenta desde la carpeta .prdrive del dispositivo. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `exclude-from = ["ignorar.txt"]`

### `--include-from`

**Copiar solo lo que diga una lista de un fichero**

- **Para qué sirve:** Copiar únicamente lo que encaje con los patrones de un fichero de texto.
- **Qué hace en la práctica:** Medido: con una línea «a.txt», solo se copia a.txt. Todo lo demás se queda fuera. Una ruta relativa se cuenta desde la carpeta .prdrive del dispositivo. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `include-from = ["solo.txt"]`

### `--files-from`

**Copiar solo los ficheros de una lista exacta**

- **Para qué sirve:** Copiar exactamente los ficheros que nombra un fichero de texto.
- **Qué hace en la práctica:** Medido: copia solo los de la lista. Cada línea es una ruta, no un patrón. Una ruta relativa se cuenta desde la carpeta .prdrive del dispositivo. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `files-from = ["lista.txt"]`

### `--min-size`

**Ignorar los ficheros pequeños**

- **Para qué sirve:** Copiar solo los ficheros mayores de un tamaño.
- **Qué hace en la práctica:** Medido: con «1k» solo pasan los de más de 1 KiB. Sin sufijo el número son KiB. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa off).
- **Ejemplo:** `min-size = "100k"`

### `--max-size`

**Ignorar los ficheros muy grandes**

- **Para qué sirve:** No copiar los ficheros mayores de un tamaño.
- **Qué hace en la práctica:** Medido: con «1k» solo pasan los de 1 KiB o menos. Sin sufijo el número son KiB. Útil para no llenar una unidad pequeña con vídeos u otros ficheros pesados. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa off).
- **Ejemplo:** `max-size = "500M"`

### `--min-age`

**Ignorar los ficheros recién modificados**

- **Para qué sirve:** Copiar solo ficheros más antiguos que un tiempo, y dejar los que se acaban de tocar.
- **Qué hace en la práctica:** Medido: con «1d» solo pasan los modificados hace más de un día. Evita copiar un fichero que aún se está escribiendo. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa off).
- **Ejemplo:** `min-age = "1h"`

### `--max-age`

**Ignorar los ficheros antiguos**

- **Para qué sirve:** Copiar solo ficheros modificados hace menos de un tiempo.
- **Qué hace en la práctica:** Medido: con «1d» solo pasan los modificados en el último día. Lo antiguo se queda fuera. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa off).
- **Ejemplo:** `max-age = "30d"`

### `--max-depth`

**Limitar a cuántas carpetas de profundidad se baja**

- **Para qué sirve:** No entrar en subcarpetas más allá de un nivel.
- **Qué hace en la práctica:** Medido: con 1 solo pasan los ficheros de la carpeta de arriba, sin ninguna subcarpeta. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa -1).
- **Ejemplo:** `max-depth = 2`

### `--exclude-if-present`

**Dejar fuera una carpeta si lleva un fichero marca**

- **Para qué sirve:** Ignorar carpetas enteras con solo poner dentro un fichero (por ejemplo .nosync).
- **Qué hace en la práctica:** Medido: una carpeta que contiene el fichero indicado no se copia. Cómodo para excluir una carpeta sin tocar los patrones. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `exclude-if-present = [".nosync"]`

### `--ignore-case`

**No distinguir mayúsculas en los filtros**

- **Para qué sirve:** Para que un patrón como *.tmp también encaje con MAYUS.TMP.
- **Qué hace en la práctica:** Medido: con él, «*.tmp» excluye también MAYUS.TMP. Sin él, rclone distingue mayúsculas. En una pareja bisync no lo uses: bisync no vigila los cambios de este flag entre una pasada y otra, y lo que deja de cumplirlo le parece borrado (medido: lo cuenta como «File was deleted» y el resultado no está garantizado). Ahí filtra con «Incluir» y «Excluir» de la pareja, que prdrive sí vigila.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `ignore-case = true`

## Esperas, reintentos y duración

Cuánto espera rclone, cuántas veces reintenta y cuánto puede durar una pasada.

### `--timeout`

**Cuánto espera rclone sin recibir nada antes de rendirse**

- **Para qué sirve:** Para que una conexión que se queda colgada acabe dando error en vez de esperar siempre.
- **Qué hace en la práctica:** Por defecto son 5 minutos sin movimiento. En redes lentas o remotos que tardan, súbelo. Lleva unidad obligatoria: "30" a secas no vale, "30s" sí.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 5m0s).
- **Ejemplo:** `timeout = "10m"`

### `--contimeout`

**Cuánto espera para conectar con el remoto**

- **Para qué sirve:** Decidir cuánto tiempo se espera a que el remoto conteste al conectar.
- **Qué hace en la práctica:** Por defecto 1 minuto. Con un remoto lejano o una red mala, súbelo. Lleva unidad obligatoria.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 1m0s).
- **Ejemplo:** `contimeout = "2m"`

### `--retries`

**Cuántas veces repite una pasada que falla**

- **Para qué sirve:** Para que rclone vuelva a intentar toda la operación si algo falla.
- **Qué hace en la práctica:** Por defecto 3. Con 1 no reintenta nada. Cada reintento vuelve a mirar lo que falló, no repite lo que ya fue bien.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 3).
- **Ejemplo:** `retries = 5`

### `--retries-sleep`

**Cuánto espera entre reintentos**

- **Para qué sirve:** Dejar un respiro entre un intento y el siguiente.
- **Qué hace en la práctica:** Por defecto no espera. Con un remoto que se satura, unos segundos ayudan. Lleva unidad obligatoria.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 0s).
- **Ejemplo:** `retries-sleep = "10s"`

### `--low-level-retries`

**Cuántas veces repite una petición suelta que falla**

- **Para qué sirve:** Para que un fallo pequeño de red no tire toda la operación.
- **Qué hace en la práctica:** Por defecto 10. Es el nivel de abajo: reintenta cada petición, mientras que --retries reintenta toda la operación.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 10).
- **Ejemplo:** `low-level-retries = 20`

### `--max-duration`

**Cortar la pasada tras un tiempo**

- **Para qué sirve:** Para que una pasada se pare sola pasado un tiempo, aunque quede trabajo.
- **Qué hace en la práctica:** Lo que quede se hará en la siguiente. Útil para no ocupar la unidad ni la red más de la cuenta. Lleva unidad obligatoria; con 0 no corta.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 0s).
- **Ejemplo:** `max-duration = "1h"`

### `--no-update-modtime`

**No corregir la fecha del destino si el contenido es igual**

- **Para qué sirve:** Evitar escrituras de fechas en remotos donde cambiarlas es lento.
- **Qué hace en la práctica:** Si solo difiere la fecha y el contenido es igual, la deja como está. Por defecto rclone la actualiza.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `no-update-modtime = true`

### `--use-server-modtime`

**Usar la fecha que da el servidor**

- **Para qué sirve:** Fiarse de la fecha del servidor en lugar de la que rclone guarda con cada fichero.
- **Qué hace en la práctica:** Evita una petición por fichero en remotos que no guardan fechas propias, pero la fecha pasa a ser la de la subida.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `use-server-modtime = true`

## Cuánto va a la vez y a qué velocidad

Cuántos ficheros van a la vez, con cuánta memoria y a qué velocidad.

### `--transfers`

**Cuántos ficheros se copian a la vez**

- **Para qué sirve:** Decidir cuántos ficheros viajan en paralelo.
- **Qué hace en la práctica:** Por defecto 4. Más ficheros a la vez sacan partido a una buena conexión con muchos ficheros pequeños; en una unidad lenta o una conexión justa, menos va mejor.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 4).
- **Ejemplo:** `transfers = 8`

### `--checkers`

**Cuántos ficheros se comparan a la vez**

- **Para qué sirve:** Decidir cuántas comparaciones (¿ha cambiado este fichero?) corren en paralelo.
- **Qué hace en la práctica:** Por defecto 8. Con miles de ficheros que apenas cambian, subirlo acelera el repaso; en una unidad lenta puede saturarla.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 8).
- **Ejemplo:** `checkers = 16`

### `--check-first`

**Comparar todo antes de empezar a copiar**

- **Para qué sirve:** Saber primero todo lo que hay que copiar y después copiarlo.
- **Qué hace en la práctica:** Ayuda en unidades lentas, donde copiar estorba a comparar, y deja exacto el orden de --order-by. A cambio, empieza a copiar más tarde.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `check-first = true`

### `--multi-thread-streams`

**Cuántos trozos de un fichero grande se bajan a la vez**

- **Para qué sirve:** Acelerar la descarga de un fichero grande troceándola.
- **Qué hace en la práctica:** Por defecto 4. Solo se usa para ficheros mayores que --multi-thread-cutoff. Con 1 no trocea.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 4).
- **Ejemplo:** `multi-thread-streams = 2`

### `--buffer-size`

**Cuánta memoria usa cada copia**

- **Para qué sirve:** Decidir cuánta memoria reserva cada fichero que se copia.
- **Qué hace en la práctica:** Por defecto 16 MiB por fichero que viaja. Bájalo en un equipo con poca memoria; subirlo ayuda con conexiones muy rápidas. Con --transfers 4 gasta 64 MiB.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 16Mi).
- **Ejemplo:** `buffer-size = "8M"`

### `--bwlimit`

**Limitar la velocidad**

- **Para qué sirve:** Para que rclone no ocupe toda tu conexión.
- **Qué hace en la práctica:** El número son KiB por segundo; con sufijo, «1M» es 1 MiB/s. Admite horarios ("08:00,512k 18:00,off") para limitar de día y soltar de noche.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `bwlimit = "2M"`

### `--bwlimit-file`

**Limitar la velocidad de cada fichero**

- **Para qué sirve:** Para que ningún fichero suelto se coma toda la velocidad.
- **Qué hace en la práctica:** Cada fichero va como mucho a esa velocidad; con varios a la vez, el total puede ser mayor. Mismo formato que --bwlimit.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `bwlimit-file = "500k"`

### `--tpslimit`

**Limitar las peticiones por segundo**

- **Para qué sirve:** No saturar a un servidor que pone límite de peticiones.
- **Qué hace en la práctica:** Útil si el remoto devuelve errores de «demasiadas peticiones». Un número bajo (5, 10) hace más lenta la pasada.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `tpslimit = 10`

### `--tpslimit-burst`

**Cuántas peticiones seguidas se permiten de golpe**

- **Para qué sirve:** Permitir pequeñas ráfagas aunque haya un --tpslimit.
- **Qué hace en la práctica:** Por defecto 1. Solo tiene efecto junto a --tpslimit.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa 1).
- **Ejemplo:** `tpslimit-burst = 5`

### `--max-connections`

**Cuántas conexiones abre como mucho**

- **Para qué sirve:** No abrir más conexiones simultáneas con el remoto de las que admite.
- **Qué hace en la práctica:** Con 0 no hay límite. Algunos servidores (SFTP, NAS pequeños) se cierran si abres demasiadas.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `max-connections = 4`

### `--fast-list`

**Listar de una vez en lugar de carpeta a carpeta**

- **Para qué sirve:** Acelerar el repaso en remotos tipo nube (S3, Drive…) que pueden listar todo de golpe.
- **Qué hace en la práctica:** Hace menos peticiones pero gasta más memoria. En remotos que no lo admiten no hace nada.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** todos
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `fast-list = true`

### `--order-by`

**En qué orden se copian los ficheros**

- **Para qué sirve:** Copiar primero lo pequeño, lo grande o lo más reciente.
- **Qué hace en la práctica:** Se escribe «campo,sentido», como «size,descending» (los grandes primero) o «modtime,ascending» (los más antiguos primero). Útil con --max-duration o --max-transfer: lo más importante se copia antes de que la pasada corte.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca.
- **Ejemplo:** `order-by = "size,ascending"`

### `--max-transfer`

**Cortar la pasada tras copiar cierta cantidad**

- **Para qué sirve:** Limitar cuánto se copia en una pasada, por ejemplo con una tarifa de datos limitada.
- **Qué hace en la práctica:** Cuando se llega a esa cantidad, rclone se para y lo que queda se hará en la siguiente. Sin sufijo el número son KiB.
- **Riesgo:** Solo lectura
- **Modos donde sirve:** up, down, up-mirror, down-mirror
- **Lo que pone prdrive:** Ninguno: prdrive no lo toca (rclone usa off).
- **Ejemplo:** `max-transfer = "1G"`

## Sin explicación propia

Son los flags de rclone v1.75.2, la que lleva prdrive, que esta guía todavía no explica. Salen con la ayuda corta de rclone, que está **en inglés**, para saber que existen y de qué tipo son. Escribirlos vale igual que cualquier otro; si el tipo del valor no es el que rclone espera, el editor lo dice al guardar.

| Flag | Tipo | Valor de fábrica | Ayuda de rclone (en inglés) | Modos |
|---|---|---|---|---|
| `--absolute` | sí o no | — | Put a leading / in front of path names | up, down, up-mirror, down-mirror |
| `--ask-password` | sí o no | true | Allow prompt for password for encrypted configuration | todos |
| `--auto-confirm` | sí o no | — | If enabled, do not request console confirmation | todos |
| `--bind` | texto | — | Local address to bind to for outgoing connections, IPv4, IPv6 or name | todos |
| `--ca-cert` | lista | — | CA certificate used to verify servers | todos |
| `--cache-dir` | texto | — | Directory rclone will use for caching | todos |
| `--check-sync` | texto | true | Controls comparison of final listings: true\|false\|only (default: true) | bisync |
| `--client-cert` | texto | — | Client SSL certificate (PEM) for mutual TLS auth | todos |
| `--client-key` | texto | — | Client SSL private key (PEM) for mutual TLS auth | todos |
| `--client-pass` | texto | — | Password for client SSL private key (PEM) for mutual TLS auth (obscured) (obscured) | todos |
| `--color` | opción | AUTO | When to show colors (and other ANSI codes) AUTO\|NEVER\|ALWAYS | todos |
| `--combined` | texto | — | Make a combined report of changes to this file | up, down, up-mirror, down-mirror |
| `--compare` | texto | — | Comma-separated list of bisync-specific compare options ex. 'size,modtime,checksum' (default: 'size,modtime') | bisync |
| `--compare-dest` | lista | — | Include additional server-side paths during comparison | todos |
| `--copy-dest` | lista | — | Implies --compare-dest but also copies files from paths into destination | todos |
| `--csv` | sí o no | — | Output in CSV format | up, down, up-mirror, down-mirror |
| `--cutoff-mode` | opción | HARD | Mode to stop transfers when reaching the max transfer limit HARD\|SOFT\|CAUTIOUS | todos |
| `--default-time` | Time | 2000-01-01T00:00:00Z | Time to show if modtime is unknown for files and directories | todos |
| `--dest-after` | texto | — | Report all files that exist on the dest post-sync | up, down, up-mirror, down-mirror |
| `--differ` | texto | — | Report all non-matching files to this file | up, down, up-mirror, down-mirror |
| `--dir-slash` | sí o no | true | Append a slash to directory names | up, down, up-mirror, down-mirror |
| `--dirs-only` | sí o no | — | Only list directories | up, down, up-mirror, down-mirror |
| `--disable` | texto | — | Disable a comma separated list of features (use --disable help to see a list) | todos |
| `--disable-http-keep-alives` | sí o no | — | Disable HTTP keep-alives and use each connection once | todos |
| `--disable-http2` | sí o no | — | Disable HTTP/2 in the global transport | todos |
| `--download-hash` | sí o no | — | Compute hash by downloading when otherwise unavailable. (warning: may be slow and use lots of data!) | bisync |
| `--dscp` | texto | — | Set DSCP value to connections, value or name, e.g. CS1, LE, DF, AF21 | todos |
| `--dump` | DumpFlags | — | List of items to dump from: headers, bodies, requests, responses, auth, filters, goroutines, openfiles, mapper, curl, errors, trace | todos |
| `--dump-bodies` | sí o no | — | Dump HTTP headers and bodies - may contain sensitive info | todos |
| `--dump-headers` | sí o no | — | Dump HTTP headers - may contain sensitive info | todos |
| `--error` | texto | — | Report all files with errors (hashing or reading) to this file | up, down, up-mirror, down-mirror |
| `--error-on-no-transfer` | sí o no | — | Sets exit code 9 if no files are transferred, useful in scripts | todos |
| `--expect-continue-timeout` | duración | 1s | Timeout when using expect / 100-continue in HTTP | todos |
| `--files-from-raw` | lista | — | Read list of source-file names from file without any processing of lines (use - to read from stdin) | todos |
| `--files-from0` | lista | — | Read list of source-file names from file using NUL as separator (use - to read from stdin) | todos |
| `--files-only` | sí o no | true | Only list files | up, down, up-mirror, down-mirror |
| `--format` | texto | p | Output format - see lsf help for details | up, down, up-mirror, down-mirror |
| `--fs-cache-expire-duration` | duración | 5m0s | Cache remotes for this long (0 to disable caching) | todos |
| `--fs-cache-expire-interval` | duración | 1m0s | Interval to check for expired remotes | todos |
| `--hash` | h | md5 | Use this hash when h is used in the format MD5\|SHA-1\|DropboxHash | up, down, up-mirror, down-mirror |
| `--hash-filter` | texto | — | Partition filenames by hash k/n or randomly @/n | todos |
| `--header` | lista | — | Set HTTP header for all transactions | todos |
| `--header-download` | lista | — | Set HTTP header for download transactions | todos |
| `--header-upload` | lista | — | Set HTTP header for upload transactions | todos |
| `--http-proxy` | texto | — | HTTP proxy URL | todos |
| `--human-readable` | sí o no | — | Print numbers in a human-readable format, sizes with suffix Ki\|Mi\|Gi\|Ti\|Pi | todos |
| `--ignore-case-sync` | sí o no | — | Ignore case when synchronizing | todos |
| `--ignore-listing-checksum` | sí o no | — | Do not use checksums for listings (add --ignore-checksum to additionally skip post-copy checksum checks) | bisync |
| `--interactive` | sí o no | — | Enable interactive mode | todos |
| `--kv-lock-time` | duración | 1s | Maximum time to keep key-value database locked by process | todos |
| `--links` | sí o no | — | Translate symlinks to/from regular files with a '.rclonelink' extension | todos |
| `--list-cutoff` | entero | 1000000 | To save memory, sort directory listings on disk above this threshold | todos |
| `--log-file-compress` | sí o no | — | If set, compress rotated log files using gzip | todos |
| `--log-file-max-age` | duración | 0s | Maximum duration to retain old log files (eg "7d") | todos |
| `--log-file-max-backups` | entero | — | Maximum number of old log files to retain | todos |
| `--log-file-max-size` | tamaño | off | Maximum size of the log file before it's rotated (eg "10M") | todos |
| `--log-format` | Bits | date,time | Comma separated list of log format options | todos |
| `--log-level` | nivel | NOTICE | Log level DEBUG\|INFO\|NOTICE\|ERROR | todos |
| `--log-systemd` | sí o no | — | Activate systemd integration for the logger | todos |
| `--match` | texto | — | Report all matching files to this file | up, down, up-mirror, down-mirror |
| `--max-backlog` | entero | 10000 | Maximum number of objects in sync or check backlog | todos |
| `--max-buffer-memory` | tamaño | off | If set, don't allocate more than this amount of memory as buffers | todos |
| `--max-stats-groups` | entero | 1000 | Maximum number of stats groups to keep in memory, on max oldest is discarded | todos |
| `--metadata` | sí o no | — | If set, preserve metadata when copying objects | todos |
| `--metadata-exclude` | lista | — | Exclude metadatas matching pattern | todos |
| `--metadata-exclude-from` | lista | — | Read metadata exclude patterns from file (use - to read from stdin) | todos |
| `--metadata-filter` | lista | — | Add a metadata filtering rule | todos |
| `--metadata-filter-from` | lista | — | Read metadata filtering patterns from a file (use - to read from stdin) | todos |
| `--metadata-include` | lista | — | Include metadatas matching pattern | todos |
| `--metadata-include-from` | lista | — | Read metadata include patterns from file (use - to read from stdin) | todos |
| `--metadata-set` | lista | — | Add metadata key=value when uploading | todos |
| `--missing-on-dst` | texto | — | Report all files missing from the destination to this file | up, down, up-mirror, down-mirror |
| `--missing-on-src` | texto | — | Report all files missing from the source to this file | up, down, up-mirror, down-mirror |
| `--multi-thread-chunk-size` | tamaño | 64Mi | Chunk size for multi-thread downloads / uploads, if not set by filesystem | todos |
| `--multi-thread-cutoff` | tamaño | 256Mi | Use multi-thread downloads for files above this size | todos |
| `--multi-thread-write-buffer-size` | tamaño | 128Ki | In memory buffer size for writing when in multi-thread mode | todos |
| `--no-check-certificate` | sí o no | — | Do not verify the server SSL certificate (insecure) | todos |
| `--no-cleanup` | sí o no | — | Retain working files (useful for troubleshooting and testing). | bisync |
| `--no-console` | sí o no | — | Hide console window (supported on Windows only) | todos |
| `--no-gzip-encoding` | sí o no | — | Don't set Accept-Encoding: gzip | todos |
| `--no-slow-hash` | sí o no | — | Ignore listing checksums only on backends where they are slow | bisync |
| `--no-traverse` | sí o no | — | Don't traverse destination file system on copy | todos |
| `--no-unicode-normalization` | sí o no | — | Don't normalize unicode characters in filenames | todos |
| `--no-update-dir-modtime` | sí o no | — | Don't update directory modification times | todos |
| `--partial-suffix` | texto | .partial | Add partial-suffix to temporary file name when --inplace is not used | todos |
| `--progress` | sí o no | — | Show progress during transfer | todos |
| `--progress-terminal-title` | sí o no | — | Show progress on the terminal title (requires -P/--progress) | todos |
| `--quiet` | sí o no | — | Print as little stuff as possible | todos |
| `--separator` | texto | ; | Separator for the items in the format | up, down, up-mirror, down-mirror |
| `--server-side-across-configs` | sí o no | — | Allow server-side operations (e.g. copy) to work across different configs | todos |
| `--slow-hash-sync-only` | sí o no | — | Ignore slow checksums for listings and deltas, but still consider them during sync calls. | bisync |
| `--stats-file-name-length` | entero | 45 | Max file name length in stats (0 for no limit) | todos |
| `--stats-log-level` | nivel | INFO | Log level to show --stats output DEBUG\|INFO\|NOTICE\|ERROR | todos |
| `--stats-one-line-date` | sí o no | — | Enable --stats-one-line and add current date/time prefix | todos |
| `--stats-one-line-date-format` | texto | — | Enable --stats-one-line-date and use custom formatted date: Enclose date string in double quotes ("), see https://golang.org/pkg/time/#Time.Format | todos |
| `--stats-unit` | texto | bytes | Show data rate in stats as either 'bits' or 'bytes' per second | todos |
| `--streaming-upload-cutoff` | tamaño | 100Ki | Cutoff for switching to chunked upload if file size is unknown, upload starts after reaching cutoff or when file ends | todos |
| `--syslog` | sí o no | — | Use Syslog for logging | todos |
| `--syslog-facility` | texto | DAEMON | Facility for syslog, e.g. KERN,USER | todos |
| `--temp-dir` | texto | — | Directory rclone will use for temporary files | todos |
| `--timeformat` | texto | — | Specify a custom time format - see docs for details (default: 2006-01-02 15:04:05) | up, down, up-mirror, down-mirror |
| `--track-renames-strategy` | texto | hash | Strategies to use when synchronizing using track-renames hash\|modtime\|leaf | bisync, up-mirror, down-mirror |
| `--use-cookies` | sí o no | — | Enable session cookiejar | todos |
| `--use-json-log` | sí o no | — | Use json log format | todos |
| `--use-mmap` | sí o no | — | Use mmap allocator (see docs) | todos |
| `--user-agent` | texto | rclone/v1.75.2 | Set the user-agent to a specified string | todos |
