"""
Avvia il backend Flask in background e apre l'interfaccia in una finestra
nativa macOS (senza bisogno del browser), tramite pywebview.
"""

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


def main():
    threading.Thread(target=run_flask, daemon=True).start()
    api = Api()
    webview.create_window(
        "Google Takeout Fixer",
        "http://127.0.0.1:5050",
        width=820,
        height=760,
        resizable=True,
        js_api=api,
    )
    webview.start()


if __name__ == "__main__":
    main()
