[← Guías](README.md)

# Conflictos y versiones

Qué pasa cuando un fichero cambia en los dos lados y cómo guardar versiones anteriores.

## Conflictos

Cuando un fichero cambia en los dos lados entre dos pasadas, bisync no elige en
silencio: con `--conflict-resolve newer` se queda con el más reciente, le cambia
el nombre al otro añadiéndole un sufijo, y copia los dos a los dos lados. Hasta
aquí, eso solo quedaba en el log de rclone —que se borra si la pasada fue bien— y
en un fichero con un nombre raro que nadie miraba, mientras las dos versiones
seguían separándose.

Ahora, después de cada pasada, `sync.py` recorre la carpeta local de la pareja,
encuentra esas copias y lo dice en su salida. La ventana pone un chip ámbar en la
pareja y los cuenta en su línea de **«cosas que revisar»**, que lleva a
**Reparación**: allí están, con sus versiones —«versión de este dispositivo» y
«versión del remoto», con tamaño y fecha—, y se elige con cuál quedarse. Eso pasa por la misma confirmación que
los demás borrados, toca **solo ficheros de este dispositivo** y la siguiente
pasada lleva el resultado al remoto. El aviso no es un suceso que se lee y se
olvida: se deriva del disco, y se va solo cuando ya no quedan copias, las haya
borrado quien las haya borrado.

**Por qué el sufijo lleva el lado.** Con el sufijo de fábrica de rclone
(`.conflict`) y `--conflict-loser num`, la copia se llama `.conflictN` con el
primer número libre (`cmd/bisync/resolve.go`), y ese número es un orden, no un
lado: después no hay forma de saber de quién era. Por eso `bisync` lleva
`--conflict-suffix conflicto-dispositivo,conflicto-remoto`: la copia se llama
`informe.docx.conflicto-remoto1` y el nombre lo dice, y sigue numerada, así que un
segundo conflicto en el mismo fichero no pisa la copia del primero (con
`--conflict-loser pathname` sí lo haría). Quien interpreta el nombre,
`common/conflicts.py`, lo lee de los flags de la pareja igual que rclone, así que
cambiar esos flags en el TOML sigue funcionando. Los `.conflictN` que ya hubiera
se siguen reconociendo, pero sin lado: ahí se elige una versión concreta.

## Versiones

Elegir entre dos versiones solo sirve cuando las dos están delante. Si lo que
pasó es que el otro lado traía un cambio más nuevo y se quedó con él, la versión
anterior no está en ninguna parte. Para eso está `versions`, en una pareja
bisync:

```toml
[[pair]]
name = "notas"
local = "sync-data/notas"
remote_path = "/datos/notas"
mode = "bisync"
versions = true
```

Con eso, **cada lado aparta en `.prversions/`** —dentro de la propia pareja— lo
que él pierde, con la estructura de carpetas del pair y la fecha en el nombre:

```
sync-data/notas/.prversions/2026/enero/memoria~20260922-093000.docx
```

Cubre lo que se sobrescribe, lo que se borra —también el borrado que llega del
otro lado— y el perdedor de un conflicto, que así deja de quedarse suelto dentro
de la carpeta. También guarda durante un `--resync`, que es donde hoy el lado
perdedor desaparece sin decir nada.

Tres cosas que conviene saber:

- **Son dos históricos independientes, no una copia.** bisync excluye
  `.prversions/`, y esa exclusión no es una preferencia: es la condición que pone
  rclone para aceptar un `--backup-dir` dentro del destino. Cada lado guarda lo
  suyo, que es exactamente lo que hace Syncthing con su `.stversions`.
- **Encenderlo o apagarlo cambia los filtros**, así que la pareja pedirá un
  `--resync`. Y al apagarlo, `.prversions/` deja de estar excluida y lo guardado
  empieza a sincronizarse como contenido normal. La ventana lo avisa antes de
  guardar.
- **Nadie la limpia sola.** Lo que ocupa cada lado, abrir la carpeta y purgar lo
  anterior a una fecha están en **«Ajustes…» → «Versiones»**, con la misma
  confirmación que los demás borrados.
