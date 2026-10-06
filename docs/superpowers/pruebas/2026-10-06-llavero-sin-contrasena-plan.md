# El llavero sin contraseña — plan de pruebas en hardware

Especificación: `../specs/2026-10-06-llavero-sin-contrasena-design.md`. Nada de
esto se ha hecho aún: cada fila es lo que hay que ver con una persona delante.
Los códigos son los de esta tabla (SC-n).

| # | Qué se hace | Qué debe pasar |
|---|---|---|
| SC-1 | En una unidad **VeraCrypt**, «Ajustes → Llavero… → Usar esta base, sin contraseña…» con una base con contraseña | Pide dónde guardar la copia de la llave (fuera de la unidad); una consola pide la contraseña actual; acaba bien; la base y `.keychain/llave.keyx` están en la unidad y la copia donde se dijo |
| SC-2 | «Abrir llavero» después | KeePassXC se abre **sin pedir nada**: la base ya está desbloqueada (`--keyfile` con la contraseña vacía) |
| SC-3 | Lo mismo en una unidad **sin cifrar** | Se rechaza antes de tocar nada, diciendo que hace falta cifrar |
| SC-4 | Con BitLocker `On`, y con BitLocker **suspendido** | `On` lo permite; suspendido, no (y una pasada ya activada deja de correr) |
| SC-5 | Otro dispositivo cifrado: «Traer el del remoto» | Pide el fichero llave; copiado a `.keychain/llave.keyx`; la primera pasada trae la base; «Abrir llavero» la abre sin pedir nada |
| SC-6 | Otro dispositivo con una llave equivocada | «Abrir llavero» dice que la llave no abre la base (sin abrir KeePassXC); «Dar el fichero llave…» la cambia |
| SC-7 | Otro dispositivo **sin cifrar**, «Traer el del remoto» | Se rechaza; en el asistente también |
| SC-8 | Guardar en los dos dispositivos a la vez y combinar | La copia de conflicto se combina **sin pedir contraseña** |
| SC-9 | Quitar el cifrado de una unidad con el llavero activo (o suspender BitLocker) | La pasada falla con el motivo, «Reparación» lo dice, la base y la llave siguen en su sitio |
| SC-10 | Mirar el remoto | La base está (`keychain/`); **no** hay ningún `llave.keyx` |
| SC-11 | Un dispositivo que ya tenía el llavero con contraseña, cuando otro lo pasa a «sin contraseña» | Documentar qué le pasa (no está avisado: la base que baja no se abre con su contraseña) |
| SC-12 | «Desactivar…» en un dispositivo con este modo | Avisa de que la llave se queda |

Resultados: pendientes (se apuntarán en un `…-resultados.md` aparte, como los de
`2026-10-04-keepassxc-portatil-resultados.md`).
