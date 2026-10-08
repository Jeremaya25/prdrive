[← Guías](README.md)

# Diagnóstico y reparación

Qué te dice la ventana cuando algo no va bien, cómo arreglarlo, emparejar un móvil y ponerle nombre e icono a la unidad.

La ventana principal no grita: cuando hay algo que mirar lo dice en **una línea**
—«Hay 3 cosas que revisar»— con un botón que lleva a **Reparación**. Ahí está
todo junto y, lo que se pueda, con su arreglo al lado:

| Lo que se ve | Lo que se puede hacer |
|---|---|
| El baseline guardado no es el de esta pareja | Apartarlo (no se borra) y resincronizar |
| La pareja necesita un `--resync` | Lanzarlo desde ahí |
| Bloqueos `.lck` de una pasada cortada | Borrarlos, solo si no hay ninguna pasada en marcha |
| Ficheros en conflicto | Elegir con qué versión te quedas |
| La última pasada falló | Abrir el log que lo explica |
| Un contenedor VeraCrypt **dinámico** se queda sin sitio fuera (menos de 1 GiB libre en la unidad) | Liberar sitio fuera del contenedor. Si se llena, lo de dentro da errores de escritura en mitad de una pasada |
| **La carpeta local no está** | **Nada, a propósito**: ver abajo |

Nada se toca sin confirmarlo antes, con la misma pantalla de consecuencias que
gobierna los demás borrados. Y si falta la carpeta local de una pareja que ya
tiene baseline, **no se ofrece crearla**: un lado local vacío se lee como «se ha
borrado todo» y eso se propagaría al remoto. Lo que hay que arreglar está fuera
del programa —el volumen no está montado donde se cree, o la carpeta se movió—,
así que la pantalla lo dice y se calla.

Desde ahí también se puede **simular una pasada** (`--dry-run`) antes de
sincronizar de verdad, y ver el informe completo, que es lo mismo que:

```bash
python sync.py --doctor
```

Dice, por cada pareja: dónde apuntan sus dos extremos, si la referencia de bisync
está sana (`fresh` / `ok` / `broken`), con qué nombre la busca rclone, si los
filtros han cambiado desde el último `--resync` y si hay algún `.lck` de un
proceso muerto; y acaba con la misma lista de averías que enseña la pantalla —es
el mismo diagnóstico, escrito en vez de dibujado.

El engranaje de **«Ajustes…»** es la otra puerta a esa pantalla, y donde vive lo
que se hace de tarde en tarde: el emparejamiento de un móvil, las versiones
guardadas y el nombre e icono de la unidad.

Los logs de rclone **solo se guardan si la pasada falla** (o con `--keep-logs`),
para no gastar ciclos de escritura de la unidad. Quedan en `.prdrive/logs/`, y
de cada pareja solo se guardan los 20 últimos. Al fallar se imprime la cola del log —sin las líneas de estadísticas, que ya contó
el progreso— y se traduce el error de rclone a una explicación, si es uno de
los conocidos.

Casos habituales:

- **«Must run --resync».** Los filtros han cambiado. `python sync.py <pareja> --resync`.
- **No encuentra la referencia.** `--resync`. Un dispositivo instalado con esta
  versión no debería llegar ahí por cambiar de equipo o de letra de unidad (ver
  [`device_remote`](configuracion.md#device_remote)); si cambiaste rutas a mano, sí.
- **La ventana de parejas dice que no hay catálogo.** Sin red se abre con la
  última copia (`state/catalog.toml`) y **no deja editarlo**: no se puede
  sobrescribir con seguridad lo que no se acaba de leer. Puede que otro
  dispositivo lo haya tocado mientras tanto.

## Emparejar un móvil

**«Ajustes…» → «Emparejar un móvil…»** enseña la conexión con el remoto como un
código QR: el backend, sus opciones, dónde está el catálogo y la clave privada.
Es la forma de llevar la conexión a un aparato que no se puede enchufar al
dispositivo.

> **El código lleva la clave privada dentro.** Quien le haga una foto a la
> pantalla tendrá el mismo acceso al remoto que el dispositivo. Enséñalo solo al
> aparato que vayas a emparejar y cierra la ventana al terminar. No se guarda en
> ningún fichero ni pasa por el portapapeles.

En Windows la ventana se excluye de las capturas de pantalla y de compartir
pantalla (Recortes, Teams, Meet, OBS…) para que un descuido no la deje en un
chat o en una videollamada, y lo dice con una línea bajo el aviso. En el monitor
se ve igual y el móvil la lee igual. Con un Windows anterior a la 2004 no se
puede excluir del todo y sale **en negro** en la captura; la línea lo dice así.
No cubre una foto hecha con otro móvil, la Lupa ni los programas con privilegios,
y en el Escritorio remoto quien se conecta la ve en negro. En Linux no hay forma
de hacerlo y la ventana no dice nada al respecto.

Funciona con claves ed25519, que es lo que usa prdrive por defecto. Una clave RSA
grande no cabe en un código QR y la ventana lo dice.

## Nombre e icono de la unidad

**«Ajustes…» → «Nombre e icono de la unidad…»** cambia cómo enseña el Explorador
de Windows la unidad al conectarla: un nombre como «Pendrive de Pere» en vez de
«Disco extraíble», y de icono la marca de prdrive en uno de cinco colores, un
`.ico` tuyo o ninguno. Los colores están
para distinguir un dispositivo de otro a simple vista.

**Es también el nombre del dispositivo** en [«Dispositivos…»](uso.md#la-ventana-de-parejas):
es el único sitio donde se le pone nombre, y al guardar cambia en los dos. El
nombre nuevo llega a esa lista con la siguiente sincronización, y no hace falta
red para guardarlo. Si lo dejas vacío, la unidad se queda sin nombre propio pero
el dispositivo conserva el que tenía.

Se guarda en un `autorun.inf` en la raíz de la unidad donde están tus datos, y
el icono dentro de `.prdrive/` (`.prdrive\icono-….ico`): en la raíz no queda
nada más que el `autorun.inf`. Ese fichero **no ejecuta nada**: Windows dejó de
arrancar programas desde una unidad extraíble en Windows 7, pero el Explorador
sigue leyendo de ahí el nombre y el icono. Si ya había uno, solo se cambian esas
dos líneas; lo demás se queda como estaba. Según cómo esté protegida la unidad:

- **Con BitLocker**, Windows no puede leerlo mientras la unidad está bloqueada.
- **Con VeraCrypt**, cambia el volumen que aparece al abrir el contenedor, no el
  pendrive que se enchufa: ese conserva su nombre y su icono.

Además:

- **Se ve al volver a conectar la unidad** (con VeraCrypt, al volver a abrirla),
  no al guardar: el Explorador lee el fichero cuando llega el volumen.
- **La etiqueta del sistema de ficheros no cambia.** En Linux, y en la ruta donde
  se monta, la unidad se sigue llamando como antes.
