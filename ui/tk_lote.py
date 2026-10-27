#!/usr/bin/env python3
"""Sigue una lista de órdenes del `rcd` hasta que acaban: la máquina de lotes de «Servidor…».

Una transferencia es un lote de UNA orden (`sync/copy`); borrar, mover, renombrar
y crear carpetas son lotes de varias, que se lanzan de una en una. La máquina es
la misma: lanza la primera, la sigue cada `intervalo_ms` con `job/status` y
`core/stats`, apunta el estado con que acaba y lanza la siguiente; al acabar la
última (o al cancelar) pide el resultado a quien la usa y lo enseña.

Es pegamento cercano al dibujo: toca el `Panel`, el `after()` de la ventana y el
`Sondeo` que se le dan, nunca `tkinter`. Todo lo que espera a la red va en
segundo plano (`segundo_plano.lanzar`) con funciones de módulo, y las respuestas
se recogen en el hilo de Tk. Qué se pinta en el panel, qué dice el resultado y
qué se hace al acabar (releer, elegir lo nuevo) lo deciden las funciones de cada
`Trabajo`: esto no sabe nada de copiar ni de borrar.

Reglas que se conservan de la pieza 2 (`docs/agents/reference/servidor.md`):

- un seguimiento que falla no suelta el trabajo mientras el `rcd` viva: tras
  `fallos_para_avisar` fallos seguidos la línea de la ventana lo dice, y el
  trabajo solo acaba con `finished`, con el proceso muerto, con «job not found»
  o al cerrar;
- «Cancelar» manda `job/stop` una sola vez y no se lanza ninguna orden más;
- cerrar con trabajo lanzado cancela y espera (hasta `rcd.ESPERA_QUIT`) antes de
  parar el `rcd`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from common import rcd

from . import segundo_plano, servidor, transferencia

TITULO_CIERRE = "Transferencia en marcha"
"""Título de la pregunta al cerrar con una transferencia en marcha (el de un `Trabajo` por defecto)."""
TEXTO_CIERRE = "Hay una transferencia en marcha. ¿Cancelarla y cerrar?"
"""Texto de esa pregunta."""
NO_SE_SABE = "No se sabe cómo acabó: revisa la carpeta."
"""Lo que dice el panel cuando rclone ya olvidó el trabajo que se seguía («job not found»)."""


@dataclass(eq=False)
class Trabajo:
    """Una lista de órdenes que se siguen juntas, y lo que se sabe de cómo van.

    Args:
        rcd: El `rcd` que las ejecuta; es el de cuando se abrió el trabajo.
        grupo: El grupo de estadísticas de todas las órdenes del trabajo.
        lanzadores: Uno por orden; cada uno recibe `(rcd, grupo)`, lanza su orden y
            devuelve su `jobid`. Corren en un hilo: nada de Tk dentro.
        progreso: `(stats, hechos, total)` → lo que enseña el panel; `hechos` son las
            órdenes que ya acabaron y `total` todas las del trabajo.
        resultado: `(estados, stats, cancelado)` → cómo acabó. `estados` es el
            `job/status` final de cada orden lanzada, en orden; `cancelado` solo es
            cierto si la persona canceló y quedó algo sin hacer.
        al_acabar: Se llama con el resultado cuando el trabajo acaba (releer, elegir lo nuevo).
            No se llama si se perdió la conexión con el `rcd`.
        reintento: Lo que repite el trabajo si el resultado ofrece «Reintentar».
        sin_respuesta: La línea de la ventana tras varios seguimientos sin respuesta.
        cancelando: Opcional: el texto de «Cancelando…» según la orden que va (desde 0).
        panel_tardio: Si es cierto no hay panel hasta que un sondeo diga que el trabajo
            sigue en marcha, y un resultado `ok` va a la línea de la ventana: lo que
            acaba antes de verse no merece un panel.
        titulo_cierre: Título de la pregunta al cerrar la ventana con el trabajo en marcha.
        texto_cierre: Texto de esa pregunta.

    Attributes:
        jobid: El de la última orden lanzada; `None` mientras no se lanzó ninguna.
        indice: La orden que va (desde 0).
        estados: Los `job/status` finales de las órdenes que ya acabaron.
        stats: El último `core/stats` recibido.
        cancelado: Si la persona pidió cancelar.
        cerrando: Si se está cancelando para cerrar la ventana.
        fallos: Seguimientos seguidos sin respuesta.
        panel_visto: Si el panel llegó a enseñarse.
        lanzando: Si hay una orden en vuelo, lanzándose y sin `jobid` todavía.
    """

    rcd: rcd.Rcd
    grupo: str
    lanzadores: list[Callable[[rcd.Rcd, str], int]]
    progreso: Callable[[dict, int, int], transferencia.Progreso]
    resultado: Callable[[list[dict], dict, bool], transferencia.Resultado]
    al_acabar: Callable[[transferencia.Resultado], None] = lambda r: None
    reintento: Callable[[], None] | None = None
    sin_respuesta: str = ""
    cancelando: Callable[[int], str] | None = None
    panel_tardio: bool = False
    titulo_cierre: str = TITULO_CIERRE
    texto_cierre: str = TEXTO_CIERRE
    jobid: int | None = None
    indice: int = 0
    estados: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    cancelado: bool = False
    cerrando: bool = False
    fallos: int = 0
    panel_visto: bool = False
    lanzando: bool = False


def _sondear(r: rcd.Rcd, jobid: int, grupo: str) -> tuple[dict, dict]:
    """Pide `(core/stats, job/status)` de una orden; corre en un hilo.

    El estado va primero: si dice `finished`, las estadísticas que se piden
    después ya son las finales.
    """
    st = rcd.estado(r, jobid)
    return rcd.progreso(r, grupo), st


def _cancelar_y_esperar(r: rcd.Rcd, jobid: int) -> None:
    """Cancela el trabajo y espera a que acabe, hasta `rcd.ESPERA_QUIT`; corre en un hilo."""
    rcd.cancelar(r, jobid)
    limite = time.monotonic() + rcd.ESPERA_QUIT
    while time.monotonic() < limite:
        try:
            if rcd.estado(r, jobid).get("finished"):
                return
        except (rcd.ErrorRc, rcd.RcdCaido):
            return
        time.sleep(0.1)


class Seguimiento:
    """Sigue un `Trabajo` a la vez: lanza sus órdenes en secuencia y enseña cómo van.

    Args:
        ventana: La ventana de la que cuelga el temporizador del seguimiento (`after`).
        panel: El `tk_transferencia.Panel` donde se enseña el progreso y el resultado.
        sondeo: El `Sondeo` de este seguimiento; distinto del de los listados, para que
            navegar no pise al trabajo.
        decir: `decir(texto, tono="Peligro.", boton=None)` escribe en la línea de la ventana.
        intervalo_ms: Milisegundos entre dos seguimientos; se lee en cada uso.
        fallos_para_avisar: Cuántos seguimientos seguidos sin respuesta hacen falta para
            decirlo; se lee en cada uso.
        perdida: Lo que dice el panel cuando el `rcd` murió.
        al_cambiar: Se llama sin argumentos cuando cambia el trabajo en marcha o lo que
            enseña el panel: es cuando la ventana enciende o apaga sus botones y se ajusta.

    Attributes:
        activo: El trabajo en marcha, o `None`.
        reintento: Lo que repite el último trabajo si acabó pidiéndolo; `None` si no.
    """

    def __init__(self, ventana, panel, sondeo, *, decir: Callable[..., None],
                 intervalo_ms: Callable[[], int], fallos_para_avisar: Callable[[], int],
                 perdida: str, al_cambiar: Callable[[], None]) -> None:
        self._ventana = ventana
        self._panel = panel
        self._sondeo = sondeo
        self._decir = decir
        self._intervalo_ms = intervalo_ms
        self._fallos_para_avisar = fallos_para_avisar
        self._perdida = perdida
        self._al_cambiar = al_cambiar
        self._tras = None
        self._parado = False
        self._despues: Callable[[], None] | None = None
        self.activo: Trabajo | None = None
        self.reintento: Callable[[], None] | None = None

    # -- abrir y soltar ------------------------------------------------------

    def abrir(self, t: Trabajo) -> Trabajo:
        """Da `t` por el trabajo en marcha, con el panel oculto, y avisa del cambio.

        Es lo primero que se hace con un trabajo, antes incluso de lo que se le
        pregunte a la persona: mientras es el activo, la ventana apaga sus botones.
        """
        self.reintento = None
        self.activo = t
        self._panel.ocultar()
        self._al_cambiar()
        return t

    def vigente(self, t: Trabajo) -> bool:
        """Si `t` sigue siendo el trabajo que se sigue y la ventana lo puede pintar."""
        return not self._parado and self.activo is t and not t.cerrando

    def soltar(self) -> None:
        """Da el trabajo por acabado sin resultado (p. ej. «Cancelar» en un diálogo)."""
        self.activo = None
        self._al_cambiar()

    def parar(self) -> None:
        """La ventana se cierra: nada más se pinta y se quita el temporizador."""
        self._parado = True
        self._quitar_espera(solo_temporizador=True)

    # -- lanzar y seguir -----------------------------------------------------

    def lanzar(self, t: Trabajo) -> None:
        """Empieza por la primera orden de `t`, en segundo plano."""
        self.reintento = None
        self._lanzar_orden(t)

    def _lanzar_orden(self, t: Trabajo) -> None:
        """Lanza en segundo plano la orden `t.indice`."""
        t.lanzando = True
        self._sondeo.esperar(
            segundo_plano.lanzar(partial(t.lanzadores[t.indice], t.rcd, t.grupo)),
            partial(self._lanzada, t))

    def _lanzada(self, t: Trabajo, encargo) -> None:
        """Con el `jobid` en la mano, enseña el panel y empieza a seguir la orden."""
        t.lanzando = False
        if t.cerrando:
            self._parar_la_lanzada(t, encargo)
            return
        if not self.vigente(t):
            return
        if encargo.error is not None:
            self.acabar_con_error(t, encargo.error, t.reintento)
            return
        t.jobid = encargo.resultado
        if t.cancelado:
            # Se pidió cancelar entre dos órdenes: la que acaba de salir no debe seguir.
            segundo_plano.lanzar(partial(rcd.cancelar, t.rcd, t.jobid))
        if not t.panel_tardio or t.panel_visto:
            self._pintar(t, t.stats)
        self._pedir_progreso(t)

    def _parar_la_lanzada(self, t: Trabajo, encargo) -> None:
        """Se pidió cerrar mientras esta orden se lanzaba: la para y espera antes de cerrar.

        Si la orden no llegó a lanzarse no hay nada que parar y se cierra ya.
        """
        despues, self._despues = self._despues, None
        if despues is None or self._parado:
            return
        if encargo.error is not None:
            despues()
            return
        t.jobid = encargo.resultado
        self._sondeo.esperar(
            segundo_plano.lanzar(partial(_cancelar_y_esperar, t.rcd, t.jobid)),
            lambda _encargo: despues())

    def _pedir_progreso(self, t: Trabajo) -> None:
        """Pide en segundo plano el progreso y el estado de la orden que va."""
        self._tras = None
        if not self.vigente(t):
            return
        self._sondeo.esperar(
            segundo_plano.lanzar(partial(_sondear, t.rcd, t.jobid, t.grupo)),
            partial(self._llega, t))

    def _esperar_y_pedir(self, t: Trabajo) -> None:
        """Programa el siguiente seguimiento dentro de `intervalo_ms`."""
        self._tras = self._ventana.after(self._intervalo_ms(), partial(self._pedir_progreso, t))

    def _llega(self, t: Trabajo, encargo) -> None:
        """Pinta el progreso que llegó, o pasa a la siguiente orden si la que iba acabó."""
        if not self.vigente(t):
            return
        if encargo.error is not None:
            self._sin_respuesta(t, encargo.error)
            return
        if t.fallos:
            if t.fallos >= self._fallos_para_avisar():
                self._decir("", "Pista.")
            t.fallos = 0
        stats, st = encargo.resultado
        t.stats = stats
        if st.get("finished"):
            self._orden_acabada(t, stats, st)
            return
        self._pintar(t, stats)
        self._esperar_y_pedir(t)

    def _orden_acabada(self, t: Trabajo, stats: dict, st: dict) -> None:
        """Apunta cómo acabó la orden que iba y lanza la siguiente, o acaba el trabajo."""
        t.estados.append(st)
        if not t.cancelado and t.indice + 1 < len(t.lanzadores):
            t.indice += 1
            t.fallos = 0
            self._lanzar_orden(t)
            return
        # Cancelar una orden que acaba bien, y era la última, no deja nada sin hacer.
        cancelado = t.cancelado and (len(t.estados) < len(t.lanzadores)
                                     or not st.get("success"))
        self._acabar(t, t.resultado(t.estados, stats, cancelado), reintento=t.reintento)

    def _pintar(self, t: Trabajo, stats: dict) -> None:
        """Enseña en el panel cómo va `t`: el progreso o «Cancelando…»."""
        if t.cancelado:
            self._mostrar_cancelando(t)
            return
        primera = not t.panel_visto
        t.panel_visto = True
        self._panel.mostrar_progreso(t.progreso(stats, len(t.estados), len(t.lanzadores)))
        if primera:
            self._al_cambiar()          # la ventana crece si el panel pide sitio

    def _mostrar_cancelando(self, t: Trabajo) -> None:
        """Dice «Cancelando…» en el panel, con el texto de la orden que va si `t` lo da."""
        if t.panel_tardio and not t.panel_visto:
            return                       # el panel no se enseñó: no sale solo para decir esto
        if t.cancelando is None:
            self._panel.mostrar_cancelando()
        else:
            self._panel.mostrar_cancelando(t.cancelando(t.indice))

    def _sin_respuesta(self, t: Trabajo, error: Exception) -> None:
        """Un seguimiento falló: con el `rcd` vivo se sigue intentando; si murió, el trabajo acabó.

        Mientras el proceso vive, la orden puede seguir corriendo aunque rclone no
        conteste (una petición perdida, un tiempo de espera), así que el trabajo
        sigue activo y los botones apagados: solo acaba cuando `job/status` dice
        `finished`, cuando el proceso muere o cuando se cierra. Nunca se ofrece
        «Reintentar» con una orden que puede estar en marcha.

        Excepción: «job not found». rclone olvida un trabajo unos 60 s después de
        acabar, así que ya no hay nada que esperar: el trabajo acaba aquí, sin
        lanzar más órdenes y sin «Reintentar» (no se sabe cómo acabó).
        """
        if isinstance(error, rcd.ErrorRc) and "job not found" in error.mensaje.lower():
            if t.fallos >= self._fallos_para_avisar():
                self._decir("", "Pista.")           # se quita la línea de «Sin respuesta…»
            self._acabar(t, transferencia.Resultado(NO_SE_SABE, "aviso", False))
            return
        if not t.rcd.vivo:
            self.acabar_con_error(t, rcd.RcdCaido(str(error)), None)
            return
        t.fallos += 1
        if t.fallos == self._fallos_para_avisar():
            self._decir(t.sin_respuesta, "Aviso.")
        self._esperar_y_pedir(t)

    # -- acabar --------------------------------------------------------------

    def _acabar(self, t: Trabajo, resultado: transferencia.Resultado, releer: bool = True,
                reintento: Callable[[], None] | None = None) -> None:
        """Enseña cómo acabó `t`, suelta el trabajo y, con `releer`, llama a `t.al_acabar`.

        Con `panel_tardio`, un panel que nunca salió y un resultado `ok`, el
        resultado va a la línea de la ventana y el panel sigue oculto.
        """
        if t.panel_tardio and not t.panel_visto and resultado.tono == "ok":
            self._decir(resultado.texto, "Pista.")
        else:
            self._panel.mostrar_resultado(resultado)
        self.reintento = reintento if resultado.reintentar else None
        self.activo = None
        self._al_cambiar()
        if releer:
            t.al_acabar(resultado)

    def acabar_con_error(self, t: Trabajo, error: Exception,
                         reintento: Callable[[], None] | None) -> None:
        """Dice por qué no pudo seguir `t` (un fallo al lanzar, o el `rcd` perdido).

        Con la conexión perdida pone «Reconectar» y no llama a `t.al_acabar`. Un
        error de rclone se cuenta como el estado fallido de la orden que no llegó a
        lanzarse, para que `t.resultado` lo diga como cualquier otro.

        Args:
            t: El trabajo que no sigue.
            error: Lo que falló.
            reintento: Lo que se ofrece con «Reintentar» si el resultado lo pide.
        """
        if isinstance(error, rcd.RcdCaido):
            self._decir(servidor.frase_error(error), boton="Reconectar")
            self._acabar(t, transferencia.Resultado(self._perdida, "aviso", False),
                         releer=False)
            return
        if isinstance(error, rcd.ErrorRc):
            fallido = {"success": False, "error": error.mensaje}
            resultado = t.resultado([*t.estados, fallido], t.stats, t.cancelado)
        else:
            resultado = transferencia.Resultado(servidor.frase_error(error), "aviso", True)
        self._acabar(t, resultado, reintento=reintento)

    # -- cancelar, reintentar y cerrar ----------------------------------------

    def cancelar(self) -> None:
        """«Cancelar»: pide parar la orden que va, una sola vez, y dice «Cancelando…» en el acto.

        No se lanza ninguna orden más. Si se pide entre dos órdenes, el `job/stop`
        que se manda alcanza a la anterior (que ya acabó) y la nueva se para al
        recibir su `jobid`.
        """
        t = self.activo
        if t is None or t.jobid is None or t.cancelado:
            return
        t.cancelado = True
        self._mostrar_cancelando(t)
        segundo_plano.lanzar(partial(rcd.cancelar, t.rcd, t.jobid))

    def reintentar(self) -> None:
        """«Reintentar»: repite el último trabajo si acabó pidiéndolo y no hay otro en marcha."""
        if self.activo is None and self.reintento is not None:
            self.reintento()

    def cerrar_cancelando(self, despues: Callable[[], None]) -> bool:
        """Cancela el trabajo lanzado y espera a que rclone lo pare, antes de cerrar.

        Se espera en segundo plano hasta `rcd.ESPERA_QUIT` (`_cancelar_y_esperar`) y
        entonces se llama a `despues()`. El trabajo deja de ser vigente: nada más se pinta.
        Si se cierra entre dos órdenes, con la siguiente lanzándose, se espera a su
        `jobid` y es esa la que se para: no queda una orden suelta al parar el `rcd`.

        Args:
            despues: Lo que se hace cuando rclone paró (cerrar la ventana).

        Returns:
            `True` si había un trabajo lanzado y `despues` se llamará más tarde;
            `False` si no había nada que parar y quien llama debe cerrar ya.
        """
        t = self.activo
        if t is None or t.jobid is None:
            return False
        t.cerrando = t.cancelado = True
        self._mostrar_cancelando(t)
        if t.lanzando:
            self._despues = despues      # `_lanzada` recoge el `jobid` y la para
            self._quitar_espera(solo_temporizador=True)
            return True
        self._quitar_espera()
        self._sondeo.esperar(
            segundo_plano.lanzar(partial(_cancelar_y_esperar, t.rcd, t.jobid)),
            lambda _encargo: despues())
        return True

    def _quitar_espera(self, solo_temporizador: bool = False) -> None:
        """Deja de esperar el siguiente seguimiento (y la respuesta del sondeo, salvo `solo_temporizador`)."""
        if not solo_temporizador:
            self._sondeo.cancelar()
        if self._tras is not None:
            try:
                self._ventana.after_cancel(self._tras)
            except Exception:                # noqa: BLE001 — ya no está
                pass
            self._tras = None
