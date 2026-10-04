"""Detect the focused window and collect the desktop state Jev will judge.

Run directly (`python3 get_desktop_state.py`) to print a test report of what
was detected. jev_decides.py imports get_desktop_state() and feeds the
returned dict to Jev as the `state`.

On KDE the focused window comes from KWin itself over DBus (definitive,
unlike the accessibility tree, whose ACTIVE flags go stale). Everywhere else
it falls back to the AT-SPI accessibility tree, which works on GNOME, X11
and Wayland. WEBAPP_METADATA sites are matched by the focused browser's
site_domain. Fields Jev wants but that can't be measured in a single-shot
run are returned as None (Jev reads plain state text, so this is fine —
they just mean "not available right now").

Only Linux is supported for now; needs python3-gi and python3-dbus from
the repos (both preinstalled on Ubuntu with KDE/GNOME).
"""

import json
import os
import tempfile
import time
import uuid

import re
import urllib.parse
from urllib.parse import urlparse

try:
    import gi

    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    _ATSPI_OK = True
except Exception:  # gi/Atspi can be missing on headless boxes
    Atspi = None
    _ATSPI_OK = False

try:
    import dbus
    import dbus.mainloop.glib
    import dbus.service

    from gi.repository import GLib

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    _DBUS_OK = True
except Exception:  # dbus-python can be missing
    dbus = None
    _DBUS_OK = False

# App-specific metadata — the extra fields Jev would need for each app to
# judge "distraction or not". Apps whose name is self-explanatory (Discord,
# Slack, etc.) only need generic window data; apps where content varies get
# their own metadata fields.
#
# Structure: APP_METADATA is a dict of app "classes". Each class maps app
# names to a list of metadata fields to collect. Browsers get their own class
# and also have their own sub-class, WEBAPP_METADATA, for sites that are
# opened inside a browser (YouTube, Notion, Reddit, ...). Those sites are not
# apps; they are extra metadata layered on top of the browser's own fields,
# picked out by matching the site_domain.

APP_METADATA = {
    # CLASS: browser. A tab can be anything, so we need to see inside it.
    # Supported: Chrome, Chromium, Firefox, Edge, Safari, Brave, Opera, Arc,
    # Vivaldi. These fields are collected for every browser window, and then
    # WEBAPP_METADATA below adds site-specific fields on top.
    "browser": {
        "chrome": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "chromium": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "firefox": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "edge": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "safari": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "brave": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "opera": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "arc": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
        "vivaldi": ["site_url", "site_domain", "tab_title", "tab_focus_seconds", "history_domains"],
    },
    # CLASS: video player (native apps). What's playing and whether it plays.
    "video": {
        "vlc": ["media_title", "playback_state"],
        "mpv": ["media_title", "playback_state"],
    },
    # CLASS: code editor. Which file/branch hints at whether it's the right project.
    "editor": {
        "code": ["workspace_name", "file_path", "git_branch", "active_file_focus_seconds", "language"],
        "jetbrains": ["project_name", "file_path", "git_branch", "tool_window_focused"],
        "sublime_text": ["project_name", "file_path"],
        "notepad++": ["file_path"],
        "vim": ["file_path", "buffer_name"],
        "neovim": ["file_path", "buffer_name"],
        "emacs": ["file_path", "buffer_name"],
        "zed": ["workspace_name", "file_path", "git_branch"],
        # KDE full IDE with its own window chrome
        "kate": ["file_path", "document_name"],
        "cursor": ["workspace_name", "file_path", "git_branch", "chat_history_snippet"],
        "windsurf": ["workspace_name", "file_path", "git_branch", "chat_history_snippet"],
    },
    # CLASS: game launcher / game. Which game, and is it running or in a menu.
    "game": {
        "steam": ["store_page_url", "game_name", "game_running", "session_state", "time_in_game"],
        "epic_games_launcher": ["store_page_url", "game_name", "game_running"],
        "riot_client": ["store_page_url", "game_name", "game_running"],
        "battledotnet": ["game_name", "game_running"],
        "ea_app": ["game_name", "game_running"],
        "gog_galaxy": ["game_name", "game_running"],
        "minecraft": ["server_name_or_singleplayer", "session_state", "time_in_game"],
        "roblox": ["experience_name", "game_running"],
        # alternative store / installer front ends
        "heroic": ["store_page_url", "game_name", "game_running"],
        # game streaming front ends (Moonlight, GeForce Now style)
        "moonlight": ["host_name", "game_name", "connection_state"],
    },
    # CLASS: chat / social (native apps). The app is usually the distraction
    # itself, so only the basics plus whether a call is active.
    "chat": {
        "discord": ["server_or_dm_name", "voice_call_active", "streaming"],
        "slack": ["channel_name", "huddle_active"],
        "teams": ["channel_or_chat_name", "call_active"],
        "telegram": ["chat_name"],
        "whatsapp": ["chat_name"],
        "signal": ["chat_name"],
    },
    # CLASS: document editor / productivity (native apps).
    "document": {
        "word": ["document_name", "doc_focus_seconds"],
        "excel": ["workbook_name", "sheet_name"],
        "powerpoint": ["presentation_name", "slide_number"],
        "onenote": ["notebook_name", "page_title"],
        "obsidian": ["vault_name", "file_path"],
        "libreoffice": ["document_name", "doc_focus_seconds"],
        "texstudio": ["file_path"],
        # document *viewer*, same treatment
        "okular": ["document_name", "file_path", "page_number"],
    },    # CLASS: desktop utilities — the apps standard to a computer: file
    # manager, settings, information tools, system utilities. KDE for now;
    # GNOME / other DEs / Windows / macOS later.
    "desktop": {
        # file manager: which folder the user is in is the main signal
        "dolphin": ["location_path", "location_name"],
        # settings apps: which panel they have open
        "systemsettings": ["panel_name"],
        "kinfocenter": ["panel_name"],
        # terminal: which session/shell title
        "konsole": ["tab_name"],
        # image viewer / editor
        "gwenview": ["image_name"],
        "kolourpaint": ["image_name"],
        # git front end: which repo is open
        "github-desktop": ["repo_name"],
        # vpn front end: which panel
        "nordvpn": ["panel_name"],
        # archive manager
        "ark": ["archive_name"],
        # screenshot tool: which capture mode is being prepared
        "spectacle": ["capture_mode"],
        # software store: which store page
        "discover": ["page_name", "package_name"],
        # device pairing tool
        "kdeconnect": ["device_name", "connection_state"],
        # disk tool
        "partitionmanager": ["disk_name", "action_state"],
        # run dialog / calculator / clipboard helpers: name only
        "_default": ["tool_name"],
    },
}

