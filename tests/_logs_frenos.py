#!/usr/bin/env python3
"""Logs REALES de los frenos de borrado de rclone, para los tests de `common/frenos.py`.

No es un test (`run_all.py` solo recoge `test_*.py`). Cada log es el que `sync.py`
dejó en `logs/` cuando la pasada falló, capturado con el rclone fijado en
`common/pins.py` (v1.75.2, la compilación oficial de Linux x64, comprobada contra
su SHA256SUMS) lanzando `sync.run_pair()` sobre un dispositivo de prueba: remoto
`nas` de tipo `local`, `device_remote = "disp"` (el de un dispositivo instalado) y
las órdenes que arma `sync.build_command()` tal cual, sin tocar nada a mano.

Lo único que se ha cambiado respecto a lo que escribió rclone es la carpeta
temporal del dispositivo de prueba (`/tmp/prdrive-test-<aleatorio>`), que aquí es
`/tmp/prdrive-frenos`. Las cifras (8 de 10, 50 borrados y 5 pendientes) son las
de rclone.

Para repetirlos: montar un dispositivo con una pareja del modo que toque, hacer
una pasada buena (`--resync` en bisync), borrar o cambiar los ficheros del lado
que se dice en cada constante y lanzar la pasada de nuevo.
"""

BISYNC_BORRADOS = """\
2026/10/15 09:35:35 INFO  : Setting --ignore-listing-checksum as neither --checksum nor --compare checksum are set.
2026/10/15 09:35:35 INFO  : Bisyncing with Comparison Settings: 
{
	"Modtime": true,
	"Size": true,
	"Checksum": false,
	"HashType1": 0,
	"HashType2": 0,
	"NoSlowHash": false,
	"SlowHashSyncOnly": false,
	"SlowHashDetected": true,
	"DownloadHash": false
}
2026/10/15 09:35:35 INFO  : lock file renewed for 2m0s. New expiration: 2026-10-15 09:37:35.940680085 +0000 UTC m=+120.064273753
2026/10/15 09:35:35 INFO  : Synching Path1 "disp{JCcy6}:sync-data/notas/" with Path2 "nas:/tmp/prdrive-frenos/remoto/notas/"
2026/10/15 09:35:35 INFO  : Using filters file /tmp/prdrive-frenos/filters/notas.txt
2026/10/15 09:35:35 INFO  : Building Path1 and Path2 listings
2026/10/15 09:35:35 INFO  : Path1 checking for diffs
2026/10/15 09:35:35 INFO  : - Path1             File was deleted                            - nota01.md
2026/10/15 09:35:35 INFO  : - Path1             File was deleted                            - nota02.md
2026/10/15 09:35:35 INFO  : - Path1             File was deleted                            - nota03.md
2026/10/15 09:35:35 INFO  : - Path1             File was deleted                            - nota04.md
2026/10/15 09:35:35 INFO  : - Path1             File was deleted                            - nota05.md
2026/10/15 09:35:35 INFO  : - Path1             File was deleted                            - nota06.md
2026/10/15 09:35:35 INFO  : - Path1             File was deleted                            - nota07.md
2026/10/15 09:35:35 INFO  : - Path1             File was deleted                            - nota08.md
2026/10/15 09:35:35 INFO  : Path1:    8 changes:    0 new,    0 modified,    8 deleted
2026/10/15 09:35:35 INFO  : Path2 checking for diffs
2026/10/15 09:35:35 ERROR : Safety abort: too many deletes (>25%, 8 of 10) on Path1 "disp{JCcy6}:sync-data/notas/". Run with --force if desired.
2026/10/15 09:35:35 NOTICE: Bisync aborted. Please try again.
2026/10/15 09:35:35 INFO  :           0 B / 0 B, -, 0 B/s, ETA -
2026/10/15 09:35:35 NOTICE: Failed to bisync: too many deletes
"""
"""bisync, `notas` en el dispositivo: 10 ficheros sincronizados y se borran 8 en el dispositivo (el freno de bisync, `max-delete = 25`, es un PORCENTAJE del listado anterior). rc 1."""

