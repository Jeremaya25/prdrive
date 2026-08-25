"""
common — Las tripas compartidas del sync del pen.

Los puntos de entrada (`sync.py`, `runsync.py`) se quedan en `rclone-sync/`
porque los lanzadores de la raíz del pen y `penwatch.py` los buscan ahí por
ruta fija. Lo que vive aquí es lo que ellos comparten:

    model    el sync_config.toml convertido en objetos ya resueltos
    bisync   lo que replica el comportamiento interno de rclone bisync

`penwatch.py` NO usa este paquete a propósito: se copia al equipo y tiene que
seguir funcionando con el pen desconectado.
"""
