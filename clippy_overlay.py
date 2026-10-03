"""
Requirements:
    pip install PySide6
"""

import sys
import os
import math
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from PySide6.QtCore import Qt, QRect, QTimer, QPoint, QEvent
from PySide6.QtGui import QPixmap

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


class ClippyOverlay(QWidget):
    """A frameless, always-on-top overlay showing clippy.png in the corner."""

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
            "happy": "happy.png",
            "sad": "sad.png",
            "default": "default.png",
        }
        image_file = mood_to_file.get(CLIPPY_MOOD, "default.png")
        image_path = os.path.join(os.path.dirname(__file__), "faces_placeholder", image_file)

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

        # --- Store window size for positioning ---
        self._win_width = scaled_pixmap.width()
        self._win_height = scaled_pixmap.height()

        # --- Position the window on screen ---
        self._position_window()

        # --- Setup sway animation ---
        self._sway_timer = None
        self._sway_time = 0
        self._base_pos = QPoint(self.pos())
        if SWAY_ENABLED:
            self._start_sway()

        # --- Install event filter to catch key presses ---
        self.installEventFilter(self)

    def showEvent(self, event):
        """Re-position the window when it's shown."""
        super().showEvent(event)
        self._position_window()

    def _position_window(self):
        """Move the window based on POSITION and MARGIN settings."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        screen_geo: QRect = screen.availableGeometry()

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

    def _start_sway(self):
        """Start the left-right sway animation."""
        self._sway_timer = QTimer(self)
        self._sway_timer.timeout.connect(self._update_sway)
        self._sway_timer.start(16)  # ~60 FPS
        self._sway_time = 0

    def _update_sway(self):
        """Update sway position using sine wave."""
        self._sway_time += 16
        offset = SWAY_AMPLITUDE * math.sin(2 * math.pi * self._sway_time / SWAY_DURATION)
        self.move(int(self._base_pos.x() + offset), self._base_pos.y())

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

    print(f"[ClippyOverlay] Mood: {CLIPPY_MOOD} — Clippy is on screen.")
    print("[ClippyOverlay] Press 'S' to toggle swaying animation.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
