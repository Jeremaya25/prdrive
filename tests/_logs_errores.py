#!/usr/bin/env python3
"""Lo que dice rclone al fallar, para los tests de `common/errores.py`.

No es un test (`run_all.py` solo recoge `test_*.py`). Hay dos procedencias, y cada
entrada de `LINEAS` dice la suya:

- **capturada**: el log que `sync.py` dejó en `logs/` cuando la pasada falló,
  capturado con el rclone fijado en `common/pins.py` (v1.75.2, la compilación oficial
  de Linux x64, comprobada contra su SHA256SUMS) lanzando `sync.py` (y con él
  `sync.run_pair()`) sobre un dispositivo de prueba: remoto `nas` de tipo `local`,
  `device_remote = "disp"` y las órdenes que arma `sync.build_command()` tal cual.
  Para los filtros y los listados que faltan se quitó la comprobación previa de
  prdrive (`bisync.resync_reasons()`), que salta la pareja antes de que rclone lo
  diga. Se han quitado las líneas `INFO` y el JSON de bisync; lo único cambiado de
  lo demás es la carpeta temporal del dispositivo de prueba, que aquí es
  `/tmp/prdrive-errores`.
- **del código fuente**: la frase que escribe el código de rclone v1.75.2 (o del
  módulo que fija su `go.mod`), con el fichero y la línea; el resto de la línea de
  log es el formato de rclone, puesto a mano. Son los errores que no se pueden
  provocar sin una cuenta de verdad (OAuth, los límites y la cuota de Google).

Los textos de Windows no están aquí: `test_errores.py` los pide a
`ctypes.FormatError()` del propio Windows, y los de un Windows en español esperan
su prueba en real (`docs/superpowers/pruebas/2026-10-27-errores-rclone-pendiente-en-real.md`).
"""

CAPTURADA = "capturada"
"""Procedencia: un log de verdad del rclone fijado."""
FUENTE = "del código fuente"
"""Procedencia: la frase del código fuente de rclone v1.75.2 o de un módulo de su `go.mod`."""

SIN_LISTADOS = """\
2026/10/27 10:34:03 ERROR : Bisync critical error: cannot find prior Path1 or Path2 listings, likely due to critical error on prior run
Tip: here are the filenames we were looking for. Do they exist?
Path1: /tmp/prdrive-errores/.prdrive/state/notas/disp_sync-data_notas..nas__tmp_prdrive-errores_remoto_notas.path1.lst
Path2: /tmp/prdrive-errores/.prdrive/state/notas/disp_sync-data_notas..nas__tmp_prdrive-errores_remoto_notas.path2.lst
Try running this command to inspect the work dir:
rclone lsl "/tmp/prdrive-errores/.prdrive/state/notas"
2026/10/27 10:34:03 ERROR : Bisync aborted. Error is retryable without --resync due to --resilient mode.
2026/10/27 10:34:03 NOTICE: Failed to bisync: bisync aborted
"""
"""bisync con los dos `.lst` apartados del workdir (y la comprobación previa de prdrive quitada, que si no la salta). Da `sin_referencia`."""

FILTROS_CAMBIADOS = """\
2026/10/27 10:02:57 ERROR : Bisync critical error: filters file has changed (must run --resync): /tmp/prdrive-errores/.prdrive/filters/notas.txt
2026/10/27 10:02:57 ERROR : Bisync aborted. Error is retryable without --resync due to --resilient mode.
2026/10/27 10:02:57 NOTICE: Failed to bisync: bisync aborted
"""
"""bisync con el `.md5` de los filtros cambiado (y la comprobación previa de prdrive quitada). Da `filtros`."""

FILTROS_SIN_MD5 = """\
2026/10/27 10:03:08 ERROR : Bisync critical error: filters file md5 hash not found (must run --resync): /tmp/prdrive-errores/.prdrive/filters/notas.txt
2026/10/27 10:03:08 ERROR : Bisync aborted. Error is retryable without --resync due to --resilient mode.
2026/10/27 10:03:08 NOTICE: Failed to bisync: bisync aborted
"""
"""bisync sin el `.md5` de los filtros (y la comprobación previa de prdrive quitada). Da `filtros`."""

