#!/usr/bin/python3
"""Native-messaging adapter from Firefox/Chrome to Jev's loopback bridge."""

import json
import os
import queue
import socket
import struct
import sys
import threading
import time


def _read_native_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        return None
    length = struct.unpack("<I", header)[0]
    if length > 1024 * 1024:
        return None
    payload = stream.read(length)
    if len(payload) != length:
        return None
    return json.loads(payload.decode("utf-8"))


def _write_native_message(stream, message):
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(payload)))
    stream.write(payload)
    stream.flush()


def _config_candidates(browser):
    home = os.path.expanduser("~")
    paths = [
        os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.join(home, ".cache")),
                     "cranky-clippy", "browser_bridge.json")
    ]
    if browser == "firefox":
        snap_common = os.environ.get(
            "SNAP_USER_COMMON", os.path.join(home, "snap", "firefox", "common")
        )
        paths.insert(0, os.path.join(
            snap_common, ".cache", "cranky-clippy", "browser_bridge.json"
        ))
    return paths


def _read_config(browser):
    for path in _config_candidates(browser):
        try:
            with open(path, encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, ValueError):
            continue
    return None


def _stdin_reader(messages):
    try:
        while True:
            message = _read_native_message(sys.stdin.buffer)
            if message is None:
                break
            messages.put(("extension", message))
    finally:
        messages.put(("stdin_closed", None))


def _socket_reader(sock, messages):
    try:
        stream = sock.makefile("r", encoding="utf-8")
        for line in stream:
            try:
                messages.put(("jev", json.loads(line)))
            except ValueError:
                continue
    except OSError:
        pass
    finally:
        messages.put(("server_closed", None))


def main():
    # Chrome passes the chrome-extension:// origin. Firefox passes the
    # extension ID. Keep explicit browser arguments as a test-friendly
    # override, but do not rely on a nonstandard host-manifest args field.
    browser = next(
        (argument for argument in reversed(sys.argv[1:])
         if argument in {"chrome", "firefox"}),
        "",
    )
    if not browser:
        browser = next(
            ("chrome" if argument.startswith("chrome-extension://") else "firefox"
             for argument in sys.argv[1:]
             if argument.startswith("chrome-extension://")
             or argument == "cranky-clippy@example.com"
             or argument.startswith("moz-extension://")),
            "",
        )
    if browser not in {"chrome", "firefox"}:
        return 2

    messages = queue.Queue()
    threading.Thread(target=_stdin_reader, args=(messages,), daemon=True).start()
    sock = None
    config = None
    buffered_extension_messages = []
    while sock is None:
        config = _read_config(browser)
        if config:
            try:
                sock = socket.create_connection(
                    (config["host"], int(config["port"])), timeout=2
                )
                break
            except (OSError, KeyError, ValueError):
                sock = None
        try:
            kind, message = messages.get(timeout=0.25)
            if kind == "stdin_closed":
                return 0
            if kind == "extension":
                buffered_extension_messages.append(message)
        except queue.Empty:
            pass

    sock.sendall((json.dumps({
        "type": "hello",
        "browser": browser,
        "token": config["token"],
    }) + "\n").encode("utf-8"))
    for message in buffered_extension_messages:
        sock.sendall((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
    threading.Thread(target=_socket_reader, args=(sock, messages), daemon=True).start()

    try:
        while True:
            kind, message = messages.get()
            if kind in {"stdin_closed", "server_closed"}:
                break
            if kind == "extension":
                sock.sendall((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
            elif kind == "jev":
                if message.get("action") == "shutdown":
                    _write_native_message(sys.stdout.buffer, message)
                    break
                _write_native_message(sys.stdout.buffer, message)
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
