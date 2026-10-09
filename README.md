# prdrive

Sincroniza una **unidad extraíble** (pendrive, SSD, tarjeta…) con **cualquier remoto de rclone**: SFTP, WebDAV, S3, Google Drive… Conectas la unidad en cualquier equipo, se abre una ventana y se sincroniza. No hay nada que instalar en el equipo —ni siquiera Python— ni servicios de terceros por medio.

- **Tu remoto es tuyo.** Vale lo que soporte rclone; el programa no conoce ningún servidor concreto.
- **El programa viaja en la unidad**, con su propio rclone y su propio Python (versiones fijadas y comprobadas). Es Python puro, solo biblioteca estándar.
- **Windows y Linux**, en x64 y ARM64, con la misma unidad. macOS no está: no hay equipo con el que probarlo.

> **Ojo: prdrive mueve y borra ficheros.** Los modos `*-mirror` borran en el destino lo que no esté en el origen. Antes de estrenar uno, prueba con **Simular** (en **Parejas**). Lee las [notas importantes](#notas-importantes).

## Cómo funciona

- **Tu remoto** guarda solo configuración: el *catálogo* de carpetas a sincronizar («parejas»). Nunca guarda el programa.
- **La unidad** lleva el programa y la conexión con su clave, y elige cuáles de esas parejas usa.
- **El equipo** donde la enchufas no necesita nada instalado.

## Instalar una unidad

Necesitas un **remote de rclone** al que puedas escribir. Se hace una vez por unidad:

1. Descarga `prdrive-install.exe` de la [última release](https://github.com/Jeremaya25/prdrive/releases/latest) y ábrelo. En Linux, o si prefieres no usar el `.exe`: clona el repositorio y ejecuta `python prdrive-install.py` (Python 3.11+ con Tk 9: `python -c "import tkinter; print(tkinter.TkVersion)"` tiene que decir 9.0 o más).
2. Elige **«En una unidad»** y sigue el asistente. Te pregunta qué unidad usar, si quieres **cifrarla**, cómo conectarte a tu remoto, qué carpetas sincronizar y para qué sistemas debe funcionar.
3. Al terminar, la unidad está lista.

La primera vez no existe todavía el catálogo: crea las carpetas desde la ventana (**Parejas → Catálogo → Añadir**). Las unidades siguientes heredan la conexión y las carpetas.

Más detalle: [Instalación](docs/guia/instalacion.md) · [Cifrar con VeraCrypt](docs/guia/cifrado.md)

## Usar la unidad

- **Windows:** doble clic en `runsync.bat`, en la raíz de la unidad. **Linux:** `runsync.sh`.
- Marca las carpetas que quieras y pulsa **Sincronizar ahora**.
- **Iniciar servicio** sincroniza cada cierto tiempo mientras la unidad siga conectada.
- Si algo falla, la ventana lo dice en una línea («Hay 3 cosas que revisar») y **Reparación** te lleva al arreglo.
- Cuando hay una versión nueva, la ventana lo avisa: **Actualizar** la instala sin tocar tu configuración ni tus datos.
- **Para quitar la unidad**, cierra la ventana antes.

Si la unidad va cifrada con VeraCrypt, empieza por **Abrir PRDRIVE** (en la raíz de la unidad) y termina con **Expulsar**.

¿Quieres que se sincronice sola al enchufarla? Hay dos formas, las dos opcionales y sin permisos de administrador: el **vigilante** (en la ventana, la línea «Al enchufarlo en este equipo…») o el **agente residente**, que se instala en el ordenador con el asistente («En este equipo»). Ver [servicio y vigilante](docs/guia/servicio-y-vigilante.md) y [agente residente](docs/guia/agente-residente.md).

Más detalle: [Uso diario](docs/guia/uso.md)

## Modos de sincronización

Cada carpeta («pareja») tiene un modo:

| Modo | Qué hace | Qué borra |
|---|---|---|
| `bisync` | Sincroniza en los dos sentidos. Lo normal para documentos y notas | Los borrados de un lado pasan al otro, con un tope del 25 % |
| `up` | Solo sube: unidad → remoto | Nada |
| `down` | Solo baja: remoto → unidad | Nada |
| `up-mirror` | Espejo: deja el remoto igual que la unidad | **En el remoto**, lo que no esté en la unidad (tope: 50 ficheros) |
| `down-mirror` | Espejo: deja la unidad igual que el remoto | **En la unidad**, lo que no esté en el remoto (tope: 50 ficheros) |

Más detalle: [Configuración, modos y filtros](docs/guia/configuracion.md)

## Notas importantes

- **La clave de tu remoto vive dentro de la unidad** (en `.prdrive/keys/`). Quien la encuentre entra en tus datos hasta que revoques esa clave. **Cífrala** (el asistente ayuda con VeraCrypt y BitLocker) y usa en el servidor un usuario dedicado y limitado, no el administrador.
- **Los modos `*-mirror` borran de verdad.** Pruébalos siempre con **Simular** antes.
- **No borres la carpeta oculta `.prdrive/`**: es el programa, con rclone, su Python y la clave. Sin ella hay que reinstalar.
- **Con VeraCrypt, la contraseña no se guarda en ningún sitio**: si la pierdes, el contenedor no se recupera.
- **Si un fichero cambia en los dos lados**, bisync se queda con el más reciente y guarda el otro al lado con otro nombre. La ventana lo avisa y en **Reparación** eliges con cuál quedarte. No se pierde nada.
- **Sin conexión**, la ventana se abre con lo último que sabía, pero no deja tocar el catálogo hasta que vuelva la red.
- **Las actualizaciones se descargan de GitHub y no están firmadas.** Se comprueban (HTTPS, CRC, versión), tu clave no interviene y solo se sustituyen los ficheros del programa. Detalle en [Seguridad](docs/guia/seguridad.md).
- **Hay partes sin probar todavía en hardware real**, como el agente residente (bandeja, avisos, carpeta del equipo) o abrir un contenedor VeraCrypt en Linux sin VeraCrypt instalado. Cada guía lo dice donde toca.

## Más información

Las [guías](docs/guia/README.md) tienen el detalle:

- **Para empezar:** [Instalación](docs/guia/instalacion.md) · [Cifrar con VeraCrypt](docs/guia/cifrado.md)
- **Día a día:** [Uso diario](docs/guia/uso.md) · [Configuración, modos y filtros](docs/guia/configuracion.md) · [Conflictos y versiones](docs/guia/conflictos-y-versiones.md) · [Diagnóstico y reparación](docs/guia/diagnostico.md) · [El llavero](docs/guia/llavero.md)
- **Que se sincronice sola:** [Servicio y vigilante](docs/guia/servicio-y-vigilante.md) · [Agente residente](docs/guia/agente-residente.md)
- **Por dentro:** [Cómo funciona](docs/guia/como-funciona.md) · [Seguridad](docs/guia/seguridad.md)

¿Vas a tocar el código? Empieza por [AGENTS.md](AGENTS.md).

## Licencia

Apache License 2.0: el texto completo está en [`LICENSE`](LICENSE).
