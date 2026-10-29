"""Instancia única por directorio de datos; IPC local permite mostrar la existente."""
import hashlib
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtCore import QLockFile
from app_paths import data_root


class SingleInstance:
    def __init__(self,on_show,root=None):
        root=root or data_root();root.mkdir(parents=True,exist_ok=True)
        self.name="headmouse-"+hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]
        self.lock=QLockFile(str(root/"application.lock"));self.lock.setStaleLockTime(0)
        self.server=None
        if not self.lock.tryLock(0):
            socket=QLocalSocket();socket.connectToServer(self.name)
            if socket.waitForConnected(500):socket.write(b"show");socket.waitForBytesWritten(500);socket.disconnectFromServer()
            self.primary=False;return
        self.primary=True;QLocalServer.removeServer(self.name)
        self.server=QLocalServer();self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self.server.listen(self.name):
            self.lock.unlock();raise RuntimeError("No se pudo crear el canal local de HeadMouse")
        def connected():
            while self.server.hasPendingConnections():
                client=self.server.nextPendingConnection();client.close();client.deleteLater();on_show()
        self.server.newConnection.connect(connected)
    def close(self):
        if self.server:self.server.close()
        if self.primary:self.lock.unlock()
