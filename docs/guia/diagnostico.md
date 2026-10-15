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
| **El freno de borrados paró la pasada** (casi todo ha desaparecido de un lado, o han cambiado todos los ficheros) | Ver qué se borraría y, si es lo que querías, **forzar una sola pasada** ([más abajo](#cuando-salta-el-freno-de-borrados)) |
| Un contenedor VeraCrypt **dinámico** se queda sin sitio fuera (menos de 1 GiB libre en la unidad) | Liberar sitio fuera del contenedor. Si se llena, lo de dentro da errores de escritura en mitad de una pasada |
| **La carpeta local no está** | **Nada, a propósito**: ver abajo |

Nada se toca sin confirmarlo antes, con la misma pantalla de consecuencias que
gobierna los demás borrados. Y si falta la carpeta local de una pareja que ya
tiene baseline, **no se ofrece crearla**: un lado local vacío se lee como «se ha
borrado todo» y eso se propagaría al remoto. Lo que hay que arreglar está fuera
del programa —el volumen no está montado donde se cree, o la carpeta se movió—,
así que la pantalla lo dice y se calla.

## Rehacer la referencia cuando tú quieras

«Reparación» ofrece **Resincronizar…** cuando una pareja `bisync` lo necesita. Si
quieres rehacer la referencia de una pareja sin que haya ningún aviso —porque has
movido ficheros a mano por los dos lados, por ejemplo—, está también en **Parejas →
Modificar… → Avanzado → Resincronizar…**.

- Enseña lo mismo que «Reparación» antes de hacer nada: compara los dos lados
  enteros, no borra nada por estar en uno solo y, si la pareja guarda versiones,
  deja copia de lo que sobrescriba. Si cancelas, no pasa nada.
- Trae una casilla, **marcada**, para **apartar la referencia actual antes**: queda en
  `state/<pareja>.old-<fecha>/`, sin borrarse, por si quieres volver atrás a mano. Si la
  desmarcas, el resync la sustituye por la nueva.
- **No es «Forzar sincronización…»**: aquello salta el freno de borrados en una sola
  pasada; esto rehace la referencia y no salta ningún freno.
- Solo está en las parejas `bisync` (`up`, `down` y los espejos no tienen referencia que
  rehacer), y no se ofrece si falta la carpeta local de una pareja que ya tiene
  referencia: mira antes si el volumen está montado.
- Si has cambiado algo en la ventana de la pareja y no lo has guardado, guárdalo o
  descártalo antes: el resync usa la pareja tal como está guardada.
- Lo pide siempre una persona: no lo lanza el servicio, ni el arranque automático, ni el
  agente.

## Cuando salta el freno de borrados

Si de golpe desaparece casi todo de un lado, lo más probable es un error —la
unidad no está montada donde toca, la carpeta es otra, el remoto está vacío— y no
una decisión tuya. Por eso rclone frena, y no se mide igual en todos los modos:

- **Las parejas `bisync`** paran cuando ha desaparecido de un lado más de un
  **porcentaje** de los ficheros que había en la última sincronización (un 25 % de
  fábrica). Al parar no han copiado nada. Paran también si **todos** los ficheros
  de un lado han cambiado (pasa con un cambio de hora, o al tocar toda la carpeta).
- **Los espejos** (`up-mirror`, `down-mirror`) borran hasta un **número** de
  ficheros (50 de fábrica) y paran. Ojo: esos ya se han borrado y no vuelven; lo
  que frena es lo que queda por borrar.

«Reparación» lo cuenta con las cifras y el lado, en vez de dejarlo en un «la última
pasada falló»: *«Se han borrado 3429 de 3452 ficheros (99 %) en el dispositivo… La
pasada se paró para no copiar ese borrado al remoto.»* Y trae tres botones:

| Botón | Qué hace |
|---|---|
| **Ver qué se borraría** | La misma pasada en simulacro (`--dry-run`): enseña los ficheros que borraría y no toca nada. No pide confirmación. |
| **Forzar sincronización…** | Enseña lo que va a pasar —qué se borrará y dónde, y que si ese lado está desmontado o vacío por error, se pierde— y solo si le dices que sí lanza **una** pasada sin el freno. |
| **Ver el log** | Abre el log de la pasada que paró. |

Forzar vale **para esa pasada y nada más**: la siguiente vuelve a llevar el freno. No
lo hace nunca el servicio, ni el arranque automático, ni el agente, ni se puede
dejar puesto en el config. Y no se ofrece si falta la carpeta local, ni en la
pareja del llavero.

Antes de forzar, mira ese lado: ¿está montado el volumen?, ¿es la carpeta de
siempre? Hay salidas menos peligrosas:

- En una pareja `bisync`, si los ficheros se borraron por error, un `--resync` los
  recupera desde el otro lado: junta los dos lados sin borrar nada.
- En un espejo, arregla el origen (móntalo, recupera la carpeta) y la siguiente
  pasada vuelve a copiar lo que falte. Un espejo no guarda versiones: lo que ya
  borró no se puede recuperar de ahí.

Desde la consola, con la pareja nombrada (sin nombre, o junto a `--resync`, se
rechaza):

```bash
python sync.py notas --dry-run --force   # qué borraría, sin tocar nada
python sync.py notas --force             # una pasada sin el freno
```

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
guardadas, el nombre e icono de la unidad… Es una sola ventana: a la izquierda
los apartados, agrupados, y a la derecha el elegido. Arriba, **«Buscar un
ajuste»** deja en la barra solo los que tienen que ver con lo que escribes
(«intervalo» encuentra «Configuración»).

Los logs de rclone **solo se guardan si la pasada falla** (o con `--keep-logs`),
para no gastar ciclos de escritura de la unidad. Quedan en `.prdrive/logs/`, y
cada vez que se guarda uno nuevo se quedan los 20 últimos de esa pareja (con
`--keep-logs`, los de las pasadas buenas van desplazando a los de las que
fallaron). Al fallar se imprime la cola del log —sin las líneas de estadísticas,
que ya contó el progreso— y se traduce el error de rclone a una explicación, si
es uno de los conocidos.

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

**«Ajustes…» → «Emparejar un móvil»** enseña la conexión con el remoto como un
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

**«Ajustes…» → «Nombre e icono»** cambia cómo enseña el Explorador
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

- **Con BitLocker**, Windows no puede leerlo mientras la unidad está bloqueada,
  y desbloqueada enseña el nombre pero deja el candado de BitLocker como icono.
- **Con VeraCrypt**, cambia el volumen que aparece al abrir el contenedor, no el
  pendrive que se enchufa: ese conserva su nombre y su icono. En Windows, el
  Explorador no lee ese fichero dentro de un contenedor de VeraCrypt, así que
  prdrive le dice el nombre y el icono de esa letra mientras el contenedor esté
  abierto (en tu registro de usuario, sin pedir administrador), y lo quita al
  expulsarlo. Lo hace prdrive al arrancar desde la unidad («Abrir PRDRIVE», su
  ventana o el agente de este equipo): si abres el contenedor solo con
  VeraCrypt, sale con el icono de siempre.

Además:

- **Se ve al volver a conectar la unidad**, no al guardar: el Explorador lee el
  fichero cuando llega el volumen. Con VeraCrypt en Windows se ve enseguida en
  «Este equipo» (en una ventana que ya estaba abierta, al pulsar F5).
- **La etiqueta del sistema de ficheros no cambia.** En Linux, y en la ruta donde
  se monta, la unidad se sigue llamando como antes.
