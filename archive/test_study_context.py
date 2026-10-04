"""Offline regression tests for app context, goal prompts, and focus timing."""

import unittest
from unittest.mock import patch
import json
import os
import tempfile

import app_catalog as catalog
import get_desktop_state as desktop
import jev_decides
import RUNTHISONE as jev_overlay


class FocusDurationTests(unittest.TestCase):
    def setUp(self):
        desktop._time_since_window_focused(None, now=0)

    def test_window_duration_advances_and_resets_on_window_change(self):
        first = ("kwin", "window-1")
        self.assertEqual(desktop._time_since_window_focused(first, now=10), 0.0)
        self.assertEqual(desktop._time_since_window_focused(first, now=16.25), 6.2)
        self.assertEqual(desktop._time_since_window_focused(("kwin", "window-2"), now=20), 0.0)
        self.assertIsNone(desktop._time_since_window_focused(None, now=25))
        self.assertEqual(desktop._time_since_window_focused(first, now=30), 0.0)

    def test_wayland_idle_and_resume_events_measure_input_activity(self):
        original = desktop._WAYLAND_IDLE_STATE.copy()
        try:
            desktop._WAYLAND_IDLE_STATE.update({
                "started": True,
                "status": "starting",
                "last_active": None,
                "first_idle_event": True,
                "monitor_started": 100.0,
            })
            # If the monitor attaches while already idle, don't invent a
            # start time; the next real input gives an exact resume timestamp.
            desktop._record_wayland_idle_event(True, now=100.01)
            self.assertEqual(desktop._WAYLAND_IDLE_STATE["status"], "initial_idle_unknown")
            self.assertIsNone(desktop._WAYLAND_IDLE_STATE["last_active"])
            desktop._record_wayland_idle_event(False, now=120.0)
            self.assertEqual(desktop._WAYLAND_IDLE_STATE["last_active"], 120.0)

            desktop._record_wayland_idle_event(True, now=130.0)
            self.assertEqual(desktop._WAYLAND_IDLE_STATE["last_active"], 129.999)
        finally:
            desktop._WAYLAND_IDLE_STATE.update(original)


class BriefCheckinPolicyTests(unittest.TestCase):
    def test_only_short_chat_and_desktop_utility_windows_get_grace(self):
        for app_class in ("chat", "desktop", "email"):
            with self.subTest(app_class=app_class):
                self.assertTrue(jev_overlay._is_brief_checkin({
                    "app_class": app_class,
                    "time_since_window_focused": 30,
                }))
                self.assertFalse(jev_overlay._is_brief_checkin({
                    "app_class": app_class,
                    "time_since_window_focused": 46,
                }))

    def test_other_classes_and_missing_time_do_not_get_grace(self):
        for app_class in ("editor", "ai_coding", "ai_chat", "browser"):
            with self.subTest(app_class=app_class):
                self.assertFalse(jev_overlay._is_brief_checkin({
                    "app_class": app_class,
                    "time_since_window_focused": 10,
                }))
        self.assertFalse(jev_overlay._is_brief_checkin({
            "app_class": "desktop",
            "time_since_window_focused": None,
        }))


