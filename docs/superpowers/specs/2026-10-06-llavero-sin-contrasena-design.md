# El llavero sin contraseña — diseño

Fecha: 06/10/2026. Parte de `2026-10-04-llavero-keepassxc-design.md`. Lo que ya
se hizo está en `docs/agents/reference/llavero.md` (sección «Key file only»);
esto es el porqué.

## Qué se quiere

Una opción para que el llavero vaya **sin contraseña**, protegido solo por un
fichero llave que **no viaja al remoto**, pensada para unidades **cifradas**
(VeraCrypt o BitLocker): el cifrado del dispositivo es la otra barrera y se
evita la contraseña diaria. Salió de un fallo real: con `--keyfile`, KeePassXC
intenta desbloquear al instante con la contraseña vacía
(`DatabaseOpenWidget::enterKey()` llama a `openDatabase()`), y con una base de
contraseña y fichero llave sale «Desbloquear la base de datos ha fallado y no
introdujo una contraseña». En una base solo con fichero llave, ese mismo
intento es lo que se quiere.

## Decisiones

1. **La bandera va en el `[keychain]` del catálogo del remoto**
   (`llave_interna = true`), para que los dispositivos nuevos lo sepan al
   activarlo y se les bloquee la opción si no están cifrados. Exige
   `fichero_llave = true`.
2. **Cifrada = VeraCrypt o BitLocker, comprobado en ejecución**
   (`common/cifrada.py`), y lo que no se puede comprobar es «no cifrada». No
   se guarda ninguna marca: una BitLocker suspendida deja de valer en el acto.
   Para poder preguntarlo desde el dispositivo, el lector de BitLocker pasa de
   `install/` a `common/` (`install/` no viaja).
3. **Sin cifrar y con la bandera: se bloquea activar y cada pasada**
   (`sync.LLAVERO_SIN_CIFRAR`, sin rclone). No se borra nada: una unidad que
   pierde el cifrado se queda con su base y su llave, pero sin sincronizar ni
   abrir (borrar sería destructivo y pediría un `EditPlan`).
4. **La llave solo se genera nueva** (prdrive nunca usa una existente), en
   `.keychain/llave.keyx` (nombre fijo, ningún filtro la deja pasar). La
   persona guarda **una copia obligatoria fuera del dispositivo** antes de que
   la base dependa de ella, y la da en cada dispositivo nuevo (se copia al
   dispositivo, no se apunta su ruta).
5. **La protección que tuviera la base se sobrescribe**
   (`keepassxc-cli db-edit --set-key-file --unset-password`), en una consola
   visible como «Combinar»: prdrive no ve la contraseña actual.
6. **Solo se avisa a los dispositivos nuevos.** Los que ya tienen el llavero no
   se enteran (no hay comparación del `[keychain]` local con el del remoto).

## Orden de lo que hace «sin contraseña» (crear)

Copiar la base (la original no se toca) → generar la llave → **guardar su
copia aparte** → `db-edit` → comprobar que la llave abre la base
(`ls --no-password`) → **solo entonces** escribir el catálogo y el dispositivo.
Si algo falla antes del catálogo, se deshace todo lo creado.

## Lo que NO se hace (v1)

- Volver a contraseña, o cambiar la llave.
- Avisar a los dispositivos que ya lo tienen.
- Crearlo desde el asistente (haría falta una consola en mitad del asistente);
  sí se puede traer el del remoto.
- Impedir que una versión vieja de prdrive ignore la bandera y no aplique el
  bloqueo.

## Lo que no está comprobado

Por lectura del código fuente y del manual de KeePassXC 2.7.12, no en hardware:
que `--keyfile` con la contraseña vacía abra una base solo-llave sin pantalla de
desbloqueo; que `ls --no-password --key-file` sirva de sonda (el CI real lo
comprueba con la CLI de verdad, paso 8 de `llavero_real.py`); que `db-edit
--set-key-file` acepte una llave que ya existe (el CI también); y qué hace
`merge --no-password` con `--same-credentials`. El plan de pruebas a mano está en
`docs/superpowers/pruebas/2026-10-06-llavero-sin-contrasena-plan.md`.