BISYNC_CAMBIADOS = """\
2026/10/15 09:35:36 INFO  : Setting --ignore-listing-checksum as neither --checksum nor --compare checksum are set.
2026/10/15 09:35:36 INFO  : Bisyncing with Comparison Settings: 
{
	"Modtime": true,
	"Size": true,
	"Checksum": false,
	"HashType1": 0,
	"HashType2": 0,
	"NoSlowHash": false,
	"SlowHashSyncOnly": false,
	"SlowHashDetected": true,
	"DownloadHash": false
}
2026/10/15 09:35:36 INFO  : lock file renewed for 2m0s. New expiration: 2026-10-15 09:37:36.12065677 +0000 UTC m=+120.066950601
2026/10/15 09:35:36 INFO  : Synching Path1 "disp{EuHVX}:sync-data/notas/" with Path2 "nas:/tmp/prdrive-frenos/remoto/notas/"
2026/10/15 09:35:36 INFO  : Using filters file /tmp/prdrive-frenos/filters/notas.txt
2026/10/15 09:35:36 INFO  : Building Path1 and Path2 listings
2026/10/15 09:35:36 INFO  : Path1 checking for diffs
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota01.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota02.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota03.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota04.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota05.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota06.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota07.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota08.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota09.md
2026/10/15 09:35:36 INFO  : - Path1             File changed: size (larger), time (newer)   - nota10.md
2026/10/15 09:35:36 INFO  : Path1:   10 changes:    0 new,   10 modified,    0 deleted
2026/10/15 09:35:36 INFO  : (Modified:   10 newer,    0 older,   10 larger,    0 smaller)
2026/10/15 09:35:36 INFO  : Path2 checking for diffs
2026/10/15 09:35:36 ERROR : Safety abort: all files were changed on Path1 "disp{EuHVX}:sync-data/notas/". Run with --force if desired.
2026/10/15 09:35:36 NOTICE: Bisync aborted. Please try again.
2026/10/15 09:35:36 INFO  :           0 B / 0 B, -, 0 B/s, ETA -
2026/10/15 09:35:36 NOTICE: Failed to bisync: all files were changed
"""
"""bisync: se modifican los 10 ficheros del dispositivo y ninguno queda igual. rc 1."""

