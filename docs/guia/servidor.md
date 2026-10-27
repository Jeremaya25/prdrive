[← Guías](README.md)

# Ver, bajar, subir y ordenar archivos del servidor

«Servidor…», en la ventana de prdrive, te deja recorrer tu servidor carpeta a carpeta, como
WinSCP: ves qué hay, cuánto ocupa cada archivo, cuándo se cambió por última vez y qué carpetas
son de una pareja. Desde ahí también puedes **bajar** archivos y carpetas al equipo y **subir**
archivos y carpetas del equipo al servidor, y **ordenarlo**: crear carpetas, cambiar nombres,
mover cosas de carpeta y borrar, que solo tocan el servidor. En el servidor, lo único que
reemplaza un archivo es «Sobrescribir» al subir, y solo si lo eliges tú; **borrar es para
siempre** (el servidor no tiene papelera).

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
- **Encima de la lista**, los botones **Nueva carpeta…**, **Renombrar…**, **Cortar** y
  **Borrar…** (ver «Ordenar el servidor»). Lo mismo sale con el botón derecho del ratón sobre la lista.
- **Abajo**, cuántos elementos hay, y junto a **Cerrar**, los botones **Bajar…**,
  **Subir archivos…** y **Subir carpeta…** (ver «Bajar y subir»).

Si la carpeta está vacía, la ventana lo dice: «Esta carpeta está vacía.»

## Las marcas

- **· pareja «Nombre»**, junto al nombre de una carpeta: es la carpeta de la pareja «Nombre», en ese mismo
  servidor. Si estás dentro de una carpeta de pareja, la ventana lo dice arriba: «Estás dentro de
  la pareja «Nombre»». Al ordenar, esas carpetas están protegidas (ver «Lo que no deja tocar»).
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
vez: mientras dura, los tres botones (y los de ordenar) están apagados.

Si rclone tarda en contestar, la ventana dice «Sin respuesta de rclone…»: la copia puede seguir en
marcha, así que los botones siguen apagados y prdrive vuelve a preguntar solo. Si rclone se ha
cerrado de verdad, lo dice y te deja «Reconectar».

### Si algo ya existe

Si en la carpeta de destino hay archivos con el mismo nombre y en el mismo sitio, prdrive
**pregunta una sola vez**, antes de copiar, y te dice cuántos son y dónde:

- **Sobrescribir**: lo que es distinto se reemplaza por la copia nueva. Lo que es igual se salta.
- **Omitir**: lo que ya existe se queda como está. Solo se copia lo que no había.
- **Cancelar**: no se copia nada.

**Nombres que solo cambian de mayúsculas.** En Windows y en unidades FAT32 o exFAT, `Foto.JPG` y
`foto.jpg` son el mismo archivo. prdrive los cuenta como iguales para el aviso (también dentro de
las carpetas), así que **pregunta** antes de sobrescribir. En un equipo que sí distingue
mayúsculas (Linux) puede avisar de más: es solo una pregunta, nunca sobrescribe sin que lo
decidas.

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
servidor conserva la versión que tenía. Así salió en las pruebas con un servidor SFTP; con otros
tipos de servidor aún no está comprobado.

Si cierras la ventana mientras se copia, prdrive pregunta si quieres cancelar la copia y cerrar.
«Seguir» no cierra nada.

### Si el programa se cierra de golpe

Si la ventana se cierra de golpe (por ejemplo, la matas desde el Administrador de tareas) mientras
se sube un archivo grande, puede quedar en el servidor un archivo temporal con una parte del
archivo. prdrive no lo borra todavía: bórralo tú desde el servidor.

## Ordenar el servidor

Todo se hace en la carpeta que estás viendo. Los botones se encienden según lo que hayas elegido.

- **Nueva carpeta…** (Ctrl+Mayús+N): pide el nombre y crea la carpeta aquí. Al acabar, queda elegida.
- **Renombrar…** (F2): con **una** fila elegida, pide el nombre nuevo. Un nombre no puede estar
  vacío, ni llevar «/», ni ser «.» o «..», ni ser el de otra cosa de la carpeta (aquí `Fotos` y
  `fotos` cuentan como el mismo nombre, porque muchos servidores los tratan como uno).
