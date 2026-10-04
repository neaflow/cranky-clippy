"""
Requirements:
    pip install PySide6
"""

import sys
import os
import math
import ctypes
from ctypes import wintypes
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from PySide6.QtCore import Qt, QRect, QTimer, QPoint, QEvent, QAbstractNativeEventFilter
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QPainterPath, QFontMetrics

# Options: "happy", "sad", "default"
CLIPPY_MOOD = "happy"

#size
SCALE_FACTOR = 0.75

#position
POSITION = "bottom-right"
MARGIN = 20

#swaying animation (toggle)
SWAY_ENABLED = True
SWAY_AMPLITUDE = 10   # pixels to sway left/right
SWAY_DURATION = 2000  # milliseconds for one full sway cycle

#vertical sway (up/down)
SWAY_VERTICAL_ENABLED = True
SWAY_VERTICAL_AMPLITUDE = 5   # pixels to move up/down
SWAY_VERTICAL_DURATION = 1500  # milliseconds for one full up/down cycle

#message settings
MESSAGE = "Hey, It's me, It's Clippy!"
MESSAGE_SPEED = 50      # ms between each letter
TEXT_MAX_WIDTH = 750   # max width of the text in pixels
TEXT_MIN_WIDTH = 500    # minimum width of the text window in pixels
TEXT_GAP = 20           # vertical gap between text and image

#minimize hotkey
MINIMIZE_MODIFIER = "ctrl"  # "ctrl", "alt", or "shift"
MINIMIZE_KEY = "M"          # key to press (e.g., "M", "F1", "Space")

#close hotkey
CLOSE_MODIFIER = "ctrl"     # "ctrl", "alt", or "shift"
CLOSE_KEY = "W"             # key to press (e.g., "W", "F4", "Q")

# Windows API constants
WM_HOTKEY = 0x0312
WM_CLOSE = 0x0010
SW_MINIMIZE = 6
HOTKEY_ID_MINIMIZE = 1
HOTKEY_ID_CLOSE = 2
MODIFIER_FLAGS = {
    "ctrl": 0x0002,
    "alt": 0x0001,
    "shift": 0x0004,
}
user32 = ctypes.windll.user32


