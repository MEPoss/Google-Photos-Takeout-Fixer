"""
Avvia il backend Flask in background e apre l'interfaccia in una finestra
nativa (senza bisogno del browser), tramite pywebview. Funziona sia su
macOS (backend Cocoa) sia su Linux (backend GTK/WebKit2).
"""

import sys
import threading

import webview

from app import app as flask_app


def run_flask():
    flask_app.run(host="127.0.0.1", port=5050, use_reloader=False)


class Api:
    """Esposta al JS della pagina come `window.pywebview.api` per aprire
    il selettore di cartelle nativo di macOS."""

    def pick_folder(self):
        window = webview.windows[0]
        result = window.create_file_dialog(webview.FileDialog.FOLDER)
        if result:
            return result[0]
        return None


def _hide_title_text(window):
    """Nasconde il testo del titolo nella titlebar (restano solo i semafori),
    come nella maggior parte delle utility app native di macOS. Solo macOS:
    su Linux la titlebar è gestita dal window manager, non da questo codice.

    Va eseguita sul main thread: l'evento `shown` di pywebview scatta invece
    su un thread secondario, e AppKit rifiuta di modificare la geometria
    della finestra fuori dal main thread.
    """
    if sys.platform != "darwin":
        return
    native = getattr(window, "native", None)
    if native is None:
        return
    try:
        import AppKit
        from PyObjCTools import AppHelper

        AppHelper.callAfter(lambda: native.setTitleVisibility_(AppKit.NSWindowTitleHidden))
    except Exception:
        pass


def main():
    threading.Thread(target=run_flask, daemon=True).start()
    api = Api()
    window = webview.create_window(
        "Google Photos Takeout Fixer",
        "http://127.0.0.1:5050",
        width=820,
        height=760,
        resizable=True,
        js_api=api,
    )
    window.events.shown += lambda: _hide_title_text(window)
    webview.start()


if __name__ == "__main__":
    main()
