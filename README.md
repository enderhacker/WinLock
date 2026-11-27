# WinLock v0.8 para Windows

WinLock usa la pantalla de bloqueo de Windows y solicita que el equipo no entre en suspensión automática mientras la sesión está bloqueada. Al volver, inicia sesión con tu PIN, contraseña o Windows Hello. WinLock libera su solicitud de energía al desbloquear o cerrar la aplicación. No necesita permisos de administrador ni cierra programas.

Esta solicitud no impide que la pantalla se apague, que se suspenda manualmente el equipo ni que Windows aplique sus políticas de energía. WinLock ya no utiliza una contraseña temporal ni admite notas en la pantalla de bloqueo.

La comprobación de versiones no bloquea el inicio. **Ver descargas oficiales** abre el [sitio de WinLock](https://winlock.labdigital.es/), que enlaza al ejecutable publicado. Puedes descargarlo en otro directorio y probarlo antes de sustituir tu copia. WinLock nunca descarga ni sustituye el ejecutable por sí solo.

## Ejecutar desde el código fuente

En Windows, usa CPython 3.14 de 64 bits con Tcl/Tk instalado. No se necesitan paquetes de Python adicionales:

```powershell
python main.py
```

Los registros están en `%LOCALAPPDATA%\WinLock\WinLock.log`.

## Compilar desde un clon limpio

1. Instala **CPython 3.14.7 de 64 bits** con Tcl/Tk y **Visual Studio 2022** o sus **Build Tools** con la carga de trabajo *Desarrollo para el escritorio con C++* y un Windows SDK.
2. Desde el directorio del repositorio:

   ```powershell
   py -3.14 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
   .\compilenew.cmd
   ```

   Si el lanzador `py` selecciona otro parche de Python, crea el entorno con el `python.exe` de la instalación 3.14.7. Nuitka puede descargar herramientas auxiliares en la primera compilación. El script no instala herramientas del sistema ni solicita elevación.

3. El ejecutable queda en `dist\WinLock.exe`. Si falla la compilación o Windows impide reemplazar un ejecutable en uso, la copia anterior queda intacta.

## Publicar una versión

Actualiza `LOCAL_VERSION` en `main.py`, el título de este README y la insignia `navVersion` de la web. Ejecuta `python -m scripts.release pending-version` para comprobar qué versión se publicará y sube los cambios a `main`.

Si esa versión supera la de `version.json`, GitHub Actions ejecuta las pruebas, compila `WinLock.exe` y guarda `downloads/<versión>/WinLock.exe` y el manifiesto actualizado en un mismo commit en `main`. El sitio web y las versiones anteriores leen `version.json` para encontrar la descarga. Los ejecutables nuevos se publican en `main`; la pestaña Releases de GitHub requiere una etiqueta.

El repositorio debe permitir que `GITHUB_TOKEN` escriba en `main`. Para volver a comprobar o publicar una versión pendiente sin otro commit, ejecuta **Publish WinLock** desde la pestaña Actions con la rama `main`.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

Las pruebas no bloquean Windows ni cambian su configuración de energía. Para una prueba manual, bloquea desde una sesión de Windows 10 u 11, comprueba que sigue en marcha una tarea de fondo y que puedes desbloquear con tus credenciales habituales. Repite sin conexión para comprobar que el aviso de actualización no impide bloquear.
