"""Small always-on-top widget that asks for a goal, then asks Jev every 4
seconds whether what you're doing right now is a distraction from it.

- Lives in the top-right corner and stays above all other windows even when
  unfocused, so the activity detector (get_desktop_state.py) keeps seeing
  your real focused app — this widget is never the focused window while it
  just displays.
- While the overlay itself *is* the focused window (i.e. you just clicked
  into it, e.g. to edit the goal), polling pauses with a "click away"
  notice so the detector never judges the overlay.
- Reuses decide() + API_KEY from jev_decides.py.
- Optional CLI: pass the goal as the first argument to skip typing it in
  the window (the prompt entry is pre-filled and polling starts at once).
"""

import json
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont

import get_desktop_state
import jev_decides

POLL_SECONDS = 4
OVERLAY_TITLE = "cranky clippy"

# colors
BG = "#1c1a24"
FG = "#f2edff"
YES = "#ff5f6b"
NO = "#5fd37a"
MUT = "#a89fc0"


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
        self.set_btn = tk.Button(
            root, text="watch my goals", command=self._on_change_goal,
            bg="#33304a", fg=FG, activebackground="#4a4468",
            activeforeground=FG, relief="flat", font=("DejaVu Sans", 8),
        )
        self.set_btn.pack(padx=10, pady=2)

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
        self.goal_label.config(text=f'goal: "{goal}"')
        if not self.goal_label.winfo_ismapped():
            self.goal_label.pack(padx=10, pady=(8, 0))
        self.set_btn.config(text="change goal")
        # hide the entry while a goal is active to keep the widget tiny
        self.goal_entry.pack_forget()
        self.status_label.pack(padx=10, pady=(4, 0))
        self.status_label.config(text="click another window — checking…")
        if self._worker is None:
            self._stop = False
            self._worker = threading.Thread(target=self._poll_loop, daemon=True)
            self._worker.start()

    def _on_change_goal(self):
        if self.goal_entry.winfo_ismapped():
            self._on_set_goal()
        else:
            # reveal the entry again, pre-filled, to edit the goal
            self.goal_entry.delete(0, tk.END)
            self.goal_entry.insert(0, getattr(self, "goal", ""))
            self.goal_entry.config(fg=FG)
            self.goal_entry.pack(padx=10, pady=(8, 2))
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
            state = get_desktop_state.get_desktop_state(user_goal=self.goal)
            universal = state.get("universal", {})
            # never judge ourselves, and never judge a focus-less desktop:
            # if the overlay is what's focused or nothing is focused at
            # all, pause until the user clicks somewhere real
            paused = (
                universal.get("focus_lost")
                or universal.get("window_title") == OVERLAY_TITLE
            )
            self.root.after(0, self._render, state, None)
            if paused:
                return
            result = jev_decides.decide(
                api_key=jev_decides.API_KEY,
                state=json.dumps(state),
                question=(
                    "The user has set a goal for themselves to work on, and your job is to "
                    "determine if what the user is currently doing is a distraction from "
                    "that goal. Is what the user is currently doing a distraction from that "
                    'goal? This is the goal that the user has set: "' + self.goal + '"'
                ),
                true_when="The user is engaging in an activity that is not aligned with their stated goal.",
                false_when="The user is engaging in an activity that is aligned with their stated goal.",
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
            if universal.get("focus_lost") or universal.get(
                "window_title"
            ) == OVERLAY_TITLE:
                # paused: keep the last verdict on screen, just explain why
                # the numbers are not refreshing
                self.status_label.config(text="paused — click into your work, not me")
                checked = "last check skipped (paused) %s" % time.strftime("%H:%M:%S")
            else:
                self.status_label.config(
                    text=f"checking every {POLL_SECONDS}s · {focused}"
                )
                checked = f"last checked {time.strftime('%H:%M:%S')}"
        else:
            self.status_label.config(
                text=f"checking every {POLL_SECONDS}s · {focused}"
            )
            yes = result.get("yes_percent", 0)
            no = result.get("no_percent", 0)
            verdict = result.get("answer", "?")
            self.result_label.config(
                text=("🚨 DISTRACTION" if verdict.startswith("YES") else "✅ on track"),
                fg=YES if verdict.startswith("YES") else NO,
            )
            self.percents_label.config(
                text=f"yes: {yes}%   no: {no}%", fg=(YES if yes >= no else NO)
            )
            checked = f"last checked {time.strftime('%H:%M:%S')}"

        if not self.percents_label.winfo_ismapped():
            self.status_label.pack(padx=10, pady=(6, 0))
            self.result_label.pack(padx=10, pady=(2, 0))
            self.percents_label.pack(padx=10)
            self.details_label.pack(padx=10, pady=(0, 6))
        self.details_label.config(text=checked)

        self._render_panel(state)

    def _render_panel(self, state):
        """Bottom panel with everything the detector saw, pretty-printed."""
        self.state_header.config(text="— what the detector saw —")
        text = json.dumps(state, indent=2, ensure_ascii=False)
        self.state_text.config(state="normal")
        self.state_text.delete("1.0", tk.END)
        self.state_text.insert("1.0", text)
        lines = text.count("\n") + 1
        # grow with content up to a sane cap so small states stay compact
        self.state_text.config(height=min(lines, 38), width=46)
        self.state_text.config(state="disabled")
        if not self.state_text.winfo_ismapped():
            self.state_header.pack(padx=10, pady=(0, 2))
            self.state_text.pack(padx=6, pady=(0, 8))
            # make sure the whole widget still fits: re-anchor to the
            # top-right after the panel changes the window size
            self.root.update_idletasks()
            w = self.root.winfo_width()
            x = self.root.winfo_screenwidth() - w - 24
            self.root.geometry(f"+{x}+40")

    def _show_error(self, message):
        short = message[:120].replace("\n", " ")
        self.result_label.config(text="⚠️ error", fg=YES)
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