class OutlinedTextLabel(QLabel):
    """A QLabel that draws text with an outline (no background)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setContentsMargins(10, 10, 10, 10)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        font = self.font()
        fm = QFontMetrics(font)
        text = self.text()
        rect = self.contentsRect()

        # Manual word wrap
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = (current_line + " " + word).strip()
            if fm.horizontalAdvance(test_line) <= rect.width():
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        # Build path with all lines
        path = QPainterPath()
        line_height = fm.lineSpacing()
        total_height = line_height * len(lines)
        y = rect.top() + (rect.height() - total_height) // 2 + fm.ascent()
        for line in lines:
            path.addText(rect.left(), y, font, line)
            y += line_height

        # Draw outline then fill
        painter.setPen(QPen(QColor("#555555"), 2))
        painter.setBrush(QColor("white"))
        painter.drawPath(path)

        painter.end()


class NativeEventFilter(QAbstractNativeEventFilter):
    """Listens for global hotkeys (minimize and close)."""

    def __init__(self, callbacks):
        super().__init__()
        self._callbacks = callbacks  # dict: hotkey_id -> callback

    def nativeEventFilter(self, eventType, message):
        if eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(message.__int__())
            if msg.message == WM_HOTKEY and msg.wParam in self._callbacks:
                self._callbacks[msg.wParam]()
                return True, 0
        return False, 0


class ClippyOverlay(QWidget):
    """A frameless, always-on-top overlay showing clippy.png in the corner.

    Uses two separate windows:
      - This window (image) sways left/right.
      - A separate text window stays still above the image.
    """

    def __init__(self):
        super().__init__()

        # --- Window flags: frameless, always on top, transparent ---
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # hides from taskbar
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        # --- Determine which image to load based on CLIPPY_MOOD ---
        mood_to_file = {
            "happy": "clippy-happy.png",
            "sad": "clippy-sad.png",
            "default": "clippy.png",
        }
        image_file = mood_to_file.get(CLIPPY_MOOD, "clippy.png")
        image_path = os.path.join(os.path.dirname(__file__), "assets", image_file)

        if not os.path.exists(image_path):
            print(f"[ERROR] {image_file} not found at: {image_path}")
            print("Please place the image in the 'assets' folder next to this script.")
            sys.exit(1)

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            print(f"[ERROR] Failed to load {image_file} (corrupt or unsupported format).")
            sys.exit(1)

        # --- Scale the pixmap based on SCALE_FACTOR ---
        scaled_pixmap = pixmap.scaled(
            int(pixmap.width() * SCALE_FACTOR),
            int(pixmap.height() * SCALE_FACTOR),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # --- Create the label that holds the image ---
        self.label = QLabel(self)
        self.label.setPixmap(scaled_pixmap)
        self.label.setScaledContents(False)
        self.label.setFixedSize(scaled_pixmap.size())
        self.setFixedSize(scaled_pixmap.size())

        # --- Store image size ---
        self._win_width = scaled_pixmap.width()
        self._win_height = scaled_pixmap.height()

        # --- Create the text window (separate, does NOT sway) ---
        self._text_window = QWidget()
        self._text_window.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self._text_window.setAttribute(Qt.WA_TranslucentBackground)
        self._text_window.setAttribute(Qt.WA_NoSystemBackground)

        self._message = MESSAGE
        self._text_label = OutlinedTextLabel(self._text_window)
        self._text_label.setWordWrap(True)
        self._text_label.setMinimumWidth(TEXT_MIN_WIDTH)
        self._text_label.setMaximumWidth(TEXT_MAX_WIDTH)
        self._text_label.setAlignment(Qt.AlignCenter)
        self._text_label.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #222222;
                font-size: 18px;
            }
        """)

        # --- Typewriter animation state ---
        self._typewriter_timer = QTimer(self)
        self._typewriter_timer.timeout.connect(self._update_typewriter)
        self._displayed_chars = 0

        # --- Position the windows on screen ---
        self._position_windows()

        # --- Show the initial message ---
        self.show_message()

        # --- Setup sway animation ---
        self._sway_timer = None
        self._sway_time = 0
        self._base_pos = QPoint(self.pos())
        if SWAY_ENABLED:
            self._start_sway()

        # --- Install event filter to catch key presses ---
        self.installEventFilter(self)

    def showEvent(self, event):
        """Re-position the windows when shown."""
        super().showEvent(event)
        self._position_windows()

    def _position_windows(self):
        """Position the image window and text window on screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        screen_geo: QRect = screen.availableGeometry()

        # --- Position image window ---
        if POSITION == "bottom-right":
            x = screen_geo.right() - self._win_width - MARGIN
            y = screen_geo.bottom() - self._win_height - MARGIN
        elif POSITION == "bottom-left":
            x = screen_geo.left() + MARGIN
            y = screen_geo.bottom() - self._win_height - MARGIN
        elif POSITION == "top-right":
            x = screen_geo.right() - self._win_width - MARGIN
            y = screen_geo.top() + MARGIN
        elif POSITION == "top-left":
            x = screen_geo.left() + MARGIN
            y = screen_geo.top() + MARGIN
        elif POSITION == "center":
            x = screen_geo.center().x() - self._win_width // 2
            y = screen_geo.center().y() - self._win_height // 2
        else:
            x = screen_geo.right() - self._win_width - MARGIN
            y = screen_geo.bottom() - self._win_height - MARGIN

        self.move(x, y)
        self._base_pos = QPoint(x, y)

        # --- Position text window above image ---
        if self._text_window.isVisible():
            self._position_text_window()

    def _position_text_window(self):
        """Position the text window above the image."""
        text_w = self._text_window.width()
        text_h = self._text_window.height()
        text_x = self._base_pos.x() + (self._win_width - text_w) // 2
        text_y = self._base_pos.y() - text_h - TEXT_GAP
        self._text_window.move(text_x, text_y)

    def show_message(self, text=None):
        """Display a message above the image with a typewriter effect.

        Pass a new string to change the message, or call with no arguments
        to replay the current message. Can be called again at any time.
        """
        if text is not None:
            self._message = text

        # Stop any running animation
        self._stop_typewriter()

        if not self._message:
            self._text_label.setText("")
            self._text_label.setFixedSize(0, 0)
            self._text_window.hide()
            return

        # Set the full text first so the label computes its final size
        self._text_label.setText(self._message)
        self._text_label.adjustSize()
        self._text_label.setFixedSize(self._text_label.size())

        # Resize text window to fit the label
        self._text_window.setFixedSize(self._text_label.size())
        self._text_window.show()

        # Reposition text window above image
        self._position_text_window()

        # Restart the typewriter animation
        self._displayed_chars = 0
        self._text_label.setText("")
        self._typewriter_timer.start(MESSAGE_SPEED)

    def _stop_typewriter(self):
        """Stop the typewriter animation if it's running."""
        if self._typewriter_timer is not None:
            self._typewriter_timer.stop()

    def _update_typewriter(self):
        """Reveal one more character of the message."""
        self._displayed_chars += 1
        if self._displayed_chars >= len(self._message):
            self._text_label.setText(self._message)
            self._stop_typewriter()
        else:
            self._text_label.setText(self._message[:self._displayed_chars])

    def _start_sway(self):
        """Start the left-right sway animation."""
        self._sway_timer = QTimer(self)
        self._sway_timer.timeout.connect(self._update_sway)
        self._sway_timer.start(16)  # ~60 FPS
        self._sway_time = 0

    def _update_sway(self):
        """Update sway position using sine waves (image only, text stays still)."""
        self._sway_time += 16
        offset_x = SWAY_AMPLITUDE * math.sin(2 * math.pi * self._sway_time / SWAY_DURATION)
        offset_y = SWAY_VERTICAL_AMPLITUDE * math.sin(2 * math.pi * self._sway_time / SWAY_VERTICAL_DURATION)
        self.move(int(self._base_pos.x() + offset_x), int(self._base_pos.y() + offset_y))

    def _stop_sway(self):
        """Stop the sway animation and snap back to base position."""
        if self._sway_timer is not None:
            self._sway_timer.stop()
            self._sway_timer = None
        self.move(self._base_pos)

    def _toggle_sway(self):
        """Toggle sway animation on/off."""
        if self._sway_timer is None:
            self._start_sway()
            print("[ClippyOverlay] Sway enabled")
        else:
            self._stop_sway()
            print("[ClippyOverlay] Sway disabled")

    def _minimize_foreground_window(self):
        """Minimize the currently focused window."""
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            user32.ShowWindow(hwnd, SW_MINIMIZE)

    def _close_foreground_window(self):
        """Close the currently focused window."""
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            user32.SendMessageW(hwnd, WM_CLOSE, 0, 0)

    def eventFilter(self, obj, event):
        """Toggle sway when 'S' key is pressed."""
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_S:
            self._toggle_sway()
            return True
        return super().eventFilter(obj, event)


