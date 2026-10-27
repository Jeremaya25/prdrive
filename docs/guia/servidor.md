[← Guías](README.md)

# Ver, bajar y subir archivos del servidor

«Servidor…», en la ventana de prdrive, te deja recorrer tu servidor carpeta a carpeta, como
WinSCP: ves qué hay, cuánto ocupa cada archivo, cuándo se cambió por última vez y qué carpetas
son de una pareja. Desde ahí también puedes **bajar** archivos y carpetas al equipo y **subir**
archivos y carpetas del equipo al servidor. **No borra nada ni cambia nombres**, ni en el
servidor ni en el equipo. Lo único que puede reemplazar un archivo es «Sobrescribir», y solo si
lo eliges tú.

> **Probado solo con un servidor de prueba en Linux.** Está cubierto por pruebas automáticas y
> se ha probado con un servidor SFTP de prueba, pero no todavía con un servidor real, ni en
> Windows, ni con unidades FAT32 o exFAT. Si algo no cuadra, dilo tal cual lo ves.

## Abrirlo

En la ventana principal, pulsa **Servidor…**, entre «Parejas…» y «Ajustes…». Se puede pulsar
cuando el dispositivo tiene al menos un servidor al que ir. Mientras hay una sincronización en
marcha, el botón está apagado.

Al abrirlo, la ventana aparece enseguida con «Conectando con el servidor…» y, en cuanto contesta,
enseña la carpeta de arriba del todo.

## La ventana

- **Arriba**, el desplegable elige el servidor. A su derecha va la **carpeta en la que estás**.
  **↑** sube a la carpeta de encima (en la de arriba del todo no hace nada). **Releer** vuelve
  a leer la carpeta, por si algo ha cambiado.
- **La lista**, con las carpetas primero y luego los archivos:
  - **Nombre**: con su icono.
  - **Tamaño**: en B, KB, MB… Las carpetas no llevan tamaño («—»): el servidor no lo da sin
    recorrerlas.
  - **Modificado**: la fecha y la hora en tu equipo. «—» si el servidor no la sabe.
  - **Permisos**: ver más abajo.
- **Entrar** en una carpeta: doble clic en ella, o selecciónala y pulsa Intro. **Retroceso** sube.
- Puedes elegir varias filas a la vez con Ctrl o Mayús.
- **Abajo**, cuántos elementos hay, y junto a **Cerrar**, los botones **Bajar…**,
  **Subir archivos…** y **Subir carpeta…** (ver «Bajar y subir»).

Si la carpeta está vacía, la ventana lo dice: «Esta carpeta está vacía.»

## Las marcas

- **· pareja «Nombre»**, junto al nombre de una carpeta: es la carpeta de la pareja «Nombre», en ese mismo
  servidor. Si estás dentro de una carpeta de pareja, la ventana lo dice arriba: «Estás dentro de
  la pareja «Nombre»». Esta versión solo lo señala.
- **Candado**: no puedes entrar en esa carpeta. Aparece cuando, al intentar entrar, el servidor
  dice que no tienes permiso. Mientras la ventana siga abierta, la carpeta se queda apagada con el
  candado. El candado no lleva texto: se reconoce por el dibujo.

## Bajar y subir

- **Bajar…**: elige en la lista lo que quieres (una o varias filas, carpetas o archivos), pulsa
  **Bajar…** y elige la carpeta del equipo donde guardarlo. Las carpetas se guardan con todo lo
  que tienen dentro.
- **Subir archivos…**: elige archivos de tu equipo. Se suben a la carpeta del servidor que estás
  viendo.
- **Subir carpeta…**: elige una carpeta de tu equipo. Se sube entera, con su nombre, a la carpeta
  que estás viendo.

Mientras se copia, un panel al pie de la lista muestra qué archivo va, cuántos llevas, la
velocidad y cuánto falta. Puedes seguir mirando carpetas mientras tanto. Solo hay una copia a la
vez: mientras dura, los tres botones están apagados.

Si rclone tarda en contestar, la ventana dice «Sin respuesta de rclone…»: la copia puede seguir en
marcha, así que los botones siguen apagados y prdrive vuelve a preguntar solo. Si rclone se ha
cerrado de verdad, lo dice y te deja «Reconectar».

### Si algo ya existe

Si en la carpeta de destino hay archivos con el mismo nombre y en el mismo sitio, prdrive
**pregunta una sola vez**, antes de copiar, y te dice cuántos son y dónde:

- **Sobrescribir**: lo que es distinto se reemplaza por la copia nueva. Lo que es igual se salta.
- **Omitir**: lo que ya existe se queda como está. Solo se copia lo que no había.
- **Cancelar**: no se copia nada.

**Cuidado con los nombres que solo cambian de mayúsculas**, en Windows y en unidades FAT32 o
exFAT: `Foto.JPG` y `foto.jpg` son el mismo archivo para el equipo, pero prdrive no los toma por
iguales y **no pregunta**: sobrescribe. Mira los nombres antes de bajar a una carpeta que ya tiene
archivos parecidos.

### Carpetas de una pareja

Lo que copies dentro de la carpeta de una pareja lo verá su siguiente sincronización, como
cualquier cambio. Por eso:

- **Subir** a la carpeta del servidor de una pareja: si la pareja es **espejo de subida**
  (`up-mirror`), prdrive **no deja subir**, porque la sincronización borraría lo subido: el
  servidor tiene que quedar igual que el equipo. En las demás parejas, prdrive avisa de lo que
  hará la pareja con lo subido y te deja seguir o cancelar.
- **Bajar** a la carpeta del equipo de una pareja: si es **espejo de bajada** (`down-mirror`),
  prdrive **no deja bajar**, por la misma razón. En las demás, avisa y te deja seguir o cancelar.
- Fuera de las carpetas de las parejas (el escritorio, «Descargas»…), no hay avisos.

### Cancelar

**Cancelar**, en el panel, para la copia. Lo que ya se había copiado se queda. El archivo que iba
a medias no deja restos: si era una subida que iba a reemplazar un archivo del servidor, el
servidor conserva la versión que tenía.

Si cierras la ventana mientras se copia, prdrive pregunta si quieres cancelar la copia y cerrar.
«Seguir» no cierra nada.

### Si el programa se cierra de golpe

Si la ventana se cierra de golpe (por ejemplo, la matas desde el Administrador de tareas) mientras
se sube un archivo grande, puede quedar en el servidor un archivo temporal con una parte del
archivo. prdrive no lo borra todavía: bórralo tú desde el servidor.

## La columna «Permisos» y el «—»

Los permisos son los de Linux: tres cifras, como `755` (el dueño puede todo; los demás, leer y
entrar). Con la versión de rclone que trae prdrive ahora, los servidores SFTP **no dan los
permisos**, y la columna dice «—» en todas sus filas. Es lo esperado, no un fallo. Cuando rclone los dé,
la columna los mostrará.

Por eso, de momento, el candado sale solo después de intentar entrar, no antes.

## Si algo falla

Lo que pasa aparece en la línea de arriba de la lista, y la carpeta que veías antes se queda en
pantalla.

- **«No tienes permiso para ver esta carpeta.»**: sale el candado. Nada más.
- **«No hay conexión con el servidor.»**: si pasa al abrir la ventana, aparece **Reintentar**. Si
  pasa estando dentro, vuelve a intentarlo con **Releer** cuando haya red.
- **«Esa carpeta ya no existe en el servidor.»**: alguien la ha borrado o movido. Sube con ↑.
- **«El servidor no ha contestado a tiempo.»**: el servidor tarda demasiado. Vuelve a intentarlo con
  **Releer**.
- **«Se ha perdido la conexión con rclone.»**: el programa que habla con el servidor se ha parado.
  **Reconectar** lo vuelve a poner en marcha y repite la última carpeta.
- **«El puerto que se eligió para rclone ya lo usa otro programa.»**: prdrive prueba una vez más con
  otro puerto. Si vuelve a fallar, aparece **Reintentar**.
- **«Este dispositivo no tiene conexión con ningún servidor.»**: no hay ningún servidor configurado
  en el dispositivo.
- **Una copia que falla** (sin espacio, sin permiso para escribir, se corta la red): el panel lo
  dice y ofrece **Reintentar**. Repite la copia con la misma respuesta de antes, y lo que ya
  estaba copiado y es igual no se vuelve a copiar.
- Cualquier otro mensaje es lo que dijo rclone, tal cual.

## Lo que no hace

- **No borra nada y no cambia nombres**, ni en el servidor ni en el equipo.
- **Cerrar la ventana corta la conexión con el servidor.** Si hay una copia en marcha, lo pregunta
  antes. No hace falta hacer nada más antes de expulsar la unidad.