ESPEJO_UP = """\
2026/10/15 09:35:36 INFO  : nota14.md: Deleted
2026/10/15 09:35:36 INFO  : nota38.md: Deleted
2026/10/15 09:35:36 INFO  : nota19.md: Deleted
2026/10/15 09:35:36 INFO  : nota15.md: Deleted
2026/10/15 09:35:36 INFO  : nota54.md: Deleted
2026/10/15 09:35:36 INFO  : nota49.md: Deleted
2026/10/15 09:35:36 INFO  : nota41.md: Deleted
2026/10/15 09:35:36 INFO  : nota52.md: Deleted
2026/10/15 09:35:36 INFO  : nota55.md: Deleted
2026/10/15 09:35:36 INFO  : nota06.md: Deleted
2026/10/15 09:35:36 INFO  : nota12.md: Deleted
2026/10/15 09:35:36 INFO  : nota08.md: Deleted
2026/10/15 09:35:36 INFO  : nota33.md: Deleted
2026/10/15 09:35:36 INFO  : nota13.md: Deleted
2026/10/15 09:35:36 INFO  : nota02.md: Deleted
2026/10/15 09:35:36 INFO  : nota20.md: Deleted
2026/10/15 09:35:36 INFO  : nota28.md: Deleted
2026/10/15 09:35:36 INFO  : nota10.md: Deleted
2026/10/15 09:35:36 INFO  : nota09.md: Deleted
2026/10/15 09:35:36 INFO  : nota11.md: Deleted
2026/10/15 09:35:36 INFO  : nota32.md: Deleted
2026/10/15 09:35:36 INFO  : nota24.md: Deleted
2026/10/15 09:35:36 INFO  : nota16.md: Deleted
2026/10/15 09:35:36 INFO  : nota25.md: Deleted
2026/10/15 09:35:36 INFO  : nota36.md: Deleted
2026/10/15 09:35:36 INFO  : nota21.md: Deleted
2026/10/15 09:35:36 INFO  : nota27.md: Deleted
2026/10/15 09:35:36 INFO  : nota34.md: Deleted
2026/10/15 09:35:36 INFO  : nota18.md: Deleted
2026/10/15 09:35:36 INFO  : nota39.md: Deleted
2026/10/15 09:35:36 INFO  : nota35.md: Deleted
2026/10/15 09:35:36 INFO  : nota37.md: Deleted
2026/10/15 09:35:36 INFO  : nota29.md: Deleted
2026/10/15 09:35:36 INFO  : nota17.md: Deleted
2026/10/15 09:35:36 INFO  : nota07.md: Deleted
2026/10/15 09:35:36 INFO  : nota22.md: Deleted
2026/10/15 09:35:36 INFO  : nota43.md: Deleted
2026/10/15 09:35:36 INFO  : nota40.md: Deleted
2026/10/15 09:35:36 INFO  : nota44.md: Deleted
2026/10/15 09:35:36 INFO  : nota45.md: Deleted
2026/10/15 09:35:36 INFO  : nota23.md: Deleted
2026/10/15 09:35:36 INFO  : nota31.md: Deleted
2026/10/15 09:35:36 INFO  : nota26.md: Deleted
2026/10/15 09:35:36 INFO  : nota50.md: Deleted
2026/10/15 09:35:36 INFO  : nota30.md: Deleted
2026/10/15 09:35:36 INFO  : nota53.md: Deleted
2026/10/15 09:35:36 INFO  : nota47.md: Deleted
2026/10/15 09:35:36 INFO  : nota46.md: Deleted
2026/10/15 09:35:36 ERROR : nota05.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 INFO  : nota04.md: Deleted
2026/10/15 09:35:36 INFO  : nota51.md: Deleted
2026/10/15 09:35:36 ERROR : nota42.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 ERROR : nota48.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 ERROR : nota01.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 ERROR : nota03.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 ERROR : Cancelling sync due to fatal error: failed to delete 5 files
2026/10/15 09:35:36 ERROR : Local file system at /tmp/prdrive-frenos/remoto/notas: not deleting directories as there were IO errors
2026/10/15 09:35:36 ERROR : Fatal error received - not attempting retries
2026/10/15 09:35:36 INFO  :           0 B / 0 B, -, 0 B/s, ETA -
2026/10/15 09:35:36 NOTICE: Failed to sync with 6 errors: last error was: failed to delete 5 files
"""
"""`up-mirror` con el freno de fábrica (`max-delete = 50`, una CUENTA de ficheros): 60 ficheros sincronizados y se borran 55 en el origen. rclone borra 50 en el remoto y para. rc 7."""