# WEBAPP_METADATA: sites that aren't apps — they run inside one of the
# browsers above. When the focused browser's site_domain matches one of
# these keys, its fields are added on top of the browser's own fields.
WEBAPP_METADATA = {
    # Video / streaming sites.
    "youtube.com": ["video_title", "channel_name", "video_category", "tab_focus_seconds"],
    "youtube_music": ["track_title", "channel_name", "tab_focus_seconds"],  # music.youtube.com
    "netflix.com": ["show_title", "playback_state", "tab_focus_seconds"],
    "disneyplus.com": ["show_title", "playback_state", "tab_focus_seconds"],
    "twitch.tv": ["streamer_name", "stream_title", "stream_category", "tab_focus_seconds"],
    "spotify.com": ["track_title", "playlist_name", "playback_state"],      # open.spotify.com
    # Social / feeds.
    "x.com": ["feed_type", "profile_viewing"],                              # twitter/x
    "instagram.com": ["reels_active", "dm_active"],
    "tiktok.com": ["video_count_this_session", "session_state"],
    "reddit.com": ["subreddit", "post_title", "site_url", "tab_focus_seconds"],
    "facebook.com": ["feed_type", "chat_name"],
    "snapchat.com": ["chat_name"],
    # Documents / productivity sites.
    "docs.google.com": ["document_name", "editor_active", "tab_focus_seconds"],
    "notion.so": ["page_name", "page_type", "tab_focus_seconds"],
    "notion.com": ["page_name", "page_type", "tab_focus_seconds"],
    "overleaf.com": ["project_name", "file_path", "tab_focus_seconds"],
    "classroom.google.com": ["class_name", "assignment_name"],
    # Generic site / not in the list above: browser fields only.
    "_default": [],
}

# AT-SPI app names that belong to the desktop shell itself, not to a
# user's app; never report them as the focused app.
SHELL_APPS = {
    "kwin", "ksmserver", "plasmashell", "kded6", "kaccess", "ksecretd",
    "xembedsniproxy", "gmenudbusmenuproxy", "ActivityManager", "kwalletd",
    "polkit-kde-authentication-agent-1", "org_kde_powerdevil",
    "xdg-desktop-portal-kde", "xdg-desktop-portal-gtk", "kdeconnect.daemon",
    "xwaylandvideobridge", "kdeconnectd", "discover.notifier", "baloorunner",
    "gcdemu", " kvm", "shell", "org.gnome.Shell", "gnome-shell",
}

# Window-title suffixes -> canonical APP_METADATA key, so
# "Page title - Chromium" identifies the app as a browser even if the
# AT-SPI app id looks odd, and gives us the active tab's title.
TITLE_SUFFIXES = {
    "google chrome": "chrome",
    "chrome canary": "chrome",
    "chromium": "chromium",
    "mozilla firefox": "firefox",
    "firefox": "firefox",
    "microsoft edge": "edge",
    "brave": "brave",
    "opera gx": "opera",
    "opera": "opera",
    "arc": "arc",
    "vivaldi": "vivaldi",
    "safari": "safari",
    "visual studio code": "code",
}

# Key: normalized app id -> APP_METADATA key. AT-SPI app names vary
# ("code", "Code", ...) so everything goes through this map first.
APP_ALIASES = {
    "vscode": "code",
    "google-chrome": "chrome",
    "microsoft-edge": "edge",
    # package/form ids that don't split into a known token
    "zenbrowser": "zen",
    "waterfox-current": "waterfox",
    "waterfox-classic": "waterfox",
    "nordvpn-gui": "nordvpn",
    "hgl": "heroic",   # Heroic Games Launcher flatpak window class
    "visual-studio-code": "code",
    "github desktop": "github-desktop",
    "githubdesktop": "github-desktop",
}

# Gecko soft-forks keep Firefox's sessionstore format and layout exactly,
# so they get the same browser metadata fields and are routed through the
# same sessionstore reader (see _GECKO_PROFILE_ROOTS for their paths).
for _gecko_fork in ("librewolf", "waterfox", "zen", "floorp"):
    APP_METADATA["browser"][_gecko_fork] = list(APP_METADATA["browser"]["firefox"])
del _gecko_fork

# Every app key defined across all APP_METADATA classes (for _canonical()).
_ALL_APP_KEYS = {key for apps in APP_METADATA.values() for key in apps}

# KWin/AT-SPI class -> the display name the app puts in its own window
# title, so "cranky-clippy — Dolphin" does not report the folder as
# "cranky-clippy".
_DESKTOP_APP_DISPLAY_NAMES = {
    "dolphin": {"dolphin", "file manager"},
    "systemsettings": {"system settings", "settings"},
    "kinfocenter": {"kinfocenter", "info center"},
    "ark": {"ark"},
    "spectacle": {"spectacle"},
    "discover": {"discover", "software center"},
    "kdeconnect": {"kde connect", "kdeconnect"},
    "partitionmanager": {"kde partition manager"},
    "konsole": {"konsole", "terminal"},
    "kolourpaint": {"kolourpaint", "kolour paint"},
    "gwenview": {"gwenview"},
    "github-desktop": {"github desktop", "githubdesktop"},
    "nordvpn": {"nordvpn"},
}

