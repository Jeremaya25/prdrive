[← Guías](README.md)

# Ver lo que hay en el servidor

«Servidor…», en la ventana de prdrive, te deja recorrer tu servidor carpeta a carpeta, como
WinSCP: ves qué hay, cuánto ocupa cada archivo, cuándo se cambió por última vez y qué carpetas
son de una pareja. **Solo mira.** No copia, no sube, no borra ni cambia nada en el servidor.

> **Sin probar todavía en un equipo de verdad.** Está cubierto por pruebas automáticas, pero no
> se ha probado todavía con un servidor real en un equipo real. Si algo no cuadra, dilo tal cual
> lo ves.

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
- **Abajo**, cuántos elementos hay. **Cerrar** cierra la ventana.

Si la carpeta está vacía, la ventana lo dice: «Esta carpeta está vacía.»

## Las marcas

- **⇄ Nombre**, junto al nombre de una carpeta: es la carpeta de la pareja «Nombre», en ese mismo
  servidor. Si estás dentro de una carpeta de pareja, la ventana lo dice arriba: «Estás dentro de
  la pareja «Nombre»». Esta versión solo lo señala.
- **Candado**: no puedes entrar en esa carpeta. Aparece cuando, al intentar entrar, el servidor
  dice que no tienes permiso. Mientras la ventana siga abierta, la carpeta se queda apagada con el
  candado. El candado no lleva texto: se reconoce por el dibujo.

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
- Cualquier otro mensaje es lo que dijo rclone, tal cual.

## Lo que no hace

- **No escribe nada en el servidor.** Ni archivos, ni carpetas, ni cambios de nombre.
- **Cerrar la ventana corta la conexión con el servidor.** No hace falta hacer nada más antes de
  expulsar la unidad.
