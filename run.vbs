' Silent launcher for PyMOL Flow (suppresses console black window)
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = currentDir
WshShell.Run chr(34) & currentDir & "\run.bat" & chr(34), 0, False
Set WshShell = Nothing