- **Mover**, con cortar y pegar: elige lo que quieras mover y pulsa **Cortar** (Ctrl+X). Encima de la
  lista aparece «3 elementos para mover desde /datos», con **Pegar aquí** y **Cancelar**. Entra en la
  carpeta de destino y pulsa **Pegar aquí** (Ctrl+V). Mientras no pegues, no se ha tocado nada.
  Puedes cambiar de carpeta, y también de servidor, con lo cortado puesto, pero solo se puede pegar
  en el servidor del que se cortó: en otro, la línea lo dice y **Pegar aquí** está apagado hasta que
  vuelvas. No se puede pegar en la carpeta de la que salió, una carpeta dentro de sí misma, ni donde
  ya haya algo con el mismo nombre: renómbralo antes. Nunca se pisa nada.
- **Borrar…** (Supr): antes cuenta lo que hay dentro («Mirando qué hay dentro…») y te pide
  confirmación con los números: «Se borrará para siempre «fotos», con 1 234 archivos (3,4 GB).».
  **No hay papelera: lo borrado no se recupera.**

Mientras dura, un panel al pie dice qué va («3 de 10 elementos») y deja **Cancelar**. Un cambio
sale de elemento en elemento: **Cancelar no corta el elemento que va, para antes del siguiente**
(rclone no sabe parar un borrado a medias). Por eso el panel dice «se para al acabar «x»», y si ese
elemento acabó mal, el resultado avisa de que puede haber quedado a medias. Al terminar, la carpeta
se vuelve a leer sola. El resultado no ofrece «Reintentar»: mira cómo ha quedado y elige otra vez.

Si cierras la ventana con un cambio en marcha, prdrive pregunta si lo cancelas y cierras.
«Seguir» no cierra nada.

### Lo que no deja tocar

Para no romper tus parejas, **no deja** (verás «No se puede» y no se hace nada):

- Borrar, renombrar o mover **la carpeta de una pareja** (su carpeta en el servidor) ni una carpeta
  que la contenga: la sincronización lo vería como que se ha perdido todo.
- Tocar **el catálogo de las parejas** (el fichero que comparten los dispositivos).
- Mover o crear algo **dentro de la carpeta de una pareja de espejo de subida** (`up-mirror`): el
  servidor tiene que quedar igual que el equipo y su próxima pasada lo borraría.

En las demás parejas deja seguir, pero antes **avisa** con lo que hará la próxima pasada, por
ejemplo «La próxima pasada de «Fotos» lo quitará también del dispositivo.» o «El dispositivo
conserva su copia: «Fotos» no borra.». Fuera de las carpetas de las parejas no hay avisos.

Las parejas **de otros dispositivos** no se conocen: este dispositivo solo sabe de las suyas. Si
tocas desde aquí la carpeta de una pareja de otro dispositivo, nadie te lo dirá.

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
- **«Ya hay algo que se llama… en esta carpeta.»** o **«Ya hay «x» en… : renómbralo antes.»**: ese
  nombre está cogido (lo mira el servidor justo antes de actuar, aunque la lista esté vieja).
  Cambia el nombre.
- **Un cambio que falla**: el panel dice qué elemento y por qué («ya no estaba», «No tienes permiso
  para borrar en /datos.», o lo que dijo rclone). Si ha fallado a mitad, dice cuántos se hicieron.
- **Una copia que falla** (sin espacio, sin permiso para escribir, se corta la red): el panel lo
  dice y ofrece **Reintentar**. Repite la copia con la misma respuesta de antes, y lo que ya
  estaba copiado y es igual no se vuelve a copiar.
- Cualquier otro mensaje es lo que dijo rclone, tal cual.

## Lo que no hace

- **No toca el equipo** al ordenar: crear, renombrar, mover y borrar son solo del servidor.
- **No tiene papelera ni deshacer.** Lo borrado se va para siempre.
- **No mueve entre servidores distintos** ni copia dentro del mismo servidor.
- Con servidores que no mueven por dentro (WebDAV, S3…), mover o renombrar una carpeta grande
  copia y borra, y tarda; todavía no está probado con ellos.
- **Cerrar la ventana corta la conexión con el servidor.** Si hay una copia en marcha, lo pregunta
  antes. No hace falta hacer nada más antes de expulsar la unidad.
