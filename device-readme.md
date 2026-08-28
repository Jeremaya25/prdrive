# prdrive

Esta unidad se sincroniza sola con tu servidor. Aquí está lo justo para usarla.
La documentación completa está en el repositorio del proyecto.

---

## Para empezar

**Doble clic en `runsync.pyw`.** Se abre una ventana con tus carpetas: marca las
que quieras y pulsa **Sincronizar ahora**.

En Linux o macOS el lanzador es `runsync.sh`.

Hace falta **Python 3.11 o superior** en el equipo donde lo conectes. Si no lo
hay, la ventana no se abre: instálalo desde [python.org](https://www.python.org)
y marca la casilla *«Add Python to PATH»*.

## Qué hay en esta unidad

| | |
|---|---|
| `runsync.pyw` / `runsync.sh` | los lanzadores. Empieza siempre por aquí |
| `sync-data/` | **tus carpetas sincronizadas** |
| `PRDRIVE` | fichero de control. **No lo borres**: es lo que identifica esta unidad |
| `.prdrive/` | el programa. Está oculta a propósito; no hace falta tocarla |

## La ventana

- **Sincronizar ahora** — una pasada y a otra cosa.
- **Cada N minutos** — deja un servicio en marcha mientras la unidad siga
  conectada. Se para solo al extraerla, o al volver a abrir la ventana.
- **Diagnóstico** — cuando algo no cuadra. Enseña dónde apunta cada carpeta y si
  su sincronización está sana.

Abajo del todo hay dos botones más:

- **Parejas** — añadir, quitar o cambiar carpetas sincronizadas.
- **Arranque automático** — que el ordenador lance esto solo al conectar la
  unidad. Se instala por usuario, sin permisos de administrador, y no escribe
  nada aquí dentro.

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
  guarda el otro al lado con otro nombre. No se pierde nada.

Cuando una pasada falla se guarda su registro en `.prdrive/logs/`. Cuando va
bien no se guarda nada, para no gastar la memoria de la unidad.

## Cuidado con esto

**Dentro de esta unidad va la clave de tu servidor**, en `.prdrive/keys/`. Quien
la encuentre entra en tus datos hasta que revoques esa clave.

- Ten la unidad **cifrada** (VeraCrypt o BitLocker). Si no lo está, vuelve a
  pasar el instalador y hazlo.
- No borres `PRDRIVE` ni `.prdrive/`. Si desaparecen, el arranque automático deja
  de reconocer la unidad y hay que reinstalar.
- **Extráela con seguridad.** El programa no escribe nada mientras no sincroniza,
  así que basta con cerrar la ventana antes.

## Actualizar

Cuando haya una versión nueva, la ventana te lo dirá en un recuadro naranja al
abrirla. Pulsa **Actualizar…** y ya está: se descarga, se sustituye el programa
y la ventana se vuelve a abrir sola. Tu configuración, tus claves y tus datos no
se tocan.

Si prefieres hacerlo a mano, vuelve a pasar el instalador (`prdrive-install`)
sobre esta misma unidad y elige **Instalar el programa**: es lo mismo.
