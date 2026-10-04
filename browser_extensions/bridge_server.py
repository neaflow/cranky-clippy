"""Loopback bridge between Jev and the browser native-messaging hosts."""

import collections
import json
import os
import secrets
import socketserver
import threading


HOST_NAME = "com.crankyclippy.bridge"


def _cache_paths():
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    standard = os.path.join(cache_home, "cranky-clippy", "browser_bridge.json")
    firefox_snap = os.path.join(
        os.path.expanduser("~"), "snap", "firefox", "common", ".cache",
        "cranky-clippy", "browser_bridge.json",
    )
    return standard, firefox_snap


class BrowserExtensionBridge:
    """Local JSON-line server used by installed browser extensions only."""

    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.connections = {}
        self.pending = collections.defaultdict(dict)
        self.lock = threading.RLock()
        self.on_message = None
        self.config_paths = _cache_paths()
        owner = self

        class Handler(socketserver.StreamRequestHandler):
            def setup(self):
                super().setup()
                self._send_lock = threading.Lock()
                self.browser = None

            def _send(self, value):
                data = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
                with self._send_lock:
                    self.wfile.write(data)
                    self.wfile.flush()

            def handle(self):
                try:
                    hello = json.loads(self.rfile.readline(65537))
                except (ValueError, OSError):
                    return
                browser = hello.get("browser")
                if hello.get("token") != owner.token or browser not in {"chrome", "firefox"}:
                    return
                self.browser = browser
                owner._register(browser, self)
                self._send({"action": "connected"})
                for line in self.rfile:
                    if len(line) > 65536:
                        continue
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    owner._received(browser, message)

            def finish(self):
                if self.browser:
                    owner._unregister(self.browser, self)
                super().finish()

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, name="clippy-browser-bridge", daemon=True
        )
        self.server_thread.start()

        config = {
            "host": "127.0.0.1",
            "port": self.server.server_address[1],
            "token": self.token,
        }
        for path in self.config_paths:
            try:
                os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump(config, stream)
                os.chmod(path, 0o600)
            except OSError as exc:
                print("[JevOverlay] Could not write browser bridge config %s: %s" % (path, exc))

    def _register(self, browser, connection):
        with self.lock:
            old = self.connections.get(browser)
            self.connections[browser] = connection
            pending = list(self.pending.pop(browser, {}).values())
        if old and old is not connection:
            try:
                old.request.shutdown(2)
            except OSError:
                pass
        for message in pending:
            try:
                connection._send(message)
            except OSError:
                break

    def _unregister(self, browser, connection):
        with self.lock:
            if self.connections.get(browser) is connection:
                del self.connections[browser]

    def _received(self, browser, message):
        if message.get("type") in {"restored", "error"}:
            print("[JevOverlay] Browser extension (%s): %s" % (browser, message))
        if self.on_message:
            self.on_message(browser, message)

    def send(self, browser, message):
        if browser not in {"chrome", "firefox"}:
            return False
        with self.lock:
            connection = self.connections.get(browser)
            if connection is None:
                # Keep the latest remembered tab plus at most the latest
                # restore request until the extension connects.
                if message.get("action") == "remember":
                    self.pending[browser]["remember"] = message
                elif message.get("action") == "restore":
                    self.pending[browser]["restore"] = message
                return False
        try:
            connection._send(message)
            return True
        except OSError:
            self._unregister(browser, connection)
            return False

    def close(self):
        for browser in ("chrome", "firefox"):
            self.send(browser, {"action": "shutdown"})
        self.server.shutdown()
        self.server.server_close()
        for path in self.config_paths:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