BLOQUEO = """\
2026/10/27 10:02:21 NOTICE: Failed to bisync: prior lock file found: /tmp/prdrive-errores/.prdrive/state/notas/disp_sync-data_notas..nas__tmp_prdrive-errores_remoto_notas.lck
Tip: this indicates that another bisync run (of these same paths) either is still running or was interrupted before completion.
If you're SURE you want to override this safety feature, you can delete the lock file with the following command, then run bisync again:
rclone deletefile "/tmp/prdrive-errores/.prdrive/state/notas/disp_sync-data_notas..nas__tmp_prdrive-errores_remoto_notas.lck"
"""
"""bisync con un `.lck` que caduca en 2099 en el workdir de la pareja. Da `bloqueo`."""

SIN_CARPETA_REMOTA_BISYNC = """\
2026/10/27 10:01:58 ERROR : Local file system at /tmp/prdrive-errores/remoto/notas: error reading source root directory: directory not found
2026/10/27 10:01:58 ERROR : Bisync critical error: directory not found
2026/10/27 10:01:58 ERROR : Bisync aborted. Must run --resync to recover.
2026/10/27 10:01:58 NOTICE: Failed to bisync with 2 errors: last error was: bisync aborted
"""
"""bisync `--resync` contra una carpeta del remoto que no existe: la causa concreta gana al «Must run --resync» que la sigue. Da `carpeta_remota`."""

SIN_CARPETA_REMOTA = """\
2026/10/27 10:00:26 ERROR : Local file system at /tmp/prdrive-errores/remoto/no-esta: error reading source root directory: directory not found
2026/10/27 10:00:26 ERROR : Attempt 1/3 failed with 1 errors and: directory not found
2026/10/27 10:00:26 ERROR : Local file system at /tmp/prdrive-errores/remoto/no-esta: error reading source root directory: directory not found
2026/10/27 10:00:26 ERROR : Attempt 2/3 failed with 1 errors and: directory not found
2026/10/27 10:00:26 ERROR : Local file system at /tmp/prdrive-errores/remoto/no-esta: error reading source root directory: directory not found
2026/10/27 10:00:26 ERROR : Attempt 3/3 failed with 1 errors and: directory not found
2026/10/27 10:00:26 NOTICE: Failed to copy: directory not found
"""
"""`down` desde una carpeta del remoto que no existe. Da `carpeta_remota`."""

RED_RECHAZADA = """\
2026/10/27 10:00:52 NOTICE: caido: No host key validation is being performed. Set known_hosts_file (to "none" to silence this notice) or use --sftp-pin-host-key to enable it. See: https://rclone.org/sftp/#host-key-validation
2026/10/27 10:01:04 CRITICAL: Failed to create file system for "caido:/x": NewFs: couldn't connect SSH: dial tcp 127.0.0.1:1: connect: connection refused
"""
"""sftp a `127.0.0.1:1`, donde no escucha nadie. Da `red`."""

RED_DNS = """\
2026/10/27 10:01:04 NOTICE: inexistente: No host key validation is being performed. Set known_hosts_file (to "none" to silence this notice) or use --sftp-pin-host-key to enable it. See: https://rclone.org/sftp/#host-key-validation
2026/10/27 10:01:04 CRITICAL: Failed to create file system for "inexistente:/x": NewFs: couldn't connect SSH: dial tcp: lookup prdrive-no-existe.invalid on 8.8.8.8:53: no such host
"""
"""sftp a un host `.invalid`, que no resuelve. Da `red`."""

SFTP_AUTENTICACION = """\
2026/10/27 10:01:14 NOTICE: clave: No host key validation is being performed. Set known_hosts_file (to "none" to silence this notice) or use --sftp-pin-host-key to enable it. See: https://rclone.org/sftp/#host-key-validation
2026/10/27 10:01:14 CRITICAL: Failed to create file system for "clave:/x": NewFs: couldn't connect SSH: ssh: handshake failed: ssh: unable to authenticate, attempted methods [none password], no supported methods remain
"""
"""sftp a un `rclone serve sftp` local que espera otro usuario y otra contraseña. Da `autenticacion`."""

SIN_SECCION = """\
2026/10/27 10:00:27 CRITICAL: Failed to create file system for "nohay:/x": didn't find section in config file ("nohay")
"""
"""una pareja cuyo remoto no está en `rclone.conf`. Da `sin_seccion`."""

SIN_EXTREMO = """\
2026/10/27 10:35:24 NOTICE: sinclave: No host key validation is being performed. Set known_hosts_file (to "none" to silence this notice) or use --sftp-pin-host-key to enable it. See: https://rclone.org/sftp/#host-key-validation
2026/10/27 10:35:24 CRITICAL: Failed to create file system for "sinclave:/x": couldn't connect to ssh-agent: SSH agent requested but SSH_AUTH_SOCK not-specified
"""
"""sftp sin contraseña ni clave y sin `SSH_AUTH_SOCK`: no hay causa más concreta que el extremo que no se abre. Da `sin_extremo`."""

