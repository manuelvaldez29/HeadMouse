"""Panel sin foco y gestión explícita del vocabulario por perfil."""
import ctypes
from ctypes import wintypes
import os
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget,
                               QPlainTextEdit, QProgressBar, QSizePolicy)

from desktop.keyboard_service import KeyboardService

ROWS = {
    "ABC": ("qwertyuiop", "asdfghjklñ", "zxcvbnm,.;"),
    "?123": ("1234567890", "@#$%&*+-/=", "¿?¡!()\"',."),
    "=\\<": ("[]{}<>|\\^~", "`_€£¥×÷±°:", "©®§µ•…;"),
    "Acentos": ("áéíóúüñ", "ÁÉÍÓÚÜÑ", "¿¡"),
    "Emoji": ("🙂😀😂👍❤️", "😊🙏👋🎉"),
}

SIZE_SPECS = {
    "compact": dict(key_h=27, aux_h=24, preview_h=26, expanded_h=52, font_px=14, margins=(8, 5, 8, 5), spacing=3, grid=3),
    "normal":  dict(key_h=31, aux_h=27, preview_h=29, expanded_h=58, font_px=15, margins=(10, 6, 10, 6), spacing=4, grid=4),
    "large":   dict(key_h=38, aux_h=32, preview_h=34, expanded_h=68, font_px=16, margins=(12, 8, 12, 8), spacing=5, grid=5),
}

_USER32 = None

_IGNORED_OVERLAY_CLASSES = (
    "UAC_InputIndicatorOverlayWnd", "UAC Input Indicator",
    "Shell_TrayWnd", "SecondaryTrayWnd", "IME", "MSCTFIME UI",
    "tooltips_class32", "SysShadow",
)

_HIGHER_BAND_SHELL_CLASSES = (
    "Windows.UI.Core.CoreWindow",
    "XamlExplorerHostIslandWindow",
    "SearchPane",
    "Shell_LightDismissOverlay",
)


def _win32_user32():
    global _USER32
    if _USER32 is None and sys.platform == "win32":
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.GetWindowLongW.restype = wintypes.LONG
        u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        u.SetWindowLongW.restype = wintypes.LONG
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetWindowPos.restype = wintypes.BOOL
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindow.restype = wintypes.HWND
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRect.restype = wintypes.BOOL
        u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetClassNameW.restype = ctypes.c_int
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        _USER32 = u
    return _USER32


def _rects_intersect(a, b):
    return a.left < b.right and a.right > b.left and a.top < b.bottom and a.bottom > b.top


def _win32_is_obscured_in_zorder(user32, hwnd, target_hwnd=None):
    GW_HWNDPREV = 3
    own_pid = os.getpid()
    kb_rect = wintypes.RECT()
    has_kb_rect = bool(user32.GetWindowRect(hwnd, ctypes.byref(kb_rect)))
    cur = user32.GetWindow(hwnd, GW_HWNDPREV)
    steps = 0
    cls_buf = ctypes.create_unicode_buffer(96)
    while cur and steps < 35:
        steps += 1
        cur_id = int(cur)
        if target_hwnd and cur_id == int(target_hwnd):
            cls_buf.value = ""
            user32.GetClassNameW(cur, cls_buf, 96)
            if cls_buf.value not in _HIGHER_BAND_SHELL_CLASSES:
                return True
        if user32.IsWindowVisible(cur):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(cur, ctypes.byref(pid))
            if pid.value != own_pid:
                rc = wintypes.RECT()
                if user32.GetWindowRect(cur, ctypes.byref(rc)) and (rc.right > rc.left) and (rc.bottom > rc.top):
                    cls_buf.value = ""
                    user32.GetClassNameW(cur, cls_buf, 96)
                    cls_name = cls_buf.value
                    if cls_name in ("CabinetWClass", "ExploreWClass",
                                    "Microsoft.UI.Content.PopupWindowSiteBridge"):
                        return True
                    if (has_kb_rect and _rects_intersect(kb_rect, rc) and
                            cls_name not in _IGNORED_OVERLAY_CLASSES):
                        return True
        cur = user32.GetWindow(cur, GW_HWNDPREV)
    return False


