"""
common — Las tripas compartidas del sync.

Los puntos de entrada (`sync.py`, `runsync.py`) se quedan en la raíz de la
carpeta de la aplicación porque los lanzadores del volumen y `penwatch.py` los
buscan ahí por ruta fija. Lo que vive aquí es lo que ellos comparten:

    model        el sync_config.toml convertido en objetos ya resueltos
    bisync       lo que replica el comportamiento interno de rclone bisync
    config_file  leer Y escribir el TOML, con round-trip verificado
    catalog      el catálogo de parejas que vive en el remoto del usuario
    store        los ficheros de estado en JSON del dispositivo

`penwatch.py` NO usa este paquete a propósito: se copia al equipo del usuario y
tiene que seguir funcionando con el dispositivo desconectado. Por eso repite las
pocas constantes que necesita (el nombre del fichero de control, el marcador de
estructura) en vez de importarlas, y hay un test que comprueba que las copias no
se separan.
"""

# El nombre del producto, en un solo sitio. Es marca Y es identificador: de aquí
# salen el título de las ventanas, la carpeta oculta del dispositivo
# (`.prdrive`), el fichero de control del volumen y el contenedor de VeraCrypt.
# `penwatch.py` es el único que lo repite, por lo dicho arriba.
APP_NAME = "prdrive"
