# prdrive

Esta unidad se sincroniza sola con tu servidor. Aquí está lo justo para usarla.
La documentación completa está en el repositorio del proyecto.

---

## Para empezar

**Doble clic en `runsync.bat`.** Se abre una ventana con tus carpetas: marca las
que quieras y pulsa **Sincronizar ahora**. (Una consola negra parpadea un instante
y se va: es el lanzador soltando la ventana.)

En Linux el lanzador es `runsync.sh`.

No hace falta instalar nada en el equipo: la unidad lleva su propio Python para
los sistemas que se eligieron al prepararla. Si la conectas en uno que no estaba
previsto, el lanzador te lo dice: vuelve a pasar el instalador (`prdrive-install`)
sobre esta unidad y pulsa **Añadir plataformas…**. Si la unidad se preparó en
modo *ligero* (con un `runsync.pyw` en la raíz), entonces sí hace falta **Python
3.11 o superior** en cada equipo.

## Qué hay en esta unidad

| | |
|---|---|
| `runsync.bat` / `runsync.sh` | los lanzadores. Empieza siempre por aquí |
| `sync-data/` | **tus carpetas sincronizadas** |
| `.prdrive/` | el programa, rclone, su Python y el fichero de control. Está oculta a propósito; no hace falta tocarla |
| `VeraCrypt/` | solo si la unidad va cifrada con VeraCrypt: el propio VeraCrypt, para poder abrirla en equipos que no lo tengan |
| `autorun.inf` | el nombre y el icono con que la ve Windows. No ejecuta nada |

## La ventana

- **Sincronizar ahora** — una pasada de lo marcado, en una ventana aparte; al
  cerrarla vuelves aquí con todo al día.
- **Iniciar servicio** — sincroniza lo marcado cada N minutos (lo pones justo
  encima) mientras la unidad siga conectada. Se para solo al extraerla, o al
  volver a abrir la ventana. Lo marcado y el intervalo se recuerdan para la
  próxima vez.
- **Diagnóstico** — cuando algo no cuadra. Enseña dónde apunta cada carpeta y si
  su sincronización está sana.
- **Expulsar** — solo si la unidad va cifrada con VeraCrypt. Cierra la ventana y
  el contenedor; cuando el aviso diga que está cerrado, ya se puede quitar.

Encima de los botones hay una línea que dice qué hace **este ordenador** al
conectar la unidad, con un botón para cambiarlo: abrir esta ventana, arrancar el
servicio o hacer una pasada. Se instala por usuario, sin permisos de
administrador, y no escribe nada aquí dentro.

Debajo de la lista, **Parejas** — añadir, quitar o cambiar carpetas sincronizadas.

## Añadir una carpeta

**Parejas → Catálogo → Añadir.** Se pide un nombre, la carpeta de aquí, la ruta
en el servidor y el modo. Lo que des de alta ahí queda disponible **para todos
tus dispositivos**, y cada uno elige después si la usa.

Los modos, en corto:

| modo | qué hace |
|---|---|
| **bisync** | dos direcciones. Lo normal para documentos y notas |
| **up** | solo sube. Nunca borra en el servidor |
| **down** | solo baja. Nunca borra en el servidor |
| **up-mirror** | espejo hacia el servidor. **Borra allí** lo que no esté aquí |
| **down-mirror** | espejo hacia aquí. **Borra aquí** lo que no esté allí |

Los dos últimos borran de verdad. Antes de estrenar uno, pruébalo con
**Simular**.

## Ponerle nombre e icono

**Ajustes (el engranaje) → Nombre e icono de la unidad…** Así la verás en el
Explorador de Windows con tu nombre y tu icono en vez de «Disco extraíble». Se
nota la próxima vez que la conectes.

## Si algo va mal

**Pulsa Diagnóstico.** Casi siempre te dice qué pasa.

- **«Hay que rehacer la referencia» / pide un resync.** Normal si has cambiado
  los filtros o las rutas de una carpeta bisync. Dale a **Rehacer la
  referencia**: compara los dos lados y vuelve a fijar el punto de partida. No
  borra por diferencias.
- **No hay conexión.** La ventana se abre igual y trabaja con lo último que
  sabía. No deja tocar el catálogo hasta que vuelva la red, para no pisar lo que
  hayan hecho tus otros dispositivos.
- **Un fichero cambiado en los dos sitios.** Se queda con el que diga la
  configuración de esa carpeta (el más nuevo, el más grande, o un lado fijo) y
  guarda el otro al lado con otro nombre. No se pierde nada. La carpeta sale con
  un aviso ámbar de **conflicto** hasta que decidas: pulsa **Revisar…**, mira las
  dos versiones y quédate con una.
- **Un aviso ámbar de que falló la última pasada.** Esa carpeta no está al día.
  **Ver el log** enseña qué dijo rclone. Si el servicio periódico está en marcha,
  él mismo abre una ventanita en cuanto algo empieza a fallar.

Cuando una pasada falla se guarda su registro en `.prdrive/logs/`. Cuando va
bien no se guarda nada, para no gastar la memoria de la unidad.

## Cuidado con esto

**Dentro de esta unidad va la clave de tu servidor**, en `.prdrive/keys/`. Quien
la encuentre entra en tus datos hasta que revoques esa clave.

- Ten la unidad **cifrada** (VeraCrypt o BitLocker). Si no lo está, vuelve a
  pasar el instalador y hazlo.
- Si va con VeraCrypt, fuera del contenedor, en la raíz de la unidad, está
  **Abrir PRDRIVE**: pide la contraseña y abre esta ventana. Sirve también en un
  equipo sin VeraCrypt instalado, con el que viaja en la carpeta `VeraCrypt\`;
  entonces hará falta aceptar el aviso de permisos de administrador: montar carga
  un driver y no hay otra forma.
  ¿Se te queda pequeño el contenedor? `VeraCrypt\VeraCryptExpander.exe` lo
  agranda sin rehacerlo.
- No borres `.prdrive/`. Si desaparece, el arranque automático deja
  de reconocer la unidad y hay que reinstalar.
- **Extráela con seguridad.** El programa no escribe nada mientras no sincroniza,
  así que basta con cerrar la ventana antes. Si va con VeraCrypt, usa
  **Expulsar** en la ventana (o **Expulsar PRDRIVE** en la raíz de la unidad):
  cierra la ventana y el contenedor. Mientras el contenedor está abierto, Windows
  no deja extraer la unidad, y tirar del cable puede estropear lo de dentro.

## Actualizar

Cuando haya una versión nueva, la ventana te lo dirá en un recuadro naranja al
abrirla. Pulsa **Actualizar…** y ya está: se descarga, se sustituye el programa
y la ventana se vuelve a abrir sola. Tu configuración, tus claves y tus datos no
se tocan.

Si prefieres hacerlo a mano, vuelve a pasar el instalador (`prdrive-install`)
sobre esta misma unidad y elige **Actualizar el programa**: es lo mismo.