ESPEJO_DOWN = """\
2026/10/15 09:35:36 INFO  : nota53.md: Deleted
2026/10/15 09:35:36 INFO  : nota38.md: Deleted
2026/10/15 09:35:36 INFO  : nota09.md: Deleted
2026/10/15 09:35:36 INFO  : nota33.md: Deleted
2026/10/15 09:35:36 INFO  : nota23.md: Deleted
2026/10/15 09:35:36 INFO  : nota10.md: Deleted
2026/10/15 09:35:36 INFO  : nota14.md: Deleted
2026/10/15 09:35:36 INFO  : nota46.md: Deleted
2026/10/15 09:35:36 INFO  : nota55.md: Deleted
2026/10/15 09:35:36 INFO  : nota40.md: Deleted
2026/10/15 09:35:36 INFO  : nota07.md: Deleted
2026/10/15 09:35:36 INFO  : nota25.md: Deleted
2026/10/15 09:35:36 INFO  : nota01.md: Deleted
2026/10/15 09:35:36 INFO  : nota34.md: Deleted
2026/10/15 09:35:36 INFO  : nota47.md: Deleted
2026/10/15 09:35:36 INFO  : nota50.md: Deleted
2026/10/15 09:35:36 INFO  : nota31.md: Deleted
2026/10/15 09:35:36 INFO  : nota03.md: Deleted
2026/10/15 09:35:36 INFO  : nota02.md: Deleted
2026/10/15 09:35:36 INFO  : nota13.md: Deleted
2026/10/15 09:35:36 INFO  : nota30.md: Deleted
2026/10/15 09:35:36 INFO  : nota17.md: Deleted
2026/10/15 09:35:36 INFO  : nota20.md: Deleted
2026/10/15 09:35:36 INFO  : nota36.md: Deleted
2026/10/15 09:35:36 INFO  : nota32.md: Deleted
2026/10/15 09:35:36 INFO  : nota39.md: Deleted
2026/10/15 09:35:36 INFO  : nota41.md: Deleted
2026/10/15 09:35:36 INFO  : nota48.md: Deleted
2026/10/15 09:35:36 INFO  : nota49.md: Deleted
2026/10/15 09:35:36 INFO  : nota51.md: Deleted
2026/10/15 09:35:36 INFO  : nota05.md: Deleted
2026/10/15 09:35:36 INFO  : nota26.md: Deleted
2026/10/15 09:35:36 INFO  : nota22.md: Deleted
2026/10/15 09:35:36 INFO  : nota18.md: Deleted
2026/10/15 09:35:36 INFO  : nota29.md: Deleted
2026/10/15 09:35:36 INFO  : nota54.md: Deleted
2026/10/15 09:35:36 INFO  : nota06.md: Deleted
2026/10/15 09:35:36 INFO  : nota35.md: Deleted
2026/10/15 09:35:36 INFO  : nota27.md: Deleted
2026/10/15 09:35:36 INFO  : nota12.md: Deleted
2026/10/15 09:35:36 INFO  : nota04.md: Deleted
2026/10/15 09:35:36 INFO  : nota15.md: Deleted
2026/10/15 09:35:36 INFO  : nota43.md: Deleted
2026/10/15 09:35:36 INFO  : nota24.md: Deleted
2026/10/15 09:35:36 INFO  : nota37.md: Deleted
2026/10/15 09:35:36 INFO  : nota16.md: Deleted
2026/10/15 09:35:36 INFO  : nota45.md: Deleted
2026/10/15 09:35:36 INFO  : nota08.md: Deleted
2026/10/15 09:35:36 INFO  : nota28.md: Deleted
2026/10/15 09:35:36 ERROR : nota11.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 ERROR : nota52.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 INFO  : nota42.md: Deleted
2026/10/15 09:35:36 ERROR : nota19.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 ERROR : nota21.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 ERROR : nota44.md: Got fatal error on delete: --max-delete threshold reached
2026/10/15 09:35:36 ERROR : Cancelling sync due to fatal error: failed to delete 5 files
2026/10/15 09:35:36 ERROR : combine root 'sync-data/notas': not deleting directories as there were IO errors
2026/10/15 09:35:36 ERROR : Fatal error received - not attempting retries
2026/10/15 09:35:36 INFO  :           0 B / 0 B, -, 0 B/s, ETA -
2026/10/15 09:35:36 NOTICE: Failed to sync with 6 errors: last error was: failed to delete 5 files
"""
"""`down-mirror`, lo mismo con el destino en el dispositivo: 60 ficheros en el remoto, se borran 55. rc 7."""