# Same idea for game launchers: their window title often carries just the
# launcher's own name, which is not a game.
_GAME_DISPLAY_NAMES = {
    "steam": {"steam"},
    "heroic": {"heroic games launcher", "heroic"},
    "epic_games_launcher": {"epic games launcher", "epic"},
    "riot_client": {"riot client"},
    "battledotnet": {"battle.net", "battle"},
    "gog_galaxy": {"gog galaxy", "gog"},
    "ea_app": {"ea app", "ea"},
    "roblox": {"roblox"},
    "minecraft": {"minecraft launcher"},
    "moonlight": {"moonlight"},
}


# --- focused-window backends -------------------------------------------------
#
# Two ways to find the focused window. On KDE, KWin itself is the only
# source of truth: the AT-SPI ACTIVE flag often stays on a dead window, so
# we ask the compositor over DBus (load a tiny script via
# org.kde.kwin.Scripting, which reports workspace.activeWindow). Everywhere
# else we use the AT-SPI accessibility tree.
#
# Reference for the KDE pattern: kdotool works the same way (loadScript +
# start + callDBus back to a private DBus service). The `start()` call is
# mandatory on current KWin versions: loadScript only parks the script.

def _desktop_kind():
    return (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()


def _active_window_kwin():
    """KDE backend: ask KWin for the focused window. Returns dict app_class,
    caption or None."""
    if not _DBUS_OK or "kde" not in _desktop_kind():
        return None

    result = {}
    loop = GLib.MainLoop()

    class _Detector(dbus.service.Object):
        def __init__(self, conn):
            dbus.service.Object.__init__(self, conn, "/com/crankyclippy/detector")

        @dbus.service.method("com.crankyclippy.detector", in_signature="ss")
        def Report(self, app_class, caption):
            result["app_class"] = str(app_class)
            result["caption"] = str(caption)
            loop.quit()

    try:
        session_bus = dbus.SessionBus()
        before = session_bus.get_unique_name()
    except Exception:
        return None

    try:
        _Detector(session_bus)
    except Exception:
        return None

    js = (
        "try {\n"
        "    var win = workspace.activeWindow;\n"
        '    if (win) { callDBus("%s", "/com/crankyclippy/detector",'
        ' "com.crankyclippy.detector", "Report",'
        " win.resourceClass, win.caption); }\n"
        "} catch (e) {\n"
        '    callDBus("%s", "/com/crankyclippy/detector",'
        ' "com.crankyclippy.detector", "Report", "SCRIPT-ERROR", String(e));\n'
        "}\n" % (before, before)
    )
    plugin_name = "cranky-detect-%s" % uuid.uuid4().hex[:8]

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(js)
        js_path = fh.name

    try:
        session_bus.call_blocking("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting",
                                  "loadScript", "ss", (js_path, plugin_name))
        # start is what actually runs the script on current KWin
        session_bus.call_blocking("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting",
                                  "start", "", ())
        def _timeout():
            loop.quit()
            return False
        GLib.timeout_add_seconds(3, _timeout)
        loop.run()
    except Exception:
        result = {}
    finally:
        try:
            session_bus.call_blocking("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting",
                                      "unloadScript", "s", (plugin_name,))
        except Exception:
            pass
        finally:
            os.unlink(js_path)

    out = result.get("app_class"), result.get("caption")
    if not out[0]:
        # no focused window at all (or the report timed out) — KWin is
        # authoritative on KDE, so signal "nothing is focused" rather than
        # letting callers fall back to the stale AT-SPI tree
        return {"no_active": True}
    if out[0] == "SCRIPT-ERROR":
        return None
    return {"app_class": out[0], "caption": out[1]}


def _active_window_atspi():
    """AT-SPI fallback: return (app_name, window_title) of the ACTIVE frame,
    or (None, None). Note: on KDE this can be stale — the KWin backend wins."""
    if not _ATSPI_OK:
        return None, None
    try:
        desktop = Atspi.get_desktop(0)
    except Exception:
        return None, None
    for i in range(desktop.get_child_count()):
        try:
            app = desktop.get_child_at_index(i)
        except Exception:
            continue
        try:
            app_name = (app.get_name() or "").lower()
        except Exception:
            continue
        if app_name in (s.strip() for s in SHELL_APPS):
            continue
        try:
            frame_count = app.get_child_count()
        except Exception:
            continue  # app died between listing and walking
        for j in range(frame_count):
            try:
                frame = app.get_child_at_index(j)
                if frame is None:
                    continue
                if frame.get_role() not in (Atspi.Role.FRAME, Atspi.Role.DIALOG):
                    continue
                if frame.get_state_set().contains(Atspi.StateType.ACTIVE):
                    return app_name, (frame.get_name() or "")
            except Exception:
                continue
    return None, None


def _find_app_frame(app_key, caption):
    """Locate the focused app's AT-SPI frame (for deep reads like the URL
    bar). Preference: ACTIVE frame -> exact caption match -> first window.

    App ids never line up perfectly between KWin ("chrome") and AT-SPI
    ("google-chrome"), so the name check tries exact, then suffix forms.
    """
    if not _ATSPI_OK:
        return None

    def _norm(s):
        return re.sub(r"[-_.\s]", "", (s or "").strip().lower())

    target = _norm(app_key)
    if not target:
        return None
    fallback = None
    caption_match = None
    try:
        desktop = Atspi.get_desktop(0)
        desktop_count = desktop.get_child_count()
    except Exception:
        return None
    for i in range(desktop_count):
        try:
            app = desktop.get_child_at_index(i)
            aname = _norm(app.get_name())
            if aname != target and not aname.endswith(target) and not target.endswith(aname):
                continue
        except Exception:
            continue
        try:
            frame_count = app.get_child_count()
        except Exception:
            continue  # app died between listing and walking
        for j in range(frame_count):
            try:
                frame = app.get_child_at_index(j)
                title = frame.get_name() or ""
            except Exception:
                continue
            fallback = fallback or frame
            if caption and _norm(title) == _norm(caption) and caption_match is None:
                caption_match = frame
    if caption_match is not None:
        return caption_match
    return fallback


def _walk(node, max_depth=12, max_nodes=1500):
    """Iterate (node, depth) over an AT-SPI subtree, best effort."""
    budget = max_nodes
    stack = [(node, 0)]
    while stack and budget > 0:
        n, d = stack.pop()
        budget -= 1
        yield n, d
        if d >= max_depth:
            continue
        try:
            for i in range(n.get_child_count()):
                try:
                    child = n.get_child_at_index(i)
                    if child is not None:
                        stack.append((child, d + 1))
                except Exception:
                    pass
        except Exception:
            pass


def _node_text(node):
    """Best-effort text of a text/entry AT-SPI node."""
    for getter in (lambda: node.get_text(0, -1), lambda: node.query_text().get_text(0, -1)):
        try:
            t = getter()
            if t and "." not in t.expandtabs(0)[:0]:
                return t
        except Exception:
            pass
    return None


# --- Firefox session store ---------------------------------------------------
#
# Snap Firefox is fenced off from AT-SPI by AppArmor, so its URL bar can't
# be read from the accessibility tree. But Firefox — and every Gecko
# soft-fork, which keep the same sessionstore format and layout — writes its
# complete session (all windows, all tabs, current URLs and titles) to
# sessionstore-backups/recovery.jsonlz4 every few seconds, and that file is
# world-readable for the user's own uid. That is the URL source for the
# Gecko family — no accessibility involved. Paths below cover deb/rpm,
# snap and flatpak installs (flatpak dirs also match by id glob).

_GECKO_PROFILE_ROOTS = {
    "firefox": (
        "~/.mozilla/firefox",
        "~/snap/firefox/common/.mozilla/firefox",
        "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
    ),
    "librewolf": (
        "~/.librewolf",
        "~/snap/librewolf/common/.librewolf",
        "~/.var/app/io.gitlab.librewolf-community/.librewolf",
    ),
    "waterfox": (
        "~/.waterfox",
        "~/.var/app/*waterfox*/.waterfox",
    ),
    "zen": (
        "~/.zen",
        "~/.var/app/app.zenbrowser.ZenBrowser/.zen",
    ),
    "floorp": (
        "~/.floorp",
        "~/snap/floorp/common/.floorp",
        "~/.var/app/one.ablaze.floorp/.floorp",
    ),
}

# Every gecko-family browser key routed through the sessionstore reader.
_GECKO_SESSIONSTORE_BROWSERS = set(_GECKO_PROFILE_ROOTS)

def _decompress_mozlz4(raw):
    """Decompress Firefox's mozlz4 file (mozLz40 header + raw LZ4 block)."""
    if not raw.startswith(b"mozLz40\0"):
        raise ValueError("not a mozlz4 file")
    out = bytearray()
    pos = 12  # magic (8) + original size (4)
    n = len(raw)
    while pos < n:
        token = raw[pos]
        pos += 1
        lit_len = token >> 4
        if lit_len == 15:
            while raw[pos] == 255:
                lit_len += 255
                pos += 1
            lit_len += raw[pos]
            pos += 1
        out += raw[pos:pos + lit_len]
        pos += lit_len
        if pos >= n:
            break
        offset = int.from_bytes(raw[pos:pos + 2], "little")
        pos += 2
        match_len = token & 0x0F
        if match_len == 15:
            while True:
                b = raw[pos]
                pos += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4
        start = len(out) - offset
        for i in range(match_len):
            out.append(out[start + i])
    return bytes(out)


def _firefox_session_file(browser_key="firefox"):
    """Newest live sessionstore file across debs, snaps, flatpaks and the
    Gecko soft-forks (LibreWolf, Waterfox, Zen, Floorp)."""
    import glob as _glob

    newest = None
    for pattern in _GECKO_PROFILE_ROOTS.get(browser_key, ()):
        for root in _glob.glob(os.path.expanduser(pattern)):
            try:
                profiles = os.scandir(root)
            except OSError:
                continue
            for profile in profiles:
                if not profile.is_dir():
                    continue
                for name in ("recovery.jsonlz4", "previous.jsonlz4"):
                    path = os.path.join(root, profile.name, "sessionstore-backups", name)
                    try:
                        mtime = os.path.getmtime(path)
                    except OSError:
                        continue
                    if newest is None or mtime > newest[0]:
                        newest = (mtime, path)
    if newest is None:
        return None
    try:
        with open(newest[1], "rb") as fh:
            raw = fh.read()
        return json.loads(_decompress_mozlz4(raw))
    except Exception:
        return None


def _tab_entry(tab):
    """url + title of the tab's current history entry."""
    entries = tab.get("entries") or []
    i = (tab.get("index") or 1) - 1
    entry = entries[i] if 0 <= i < len(entries) else {}
    return (entry.get("url") or tab.get("url") or ""), (entry.get("title") or tab.get("title") or "")


def _firefox_focus(window_title, browser_key="firefox"):
    """Return the tab dict most likely to be the focused Gecko-family tab."""
    session = _firefox_session_file(browser_key)
    if not session:
        return None
    needle = _tab_title_from_window(window_title)  # caption minus "- Firefox"
    fallback = None
    for window in session.get("windows", []):
        for idx, tab in enumerate(window.get("tabs", [])):
            url, title = _tab_entry(tab)
            cand = {
                "url": url,
                "title": title,
                "tab": tab,
                "window": window,
                "idx": idx,
                "lastAccessed": tab.get("lastAccessed") or 0,
            }
            if fallback is None or cand["lastAccessed"] > fallback["lastAccessed"]:
                fallback = cand
            if _title_matches(needle, title):
                return cand
    return fallback


def _firefox_other_domains(window, exclude_idx, limit=8):
    """Domains of the other open tabs in the window, most recent first."""
    per_domain = {}
    for idx, tab in enumerate(window.get("tabs", [])):
        if idx == exclude_idx:
            continue
        url, _ = _tab_entry(tab)
        if not url.startswith("http"):
            continue
        domain = _domain_from_url(url)
        if domain:
            per_domain[domain] = max(per_domain.get(domain, 0), tab.get("lastAccessed") or 0)
    return [d for d, _ in sorted(per_domain.items(), key=lambda kv: kv[1], reverse=True)[:limit]]


def _read_browser_url(frame):
    """Read the URL from the browser's address bar, if accessibility allows.

    Firefox exposes its URL bar as "Search or enter web address", Chrome
    family as "Address and search bar"/"Omnibox". Anything that looks like
    a URL is taken; None when the browser does not cooperate.
    """
    url_re = re.compile(r"^[a-z][a-z0-9+.-]*://|^(about|chrome|moz):/", re.I)
    for node, _ in _walk(frame):
        if node.get_role() not in (Atspi.Role.ENTRY, Atspi.Role.TEXT):
            continue
        name = (node.get_name() or "").lower()
        text = _node_text(node)
        if text and url_re.match(text.strip()):
            return text.strip()
        if not text and ("address" in name or "url" in name or "enter" in name):
            # the url-bar entry exists but its text came back empty
            continue
    return None


# --- Chromium-family history fallback ----------------------------------------
#
# Chrome/Chromium/Brave/Edge/Opera (and Opera GX) do not expose their UI
# through AT-SPI on some Wayland sessions — the browser frame shows up as a
# stub with no children. They do, however, keep a plain SQLite History
# database that is updated while browsing, so the current page can be found
# there: match the window title (page title) against the most recent
# visited rows. Read-only against a temp copy so the live database lock
# never matters.

# Chromium-family History fallback per browser, across packaging forms
# (deb/rpm direct config, flatpak ~/.var/app, snap ~/snap/<name>). Some
# roots may contain glob chars; each root may either hold the profile's
# History DB directly (Opera) or hold profile subdirectories that do
# (Chrome's Default/, Profile 1/...).

_CHROMIUM_PROFILE_ROOTS = {
    "chrome": (
        "~/.config/google-chrome",
        "~/.var/app/com.google.Chrome/config/google-chrome",
    ),
    "chromium": (
        "~/.config/chromium",
        "~/snap/chromium/common/chromium",
        "~/.var/app/org.chromium.Chromium/config/chromium",
    ),
    "brave": (
        "~/.config/BraveSoftware/Brave-Browser",
        "~/snap/brave/current/.config/BraveSoftware/Brave-Browser",
        "~/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser",
    ),
    "edge": (
        "~/.config/microsoft-edge",
        "~/.var/app/com.microsoft.Edge/config/microsoft-edge",
    ),
    "opera": (
        "~/.config/opera",
        "~/.config/opera-gx",
        "~/snap/opera/common/.config/opera",
        "~/.var/app/com.opera.Opera/config/opera",
        "~/.var/app/com.opera.OperaGX/config/opera-gx",
    ),
    "vivaldi": (
        "~/.config/vivaldi",
        "~/.var/app/com.vivaldi.Vivaldi/config/vivaldi",
    ),
}

# Profile directories that never contain a user's browsing history.
_PROFILE_DIR_SKIPS = {
    "system profile", "guest profile", "crashpad", "registration",
    "component updater", "crash reports", "pending pings", "profile groups",
}


def _chromium_history_db(app_key):
    """Path of the History DB with the most recent mtime, or None.

    Each root is either a profile directory itself (History directly
    inside — Opera's layout) or a parent of profile directories
    (Chrome's Default/, Profile 1/, ...).
    """
    import glob as _glob

    newest = None
    for pattern in _CHROMIUM_PROFILE_ROOTS.get(app_key, []):
        root = os.path.expanduser(pattern)
        if os.path.isdir(root):
            search = [root]
        else:
            search = [r for r in _glob.glob(root) if os.path.isdir(r)]
        for base in search:
            for profile_dir in [base] + [
                p.path for p in os.scandir(base) if p.is_dir()
            ]:
                if os.path.basename(profile_dir).lower() in _PROFILE_DIR_SKIPS:
                    continue
                hist = os.path.join(profile_dir, "History")
                try:
                    mtime = os.path.getmtime(hist)
                except OSError:
                    continue
                if newest is None or mtime > newest[0]:
                    newest = (mtime, hist)
    return newest[1] if newest else None


def _chromium_history_rows(app_key, limit=60):
    """Most recent visits as (url, title, last_visit_time) tuples, or []."""
    import shutil
    import sqlite3

    db = _chromium_history_db(app_key)
    if not db:
        return []
    tmp = os.path.join(tempfile.gettempdir(), "cranky-%s-%d-History" % (app_key, os.getpid()))
    try:
        shutil.copy2(db, tmp)
        # include the WAL companion or recent writes may be invisible
        for ext in ("-wal", "-shm"):
            try:
                shutil.copy2(db + ext, tmp + ext)
            except OSError:
                pass
        conn = sqlite3.connect(tmp)
        try:
            rows = conn.execute(
                "SELECT url, title, last_visit_time FROM urls "
                "ORDER BY last_visit_time DESC LIMIT %d" % limit
            ).fetchall()
        finally:
            conn.close()
        return rows
    except Exception:
        return []
    finally:
        for ext in ("", "-wal", "-shm"):
            try:
                os.unlink(tmp + ext)
            except OSError:
                pass


def _clean_chromium_title(title):
    return re.sub(r"^\(\d+\)\s*", "", (title or "").strip())


def _title_matches(needle, title):
    """Needle-vs-title match that tolerates prefixes/suffixes but refuses
    trivial hits (e.g. one-word title 'X' matching '(3) Home / X')."""
    if not needle or not title:
        return False
    t = _clean_chromium_title(title).lower()
    n = _clean_chromium_title(needle).lower()
    if t == n:
        return True
    if len(t) >= 15 and t in n:
        return True
    if len(n) >= 15 and n in t:
        return True
    return False


def _chromium_history_url(app_key, window_title):
    """Best-guess URL + title of the page in the focused Chromium window."""
    rows = _chromium_history_rows(app_key)
    if not rows:
        return None
    needle = _tab_title_from_window(window_title)
    if needle:
        for url, title, _t in rows:
            if _title_matches(needle, title):
                return url, title
    url, title, _t = rows[0]
    return url, title


def _chromium_recent_domains(app_key, needle, limit=8):
    """Domains from the most recent browsing (current tab first)."""
    rows = _chromium_history_rows(app_key)
    out, self_domain = {}, None
    for url, title, t in rows:
        domain = _domain_from_url(url)
        if not domain or not url.startswith("http"):
            continue
        if needle and self_domain is None and _title_matches(needle, title):
            self_domain = domain   # skip the focused tab's domain entirely
            continue
        if self_domain and domain == self_domain:
            continue
        out.setdefault(domain, t)
    return [d for d in sorted(out, key=out.get, reverse=True)][:limit]


def _domain_from_url(url):
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
        # drop the cosmetic subdomains we add to match keys: open./www.;
        # music. is kept so YouTube Music can be told apart from YouTube
        return re.sub(r"^(open|www)\.", "", host)
    except Exception:
        return None


def _canonical(raw):
    """Reduce an app id to an APP_METADATA key.

    Handles the messy ids desktops hand out: "firefox_firefox" (snap),
    "org.mozilla.firefox" (flatpak), "google-chrome-stable", "vscode"...
    """
    raw = (raw or "").strip().lower()
    if raw in APP_ALIASES:
        return APP_ALIASES[raw]
    if raw in _ALL_APP_KEYS:
        return raw
    # snap/flatpak/deb-style ids: find a token that names a known app
    for token in re.split(r"[-_. ]", raw):
        if not token:
            continue
        if token in APP_ALIASES:
            return APP_ALIASES[token]
        if token in _ALL_APP_KEYS:
            return token
    return raw


def _title_suffix_re(suffix):
    """RegExp for a title suffix after ' - ', ' — ' or ' – ' (KDE, Firefox
    and friends use em dashes, most Chromium windows use plain hyphens)."""
    return re.compile(r"\s+[-\u2013\u2014]\s+" + re.escape(suffix) + r"\s*$", re.I)


def _tab_title_from_window(window_title):
    """Strip the browser/identity suffix from a window title.

    Window titles look like "<tab title> - Chromium" or
    "<file path> - <project> - Visual Studio Code"; drop the LAST known
    suffix and return what's left (the active tab's title).
    """
    if not window_title:
        return None
    for suffix, _ in TITLE_SUFFIXES.items():
        m = _title_suffix_re(suffix).search(window_title)
        if m:
            return window_title[: m.start()].strip() or None
    return window_title.strip() or None


def _match_app(app_name, window_title):
    """Map the raw app id / window title to (class, app key)."""
    raw = _canonical(app_name).strip().lower()
    for cls, apps in APP_METADATA.items():
        if raw in apps:
            return cls, raw
    alias = APP_ALIASES.get(raw, raw)
    if alias != raw:
        for cls, apps in APP_METADATA.items():
            if alias in apps:
                return cls, alias
    # fall back to window-title suffixes (always names a known app)
    for suffix, key in TITLE_SUFFIXES.items():
        if _title_suffix_re(suffix).search(window_title or ""):
            for cls, apps in APP_METADATA.items():
                if key in apps:
                    return cls, key
    return None, None


def _collect_browser_metadata(app_key, window_title, frame):
    """URL/tab title for the focused browser window.

    Firefox: sessionstore file (its URL bar is AppArmor-fenced in the snap).
    Chromium family: AT-SPI address bar read when the browser exposes one;
    otherwise its History DB, matching the window title against the most
    recent visits.
    """
    url = None
    tab_title = None
    history = None

    if app_key in _GECKO_SESSIONSTORE_BROWSERS:
        info = _firefox_focus(window_title, app_key)
        if info:
            url = info["url"] or None
            tab_title = info["title"] or None
            history = _firefox_other_domains(info["window"], info["idx"])
    else:
        url = _read_browser_url(frame) if frame is not None else None
        if not url:
            info = _chromium_history_url(app_key, window_title)
            if info:
                url = info[0]
                tab_title = info[1]
        if not tab_title:
            tab_title = _tab_title_from_window(window_title)
        if not history and url:
            history = _chromium_recent_domains(
                app_key, _tab_title_from_window(window_title))

    if not tab_title:
        tab_title = _tab_title_from_window(window_title)
    domain = _domain_from_url(url) if url else None
    fields = {
        "site_url": url,
        "site_domain": domain,
        "tab_title": tab_title,
        # focus timing needs a running tracker; single-shot runs report None
        "tab_focus_seconds": None,
        "history_domains": history,
    }
    return {k: fields.get(k) for k in APP_METADATA["browser"][app_key]}


def _title_parts(window_title):
    parts = [p.strip() for p in (window_title or "").split(" - ") if p.strip()]
    # KDE apps (Dolphin etc.) split with an em/en dash: "folder — Dolphin"
    out = []
    for p in parts:
        out.extend(q.strip() for q in re.split(r"\s+[—–]\s+", p) if q.strip())
    return out


def _collect_generic_metadata(cls, app_key, window_title):
    """Best-effort metadata for non-browser apps.

    Everything truly derivable from the window title goes in; fields that
    need deeper per-app integrations stay None for now (Jev tolerates it).
    """
    parts = _title_parts(window_title)
    meta = {}
    for field in APP_METADATA[cls][app_key]:
        meta[field] = None

    if cls == "editor":
        # "file.py - project - Visual Studio Code" / "file.py — Kate" /
        # "file.py - Vim": first part is the file; workspace (rarely) in
        # parts[1] only when it is not the app's own identify.
        identity = {
            "visual studio code", "kate", "vim", "neovim", "emacs",
            "sublime text", "zed", "code", "cursor", "windsurf",
        }
        if parts:
            meta["file_path"] = parts[0]
            base = os.path.basename(parts[0])
            if "document_name" in meta:
                meta["document_name"] = base or None
            for p in parts[1:]:
                if p.lower() not in identity:
                    if "workspace_name" in meta:
                        meta["workspace_name"] = p
                    break
            ext = base.rsplit(".", 1)[-1]
            if "language" in meta and "." in base and 1 <= len(ext) <= 5:
                meta["language"] = ext
    elif cls == "video" or app_key in ("vlc", "mpv"):
        # "video_title - VLC media player" / "<title> - mpv"
        meta["media_title"] = _tab_title_from_window(window_title)
    elif cls == "chat":
        # Discord: "server - channel - Discord"
        if parts and "?" not in parts[-1]:
            meta["server_or_dm_name"] = parts[0]
        if window_title and ("voice" in window_title.lower() or "call" in window_title.lower()):
            meta["voice_call_active"] = True
        if window_title and "stream" in window_title.lower():
            meta["streaming"] = True
    elif cls == "document":
        if parts:
            meta["document_name"] = parts[0]
    elif cls == "desktop":
        # Window titles are "<what is open><dash><App name>". The first
        # part is usually the thing being worked on (folder, settings
        # panel, archive, ...); polish per app.
        thing = None
        for p in parts:
            if p.lower() not in _DESKTOP_APP_DISPLAY_NAMES.get(app_key, {app_key}):
                thing = p
                break
        if app_key == "dolphin":
            # title is "<folder — Dolphin"; real full path needs a deep
            # read, so the folder name goes to location_name for now
            meta["location_name"] = thing
        elif app_key in ("systemsettings", "kinfocenter"):
            meta["panel_name"] = thing
        elif app_key == "ark":
            meta["archive_name"] = thing
        elif app_key == "spectacle":
            meta["capture_mode"] = thing
        elif app_key == "discover":
            meta["page_name"] = thing
        elif app_key == "kdeconnect":
            meta["device_name"] = thing
        elif app_key == "partitionmanager":
            meta["disk_name"] = thing
        elif app_key in ("kolourpaint", "gwenview"):
            meta["image_name"] = thing
        elif app_key == "konsole":
            meta["tab_name"] = thing
        elif app_key == "github-desktop":
            meta["repo_name"] = thing
        elif app_key == "nordvpn":
            meta["panel_name"] = thing
        else:
            meta["tool_name"] = thing
    elif cls == "game":
        # launchers show the current page in the title; exact page name only
        # when it is not just the launcher's own name.
        display = _GAME_DISPLAY_NAMES.get(app_key, {app_key})
        for p in parts:
            if p.lower() not in display:
                meta["game_name"] = p
                break
    return meta


def _match_webapp(domain):
    """Match a site domain to WEBAPP_METADATA; ('youtube_music' etc. handled)."""
    if not domain:
        return None
    # YouTube Music must be checked before the youtube.com suffix match
    if domain == "music.youtube.com" or domain.endswith(".music.youtube.com"):
        return "youtube_music"
    for key in WEBAPP_METADATA:
        if key == "_default":
            continue
        if domain == key or domain.endswith("." + key):
            return key
    return "_default"


# When the URL isn't available (snap Firefox hides its URL bar behind
# AppArmor), many sites still identify themselves by their title suffix.
_WEBAPP_TITLE_HINTS = (
    (r"\s+[-\u2013\u2014]\s+YouTube Music$", "youtube_music"),
    (r"\s+[-\u2013\u2014]\s+YouTube$", "youtube.com"),
    (r"\s+\|\s+Netflix$", "netflix.com"),
    (r"\s+\|\s+Disney\+$", "disneyplus.com"),
    (r"\s+\|\s+Spotify", "spotify.com"),
    (r"\s+[-\u2013\u2014]\s+Twitch$", "twitch.tv"),
    (r"\s+[-\u2013\u2014]\s+Reddit$", "reddit.com"),
    (r"^Reddit\s+[-\u2013\u2014]\s+", "reddit.com"),
    (r"\s+[-\u2013\u2014]\s+Google Docs$", "docs.google.com"),
    (r"[\s|]+\s*Notion.?$", "notion.so"),
    (r"\s+[-\u2013\u2014]\s+Overleaf, Online LaTeX Editor", "overleaf.com"),
)


def _match_webapp_from_title(tab_title):
    """Guess the webapp from a known site title suffix; None when unknown."""
    if not tab_title:
        return None
    for pat, key in _WEBAPP_TITLE_HINTS:
        if re.search(pat, tab_title, re.I):
            return key
    return None


def _youtube_video_id(url):
    """v= parameter or /shorts/<id> path segment; None when not a watch URL."""
    try:
        query = urllib.parse.parse_qs(urlparse(url).query) if url else {}
        if "v" in query and query["v"]:
            return query["v"][0]
        m = re.search(r"/shorts/([A-Za-z0-9_-]{5,20})", url or "")
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _youtube_channel_from_url(url):
    """Channel name via YouTube's public oEmbed endpoint (unauthenticated).

    network-bound, so strictly best-effort: any failure returns None.
    """
    video_id = _youtube_video_id(url)
    if not video_id:
        return None
    try:
        import urllib.parse
        import urllib.request

        embed_url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(
            "https://www.youtube.com/watch?v=" + video_id, safe=""
        )
        with urllib.request.urlopen(embed_url, timeout=2) as resp:
            data = json.loads(resp.read().decode())
        author = data.get("author_name")
        return author if author else None
    except Exception:
        return None


def _collect_webapp_metadata(webapp_key, site_url, tab_title, window_title):
    """Best-effort site metadata from URL/tab title; None where unavailable."""
    meta = {k: None for k in WEBAPP_METADATA.get(webapp_key, [])}
    if webapp_key == "_default":
        return meta

    if webapp_key == "youtube.com":
        # page title is usually "<video title> - YouTube"; live/premiere
        # titles may carry a "(N) watching" prefix — drop it
        m = re.search(r"^(.*)\s+-\s+YouTube$", tab_title or window_title or "")
        if m:
            meta["video_title"] = re.sub(r"^\(\d+\)\s*", "", m.group(1).strip())
        if site_url:
            meta["channel_name"] = _youtube_channel_from_url(site_url)
    elif webapp_key == "youtube_music":
        m = re.search(r"^(.*)\s+-\s+YouTube Music$", tab_title or window_title or "")
        if m:
            meta["track_title"] = m.group(1).strip()
        if site_url:
            meta["channel_name"] = _youtube_channel_from_url(site_url)
    elif webapp_key == "netflix.com":
        m = re.search(r"^(.*)\s+\|\s+Netflix.*$", tab_title or window_title or "")
        if m:
            meta["show_title"] = m.group(1).strip()
    elif webapp_key == "twitch.tv":
        m = re.search(r"^(.*)\s+[-\u2013\u2014]\s+Twitch$", tab_title or window_title or "")
        url_streamer = None
        if site_url:
            path = urlparse(site_url).path.strip("/")
            first = path.split("/")[0] if path else ""
            if first and first.lower() not in (
                "directory", "videos", "downloads", "settings", "jobs", "store", "turbo",
            ):
                url_streamer = first
        if url_streamer:
            meta["streamer_name"] = url_streamer
        if m:
            # "streamer - stream title - Twitch" or just "streamer - Twitch"
            segs = [s.strip() for s in m.group(1).split(" - ") if s.strip()]
            if len(segs) >= 2:
                if not url_streamer:
                    meta["streamer_name"] = segs[0]
                meta["stream_title"] = " - ".join(segs[1:])
            elif len(segs) == 1 and not url_streamer:
                meta["stream_title"] = segs[0]
    elif webapp_key == "spotify.com":
        combined = tab_title or window_title or ""
        m = re.search(r"^(.*)\s+\|\s+Spotify(.*)$", combined)
        if m:
            name = m.group(1).strip()
            if m.group(2).lower().startswith(" playlist"):
                meta["playlist_name"] = name
            else:
                meta["track_title"] = name
    elif webapp_key == "reddit.com":
        meta["site_url"] = site_url
        combined = tab_title or ""
        m = re.search(
            r"^(.*\S)\s+(?:[-\u2013\u2014]|\u2022)\s+(r/[\w-]+)\s*(?:[-\u2013\u2014]\s+Reddit.?)?$",
            combined,
        )
        if m:
            meta["post_title"] = m.group(1).strip()
            meta["subreddit"] = m.group(2).strip()
        else:
            m2 = re.search(r"^(.*\S)\s+[-\u2013\u2014]\s+Reddit.?$", combined)
            if m2:
                meta["post_title"] = m2.group(1).strip()
    elif webapp_key == "docs.google.com":
        m = re.search(r"^(.*)\s+[-\u2013\u2014]\s+Google Docs$", tab_title or window_title or "")
        name = m.group(1).strip() if m else (tab_title or "").strip()
        if name:
            meta["document_name"] = name
    elif webapp_key == "notion.so":
        m = re.search(r"^(.*\S)\s+[-\u2013\u2014|]\s+Notion.?$", tab_title or window_title or "")
        name = m.group(1).strip() if m else (tab_title or "").strip()
        if name:
            meta["page_name"] = name
    elif webapp_key == "overleaf.com":
        m = re.search(r"^(.*)\s+-\s+Overleaf", tab_title or window_title or "")
        if m:
            meta["project_name"] = m.group(1).strip()
    return meta


def get_desktop_state(user_goal=None):
    """Collect what the user is doing right now; returns the state dict."""
    kwin = _active_window_kwin()
    if kwin is not None and kwin.get("no_active"):
        # On KDE, KWin is the only source of truth: if it says nothing is
        # focused (desktop peek, no focus, or between windows) we report
        # exactly that instead of the stale accessibility tree.
        universal = {
            "app_focused_name": "none",
            "app_class": "none",
            "window_title": None,
            "detection_backend": "kwin",
            "focus_lost": True,
            "time_window_focused": None,
            "last_active_seconds": None,
            "afk_seconds": None,
            "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if user_goal:
            universal["user_goal"] = user_goal
        return {"universal": universal}

    if kwin is not None:
        state_source = "kwin"
        raw_app_name = kwin["app_class"]
        window_title = kwin["caption"]
    else:
        state_source = "atspi"
        raw_app_name, window_title = _active_window_atspi()

    cls, app_key = _match_app(raw_app_name, window_title)
    # Deep reads (browser URL bar) go through the accessibility tree; look
    # up the frame by the canonical app key when we have one.
    want_frame = app_key or _canonical(raw_app_name)
    frame = _find_app_frame(want_frame, window_title) if want_frame else None

    universal = {
        "app_focused_name": app_key or (raw_app_name or "").strip().lower() or "unknown",
        "app_class": cls or "unknown",
        "window_title": window_title,
        "detection_backend": state_source,
        "focus_lost": False,
        # single-shot run: no tracker running yet, so these are None until
        # the polling/timing collector exists.
        "time_window_focused": None,
        "last_active_seconds": None,
        "afk_seconds": None,
        "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if user_goal:
        universal["user_goal"] = user_goal

    state = {"universal": universal}

    if cls:
        if cls == "browser":
            state["app_metadata"] = _collect_browser_metadata(app_key, window_title, frame)
        else:
            state["app_metadata"] = _collect_generic_metadata(cls, app_key, window_title)

        if cls == "browser":
            md = state["app_metadata"]
            # The tab title is the freshest signal (it IS the visible tab),
            # so a title hint outranks the possibly-stale history DB match.
            hinted = _match_webapp_from_title(md.get("tab_title"))
            webapp_key = hinted
            if webapp_key:
                matched_via = "tab_title"
            else:
                webapp_key = _match_webapp(md.get("site_domain"))
                matched_via = "url"
            if webapp_key and webapp_key != "_default":
                state["webapp"] = {
                    "site_domain": md.get("site_domain"),
                    "matched_via": matched_via,
                    "metadata": _collect_webapp_metadata(
                        webapp_key,
                        md.get("site_url"),
                        md.get("tab_title"),
                        window_title,
                    ),
                }
    return state


def _print_state(state):
    """Human-readable test report: universal -> app metadata -> web metadata."""
    u = state.get("universal", {})
    print("== UNIVERSAL ==")
    for k, v in u.items():
        print(f"{k}: {v}")
    if "app_metadata" in state:
        print("\n== APP METADATA ==")
        for k, v in state["app_metadata"].items():
            print(f"{k}: {v}")
    if "webapp" in state:
        print(f"\n== WEBAPP: {state['webapp']['site_domain']} ==")
        for k, v in state["webapp"]["metadata"].items():
            print(f"{k}: {v}")


def _main():
    state = get_desktop_state()
    _print_state(state)


if __name__ == "__main__":
    _main()
