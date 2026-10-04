"""Register Jev's native-messaging bridge for this user's Firefox and Chrome."""

import json
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent
HOST_NAME = "com.crankyclippy.bridge"
CHROME_EXTENSION_ID = "kfcdbpbcgbnchboagjfonaegocnpglbh"
SOURCE_HOST = ROOT / "native_messaging_host.py"


def write_manifest(path, executable, browser):
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": HOST_NAME,
        "description": "Cranky Clippy browser tab bridge",
        "path": str(executable),
        "type": "stdio",
    }
    if browser == "chrome":
        manifest["allowed_origins"] = [
            "chrome-extension://%s/" % CHROME_EXTENSION_ID
        ]
    else:
        manifest["allowed_extensions"] = ["cranky-clippy@example.com"]
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main():
    SOURCE_HOST.chmod(SOURCE_HOST.stat().st_mode | 0o111)
    home = Path.home()

    chrome_manifest = (
        home / ".config/google-chrome/NativeMessagingHosts"
        / (HOST_NAME + ".json")
    )
    write_manifest(chrome_manifest, SOURCE_HOST, "chrome")

    # Standard Firefox path (for non-Snap installs).
    firefox_manifest = (
        home / ".mozilla/native-messaging-hosts" / (HOST_NAME + ".json")
    )
    write_manifest(firefox_manifest, SOURCE_HOST, "firefox")

    # Firefox Snap cannot execute/read arbitrary files in ~/Documents or
    # ~/.cache. Keep its host and bridge config within Snap's shared area.
    snap_common = home / "snap/firefox/common/cranky-clippy"
    snap_common.mkdir(parents=True, exist_ok=True)
    snap_host = snap_common / "native_messaging_host.py"
    shutil.copy2(SOURCE_HOST, snap_host)
    snap_host.chmod(snap_host.stat().st_mode | 0o111)
    firefox_snap_manifest = (
        home / "snap/firefox/common/.mozilla/native-messaging-hosts"
        / (HOST_NAME + ".json")
    )
    write_manifest(firefox_snap_manifest, snap_host, "firefox")

    print("Registered Chrome native host:", chrome_manifest)
    print("Registered Firefox native host:", firefox_manifest)
    print("Registered Firefox Snap native host:", firefox_snap_manifest)


if __name__ == "__main__":
    main()
