[← Guías](README.md)

# Seguridad

Qué hay que saber antes de usar prdrive con datos que te importen.

Léelo entero antes de usar esto con datos que te importen.

- **La clave de tu remoto vive dentro del dispositivo**, en `.prdrive/keys/`.
  Quien lo encuentre entra en tus datos hasta que revoques esa clave. **Cífralo**
  (el asistente ayuda con VeraCrypt y BitLocker) y usa en el servidor un usuario
  dedicado y limitado, no el administrador.
- **La clave nunca sube al remoto.** Ninguna pareja sincroniza `.prdrive/`: las
  que sincronizan la raíz entera (`local = "."`) llevan una regla del programa que
  la deja fuera, y el config no puede quitarla. Las rutas del `rclone.conf` del
  dispositivo son relativas (`key_file = keys/…`), que es además lo que lo hace
  funcionar con cualquier letra de unidad.
- **Si una versión anterior ya subió `.prdrive/`, bórrala del remoto.** El programa
  no borra nada por su cuenta: una pareja `bisync` de la raíz entera pide un
  `--resync` tras actualizar, y la confirmación te dice dónde está esa copia. Como
  lleva tu clave, conviene además cambiarla por otra.
- **Los modos `*-mirror` borran.** `--max-delete` es el único freno automático.
  Prueba siempre con `--dry-run` primero.
- **Escribir el catálogo es lo más arriesgado del programa**, porque gobierna
  borrados en todos tus dispositivos. Por eso `catalog.push()` genera y verifica
  el TOML antes de tocar la red, **relee el remoto y se niega si ha cambiado**
  desde que se leyó, deja una copia del catálogo a su lado (`.bak`) y solo
  entonces sube.
- **Actualizarse descarga y ejecuta código.** Conviene saber exactamente qué lo
  respalda, que es esto y nada más: HTTPS con validación de certificado contra
  `api.github.com` y `codeload.github.com`, el CRC del zip, que estén todos los
  ficheros que tiene que traer, y que el `VERSION` de dentro cuadre con el tag
  que se pidió. **No hay firma**: el repositorio es público y este es el nivel
  que hay. Tu clave privada no interviene en ningún momento — el remoto ni se
  toca—, y lo que se sustituye son solo los ficheros del programa.
- **El instalador con perfil incrustado lleva tu clave privada.** No lo publiques.
- **El instalador descarga rclone y Python**, y lo que baja se ejecuta y acaba
  copiado dentro del dispositivo. Los dos son de su publicador —nada se compila
  aquí—, de la versión **fijada** en `common/pins.py` (el zip versionado de
  rclone, nunca el alias `current`; la release concreta de python-build-standalone),
  y se comprueban contra el `SHA256SUMS` que publica cada uno. Si no cuadra **no
  se guarda nada**. Un archivo de Python que traiga un solo miembro que se salga
  de su carpeta se rechaza entero antes de escribir el primero. Con la misma
  honestidad que arriba: esas sumas viajan desde el mismo servidor y por el mismo
  TLS que lo que describen, así que no protegen de que rclone.org o GitHub estén
  comprometidos. Sí de una descarga a medias, de un proxy que devuelve otra cosa
  y de una caché que sirve un artefacto viejo. Un fallo de red se reintenta; una
  suma que no cuadra **no**: el archivo llegó entero, así que no es un corte sino
  otra cosa contestando en su lugar, y se te dice con las dos sumas. Lo que dejes
  **a mano** en la caché (el zip o el archivo oficial, con su `SHA256SUMS`) pasa
  por la misma comprobación, y protege de lo mismo: los dos salen del mismo
  servidor.
  Lo mismo vale cuando el **dispositivo** pone al día sus componentes desde la
  ventana: es la misma maquinaria, ejecutada desde el zip del código recién
  descargado y verificado. Y una garantía más, porque aquí se sustituye algo que
  ya funcionaba: el intercambio es un renombrado, así que un corte deja el
  componente de antes exactamente como estaba, nunca uno a medias.
- **La clave de recuperación de BitLocker no la toca el programa.** Leerla exige
  permisos de administrador y no compensaba: guárdala donde te diga Windows,
  pero **no dentro del dispositivo** —es el volumen que descifra, así que ahí no
  serviría de nada—.