SIMULACION_BISYNC = """\
2026/10/15 09:44:30 INFO  : Setting --ignore-listing-checksum as neither --checksum nor --compare checksum are set.
2026/10/15 09:44:30 INFO  : Bisyncing with Comparison Settings: 
{
	"Modtime": true,
	"Size": true,
	"Checksum": false,
	"HashType1": 0,
	"HashType2": 0,
	"NoSlowHash": false,
	"SlowHashSyncOnly": false,
	"SlowHashDetected": true,
	"DownloadHash": false
}
2026/10/15 09:44:30 INFO  : Synching Path1 "disp{8Issk}:sync-data/notas/" with Path2 "nas:/tmp/prdrive-frenos/remoto/notas/"
2026/10/15 09:44:30 INFO  : Using filters file /tmp/prdrive-frenos/filters/notas.txt
2026/10/15 09:44:30 INFO  : Building Path1 and Path2 listings
2026/10/15 09:44:30 INFO  : Path1 checking for diffs
2026/10/15 09:44:30 NOTICE: - Path1             File was deleted                            - nota01.md
2026/10/15 09:44:30 NOTICE: - Path1             File was deleted                            - nota02.md
2026/10/15 09:44:30 NOTICE: - Path1             File was deleted                            - nota03.md
2026/10/15 09:44:30 NOTICE: - Path1             File was deleted                            - nota04.md
2026/10/15 09:44:30 NOTICE: - Path1             File was deleted                            - nota05.md
2026/10/15 09:44:30 NOTICE: - Path1             File was deleted                            - nota06.md
2026/10/15 09:44:30 NOTICE: - Path1             File was deleted                            - nota07.md
2026/10/15 09:44:30 NOTICE: - Path1             File was deleted                            - nota08.md
2026/10/15 09:44:30 INFO  : Path1:    8 changes:    0 new,    0 modified,    8 deleted
2026/10/15 09:44:30 INFO  : Path2 checking for diffs
2026/10/15 09:44:30 INFO  : Applying changes
2026/10/15 09:44:30 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota01.md
2026/10/15 09:44:30 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota02.md
2026/10/15 09:44:30 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota03.md
2026/10/15 09:44:30 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota04.md
2026/10/15 09:44:30 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota05.md
2026/10/15 09:44:30 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota06.md
2026/10/15 09:44:30 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota07.md
2026/10/15 09:44:30 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota08.md
2026/10/15 09:44:30 NOTICE: - Path1             Do queued copies to                         - Path2
2026/10/15 09:44:30 NOTICE: nota07.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 NOTICE: nota08.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 NOTICE: nota01.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 NOTICE: nota02.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 NOTICE: nota03.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 NOTICE: nota04.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 NOTICE: nota05.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 NOTICE: nota06.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 INFO  : There was nothing to transfer
2026/10/15 09:44:30 INFO  : Updating listings
2026/10/15 09:44:30 INFO  : Bisync successful
2026/10/15 09:44:30 NOTICE:           0 B / 0 B, -, 0 B/s, ETA -
"""
"""`sync.py notas --dry-run --force` sobre el bisync de arriba (8 de 10 borrados en el dispositivo): rc 0, no toca nada y apunta cada borrado que haría."""

SIMULACION_ESPEJO = """\
2026/10/15 09:44:30 NOTICE: nota07.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 NOTICE: nota39.md: Skipped delete as --dry-run is set (size 8)
2026/10/15 09:44:30 NOTICE: nota24.md: Skipped delete as --dry-run is set (size 8)
2026/10/15 09:44:30 NOTICE: nota41.md: Skipped delete as --dry-run is set (size 8)
2026/10/15 09:44:30 NOTICE: nota09.md: Skipped delete as --dry-run is set (size 7)
2026/10/15 09:44:30 INFO  : There was nothing to transfer
2026/10/15 09:44:30 NOTICE:           0 B / 0 B, -, 0 B/s, ETA -
"""
"""`sync.py notas --dry-run --force` sobre el `up-mirror` de arriba (`--max-delete -1`): rc 0, no toca nada y apunta cada borrado que haría."""

