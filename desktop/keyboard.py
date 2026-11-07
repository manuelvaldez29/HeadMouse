"""Panel sin foco y gestión explícita del vocabulario por perfil."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from desktop.keyboard_service import KeyboardService

ROWS = {
    "ABC": ("qwertyuiop", "asdfghjklñ", "zxcvbnm,.;"),
    "?123": ("1234567890", "@#$%&*+-/=", "¿?¡!()\"',."),
    "=\\<": ("[]{}<>|\\^~", "`_€£¥×÷±°:", "©®§µ•…;"),
    "Acentos": ("áéíóúüñ", "ÁÉÍÓÚÜÑ", "¿¡"),
    "Emoji": ("🙂😀😂👍❤️", "😊🙏👋🎉"),
}


class VirtualKeyboard(QWidget):
    def __init__(self, bridge):
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
        self.service = KeyboardService(bridge,self)
        self.service.view.connect(self.present,Qt.ConnectionType.QueuedConnection)
        self.service.error.connect(self.show_status,Qt.ConnectionType.QueuedConnection)
        self.setStyleSheet("""
            QWidget#VirtualKeyboard { background: #111d2d; border: 1px solid #55728e; border-radius: 12px; }
            QLabel { color: #f1f5f9; background: transparent; }
            QPushButton { color: #fff; background: #283d55; border: 1px solid #527391;
                          border-radius: 8px; padding: 5px 7px; font-weight: 600; }
            QPushButton:hover { color: #102334; background: #6ee7dc; }
            QPushButton:checked { color: #102334; background: #9eeeee; }
            QPushButton:disabled { color: #8ca2b7; background: #1b2b3d; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12,10,12,10)
        layout.setSpacing(6)
        top = QHBoxLayout()
        self.status = QLabel("Teclado · Español")
        top.addWidget(self.status,1)
        self.mic = self.button("🎙 Dictar", lambda: self.send("mic"))
        top.addWidget(self.mic)
        top.addWidget(self.button("Ocultar",self.hide_keyboard))
        layout.addLayout(top)
        suggestions = QHBoxLayout()
        self.prediction_buttons = []
        for index in range(3):
            button = self.button("—", lambda i=index: self.choose(i))
            suggestions.addWidget(button,1)
            self.prediction_buttons.append(button)
        layout.addLayout(suggestions)
        pages = QHBoxLayout()
        self.page_buttons = {}
        for mode in ROWS:
            button = self.button(mode,lambda name=mode:self.set_mode(name))
            button.setCheckable(True)
            pages.addWidget(button)
            self.page_buttons[mode]=button
        layout.addLayout(pages)
        self.grid = QGridLayout()
        self.grid.setSpacing(5)
        layout.addLayout(self.grid)
        bottom = QHBoxLayout()
        self.shift_button = self.button("⇧", self.toggle_shift)
        self.caps_button = self.button("Bloq ⇧", self.toggle_caps)
        for button in (self.shift_button,self.caps_button):
            button.setCheckable(True)
            bottom.addWidget(button)
        self.control_buttons = {}
        for name in ("Ctrl","Alt"):
            button = self.button(name,lambda mod=name:self.toggle_modifier(mod))
            button.setCheckable(True)
            bottom.addWidget(button)
            self.control_buttons[name] = button
        self.action_buttons = []
        navigation = QHBoxLayout()
        for name in ("Tab","Espacio","⌫","Enter","Supr","Inicio","←","↑","↓","→","Fin"):
            button = self.button(name,lambda value=name:self.press(value))
            self.action_buttons.append(button)
            row = bottom if name in ("Tab","Espacio","⌫","Enter") else navigation
            row.addWidget(button, 4 if name=="Espacio" else 1)
        layout.addLayout(bottom)
        layout.addLayout(navigation)
        self.set_mode("ABC")

    @staticmethod
    def button(title, callback):
        button = QPushButton(title)
        button.setAccessibleName(title)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRepeat(False)
        button.clicked.connect(lambda checked=False: callback())
        return button

    def nativeEvent(self,event_type,message):
        if sys.platform=="win32":
            from ctypes import wintypes
            if wintypes.MSG.from_address(int(message)).message==0x21:  # WM_MOUSEACTIVATE
                return True,3  # MA_NOACTIVATE: entrega el clic y conserva el foco
        return super().nativeEvent(event_type,message)

    def set_mode(self,mode):
        self.mode = mode
        for name,button in self.page_buttons.items():
            button.setChecked(name==mode)
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        self.letter_buttons = []
        for row,keys in enumerate(ROWS[mode]):
            if mode=="Emoji":
                keys = ("🙂","😀","😂","👍","❤️") if row==0 else ("😊","🙏","👋","🎉")
            for column,value in enumerate(keys):
                text = value.upper() if mode=="ABC" and (self.shift != self.caps) else value
                button = self.button(text,lambda char=text:self.press(char))
                self.grid.addWidget(button,row,column)
                self.letter_buttons.append(button)
        self.update_keys()

    def update_keys(self):
        height = {"compact":30,"normal":40,"large":50}[self.state.get("size","normal")]
        for button in (*self.letter_buttons,*self.action_buttons,*self.prediction_buttons):
            button.setMinimumHeight(height)
        for button in (*self.letter_buttons,*self.action_buttons):
            button.setEnabled(self.state.get("usable",False))

    def toggle_shift(self):
        self.shift = not self.shift
        self.shift_button.setChecked(self.shift)
        self.set_mode(self.mode)

    def toggle_caps(self):
        self.caps = not self.caps
        self.caps_button.setChecked(self.caps)
        self.set_mode(self.mode)

    def toggle_modifier(self,name):
        if name in self.modifiers:
            self.modifiers.remove(name)
        else:
            self.modifiers.add(name)

    def press(self,value):
        from keyboard_input import KEYS
        mods = tuple(name for name in ("Ctrl","Alt") if name in self.modifiers)
        if value=="Espacio" and mods:
            self.send("key",(" ",mods))
        elif value in KEYS or mods:
            self.send("key",(value,mods))
        else:
            self.send("text"," " if value=="Espacio" else value)
        self.modifiers.clear()
        for button in self.control_buttons.values():
            button.setChecked(False)
        if self.shift:
            self.toggle_shift()

    def send(self,action,value=None):
        self.service.submit(action,value,self.state.get("token"))

    def choose(self,index):
        entries = self.state.get("predictions",[])
        if index < len(entries):
            self.send("suggest",entries[index][0])

    def show_status(self,text):
        self.status.setText(text)
        if not self.isVisible():
            parent = self.parentWidget()
            if parent and hasattr(parent,"show_error"):
                parent.show_error(text)

    def toggle(self):
        self.service.submit("toggle")

    def hide_keyboard(self):
        self.hide()
        self.service.submit("hide")

    def closeEvent(self,event):
        self.service.close()
        super().closeEvent(event)

    def present(self,state):
        geometry_changed = any(self.state.get(key)!=state[key] for key in ("size","position","visible"))
        if self.state.get("token") != state["token"]:
            self.modifiers.clear()
            for button in self.control_buttons.values():
                button.setChecked(False)
        self.state = state
        if not state["visible"]:
            self.hide()
            return
        self.status.setText("Escuchando…" if state["listening"] else "Dictado en curso" if state["busy"] else "Escritura privada" if state["private"] else
                            "Teclado · Español" if state["usable"] else "Seleccioná un campo de texto")
        self.mic.setVisible(state["show_mic"])
        self.mic.setEnabled(state["mic"])
        self.mic.setText("Detener dictado" if state["busy"] else "🎙 Dictar")
        for index,button in enumerate(self.prediction_buttons):
            if index < len(state["predictions"]):
                word,correction = state["predictions"][index]
                button.setText("✓ "+word if correction else word)
                button.setAccessibleName("Aceptar corrección "+word if correction else "Completar "+word)
                button.setEnabled(True)
            else:
                button.setText("—")
                button.setEnabled(False)
        self.update_keys()
        if geometry_changed:
            screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            area = screen.availableGeometry()
            ratio = {"compact":.70,"normal":.85,"large":.96}[state["size"]]
            self.resize(min(area.width()-16,int(area.width()*ratio)), self.sizeHint().height())
            self.move(area.x()+(area.width()-self.width())//2,
                      area.y()+8 if state["position"]=="top" else area.bottom()-self.height()-7)
        self.show()

    def manage(self,parent):
        profile=(self.bridge.snapshot().get("profile") or {}).get("user_id")
        if not profile:
            parent.show_error("Elegí un perfil para administrar su diccionario.")
            return
        dialog = QDialog(parent)
        dialog.setWindowTitle("Diccionario personal")
        dialog.resize(480,420)
        layout = QVBoxLayout(dialog)
        words = QListWidget()
        words.setAccessibleName("Palabras aprendidas por este perfil")
        layout.addWidget(words)
        delete = QPushButton("Eliminar palabra")
        delete.clicked.connect(lambda: self.service.submit("delete",words.currentItem().text(),profile)
                               if words.currentItem() else None)
        layout.addWidget(delete)
        clear = QPushButton("Borrar todo el diccionario personal")
        def confirm():
            if QMessageBox.question(dialog,"Borrar diccionario","¿Borrar todas las palabras y combinaciones aprendidas?",
                                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
                self.service.submit("clear",token=profile)
        clear.clicked.connect(confirm)
        layout.addWidget(clear)
        close = QPushButton("Cerrar")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        def update(owner,entries):
            if owner==profile:
                words.clear()
                words.addItems(entries)
        self.service.vocabulary.connect(update,Qt.ConnectionType.QueuedConnection)
        self.service.submit("list",token=profile)
        try:
            dialog.exec()
        finally:
            self.service.vocabulary.disconnect(update)
            dialog.deleteLater()