def _win32_find_occluding_rect_above(user32, hwnd):
    """Detecta si una ventana de banda superior (ej. Windows Search) sigue por encima tras HWND_TOPMOST."""
    GW_HWNDPREV = 3
    own_pid = os.getpid()
    kb_rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(kb_rect)):
        return None
    cur = user32.GetWindow(hwnd, GW_HWNDPREV)
    steps = 0
    cls_buf = ctypes.create_unicode_buffer(96)
    while cur and steps < 35:
        steps += 1
        if user32.IsWindowVisible(cur):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(cur, ctypes.byref(pid))
            if pid.value != own_pid:
                rc = wintypes.RECT()
                if user32.GetWindowRect(cur, ctypes.byref(rc)):
                    w, h = rc.right - rc.left, rc.bottom - rc.top
                    if w >= 200 and h >= 150 and _rects_intersect(kb_rect, rc):
                        cls_buf.value = ""
                        user32.GetClassNameW(cur, cls_buf, 96)
                        cls_name = cls_buf.value
                        if cls_name not in _IGNORED_OVERLAY_CLASSES:
                            return (rc.left, rc.top, w, h)
        cur = user32.GetWindow(cur, GW_HWNDPREV)
    return None


def _win32_ensure_topmost(widget, target_hwnd=None, force=False, always_on_top=True):
    if not always_on_top or sys.platform != "win32":
        return False
    app = QApplication.instance()
    if app is None or app.platformName() != "windows" or not widget.isVisible():
        return False
    modal = QApplication.activeModalWidget()
    if modal is not None and modal is not widget and modal.isVisible():
        return False
    try:
        hwnd = int(widget.winId())
    except Exception:
        return False
    if not hwnd:
        return False
    user32 = _win32_user32()
    if user32 is None:
        return False
    GWL_EXSTYLE = -20
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    required = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style_missing = (exstyle & required) != required
    if style_missing:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle | required)
    if not force and not style_missing and not _win32_is_obscured_in_zorder(user32, hwnd, target_hwnd):
        return False
    widget.raise_()
    HWND_TOPMOST = wintypes.HWND(-1)
    FLAGS = 0x0001 | 0x0002 | 0x0010 | 0x0040 | 0x0200
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, FLAGS)
    return True


def _win32_get_higher_band_occluder(widget):
    if sys.platform != "win32":
        return None
    app = QApplication.instance()
    if app is None or app.platformName() != "windows" or not widget.isVisible():
        return None
    try:
        hwnd = int(widget.winId())
    except Exception:
        return None
    user32 = _win32_user32()
    if not hwnd or user32 is None:
        return None
    return _win32_find_occluding_rect_above(user32, hwnd)


class RestoreHandle(QPushButton):
    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            if wintypes.MSG.from_address(int(message)).message == 0x21:  # WM_MOUSEACTIVATE
                return True, 3  # MA_NOACTIVATE
        return super().nativeEvent(event_type, message)


