Set UAC = CreateObject("Shell.Application")
' Ejecuta como admin
UAC.ShellExecute "cmd.exe", "/k """"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"" && cd /d C:\Users\jaime.munniz.garcia_\Desktop\winlock && compilenew.cmd""", "", "runas", 1