PERMISO = """\
2026/10/27 10:34:49 ERROR : permiso/cerrada: failed to open directory "permiso/cerrada": open /tmp/prdrive-errores/sync-data/permiso/cerrada: permission denied
2026/10/27 10:34:49 ERROR : Can't retry any of the errors - not attempting retries
2026/10/27 10:34:49 NOTICE: Failed to copy: failed to open directory "permiso/cerrada": open /tmp/prdrive-errores/sync-data/permiso/cerrada: permission denied
"""
"""`up` con una subcarpeta local en `chmod 000`, lanzado como `nobody` (root lo lee todo). Da `permiso`."""

NOMBRE_LARGO = """\
2026/10/27 10:34:34 ERROR : dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd: failed to get info about directory entry "/tmp/prdrive-errores/r/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd": lstat /tmp/prdrive-errores/r/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd: file name too long
2026/10/27 10:34:34 ERROR : Can't retry any of the errors - not attempting retries
2026/10/27 10:34:34 NOTICE: Failed to copy: failed to get info about directory entry "/tmp/prdrive-errores/r/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd": lstat /tmp/prdrive-errores/r/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd/dddd: file name too long
"""
"""`down` de un árbol del remoto cuya ruta pasa de PATH_MAX (4096). Cada `dddd` era una carpeta de 200 `d`. Da `nombre_invalido`."""

DISCO_LLENO = """\
2026/10/27 10:35:09 NOTICE: grande.bin.0b73b83b.partial: Removing partially written file on error: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 ERROR : grande.bin: Failed to copy: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 ERROR : Attempt 1/3 failed with 1 errors and: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 NOTICE: grande.bin.0b73b83b.partial: Removing partially written file on error: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 ERROR : grande.bin: Failed to copy: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 ERROR : Attempt 2/3 failed with 1 errors and: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 NOTICE: grande.bin.0b73b83b.partial: Removing partially written file on error: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 ERROR : grande.bin: Failed to copy: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 ERROR : Attempt 3/3 failed with 1 errors and: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
2026/10/27 10:35:09 NOTICE: Failed to copy: write /tmp/prdrive-errores/remoto/lleno/grande.bin.0b73b83b.partial: no space left on device
"""
"""`up` de 300 KB a un remoto `local` en un tmpfs de 64 KB, con `local-no-preallocate = true` en los flags de la pareja. Da `disco_lleno`."""

DISCO_LLENO_RESERVA = """\
2026/10/27 10:34:56 ERROR : grande.bin: Failed to copy: preallocate: file too big for remaining disk space
2026/10/27 10:34:56 ERROR : Attempt 1/3 failed with 1 errors and: preallocate: file too big for remaining disk space
2026/10/27 10:34:56 ERROR : grande.bin: Failed to copy: preallocate: file too big for remaining disk space
2026/10/27 10:34:56 ERROR : Attempt 2/3 failed with 1 errors and: preallocate: file too big for remaining disk space
2026/10/27 10:34:56 ERROR : grande.bin: Failed to copy: preallocate: file too big for remaining disk space
2026/10/27 10:34:56 ERROR : Attempt 3/3 failed with 1 errors and: preallocate: file too big for remaining disk space
2026/10/27 10:34:56 NOTICE: Failed to copy: preallocate: file too big for remaining disk space
"""
"""Lo mismo con los flags de fábrica: rclone reserva el sitio antes y avisa él (lib/file/preallocate.go:6). Da `disco_lleno`."""

FLAG_DESCONOCIDO = """\
--- salida directa de rclone (no pasó por --log-file) ---
Error: unknown flag: --no-existe-esto
2026/10/27 10:34:13 NOTICE: Fatal error: unknown flag: --no-existe-esto
"""
"""`no-existe-esto = true` en los flags de la pareja. Da `flag_desconocido`."""

FLAG_VALOR = """\
--- salida directa de rclone (no pasó por --log-file) ---
Error: invalid argument "muchos" for "--checkers" flag: parsing "muchos" as int failed: expected integer
2026/10/27 10:34:13 NOTICE: Fatal error: invalid argument "muchos" for "--checkers" flag: parsing "muchos" as int failed: expected integer
"""
"""`checkers = "muchos"` en los flags de la pareja. Da `flag_valor`."""