SIMULACION_BISYNC_VERSIONES = """\
2026/10/15 11:12:32 INFO  : Setting --ignore-listing-checksum as neither --checksum nor --compare checksum are set.
2026/10/15 11:12:32 INFO  : Bisyncing with Comparison Settings: 
{
	"Modtime": true,
	"Size": true,
	"Checksum": false,
	"HashType1": 0,
	"HashType2": 0,
	"NoSlowHash": false,
	"SlowHashSyncOnly": false,
	"SlowHashDetected": true,
	"DownloadHash": false
}
2026/10/15 11:12:32 INFO  : Synching Path1 "disp{bI9xF}:sync-data/notas/" with Path2 "nas:/tmp/prdrive-frenos/remoto/notas/"
2026/10/15 11:12:32 INFO  : Using filters file /tmp/prdrive-frenos/filters/notas.txt
2026/10/15 11:12:32 INFO  : Building Path1 and Path2 listings
2026/10/15 11:12:32 INFO  : Path1 checking for diffs
2026/10/15 11:12:32 NOTICE: - Path1             File was deleted                            - nota01.md
2026/10/15 11:12:32 NOTICE: - Path1             File was deleted                            - nota02.md
2026/10/15 11:12:32 NOTICE: - Path1             File was deleted                            - nota03.md
2026/10/15 11:12:32 NOTICE: - Path1             File was deleted                            - nota04.md
2026/10/15 11:12:32 NOTICE: - Path1             File was deleted                            - nota05.md
2026/10/15 11:12:32 NOTICE: - Path1             File was deleted                            - nota06.md
2026/10/15 11:12:32 NOTICE: - Path1             File was deleted                            - nota07.md
2026/10/15 11:12:32 NOTICE: - Path1             File was deleted                            - nota08.md
2026/10/15 11:12:32 NOTICE: - Path1             File changed: size (larger), time (newer)   - nota09.md
2026/10/15 11:12:32 NOTICE: - Path1             File changed: size (larger), time (newer)   - nota10.md
2026/10/15 11:12:32 INFO  : Path1:   10 changes:    0 new,    2 modified,    8 deleted
2026/10/15 11:12:32 INFO  : (Modified:    2 newer,    0 older,    2 larger,    0 smaller)
2026/10/15 11:12:32 INFO  : Path2 checking for diffs
2026/10/15 11:12:32 INFO  : Applying changes
2026/10/15 11:12:32 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota01.md
2026/10/15 11:12:32 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota02.md
2026/10/15 11:12:32 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota03.md
2026/10/15 11:12:32 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota04.md
2026/10/15 11:12:32 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota05.md
2026/10/15 11:12:32 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota06.md
2026/10/15 11:12:32 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota07.md
2026/10/15 11:12:32 NOTICE: - Path2             Queue delete                                - nas:/tmp/prdrive-frenos/remoto/notas/nota08.md
2026/10/15 11:12:32 NOTICE: - Path1             Queue copy to Path2                         - nas:/tmp/prdrive-frenos/remoto/notas/nota09.md
2026/10/15 11:12:32 NOTICE: - Path1             Queue copy to Path2                         - nas:/tmp/prdrive-frenos/remoto/notas/nota10.md
2026/10/15 11:12:32 NOTICE: - Path1             Do queued copies to                         - Path2
2026/10/15 11:12:32 NOTICE: nota09.md: Skipped move to nota09~20261015-100000.md as --dry-run is set (size 7)
2026/10/15 11:12:32 NOTICE: nota09.md: Skipped copy as --dry-run is set (size 29)
2026/10/15 11:12:32 NOTICE: nota10.md: Skipped move to nota10~20261015-100000.md as --dry-run is set (size 8)
2026/10/15 11:12:32 NOTICE: nota10.md: Skipped copy as --dry-run is set (size 29)
2026/10/15 11:12:32 NOTICE: nota02.md: Skipped move into backup dir as --dry-run is set (size 7)
2026/10/15 11:12:32 NOTICE: nota03.md: Skipped move into backup dir as --dry-run is set (size 7)
2026/10/15 11:12:32 NOTICE: nota05.md: Skipped move into backup dir as --dry-run is set (size 7)
2026/10/15 11:12:32 NOTICE: nota08.md: Skipped move into backup dir as --dry-run is set (size 7)
2026/10/15 11:12:32 NOTICE: nota07.md: Skipped move into backup dir as --dry-run is set (size 7)
2026/10/15 11:12:32 NOTICE: nota01.md: Skipped move into backup dir as --dry-run is set (size 7)
2026/10/15 11:12:32 NOTICE: nota06.md: Skipped move into backup dir as --dry-run is set (size 7)
2026/10/15 11:12:32 NOTICE: nota04.md: Skipped move into backup dir as --dry-run is set (size 7)
2026/10/15 11:12:32 INFO  : Updating listings
2026/10/15 11:12:32 INFO  : Bisync successful
2026/10/15 11:12:32 NOTICE:          73 B / 73 B, 100%, 0 B/s, ETA -
"""
"""`sync.py notas --dry-run --force` sobre un bisync con `versions = true`: 8 ficheros borrados en el dispositivo y 2 modificados. Lo que borra va a `.prversions/` y rclone lo apunta como `Skipped move into backup dir`, no como `Skipped delete`; lo que sobrescribe, como `Skipped move to <nombre>~<marca>` y `Skipped copy`."""
