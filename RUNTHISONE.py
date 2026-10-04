"""Small always-on-top widget that asks for a goal, then asks Jev every 4
seconds whether what you're doing right now is a distraction from it.

- Lives in the top-right corner and stays above all other windows even when
  unfocused, so the activity detector (get_desktop_state.py) keeps seeing
  your real focused app - this widget is never the focused window while it
  just displays.
- While the overlay itself *is* the focused window (i.e. you just clicked
  into it, e.g. to edit the goal), polling pauses with a "click away"
  notice so the detector never judges the overlay.
- Reuses decide() + API_KEY from jev_decides.py.
- Optional CLI: pass the goal as the first argument to skip typing it in
  the window (the prompt entry is pre-filled and polling starts at once).
"""

import json
import os
import queue
import shutil
import sys
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont

import get_desktop_state
import jev_decides
from browser_extensions.bridge_server import BrowserExtensionBridge

POLL_SECONDS = 4
OVERLAY_TITLE = "cranky clippy"

# colors
BG = "#1c1a24"
FG = "#f2edff"
YES = "#ff5f6b"
NO = "#5fd37a"
MUT = "#a89fc0"


BRIEF_CHECKIN_APP_CLASSES = frozenset({"chat", "collaboration", "desktop", "email"})
BRIEF_CHECKIN_MAX_SECONDS = 45.0
HAPPY_AFTER_FOCUSED_SECONDS = 60.0
OFF_TASK_ESCALATION_STAGES = (
    (0.0, "sad"),
    (10.0, "ticked-off"),
    (25.0, "angry"),
    (45.0, "very-angry"),
)
BRIEF_CHECKIN_ESCALATION_STAGES = (
    (15.0, "angry"),
    (35.0, "very-angry"),
)


def _is_brief_checkin(universal, webapp=None):
    """Hard-coded short-dwell allowance for chat, utilities, and email."""
    elapsed = universal.get("time_since_window_focused")
    return (
        (
            universal.get("app_class") in BRIEF_CHECKIN_APP_CLASSES
            or (webapp or {}).get("category") == "email"
        )
        and isinstance(elapsed, (int, float))
        and 0 <= elapsed <= BRIEF_CHECKIN_MAX_SECONDS
    )


def _focus_target(state):
    """Return the app/site/tab identity Jev sees for the current focus."""
    universal = state.get("universal") or {}
    metadata = state.get("app_metadata") or {}
    return {
        "app": str(universal.get("app_focused_name") or "unknown"),
        "site": str(metadata.get("site_domain") or ""),
        "url": str(metadata.get("site_url") or "")[:400],
        "title": str(metadata.get("tab_title") or universal.get("window_title") or "")[:200],
        "window_id": str(universal.get("window_id") or ""),
    }


def _target_signature(target):
    app = str(target.get("app", "")).strip().casefold()
    site = str(target.get("site", "")).strip().casefold()
    url = str(target.get("url", "")).strip().casefold()
    identity = url or str(target.get("title", "")).strip().casefold()
    window_id = str(target.get("window_id", "")).strip().casefold()
    return app, site, identity, window_id