class InstalledAppContextTests(unittest.TestCase):
    def test_desktop_shell_windows_are_skipped_by_activity_judgment(self):
        shell_apps = (
            "plasmashell",
            "org.kde.plasmashell",
            "org.gnome.Shell",
            "gnome-shell",
        )
        for app_name in shell_apps:
            with self.subTest(app=app_name), patch.object(
                desktop,
                "_active_window_kwin",
                return_value={
                    "app_class": app_name,
                    "caption": "Application Launcher",
                    "window_id": "shell-window",
                    "desktop_file_id": "",
                },
            ), patch.object(
                desktop, "_time_since_last_active", return_value=(0.0, "test")
            ):
                state = desktop.get_desktop_state("write a report")

            self.assertTrue(state["universal"]["skip_decision"])
            self.assertEqual(
                state["universal"]["skip_decision_reason"], "desktop_shell"
            )
            self.assertEqual(state["universal"]["app_class"], "desktop_shell")
            self.assertNotIn("app_metadata", state)

    def test_gnome_shell_launcher_is_skipped_through_atspi_detection(self):
        class ActiveState:
            def contains(self, _state):
                return True

        class Frame:
            def get_role(self):
                return "frame"

            def get_state_set(self):
                return ActiveState()

            def get_name(self):
                return "Applications"

        class App:
            def get_name(self):
                return "org.gnome.Shell"

            def get_child_count(self):
                return 1

            def get_child_at_index(self, _index):
                return Frame()

        class Desktop:
            def get_child_count(self):
                return 1

            def get_child_at_index(self, _index):
                return App()

        class FakeAtspi:
            class Role:
                FRAME = "frame"
                DIALOG = "dialog"

            class StateType:
                ACTIVE = "active"

            @staticmethod
            def get_desktop(_index):
                return Desktop()

        with (
            patch.object(desktop, "_ATSPI_OK", True),
            patch.object(desktop, "Atspi", FakeAtspi),
            patch.object(desktop, "_active_window_kwin", return_value=None),
            patch.object(desktop, "_time_since_last_active", return_value=(0.0, "test")),
        ):
            state = desktop.get_desktop_state("write a report")

        self.assertTrue(state["universal"]["skip_decision"])
        self.assertEqual(state["universal"]["skip_decision_reason"], "desktop_shell")

    def test_installed_niche_apps_have_a_category_and_description(self):
        cases = {
            "ai.opencode.desktop": ("ai_coding", "opencode"),
            "Antigravity": ("ai_coding", "antigravity"),
            "com.differentai.openwork": ("assistant", "openwork"),
            "ZCode": ("ai_coding", "zcode"),
            "dev.zed.Zed": ("ai_coding", "zed"),
            "Cursor": ("ai_coding", "cursor"),
            "Windsurf": ("ai_coding", "windsurf"),
            "claude-code": ("ai_coding", "claude_code"),
            "codex-cli": ("ai_coding", "codex"),
            "Cline": ("ai_coding", "cline"),
            "Roo-Code": ("ai_coding", "roo_code"),
            "org.kde.konsole": ("terminal", "konsole"),
            "org.gnome.Terminal": ("terminal", "gnome_terminal"),
            "kitty": ("terminal", "kitty"),
            "com.mitchellh.ghostty": ("terminal", "ghostty"),
            "ChatGPT": ("ai_chat", "chatgpt"),
            "Claude": ("ai_chat", "claude"),
            "DeepSeek": ("ai_chat", "deepseek"),
            "Gemini": ("ai_chat", "gemini"),
            "Perplexity": ("ai_chat", "perplexity"),
            "processing-app-Base": ("editor", "arduino"),
            "Vesktop": ("chat", "vesktop"),
            "Balatro": ("game", "balatro"),
            "Cookie Clicker": ("game", "cookie_clicker"),
            "net.lutris.arknights-endfield-3": ("game", "arknights_endfield"),
            "cura-slicer": ("creative", "cura_slicer"),
            "thunderbird": ("email", "thunderbird"),
            "org.kde.kmail": ("email", "kmail"),
            "evolution": ("email", "evolution"),
            "prismlauncher-alpo": ("game", "prismlauncher"),
        }
        for raw_app, expected in cases.items():
            with self.subTest(app=raw_app):
                actual = catalog._match_app(raw_app, "")
                self.assertEqual(actual, expected)
                self.assertTrue(catalog.APP_DESCRIPTIONS[expected[1]])

    def test_terminal_metadata_includes_its_session_context(self):
        metadata = desktop._collect_generic_metadata(
            "terminal", "konsole", "bash — Konsole"
        )
        self.assertEqual(metadata["tab_name"], "bash")
        self.assertEqual(metadata["session_context"], "bash — Konsole")

    def test_missing_catalog_description_uses_installed_desktop_entry(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "sample.desktop"), "w", encoding="utf-8") as entry:
                entry.write(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=Sample Utility\n"
                    "GenericName=System Monitor\n"
                    "Comment=Inspect CPU and memory usage\n"
                    "StartupWMClass=sample-window\n"
                )
            desktop._desktop_entry_roots.cache_clear()
            desktop._installed_app_description.cache_clear()
            try:
                with (
                    patch.object(desktop, "_DESKTOP_ENTRY_DIRS", (root,)),
                    patch.object(desktop, "_APPSTREAM_DIRS", ()),
                    patch.object(desktop, "_active_window_kwin", return_value={
                        "app_class": "sample-window", "caption": "Sample Utility",
                        "window_id": "window-1", "desktop_file_id": "sample",
                    }),
                    patch.object(desktop, "_time_since_last_active", return_value=(1.0, "test")),
                    patch.object(desktop, "_find_app_frame", return_value=None),
                ):
                    state = desktop.get_desktop_state("test goal")
                self.assertIn("Sample Utility", state["app_metadata"]["app_description"])
                self.assertIn("Inspect CPU and memory usage", state["app_metadata"]["app_description"])
                self.assertEqual(state["app_metadata"]["app_description_source"], "desktop_entry")
            finally:
                desktop._desktop_entry_roots.cache_clear()
                desktop._installed_app_description.cache_clear()

    def test_appstream_is_used_when_desktop_entry_has_no_description(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "sample.desktop"), "w", encoding="utf-8") as entry:
                entry.write("[Desktop Entry]\nType=Application\nName=Sample App\n")
            with open(os.path.join(root, "sample.metainfo.xml"), "w", encoding="utf-8") as metainfo:
                metainfo.write(
                    "<component type='desktop-application'><id>sample</id>"
                    "<summary>Sample application</summary>"
                    "<description><p>Explains the app's purpose.</p></description>"
                    "</component>"
                )
            desktop._desktop_entry_roots.cache_clear()
            desktop._appstream_roots.cache_clear()
            desktop._installed_app_description.cache_clear()
            try:
                with (
                    patch.object(desktop, "_DESKTOP_ENTRY_DIRS", (root,)),
                    patch.object(desktop, "_APPSTREAM_DIRS", (root,)),
                ):
                    description, source = desktop._installed_app_description(
                        "sample", "sample", "sample"
                    )
                self.assertIn("Sample application", description)
                self.assertIn("Explains the app's purpose", description)
                self.assertEqual(source, "appstream")
            finally:
                desktop._desktop_entry_roots.cache_clear()
                desktop._appstream_roots.cache_clear()
                desktop._installed_app_description.cache_clear()

    def test_webmail_is_classified_as_email_not_chat(self):
        for domain, provider in catalog.EMAIL_WEBAPP_PROVIDERS.items():
            with self.subTest(domain=domain):
                self.assertEqual(catalog._match_webapp(domain), domain)
                self.assertEqual(catalog.WEBAPP_CATEGORIES[domain], "email")
                metadata = desktop._collect_webapp_metadata(
                    domain, "https://%s/" % domain, "Inbox - %s" % provider, ""
                )
                self.assertEqual(metadata["mail_provider"], provider)
                self.assertNotIn("thunderbird", catalog.APP_METADATA["chat"])

    def test_browser_webmail_state_gets_email_category(self):
        fake_browser_metadata = {
            "site_url": "https://mail.google.com/",
            "site_domain": "mail.google.com",
            "tab_title": "Inbox - Gmail",
            "tab_focus_seconds": None,
            "history_domains": None,
        }
        with (
            patch.object(desktop, "_active_window_kwin", return_value={
                "app_class": "chrome", "caption": "Inbox - Gmail - Google Chrome",
                "window_id": "window-1",
            }),
            patch.object(desktop, "_time_since_last_active", return_value=(0.0, "test")),
            patch.object(desktop, "_find_app_frame", return_value=None),
            patch.object(desktop, "_collect_browser_metadata", return_value=fake_browser_metadata),
        ):
            state = desktop.get_desktop_state("write a lab report")
        self.assertEqual(state["universal"]["app_class"], "browser")
        self.assertEqual(state["webapp"]["category"], "email")
        self.assertEqual(state["webapp"]["app_description"].split()[0], "Gmail")

    def test_browser_ai_chat_gets_neutral_ai_chat_category(self):
        fake_browser_metadata = {
            "site_url": "https://chatgpt.com/",
            "site_domain": "chatgpt.com",
            "tab_title": "Explain photosynthesis - ChatGPT",
            "tab_focus_seconds": None,
            "history_domains": None,
        }
        with (
            patch.object(desktop, "_active_window_kwin", return_value={
                "app_class": "firefox", "caption": "Explain photosynthesis - ChatGPT - Firefox",
                "window_id": "window-1",
            }),
            patch.object(desktop, "_time_since_last_active", return_value=(0.0, "test")),
            patch.object(desktop, "_find_app_frame", return_value=None),
            patch.object(desktop, "_collect_browser_metadata", return_value=fake_browser_metadata),
        ):
            state = desktop.get_desktop_state("study biology")
        self.assertEqual(state["universal"]["app_class"], "browser")
        self.assertEqual(state["webapp"]["category"], "ai_chat")
        self.assertEqual(state["webapp"]["metadata"]["ai_provider"], "ChatGPT")
        self.assertIn("conversational AI", state["webapp"]["app_description"])


