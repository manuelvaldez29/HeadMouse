Option Explicit
Dim files, folder, python, shell
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
If Not files.FileExists(python) Then
  MsgBox "Falta preparar HeadMouse. Consulte la seccion Instalacion del README.", 48, "HeadMouse"
  WScript.Quit 1
End If
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = folder
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & files.BuildPath(folder, "app.py") & Chr(34), 0, False