class GoalOverlay:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(OVERLAY_TITLE)
        root.attributes("-topmost", True)  # keep above everything, even unfocused
        # X11 utility windows: no taskbar entry, small decorations
        try:
            root.attributes("-type", "utility")
        except tk.TclError:
            pass
        root.configure(bg=BG)
        root.resizable(False, False)

        self._worker = None
        self._stop = False
        self._inflight = False
        self._pet_process = None
        self._pet_stdin_lock = threading.Lock()
        self._browser_bridge = BrowserExtensionBridge()
        self._browser_bridge.on_message = self._on_browser_bridge_message
        self._browser_restore_acks = queue.Queue()
        self._ignore_next_on_task = threading.Event()
        self._excused_target_signature = None
        self._excuse_pending = False
        self._typing_pause_started_at = None
        self._typing_pause_until = 0.0
        self._typing_pause_total = 0.0
        self._last_on_task_target = None
        self._final_action_attempted = False
        self._activity_phase = None
        self._activity_target = None
        self._on_task_target_signature = None
        self._happy_focus_target_signature = None
        self._distraction_started_at = None
        self._escalation_started_at = None
        self._escalation_stage = -1
        self._brief_checkin_expired = False
        self._collapsed = False
        self._collapsed_pack_info = {}
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.goal_entry = tk.Entry(
            root, width=26, bg=BG, fg=MUT, insertbackground=FG,
            font=("DejaVu Sans", 10), justify="center",
        )
        self._placeholder = "set your goal here"
        self.goal_entry.insert(0, self._placeholder)
        self.goal_entry.bind(
            "<FocusIn>",
            lambda e: self.goal_entry.delete(0, tk.END)
            if self.goal_entry.get() == self._placeholder else None,
        )
        self.goal_entry.bind("<Return>", lambda e: self._on_set_goal())
        self.goal_entry.pack(padx=10, pady=(8, 2))
        self.goal_actions = tk.Frame(root, bg=BG)
        self.set_btn = tk.Button(
            self.goal_actions, text="watch my goals", command=self._on_change_goal,
            bg="#33304a", fg=FG, activebackground="#4a4468",
            activeforeground=FG, relief="flat", font=("DejaVu Sans", 8),
        )
        self.set_btn.pack(side="left", padx=(10, 3), pady=2)
        self.collapse_btn = tk.Button(
            self.goal_actions, text="collapse", command=self._collapse_window,
            bg="#33304a", fg=FG, activebackground="#4a4468",
            activeforeground=FG, relief="flat", font=("DejaVu Sans", 8),
        )
        self.collapse_btn.pack(side="left", padx=(3, 10), pady=2)
        self.goal_actions.pack()
        self.expand_btn = tk.Button(
            root, text="expand", command=self._expand_window,
            bg="#33304a", fg=FG, activebackground="#4a4468",
            activeforeground=FG, relief="flat", font=("DejaVu Sans", 8),
        )

        self.goal_label = tk.Label(
            root, text="", bg=BG, fg=MUT, font=("DejaVu Sans", 8),
            wraplength=264, justify="center",
        )
        self.status_label = tk.Label(
            root, text="", bg=BG, fg=MUT, font=("DejaVu Sans", 8),
        )
        self.result_label = tk.Label(
            root, text="", bg=BG, fg=FG, font=("DejaVu Sans", 11, "bold"),
            justify="center", wraplength=264,
        )
        self.percents_label = tk.Label(
            root, text="", bg=BG, font=("DejaVu Sans", 9), justify="center",
        )
        self.details_label = tk.Label(
            root, text="", bg=BG, fg=MUT, font=("DejaVu Sans", 7),
            wraplength=264, justify="center",
        )
        # bottom panel: everything the detector saw this tick, verbatim
        self.state_header = tk.Label(
            root, text="", bg=BG, fg=MUT, font=("DejaVu Sans", 7),
        )
        self._panel_font = tkfont.Font(family="DejaVu Sans Mono", size=-10)
        self.state_text = tk.Text(
            root, bg="#15131c", fg="#cfc7e8", bd=0, wrap="char",
            font=self._panel_font, height=1, width=46,
            insertontime=0, cursor="arrow", takefocus=0,
        )

        # top-right placement
        root.update_idletasks()
        w = max(300, root.winfo_reqwidth())
        x = root.winfo_screenwidth() - w - 24
        root.geometry(f"+{x}+40")

        self.goal_entry.focus_set()

    def _reanchor_window(self):
        self.root.update_idletasks()
        width = max(1, self.root.winfo_reqwidth())
        x = self.root.winfo_screenwidth() - width - 24
        self.root.geometry(f"+{x}+40")

    def _pack_if_expanded(self, widget, **options):
        if not self._collapsed and not widget.winfo_manager():
            widget.pack(**options)

    def _collapse_window(self):
        if self._collapsed:
            return
        self._collapsed_pack_info = {}
        for widget in self.root.winfo_children():
            if widget is self.expand_btn:
                continue
            if widget.winfo_manager() == "pack":
                self._collapsed_pack_info[widget] = widget.pack_info()
                widget.pack_forget()
        self._collapsed = True
        self.expand_btn.pack(padx=4, pady=4)
        self._reanchor_window()

    def _expand_window(self):
        if not self._collapsed:
            return
        self.expand_btn.pack_forget()
        self._collapsed = False
        for widget, options in self._collapsed_pack_info.items():
            if not widget.winfo_manager():
                widget.pack(**options)
        self._collapsed_pack_info = {}
        self._reanchor_window()

    def _prefill_goal(self, goal):
        """Goal given on the command line: fill the entry quietly."""
        self.goal_entry.delete(0, tk.END)
        self.goal_entry.insert(0, goal)
        self.goal_entry.config(fg=FG)
        self._placeholder = None

    def _on_set_goal(self):
        goal = self.goal_entry.get().strip()
        if not goal or (self._placeholder and goal == self._placeholder):
            return
        self._apply_goal(goal)

    def _apply_goal(self, goal):
        self.goal = goal
        self._start_pet_process()
        self.goal_label.config(text=f'goal: "{goal}"')
        if not self.goal_label.winfo_ismapped():
            self._pack_if_expanded(self.goal_label, padx=10, pady=(8, 0))
        self.set_btn.config(text="change goal")
        # hide the entry while a goal is active to keep the widget tiny
        self.goal_entry.pack_forget()
        self._pack_if_expanded(self.status_label, padx=10, pady=(4, 0))
        self.status_label.config(text="click another window - checking...")
        if self._worker is None:
            self._stop = False
            self._worker = threading.Thread(target=self._poll_loop, daemon=True)
            self._worker.start()

    def _start_pet_process(self):
        """Launch Clippy as a quiet child process controlled by Jev events."""
        if self._pet_process is not None and self._pet_process.poll() is None:
            return
        pet_script = os.path.join(os.path.dirname(__file__), "clippy_overlay.py")
        try:
            self._pet_process = subprocess.Popen(
                [sys.executable, "-u", pet_script],
                cwd=os.path.dirname(__file__),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            threading.Thread(
                target=self._read_pet_events,
                args=(self._pet_process,),
                name="clippy-event-reader",
                daemon=True,
            ).start()
        except OSError as exc:
            self._pet_process = None
            print("[JevOverlay] Could not start Clippy: %s" % exc, file=sys.stderr)

    def _read_pet_events(self, process):
        prefix = "__CLIPPY_PARENT_EVENT__"
        for line in process.stdout or ():
            if not line.startswith(prefix):
                continue
            try:
                message = json.loads(line[len(prefix):])
                self.root.after(0, self._handle_pet_parent_event, message)
            except (ValueError, tk.TclError):
                return

    def _finish_typing_pause(self, now):
        if (
            self._typing_pause_started_at is not None
            and not self._excuse_pending
            and now >= self._typing_pause_until
        ):
            self._typing_pause_total += max(
                0.0, self._typing_pause_until - self._typing_pause_started_at
            )
            self._typing_pause_started_at = None
            self._typing_pause_until = 0.0

    def _record_excuse_typing(self):
        now = time.monotonic()
        self._finish_typing_pause(now)
        if self._typing_pause_started_at is None:
            self._typing_pause_started_at = now
        self._typing_pause_until = now + 3.0

    def _handle_pet_parent_event(self, event):
        event_type = event.get("type")
        if event_type == "excuse_typing":
            self._record_excuse_typing()
        elif event_type == "excuse_submitted":
            self._record_excuse_typing()
            self._excuse_pending = True
        elif event_type == "excuse_accepted":
            target = event.get("target") or {}
            self._excused_target_signature = _target_signature(target)
            self._activity_phase = "excused"
            self._activity_target = target
            self._excuse_pending = False
            self._escalation_started_at = None
            self._escalation_stage = -1
            self._typing_pause_started_at = None
            self._typing_pause_until = 0.0
            self._typing_pause_total = 0.0
            print("[JevOverlay] Clippy accepted the user's excuse for this app/tab.")
        elif event_type == "excuse_rejected":
            self._excuse_pending = False
            if self._activity_phase == "off_task":
                # Rejection advances the first confrontation to ticked-off.
                self._escalation_stage = max(self._escalation_stage, 1)
                now = time.monotonic()
                self._finish_typing_pause(now)
                remaining_pause = (
                    max(0.0, self._typing_pause_until - now)
                    if self._typing_pause_started_at is not None else 0.0
                )
                self._typing_pause_started_at = now if remaining_pause else None
                self._typing_pause_until = now + remaining_pause if remaining_pause else 0.0
                self._typing_pause_total = 0.0
                self._escalation_started_at = now - 10.0
            print("[JevOverlay] Clippy rejected the excuse; normal distraction escalation resumes.")

    def _off_task_escalation_elapsed(self, now):
        """Elapsed escalation time excluding typing and the post-typing grace."""
        self._finish_typing_pause(now)
        if self._escalation_started_at is None:
            return 0.0
        if self._typing_pause_started_at is not None:
            elapsed_until_pause = self._typing_pause_started_at - self._escalation_started_at
            return max(0.0, elapsed_until_pause - self._typing_pause_total)
        return max(
            0.0,
            now - self._escalation_started_at - self._typing_pause_total,
        )

    def _send_pet_event(self, event, state, result, stage_mood=None, elapsed=None,
                        previous_target=None, final_return_to_task=False):
        process = self._pet_process
        if process is None or process.poll() is not None or process.stdin is None:
            return
        universal = state.get("universal", {})
        metadata = state.get("app_metadata") or {}
        relevant_fields = (
            "game_name", "game_running", "time_in_game", "media_title",
            "playback_state", "document_name", "file_path", "workspace_name",
            "channel_or_chat_name", "server_or_dm_name", "channel_name",
            "space_or_chat_name", "stream_name", "mail_folder", "mail_subject",
        )
        activity_details = {
            key: value[:200] if isinstance(value, str) else value
            for key in relevant_fields
            if (value := metadata.get(key)) is not None
        }
        context = {
            "goal": self.goal,
            "focused_app": universal.get("app_focused_name"),
            "app_class": universal.get("app_class"),
            "window_title": (universal.get("window_title") or "")[:200],
            "target": _focus_target(state),
            "app_description": (metadata.get("app_description") or "")[:300],
            "activity_details": activity_details,
            "elapsed_seconds": round(max(0.0, elapsed), 1) if elapsed is not None else 0,
        }
        if stage_mood:
            context["stage_mood"] = stage_mood
        if previous_target:
            context["previous_target"] = previous_target
        if final_return_to_task:
            context["final_return_to_task"] = True
        if event.startswith("brief_checkin"):
            context["brief_checkin_seconds"] = BRIEF_CHECKIN_MAX_SECONDS
        if result:
            context["jev_verdict"] = result.get("answer")
            context["on_track_percent"] = result.get("on_track_percent")
            context["not_on_track_percent"] = result.get("not_on_track_percent")
        try:
            with self._pet_stdin_lock:
                process.stdin.write(json.dumps({"event": event, "context": context}) + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            print("[JevOverlay] Could not send event to Clippy: %s" % exc, file=sys.stderr)

    def _send_pet_mood(self, mood, persistent=False):
        process = self._pet_process
        if process is None or process.poll() is not None or process.stdin is None:
            return
        try:
            with self._pet_stdin_lock:
                process.stdin.write(json.dumps({
                    "action": "set_mood", "mood": mood, "persistent": persistent,
                }) + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            print("[JevOverlay] Could not change Clippy's animation: %s" % exc, file=sys.stderr)

    def _remember_on_task_target(self, state):
        universal = state.get("universal", {})
        metadata = state.get("app_metadata") or {}
        app = universal.get("app_focused_name")
        is_browser = universal.get("app_class") == "browser" and app in {"chrome", "firefox"}
        target = {
            "app": app,
            "app_class": universal.get("app_class"),
            "browser": app if is_browser else None,
            "window_id": universal.get("window_id"),
            "desktop_file_id": universal.get("desktop_file_id"),
            "window_title": universal.get("window_title") or "",
            "site_url": metadata.get("site_url"),
            "site_domain": metadata.get("site_domain"),
            "tab_title": metadata.get("tab_title"),
            "launch_uri": metadata.get("file_path") or metadata.get("document_path"),
            "goal": self.goal,
        }
        self._last_on_task_target = target
        if is_browser:
            self._browser_bridge.send(app, {"action": "remember", "target": target})

    def _return_to_last_on_task_target(self, current_state):
        if self._final_action_attempted:
            return
        self._final_action_attempted = True
        target = self._last_on_task_target
        if not target:
            print("[JevOverlay] Final anger reached without a remembered on-task target.")
            return

        current_window_id = (current_state.get("universal") or {}).get("window_id")

        def restore():
            browser = target.get("browser")
            window_restored, control_detail = get_desktop_state._kwin_activate_and_minimize(
                target.get("window_id"),
                expected_active_window_id=current_window_id,
                minimize_if_target_missing=True,
                return_detail=True,
                target_desktop_file_id=target.get("desktop_file_id"),
                target_caption=target.get("window_title"),
            )
            if browser:
                if control_detail == "active window changed":
                    print("[JevOverlay] Skipping final browser return; focus changed since Jev sampled it.")
                    return
                while not self._browser_restore_acks.empty():
                    try:
                        self._browser_restore_acks.get_nowait()
                    except queue.Empty:
                        break
                extension_notified = self._browser_bridge.send(
                    browser, {"action": "restore", "target": target}
                )
                restored = False
                if extension_notified:
                    deadline = time.monotonic() + 6
                    while time.monotonic() < deadline:
                        try:
                            reply_browser, reply = self._browser_restore_acks.get(
                                timeout=max(0.05, deadline - time.monotonic())
                            )
                        except queue.Empty:
                            break
                        if reply_browser != browser:
                            continue
                        if reply.get("type") == "restored":
                            restored = True
                            break
                        if reply.get("type") == "error" and reply.get("action") == "restore":
                            break
                if not restored and target.get("site_url"):
                    executable = shutil.which(
                        "firefox" if browser == "firefox" else "google-chrome"
                    )
                    if executable:
                        try:
                            subprocess.Popen(
                                [executable, "--new-tab", target["site_url"]],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            restored = True  # startup URL opens the saved page
                        except OSError as exc:
                            print("[JevOverlay] Could not reopen %s: %s" % (browser, exc))
                print(
                    "[JevOverlay] Final anger: restored browser task %s (window=%s, extension=%s)."
                    % (target.get("site_url") or target.get("tab_title"),
                       window_restored, extension_notified)
                )
                if restored:
                    self._notify_pet_auto_returned()
            elif control_detail == "target window not found":
                if not self._launch_task_application(target):
                    print("[JevOverlay] Could not reopen the remembered task window.")
                    return
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    time.sleep(0.35)
                    window_restored, control_detail = get_desktop_state._kwin_activate_and_minimize(
                        None,
                        expected_active_window_id=None,
                        minimize_current=False,
                        return_detail=True,
                        target_desktop_file_id=target.get("desktop_file_id"),
                        target_caption=target.get("window_title"),
                    )
                    if window_restored:
                        break
                print(
                    "[JevOverlay] Reopened remembered task application %r (success=%s)."
                    % (target.get("desktop_file_id") or target.get("app"), window_restored)
                )
                if window_restored:
                    self._notify_pet_auto_returned()
            else:
                print(
                    "[JevOverlay] Final anger: restored on-task window %r (success=%s)."
                    % (target.get("window_title"), window_restored)
                )
                if window_restored:
                    self._notify_pet_auto_returned()

        threading.Thread(target=restore, name="clippy-return-to-task", daemon=True).start()

    def _on_browser_bridge_message(self, browser, message):
        if message.get("type") in {"restored", "error"}:
            self._browser_restore_acks.put((browser, message))

    def _notify_pet_auto_returned(self):
        """Suppress the next Jev YES reaction after Clippy restores the target."""
        self._ignore_next_on_task.set()
        process = self._pet_process
        if process is None or process.poll() is not None or process.stdin is None:
            return
        try:
            with self._pet_stdin_lock:
                process.stdin.write(json.dumps({"action": "auto_returned"}) + "\n")
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            print("[JevOverlay] Could not notify Clippy of automatic return: %s" % exc)

    @staticmethod
    def _launch_task_application(target):
        """Reopen a closed on-task app from its KWin desktop-file identity."""
        desktop_id = (target.get("desktop_file_id") or "").strip()
        gtk_launch = shutil.which("gtk-launch")
        if gtk_launch and desktop_id:
            application_id = desktop_id.removesuffix(".desktop")
            launch_args = [gtk_launch, application_id]
            launch_uri = target.get("launch_uri")
            if isinstance(launch_uri, str) and os.path.isabs(launch_uri) and os.path.exists(launch_uri):
                launch_args.append(launch_uri)
            try:
                subprocess.Popen(
                    launch_args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except OSError as exc:
                print("[JevOverlay] Could not launch task desktop entry: %s" % exc)

        app = (target.get("app") or "").strip()
        executable_names = {
            "visual_studio_code": "code", "google_chrome": "google-chrome",
            "msedge": "microsoft-edge", "libreoffice_writer": "libreoffice",
        }
        executable = shutil.which(executable_names.get(app, app))
        if not executable:
            return False
        try:
            subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError as exc:
            print("[JevOverlay] Could not launch task app %r: %s" % (app, exc))
            return False

    def _update_pet_state(self, state, result, brief_check_in):
        """Send pet commands only for phase, target, or escalation changes."""
        now = time.monotonic()
        universal = state.get("universal", {})
        verdict = result.get("answer", "?")
        phase = (
            "on_task" if verdict.startswith("YES")
            else "brief_checkin" if brief_check_in
            else "off_task"
        )
        target = _focus_target(state)
        previous_phase = self._activity_phase
        target_changed = (
            self._activity_target is not None
            and _target_signature(target) != _target_signature(self._activity_target)
        )

        target_signature = _target_signature(target)
        if phase != "on_task" and self._excused_target_signature is not None:
            if target_signature == self._excused_target_signature:
                self._activity_phase = "excused"
                self._activity_target = target
                return
            # An excuse only applies to the exact app/tab/window it justified.
            self._excused_target_signature = None
        if self._excuse_pending and phase != "on_task":
            # Don't escalate or prompt again while Gemini is judging the typed
            # explanation; the escalation clock is paused during this check.
            return

        if phase == "on_task":
            self._final_action_attempted = False
            self._excused_target_signature = None
            self._excuse_pending = False
            auto_returned = self._ignore_next_on_task.is_set()
            if auto_returned:
                self._ignore_next_on_task.clear()
            elif previous_phase in {"brief_checkin", "off_task"}:
                elapsed = (
                    now - self._distraction_started_at
                    if self._distraction_started_at is not None else 0
                )
                self._send_pet_event("on_task", state, result, elapsed=elapsed)
            if self._on_task_target_signature != target_signature:
                if self._on_task_target_signature is not None:
                    self._send_pet_mood("idle")
                self._on_task_target_signature = target_signature
                self._happy_focus_target_signature = None
            focused_seconds = universal.get("time_since_window_focused")
            if isinstance(focused_seconds, (int, float)) and focused_seconds > HAPPY_AFTER_FOCUSED_SECONDS:
                if self._happy_focus_target_signature != target_signature:
                    self._send_pet_mood("happy", persistent=True)
                    self._happy_focus_target_signature = target_signature
            self._activity_phase = phase
            self._activity_target = target
            self._distraction_started_at = None
            self._escalation_started_at = None
            self._escalation_stage = -1
            self._brief_checkin_expired = False
            self._typing_pause_started_at = None
            self._typing_pause_until = 0.0
            self._typing_pause_total = 0.0
            return

        if phase == "brief_checkin":
            self._on_task_target_signature = None
            self._happy_focus_target_signature = None
            self._happy_focus_target_signature = None
            if self._distraction_started_at is None:
                self._distraction_started_at = now
            if previous_phase != "brief_checkin":
                self._send_pet_event(
                    "brief_checkin_started", state, result, stage_mood="idle",
                    elapsed=now - self._distraction_started_at,
                )
            elif target_changed:
                self._send_pet_event(
                    "brief_checkin_changed", state, result, stage_mood="idle",
                    elapsed=now - self._distraction_started_at,
                )
            self._activity_phase = phase
            self._activity_target = target
            return

        # Off-task: a check-in that has passed its allowance gets a distinct
        # ticked-off reaction; changing from check-in to another app starts a
        # fresh off-task escalation instead.
        if previous_phase == "brief_checkin" and not target_changed:
            self._escalation_started_at = now
            self._escalation_stage = 1  # ticked-off
            self._brief_checkin_expired = True
            self._send_pet_event(
                "brief_checkin_expired", state, result, stage_mood="ticked-off",
                elapsed=BRIEF_CHECKIN_MAX_SECONDS,
            )
        elif previous_phase != "off_task":
            self._distraction_started_at = now
            self._escalation_started_at = now
            self._escalation_stage = 0  # sad
            self._brief_checkin_expired = False
            self._final_action_attempted = False
            self._excuse_pending = False
            self._typing_pause_started_at = None
            self._typing_pause_until = 0.0
            self._typing_pause_total = 0.0
            self._send_pet_event(
                "distraction_started", state, result, stage_mood="sad", elapsed=0
            )
        else:
            escalation_elapsed = self._off_task_escalation_elapsed(now)
            if self._brief_checkin_expired:
                desired_stage = max(
                    index + 2
                    for index, (seconds, _mood) in enumerate(BRIEF_CHECKIN_ESCALATION_STAGES)
                    if seconds <= escalation_elapsed
                ) if escalation_elapsed >= BRIEF_CHECKIN_ESCALATION_STAGES[0][0] else 1
            else:
                desired_stage = max(
                    index for index, (seconds, _mood) in enumerate(OFF_TASK_ESCALATION_STAGES)
                    if seconds <= escalation_elapsed
                )
            if target_changed:
                self._escalation_stage = max(self._escalation_stage, desired_stage)
                mood = OFF_TASK_ESCALATION_STAGES[self._escalation_stage][1]
                self._send_pet_event(
                    "distraction_changed", state, result, stage_mood=mood,
                    elapsed=escalation_elapsed, previous_target=self._activity_target,
                    final_return_to_task=(self._escalation_stage == 3),
                )
            elif desired_stage > self._escalation_stage:
                self._escalation_stage = desired_stage
                mood = OFF_TASK_ESCALATION_STAGES[desired_stage][1]
                self._send_pet_event(
                    "escalation", state, result, stage_mood=mood,
                    elapsed=escalation_elapsed,
                    final_return_to_task=(desired_stage == 3),
                )

        self._activity_phase = phase
        self._activity_target = target
        if phase != "on_task":
            self._on_task_target_signature = None
        self._happy_focus_target_signature = None
        if phase == "off_task" and self._escalation_stage >= 3:
            self._return_to_last_on_task_target(state)

    def _on_close(self):
        self._stop = True
        self._browser_bridge.close()
        process = self._pet_process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        self.root.destroy()

    def _on_change_goal(self):
        if self.goal_entry.winfo_ismapped():
            self._on_set_goal()
        else:
            # reveal the entry again, pre-filled, to edit the goal
            self.goal_entry.delete(0, tk.END)
            self.goal_entry.insert(0, getattr(self, "goal", ""))
            self.goal_entry.config(fg=FG)
            self._pack_if_expanded(self.goal_entry, padx=10, pady=(8, 2))
            self.goal_entry.focus_set()

    def _poll_loop(self):
        while not self._stop:
            t0 = time.time()
            try:
                self._tick()
            finally:
                elapsed = time.time() - t0
                rest = max(1.0, POLL_SECONDS - elapsed)
                time.sleep(rest)

    def _tick(self):
        self._inflight = True
        try:
            detected_state = get_desktop_state.get_desktop_state(user_goal=self.goal)
            jev_state_json = jev_decides.prepare_state_for_jev(
                json.dumps(detected_state, ensure_ascii=False)
            )
            state = json.loads(jev_state_json)
            universal = state.get("universal", {})
            # Never judge ourselves, a focus-less desktop, or transient
            # desktop-shell UI such as the application launcher.
            paused = (
                universal.get("focus_lost")
                or universal.get("skip_decision")
                or universal.get("window_title") == OVERLAY_TITLE
            )
            self.root.after(0, self._render, state, None)
            if paused:
                return
            prompt = jev_decides.goal_alignment_prompt(self.goal)
            result = jev_decides.decide(
                api_key=jev_decides.API_KEY,
                state=jev_state_json,
                **prompt,
                state_prepared=True,
            )
            self.root.after(0, self._render, state, result)
        except Exception as e:
            self.root.after(0, self._show_error, str(e))
        finally:
            self._inflight = False

    def _render(self, state, result):
        """One UI pass: status, verdict, and the full raw detector state."""
        universal = state.get("universal", {})
        focused = universal.get("app_focused_name", "?")

        if result is None:
            if universal.get("skip_decision_reason") == "desktop_shell":
                self.status_label.config(
                    text="desktop launcher open - checking resumes when you open an app"
                )
                checked = "decision skipped (desktop shell) %s" % time.strftime("%H:%M:%S")
            elif universal.get("focus_lost") or universal.get("window_title") == OVERLAY_TITLE:
                # paused: keep the last verdict on screen, just explain why
                # the numbers are not refreshing
                self.status_label.config(text="paused - click into your work, not me")
                checked = "last check skipped (paused) %s" % time.strftime("%H:%M:%S")
            else:
                self.status_label.config(
                    text=f"checking every {POLL_SECONDS}s | {focused}"
                )
                checked = f"last checked {time.strftime('%H:%M:%S')}"
        else:
            self.status_label.config(
                text=f"checking every {POLL_SECONDS}s | {focused}"
            )
            yes = result.get("on_track_percent", 0)
            no = result.get("not_on_track_percent", 0)
            verdict = result.get("answer", "?")
            if verdict.startswith("YES"):
                self._remember_on_task_target(state)
            brief_check_in = (
                not verdict.startswith("YES")
                and _is_brief_checkin(universal, state.get("webapp"))
            )
            self._update_pet_state(state, result, brief_check_in)
            self.result_label.config(
                text=(
                    "ON TRACK" if verdict.startswith("YES")
                    else "BRIEF CHECK-IN" if brief_check_in
                    else "NOT SHOWN ON-TASK"
                ),
                fg=NO if verdict.startswith("YES") or brief_check_in else YES,
            )
            self.percents_label.config(
                text=f"on-track: {yes}%   not on-task: {no}%",
                fg=(NO if verdict.startswith("YES") or brief_check_in else YES),
            )
            checked = f"last checked {time.strftime('%H:%M:%S')}"

        if not self.percents_label.winfo_ismapped():
            self._pack_if_expanded(self.status_label, padx=10, pady=(6, 0))
            self._pack_if_expanded(self.result_label, padx=10, pady=(2, 0))
            self._pack_if_expanded(self.percents_label, padx=10)
            self._pack_if_expanded(self.details_label, padx=10, pady=(0, 6))
        self.details_label.config(text=checked)

        self._render_panel(state)

    def _render_panel(self, state):
        """Bottom panel with everything the detector saw, pretty-printed."""
        self.state_header.config(text="-- exact state context sent to Jev --")
        text = json.dumps(state, indent=2, ensure_ascii=False)
        self.state_text.config(state="normal")
        self.state_text.delete("1.0", tk.END)
        self.state_text.insert("1.0", text)
        lines = text.count("\n") + 1
        # grow with content up to a sane cap so small states stay compact
        self.state_text.config(height=min(lines, 38), width=46)
        self.state_text.config(state="disabled")
        if not self.state_text.winfo_ismapped():
            self._pack_if_expanded(self.state_header, padx=10, pady=(0, 2))
            self._pack_if_expanded(self.state_text, padx=6, pady=(0, 8))
            # make sure the whole widget still fits: re-anchor to the
            # top-right after the panel changes the window size
            self.root.update_idletasks()
            w = self.root.winfo_width()
            x = self.root.winfo_screenwidth() - w - 24
            self.root.geometry(f"+{x}+40")

    def _show_error(self, message):
        short = message[:120].replace("\n", " ")
        self.result_label.config(text="ERROR", fg=YES)
        self.percents_label.config(text=short, fg=MUT)


def main():
    root = tk.Tk()
    overlay = GoalOverlay(root)
    # optional CLI goal: python3 jev_overlay.py "working on X"
    goal = sys.argv[1].strip() if len(sys.argv) > 1 and sys.argv[1].strip() else None
    if goal:
        overlay._prefill_goal(goal)
        # let the window map first, then kick off polling
        root.after(400, lambda: overlay._apply_goal(goal))
    root.mainloop()


if __name__ == "__main__":
    main()