class GoalPromptScenarioTests(unittest.TestCase):
    """Check the test cases and rubric without making paid/live Jev calls."""

    def test_science_report_rubric_distinguishes_relevance_from_productivity(self):
        prompt = jev_decides.goal_alignment_prompt("write a science lab report")
        question = prompt["question"].lower()
        self.assertIn("be strict about saying yes", question)
        self.assertIn("generic vs code/opencode", question)
        self.assertIn("purpose-built coding editor, coding agent, or terminal emulator", question)
        self.assertIn("terminal emulator", question)
        self.assertIn("version control", question)
        self.assertNotIn("AI chat", question)
        self.assertIn("science research", question)
        self.assertIn("about:newtab", question)
        self.assertIn("intermediate", prompt["true_when"].lower())
        self.assertNotIn("45 seconds", question)
        self.assertNotIn("2 minutes", question)
        self.assertIn("another course's work", question)
        self.assertIn("talk to clients", question)
        self.assertIn("organize files", question)
        self.assertIn("concrete", prompt["true_when"].lower())
        self.assertIn("when unsure", prompt["false_when"].lower())

    def test_positive_decision_remains_at_existing_threshold(self):
        self.assertEqual(jev_decides.yes_threshold, 50.0)

    def test_yes_means_on_track_and_threshold_boundary_is_unchanged(self):
        class FakeResponse:
            def __init__(self, probability):
                self.probability = probability

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "answers": {"decision": {"noul": self.probability}}
                }).encode()

        with patch.object(jev_decides.urllib.request, "urlopen", return_value=FakeResponse(0.49)):
            below = jev_decides.decide("test-key", "{}", "q", "on task", "not on task")
        with patch.object(jev_decides.urllib.request, "urlopen", return_value=FakeResponse(0.50)):
            at_threshold = jev_decides.decide("test-key", "{}", "q", "on task", "not on task")
        self.assertEqual(below["answer"], "NO")
        self.assertEqual(below["not_on_track_percent"], 51.0)
        self.assertEqual(at_threshold["answer"], "YES")
        self.assertEqual(at_threshold["on_track_percent"], 50.0)

    def test_browser_history_is_removed_from_jev_state_but_active_tab_stays(self):
        state = {
            "universal": {"app_class": "browser", "app_focused_name": "firefox"},
            "app_metadata": {
                "site_url": "about:newtab",
                "site_domain": "",
                "tab_title": "New Tab",
                "history_domains": ["youtube.com", "sfu.ca", "opencode.ai"],
            },
        }
        prepared = json.loads(jev_decides.prepare_state_for_jev(json.dumps(state)))
        self.assertEqual(prepared["app_metadata"]["site_url"], "about:newtab")
        self.assertEqual(prepared["app_metadata"]["tab_title"], "New Tab")
        self.assertNotIn("history_domains", prepared["app_metadata"])
        self.assertIn("history_domains", state["app_metadata"], "input should not be mutated")

    def test_non_browser_state_is_not_filtered(self):
        state = {
            "universal": {"app_class": "desktop"},
            "app_metadata": {"history_domains": ["example.com"]},
        }
        prepared = json.loads(jev_decides.prepare_state_for_jev(json.dumps(state)))
        self.assertEqual(prepared, state)


if __name__ == "__main__":
    unittest.main()