OAUTH_CADUCADO = (
    '2026/10/27 10:00:00 ERROR : Attempt 1/3 failed with 1 errors and: couldn\'t list '
    'directory: Get "https://www.googleapis.com/drive/v3/files": maybe token expired? - try '
    'refreshing with "rclone config reconnect drive:"\n')
"""lib/oauthutil/oauthutil.go:302 (la sugerencia que acompaña a un token rechazado). Da `autenticacion`."""
OAUTH_SIN_TOKEN = (
    "2026/10/27 10:00:00 CRITICAL: Failed to create file system for \"drive:notas\": "
    "couldn't fetch token: unauthorized_client: if you're using your own client id/secret, "
    "make sure they're properly set up following the docs\n")
"""lib/oauthutil/oauthutil.go:368 (`couldn't fetch token: %w`). Da `autenticacion` y no `sin_extremo`."""
LIMITE_API = (
    "2026/10/27 10:00:00 ERROR : nota.md: Failed to copy: googleapi: Error 403: User rate "
    "limit exceeded., userRateLimitExceeded\n")
"""backend/drive/drive.go:959 (el motivo), escrito por googleapi.Error.Error() (google.golang.org/api v0.293.0, googleapi/googleapi.go:117). Da `limite_api`."""
CUOTA_DRIVE = (
    "2026/10/27 10:00:00 ERROR : nota.md: Failed to copy: googleapi: Error 403: The user's "
    "Drive storage quota has been exceeded., storageQuotaExceeded\n")
"""backend/drive/drive.go:968 (el motivo), con el mismo formato que `LIMITE_API`. Da `remoto_lleno`."""
CUOTA_DESCARGA = (
    "2026/10/27 10:00:00 ERROR : nota.md: Failed to copy: googleapi: Error 403: The download "
    "quota for this file has been exceeded., downloadQuotaExceeded\n")
"""backend/drive/drive.go:965: es otro límite (de descarga), no un remoto lleno. No da `remoto_lleno`."""
SIN_ESPACIO_HTTP = (
    "2026/10/27 10:00:00 ERROR : nota.md: Failed to copy: 507 Insufficient Storage: \n")
"""backend/onedrive/onedrive.go:1055: sin error propio del servidor, el código es `resp.Status` (el 507 de net/http). Da `remoto_lleno`."""

LINEAS = (
    (SIN_LISTADOS, "sin_referencia", CAPTURADA),
    (FILTROS_CAMBIADOS, "filtros", CAPTURADA),
    (FILTROS_SIN_MD5, "filtros", CAPTURADA),
    (BLOQUEO, "bloqueo", CAPTURADA),
    (SIN_CARPETA_REMOTA_BISYNC, "carpeta_remota", CAPTURADA),
    (SIN_CARPETA_REMOTA, "carpeta_remota", CAPTURADA),
    (RED_RECHAZADA, "red", CAPTURADA),
    (RED_DNS, "red", CAPTURADA),
    (SFTP_AUTENTICACION, "autenticacion", CAPTURADA),
    (SIN_SECCION, "sin_seccion", CAPTURADA),
    (SIN_EXTREMO, "sin_extremo", CAPTURADA),
    (PERMISO, "permiso", CAPTURADA),
    (NOMBRE_LARGO, "nombre_invalido", CAPTURADA),
    (DISCO_LLENO, "disco_lleno", CAPTURADA),
    (DISCO_LLENO_RESERVA, "disco_lleno", CAPTURADA),
    (FLAG_DESCONOCIDO, "flag_desconocido", CAPTURADA),
    (FLAG_VALOR, "flag_valor", CAPTURADA),
    (OAUTH_CADUCADO, "autenticacion", FUENTE),
    (OAUTH_SIN_TOKEN, "autenticacion", FUENTE),
    (LIMITE_API, "limite_api", FUENTE),
    (CUOTA_DRIVE, "remoto_lleno", FUENTE),
    (SIN_ESPACIO_HTTP, "remoto_lleno", FUENTE),
)
"""Cada log con la clave que tiene que dar y su procedencia."""

ABORTO = "2026/10/27 10:01:58 ERROR : Bisync aborted. Must run --resync to recover.\n"
"""La línea del aborto crítico de bisync, sacada de `SIN_CARPETA_REMOTA_BISYNC`. Sola, da `critico`."""