def main():
    app = QApplication(sys.argv)

    # Optional: set application name (shows in some contexts)
    app.setApplicationName("ClippyOverlay")

    overlay = ClippyOverlay()
    overlay.show()
    overlay._text_window.show()

    # Register global hotkeys
    callbacks = {}

    # Minimize hotkey
    mod_flag = MODIFIER_FLAGS.get(MINIMIZE_MODIFIER, 0x0002)
    vk_key = ord(MINIMIZE_KEY.upper()) if len(MINIMIZE_KEY) == 1 else 0
    if user32.RegisterHotKey(None, HOTKEY_ID_MINIMIZE, mod_flag, vk_key):
        print(f"[ClippyOverlay] Hotkey registered: {MINIMIZE_MODIFIER}+{MINIMIZE_KEY} to minimize active window")
        callbacks[HOTKEY_ID_MINIMIZE] = overlay._minimize_foreground_window
    else:
        print("[ClippyOverlay] WARNING: Failed to register minimize hotkey (may already be in use)")

    # Close hotkey
    mod_flag = MODIFIER_FLAGS.get(CLOSE_MODIFIER, 0x0002)
    vk_key = ord(CLOSE_KEY.upper()) if len(CLOSE_KEY) == 1 else 0
    if user32.RegisterHotKey(None, HOTKEY_ID_CLOSE, mod_flag, vk_key):
        print(f"[ClippyOverlay] Hotkey registered: {CLOSE_MODIFIER}+{CLOSE_KEY} to close active window")
        callbacks[HOTKEY_ID_CLOSE] = overlay._close_foreground_window
    else:
        print("[ClippyOverlay] WARNING: Failed to register close hotkey (may already be in use)")

    # Install native event filter to catch both hotkeys
    hotkey_filter = NativeEventFilter(callbacks)
    app.installNativeEventFilter(hotkey_filter)

    print(f"[ClippyOverlay] Mood: {CLIPPY_MOOD} — Clippy is on screen.")
    print("[ClippyOverlay] Press 'S' to toggle swaying animation.")
    print(f"[ClippyOverlay] Message: \"{MESSAGE}\"")
    print("[ClippyOverlay] Call overlay.show_message(\"new text\") to change it.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