class VirtualKeyboard(QWidget):
    def __init__(self, bridge, coordinator=None):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.FramelessWindowHint)
        self.bridge = bridge
        self.setObjectName("VirtualKeyboard")
        self.setWindowTitle("Teclado virtual de HeadMouse")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.mode = "ABC"
        self.shift = self.caps = False
        self.modifiers = set()
        self.state = {"visible": False}
        self.effective_size = "normal"
        self.preview_override = None
        self._drag_offset = None
        self._last_topmost_target = None
        self._occluding_bounds = None
        from desktop.overlay_layout import OverlayCoordinator
        self.coordinator = coordinator or OverlayCoordinator(self)
        self.coordinator.keyboard = self
        self.pending_keys = []
        self.selected_button = None
        self.hiding = False
        self.service = KeyboardService(bridge, self)
        self.service.view.connect(self.present, Qt.ConnectionType.QueuedConnection)
        self.service.error.connect(self.show_status, Qt.ConnectionType.QueuedConnection)
        self.service.feedback.connect(self.key_executed, Qt.ConnectionType.QueuedConnection)
        self.restore_handle = RestoreHandle("⌨ Abrir teclado", None)
        self.restore_handle.setWindowFlags(self.windowFlags())
        self.restore_handle.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.restore_handle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.restore_handle.setAccessibleName("Volver a abrir el teclado de HeadMouse")
        self.restore_handle.setMinimumSize(148, 38)
        self.restore_handle.clicked.connect(self.toggle)
        self.restore_handle.setStyleSheet("QPushButton {background:#173d49;color:#f1fffe;border:2px solid #6ee7dc;"
                                         "border-radius:8px;padding:5px 8px;font-size:14px;font-weight:bold;}")
        self.setStyleSheet("""
            QWidget#VirtualKeyboard { background: #111d2d; border: 1px solid #55728e; border-radius: 10px; }
            QLabel { color: #f1f5f9; background: transparent; font-size: 12px; }
            QPushButton { color: #fff; background: #283d55; border: 1px solid #527391;
                          border-radius: 6px; padding: 2px 6px; font-weight: 600; font-size: 15px; }
            QPushButton:hover { color: #102334; background: #6ee7dc; }
            QPushButton:checked { color: #102334; background: #9eeeee; }
            QPushButton[feedback="pending"] { color:#ffffff; background:#305c99; border:2px solid #a3c8ff; }
            QPushButton[feedback="sent"] { color:#052b26; background:#6ee7b7; border:2px solid #d8fff0; }
            QPushButton[feedback="failed"] { color:#ffffff; background:#913c4c; border:2px solid #ffc3c3; }
            QPushButton:disabled { color: #8ca2b7; background: #1b2b3d; }
        """)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 6, 10, 6)
        self.main_layout.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.status = QLabel("Teclado · Español")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        top.addWidget(self.status, 1)
        self.key_preview = QLabel()
        self.key_preview.setStyleSheet("font-size:20px;font-weight:bold;color:#bdfff1;")
        self.key_preview.setMinimumWidth(32)
        top.addWidget(self.key_preview)
        self.page_buttons = {}
        for mode in ROWS:
            btn = self.button(mode, lambda name=mode: self.set_mode(name))
            btn.setCheckable(True)
            top.addWidget(btn)
            self.page_buttons[mode] = btn
        self.mic = self.button("🎙 Dictar", lambda: self.send("mic"))
        top.addWidget(self.mic)
        self.hide_button = self.button("Ocultar", self.hide_keyboard)
        top.addWidget(self.hide_button)
        self.main_layout.addLayout(top)

        self.preview_row = QWidget()
        preview_layout = QHBoxLayout(self.preview_row)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)
        self.composition = QPlainTextEdit()
        self.composition.setAccessibleName("Vista previa del texto compuesto por HeadMouse")
        self.composition.setReadOnly(True)
        self.composition.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.composition.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.composition.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.composition.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.composition.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.composition.setFixedHeight(28)
        self.composition.setStyleSheet("background:#091421;color:#f6fcff;border:1px solid #61839a;"
                                      "border-radius:5px;font-size:14px;padding:2px 6px;")
        preview_layout.addWidget(self.composition, 3)
        self.composition_label = QLabel("Texto compuesto por HeadMouse · sólo en esta sesión")
        self.composition_label.setStyleSheet("color:#9fb6cd;font-size:11px;")
        self.composition_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        preview_layout.addWidget(self.composition_label, 2)
        self.preview_toggle = self.button("▾", self.toggle_preview_mode)
        self.preview_toggle.setToolTip("Expandir o compactar la vista previa de texto")
        self.preview_toggle.setAccessibleName("Expandir o compactar vista previa")
        self.preview_toggle.setMinimumWidth(28)
        preview_layout.addWidget(self.preview_toggle)
        self.main_layout.addWidget(self.preview_row)

        self.suggestions_row = QWidget()
        suggestions = QHBoxLayout(self.suggestions_row)
        suggestions.setContentsMargins(0, 0, 0, 0)
        suggestions.setSpacing(4)
        self.prediction_buttons = []
        for index in range(3):
            button = self.button("—", lambda i=index: self.choose(i))
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            suggestions.addWidget(button, 1)
            self.prediction_buttons.append(button)
        self.main_layout.addWidget(self.suggestions_row)

        self.grid = QGridLayout()
        self.grid.setSpacing(4)
        self.main_layout.addLayout(self.grid)

        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        self.shift_button = self.button("⇧", self.toggle_shift)
        self.caps_button = self.button("Bloq ⇧", self.toggle_caps)
        for button in (self.shift_button, self.caps_button):
            button.setCheckable(True)
            button.setMinimumWidth(36)
            bottom.addWidget(button)
        self.caps_button.setMinimumWidth(58)
        self.control_buttons = {}
        for name in ("Ctrl", "Alt"):
            button = self.button(name, lambda mod=name: self.toggle_modifier(mod))
            button.setCheckable(True)
            button.setMinimumWidth(36)
            bottom.addWidget(button)
            self.control_buttons[name] = button
        self.action_buttons = []
        navigation = QHBoxLayout()
        navigation.setSpacing(4)
        for name in ("Tab", "Espacio", "⌫", "Enter", "Supr", "Inicio", "←", "↑", "↓", "→", "Fin"):
            button = self.button(name, lambda value=name: self.press(value))
            self.action_buttons.append(button)
            row = bottom if name in ("Tab", "Espacio", "⌫", "Enter") else navigation
            row.addWidget(button, 4 if name == "Espacio" else 1)
        self.main_layout.addLayout(bottom)
        self.main_layout.addLayout(navigation)

        self.dwell_bar = QProgressBar()
        self.dwell_bar.setAccessibleName("Progreso de selección por permanencia")
        self.dwell_bar.setRange(0, 100)
        self.dwell_bar.setTextVisible(False)
        self.dwell_bar.setMaximumHeight(5)
        self.dwell_bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.dwell_bar.hide()
        self.dwell_bar.setGeometry(10, self.height()-6, max(1, self.width()-20), 5)
        self.dwell_button = self.dwell_anchor = self.dwell_since = self.dwell_latched = None
        self.dwell_click_revision = 0
        self.dwell_token = None
        self.dwell_timer = QTimer(self)
        self.dwell_timer.setInterval(50)
        self.dwell_timer.timeout.connect(self._advance_dwell)

        self.topmost_timer = QTimer(self)
        self.topmost_timer.setInterval(250)
        self.topmost_timer.timeout.connect(self._check_topmost_order)

        self.set_mode("ABC")

    def _advance_dwell(self):
        controller = self.bridge.controller
        ui = self.bridge.snapshot().get("settings", {}).get("ui", {})
        allowed = getattr(controller, "ocular_keyboard_dwell_allowed", None)
        if (not ui.get("ocular_keyboard_dwell") or ui.get("tracking_method") not in ("eye_joystick", "eye_absolute")
                or not self.isVisible() or not self.state.get("usable")):
            self.dwell_bar.hide()
            self.dwell_button = self.dwell_latched = None
            return
        point = self.mapFromGlobal(QCursor.pos())
        child = self.childAt(point)
        button = child if isinstance(child, QPushButton) and child.isEnabled() else None
        token = self.state.get("token")
        if token != self.dwell_token:
            self.dwell_token = token
            self.dwell_latched = button  # entering a new field requires leaving the initial key
            self.dwell_button = None
        pointer_click = getattr(controller.control, "pointer_click", (0, None, 0))[0]
        wink_clicked = pointer_click != self.dwell_click_revision
        self.dwell_click_revision = pointer_click
        if button is not self.dwell_latched:
            self.dwell_latched = None
        if wink_clicked:
            self.dwell_latched = button
        if button is None or button is self.dwell_latched or not (allowed and allowed()):
            self.dwell_button = None
            self.dwell_bar.hide()
            return
        now = time.monotonic()
        if self.dwell_button is not button or (point - self.dwell_anchor).manhattanLength() > 3:
            self.dwell_button, self.dwell_anchor, self.dwell_since = button, point, now
        elapsed_ms = (now - self.dwell_since) * 1000
        self.dwell_bar.setValue(min(100, int(100 * elapsed_ms / ui["ocular_keyboard_dwell_ms"])))
        self.dwell_bar.setGeometry(10, self.height()-6, max(1, self.width()-20), 5)
        self.dwell_bar.show()
        self.dwell_bar.raise_()
        if self.dwell_bar.value() == 100 and allowed():
            self.dwell_latched = button
            button.click()

    def button(self, title, callback):
        button = QPushButton(title)
        button.setAccessibleName(title)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRepeat(False)
        button.setMinimumHeight(24)
        button.setMinimumWidth(26)
        def selected():
            self.selected_button = button
            try:
                callback()
            finally:
                self.selected_button = None
        button.clicked.connect(selected)
        return button

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            if wintypes.MSG.from_address(int(message)).message == 0x21:  # WM_MOUSEACTIVATE
                return True, 3  # MA_NOACTIVATE: entrega el clic y conserva el foco
        return super().nativeEvent(event_type, message)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            target_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(target_pos)
            self.coordinator.set_manual_position(target_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def is_preview_expanded(self):
        mode = self.preview_override or self.state.get("preview_mode", "compact")
        return mode == "expanded"

    def toggle_preview_mode(self):
        self.preview_override = "compact" if self.is_preview_expanded() else "expanded"
        self.update_keys()
        self._update_composition_view(force_scroll=True)
        if self.isVisible():
            self.coordinator.keyboard_key = None
            self.coordinator.place_keyboard(self, self.state)

    def _update_composition_view(self, force_scroll=False):
        state = self.state
        show_preview = (state.get("show_preview", True) and not state.get("private", False)
                        and state.get("preview_mode", "compact") != "hidden")
        text = state.get("preview", "") if show_preview else ""
        cursor = min(len(text), state.get("cursor", len(text)))
        before_text = text[:cursor]
        after_text = text[cursor:]
        if not self.is_preview_expanded() and "\n" in text:
            before_text = before_text.replace("\n", " ↵ ")
            after_text = after_text.replace("\n", " ↵ ")
        shown = before_text + "▏" + after_text
        changed = self.composition.toPlainText() != shown
        if changed:
            self.composition.setPlainText(shown)
        if changed or force_scroll:
            caret = self.composition.textCursor()
            caret.setPosition(len((before_text + "▏").encode("utf-16-le")) // 2)
            self.composition.setTextCursor(caret)
            self.composition.ensureCursorVisible()
        return changed

    def apply_effective_size(self, effective_size):
        if effective_size in SIZE_SPECS and effective_size != self.effective_size:
            self.effective_size = effective_size
            self.update_keys()

    def set_mode(self, mode):
        self.mode = mode
        for name, button in self.page_buttons.items():
            button.setChecked(name == mode)
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        self.letter_buttons = []
        for row, keys in enumerate(ROWS[mode]):
            if mode == "Emoji":
                keys = ("🙂", "😀", "😂", "👍", "❤️") if row == 0 else ("😊", "🙏", "👋", "🎉")
            for column, value in enumerate(keys):
                text = value.upper() if mode == "ABC" and (self.shift != self.caps) else value
                button = self.button(text, lambda char=text: self.press(char))
                self.grid.addWidget(button, row, column)
                self.letter_buttons.append(button)
        self.update_keys()

    def update_keys(self):
        requested = self.state.get("size", "auto")
        size_name = requested if requested in SIZE_SPECS else self.effective_size
        spec = SIZE_SPECS.get(size_name, SIZE_SPECS["normal"])
        self.main_layout.setContentsMargins(*spec["margins"])
        self.main_layout.setSpacing(spec["spacing"])
        self.grid.setSpacing(spec["grid"])
        for button in self.letter_buttons:
            button.setFixedHeight(spec["key_h"])
        for button in (*self.action_buttons, self.shift_button, self.caps_button, *self.control_buttons.values()):
            button.setFixedHeight(spec["aux_h"])
        for button in (*self.prediction_buttons, *self.page_buttons.values(), self.mic, self.hide_button, self.preview_toggle):
            button.setFixedHeight(spec["aux_h"])
        expanded = self.is_preview_expanded()
        preview_h = spec["expanded_h"] if expanded else spec["preview_h"]
        wrap_mode = QPlainTextEdit.LineWrapMode.WidgetWidth if expanded else QPlainTextEdit.LineWrapMode.NoWrap
        if self.composition.lineWrapMode() != wrap_mode:
            self.composition.setLineWrapMode(wrap_mode)
        if self.composition.height() != preview_h:
            self.composition.setFixedHeight(preview_h)
        if self.preview_row.height() != preview_h:
            self.preview_row.setFixedHeight(preview_h)
        self.preview_toggle.setText("▴" if expanded else "▾")
        usable = self.state.get("usable", False)
        for button in (*self.letter_buttons, *self.action_buttons):
            button.setEnabled(usable)
        if self.preview_row.layout() is not None:
            self.preview_row.layout().activate()
        if self.suggestions_row.layout() is not None:
            self.suggestions_row.layout().activate()
        self.main_layout.activate()

    def _check_topmost_order(self):
        if not self.state.get("always_on_top", True):
            return
        target_hwnd = self.state.get("window")
        if self.isVisible():
            _win32_ensure_topmost(self, target_hwnd=target_hwnd, force=False, always_on_top=True)
            if not self.state.get("panel_bounds"):
                occ = _win32_get_higher_band_occluder(self)
                if occ is not None and occ != self._occluding_bounds:
                    self._occluding_bounds = occ
                    self.coordinator.place_keyboard(self, self.state)
        elif self.restore_handle.isVisible():
            _win32_ensure_topmost(self.restore_handle, target_hwnd=target_hwnd, force=False, always_on_top=True)

    def toggle_shift(self):
        self.shift = not self.shift
        self.shift_button.setChecked(self.shift)
        self.set_mode(self.mode)

    def toggle_caps(self):
        self.caps = not self.caps
        self.caps_button.setChecked(self.caps)
        self.set_mode(self.mode)

    def toggle_modifier(self, name):
        if name in self.modifiers:
            self.modifiers.remove(name)
        else:
            self.modifiers.add(name)

    def press(self, value):
        from keyboard_input import KEYS
        mods = tuple(name for name in ("Ctrl", "Alt") if name in self.modifiers)
        if value == "Espacio" and mods:
            self.send("key", (" ", mods))
        elif value in KEYS or mods:
            self.send("key", (value, mods))
        else:
            self.send("text", " " if value == "Espacio" else value)
        self.modifiers.clear()
        for button in self.control_buttons.values():
            button.setChecked(False)
        if self.shift:
            self.toggle_shift()

    def send(self, action, value=None):
        from shiboken6 import isValid
        button = self.selected_button
        if button is not None and isValid(button):
            self.pending_keys.append((action, self.state.get("token"), button))
            if self.state.get("feedback", True):
                self.flash(button, "pending")
            if self.state.get("enlarged_key"):
                self.key_preview.setText("•" if self.state.get("private") else button.text()[:12])
        self.selected_button = None
        self.service.submit(action, value, self.state.get("token"))

    @staticmethod
    def flash(button, kind):
        from shiboken6 import isValid
        if not isValid(button):
            return
        button.setProperty("feedback", kind)
        button.style().unpolish(button)
        button.style().polish(button)
        if kind != "pending":
            def clear():
                if isValid(button) and button.property("feedback") == kind:
                    button.setProperty("feedback", "")
                    button.style().unpolish(button)
                    button.style().polish(button)
            QTimer.singleShot(300, clear)

    def key_executed(self, result):
        for index, (action, token, button) in enumerate(self.pending_keys):
            if action == result["action"] and token == result["token"]:
                self.pending_keys.pop(index)
                if self.state.get("feedback", True):
                    self.flash(button, "sent" if result["executed"] else "failed")
                break
        if not result["executed"]:
            self.show_status("La tecla no se pudo enviar al campo.")

    def choose(self, index):
        entries = self.state.get("predictions", [])
        if index < len(entries):
            self.send("suggest", entries[index][0])

    def show_status(self, text):
        self.status.setText(text)
        if not self.isVisible():
            parent = self.parentWidget()
            if parent and hasattr(parent, "show_error"):
                parent.show_error(text)

    def toggle(self):
        self.service.submit("toggle")

    def hide_keyboard(self):
        self.hiding = True
        self.topmost_timer.stop()
        self.dwell_timer.stop()
        self.dwell_bar.hide()
        self.dwell_button = self.dwell_latched = None
        self.composition.clear()
        self.hide()
        self.service.submit("hide")

    def closeEvent(self, event):
        self.topmost_timer.stop()
        self.dwell_timer.stop()
        self.service.close()
        if self.coordinator.keyboard is self:
            self.coordinator.keyboard = None
            self.coordinator.field = None
            self.coordinator.panel = None
        self.restore_handle.close()
        self.restore_handle.deleteLater()
        super().closeEvent(event)

    def present(self, state):
        ui = self.bridge.snapshot().get("settings", {}).get("ui", {})
        if state["visible"] and ui.get("tracking_method") in ("eye_joystick", "eye_absolute") and ui.get("ocular_keyboard_dwell"):
            if not self.dwell_timer.isActive():
                self.dwell_timer.start()
        else:
            self.dwell_timer.stop()
            self.dwell_bar.hide()
            self.dwell_button = self.dwell_latched = None
        if self.hiding and state["visible"]:
            return
        target_changed = (self.state.get("target") != state.get("target") or
                          self.state.get("window") != state.get("window"))
        if target_changed:
            self._occluding_bounds = None
        if self.state.get("token") != state["token"]:
            self.modifiers.clear()
            for button in self.control_buttons.values():
                button.setChecked(False)
            self.pending_keys.clear()
            self.composition.clear()
            self.key_preview.clear()
        self.state = state
        always_on_top = state.get("always_on_top", True)
        target_hwnd = state.get("window")
        if not state["visible"]:
            self.hiding = False
            self.composition.clear()
            self.hide()
            self.coordinator.field = None
            self.coordinator.panel = None
            if state.get("restore"):
                from desktop.overlay_layout import logical_field, keyboard_rect
                from PySide6.QtCore import QSize
                screens = QApplication.screens()
                screen, field = logical_field(state.get("bounds"), screens)
                _, panel = logical_field(state.get("panel_bounds") or self._occluding_bounds, screens)
                previous = self.coordinator.keyboard_screen
                screen = screen or (previous if previous in screens else QApplication.primaryScreen())
                was_handle_visible = self.restore_handle.isVisible()
                self.restore_handle.setGeometry(keyboard_rect(screen.availableGeometry(), QSize(156, 40), field, panel=panel))
                self.restore_handle.show()
                _win32_ensure_topmost(self.restore_handle, target_hwnd=target_hwnd,
                                      force=not was_handle_visible or target_changed, always_on_top=always_on_top)
                if not self.topmost_timer.isActive():
                    self.topmost_timer.start()
            else:
                self.restore_handle.hide()
                self.topmost_timer.stop()
            return
        self.restore_handle.hide()
        self.status.setText("Escuchando…" if state["listening"] else "Dictado en curso" if state["busy"] else "Escritura privada" if state["private"] else
                            "Teclado · Español" if state["usable"] else "Seleccioná un campo de texto")
        self.mic.setVisible(state["show_mic"])
        self.mic.setEnabled(state["mic"])
        self.mic.setText("Detener dictado" if state["busy"] else "🎙 Dictar")
        show_preview = state.get("show_preview", True) and not state["private"] and state.get("preview_mode", "compact") != "hidden"
        self.preview_row.setVisible(show_preview)
        self.composition.setVisible(show_preview)
        self.composition_label.setVisible(show_preview)
        self.preview_toggle.setVisible(show_preview)
        show_suggestions = bool(state.get("suggestions", True) and not state["private"])
        self.suggestions_row.setVisible(show_suggestions)
        self.key_preview.setVisible(state.get("enlarged_key", False))
        if state["private"]:
            self.key_preview.setText("•")
        self.setWindowOpacity(state.get("opacity", 100) / 100)
        text = state.get("preview", "") if show_preview else ""
        self.composition_label.setText("Composición de HeadMouse · " + (
            "campo o cursor cambiado; vista limpiada" if state.get("preview_status") == "changed" else
            "cursor comprobado" if state.get("preview_status") == "confirmed" else
            "composición recuperada en este campo" if state.get("preview_status") == "recovered" else
            "enviada; destino sin confirmar" if text else
            "sólo esta sesión, sin guardar"))
        for index, button in enumerate(self.prediction_buttons):
            if index < len(state["predictions"]):
                word, correction = state["predictions"][index]
                button.setText("✓ " + word if correction else word)
                button.setAccessibleName("Aceptar corrección " + word if correction else "Completar " + word)
                button.setEnabled(True)
            else:
                button.setText("—")
                button.setEnabled(False)
        self.update_keys()
        was_visible = self.isVisible()
        composition_changed = self._update_composition_view(force_scroll=not was_visible or target_changed)
        moves_before = self.coordinator.keyboard_moves
        self.coordinator.place_keyboard(self, state)
        moved = self.coordinator.keyboard_moves != moves_before
        self.show()
        if show_preview and (composition_changed or not was_visible or moved):
            self.composition.ensureCursorVisible()
        _win32_ensure_topmost(self, target_hwnd=target_hwnd,
                              force=(not was_visible) or target_changed or moved,
                              always_on_top=always_on_top)
        if always_on_top and not state.get("panel_bounds"):
            occ = _win32_get_higher_band_occluder(self)
            if occ is not None and occ != self._occluding_bounds:
                self._occluding_bounds = occ
                self.coordinator.place_keyboard(self, state)
        if not self.topmost_timer.isActive():
            self.topmost_timer.start()

    def manage(self, parent):
        profile = (self.bridge.snapshot().get("profile") or {}).get("user_id")
        if not profile:
            parent.show_error("Elegí un perfil para administrar su diccionario.")
            return
        was_visible = self.isVisible()
        if was_visible:
            self.hide()
        dialog = QDialog(parent)
        dialog.setWindowTitle("Diccionario personal")
        dialog.resize(480, 420)
        layout = QVBoxLayout(dialog)
        words = QListWidget()
        words.setAccessibleName("Palabras aprendidas por este perfil")
        layout.addWidget(words)
        delete = QPushButton("Eliminar palabra")
        delete.clicked.connect(lambda: self.service.submit("delete", words.currentItem().text(), profile)
                               if words.currentItem() else None)
        layout.addWidget(delete)
        clear = QPushButton("Borrar todo el diccionario personal")
        def confirm():
            if QMessageBox.question(dialog, "Borrar diccionario", "¿Borrar todas las palabras y combinaciones aprendidas?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.service.submit("clear", token=profile)
        clear.clicked.connect(confirm)
        layout.addWidget(clear)
        close = QPushButton("Cerrar")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        def update(owner, entries):
            if owner == profile:
                words.clear()
                words.addItems(entries)
        self.service.vocabulary.connect(update, Qt.ConnectionType.QueuedConnection)
        self.service.submit("list", token=profile)
        try:
            dialog.exec()
        finally:
            self.service.vocabulary.disconnect(update)
            if was_visible and self.state.get("visible"):
                self.show()
