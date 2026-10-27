# Plan de consolidación y distribución — no ejecutado

Las fases C/D quedan detrás del pilotaje y la autorización expresa del usuario.
Este archivo prepara decisiones y criterios de aceptación. No se ejecutaron
commits, push, merge, cambios de rama/default, instalación de compiladores,
empaquetado, migración de datos ni release.

## Historia Git observada localmente

Auditoría del 26/10/2026 sobre las referencias ya disponibles; no se hizo fetch.
El equipo puede haber actualizado el remoto después de esas referencias. Antes
de integrar será obligatorio refrescarlas y repetir el análisis.

```text
d4379d7  Pipeline inicial
├── 0e23862  main / origin/main / origin/HEAD
└── ... 13 commits exclusivos ...
    └── 32caef6  origin/tesis-v0.2
        └── b663fcc  experiment/eye-tracking / origin/experiment/eye-tracking
            + trabajo local sin commit de ambas continuaciones
```

- `git rev-list --left-right --count main...origin/tesis-v0.2`: **1 / 13**.
- `origin/tesis-v0.2...experiment/eye-tracking`: **0 / 1**.
- La rama `tesis-v0.2` no existe como rama local en este checkout; sí su referencia
  `origin/tesis-v0.2`. Su nombre no describe todo el contenido: incluye desktop,
  calibración adaptativa, dictado y otras funciones posteriores a la base.
- `git diff main origin/tesis-v0.2 --stat`: 101 archivos, 11.453 inserciones y 687
  eliminaciones. Este agregado no es un criterio de calidad, solo de magnitud.
- El commit exclusivo de main, `0e23862`, cambia el failsafe del loop de control:
  auto-pausa en lugar de detener. El trabajo actual detiene y revoca salida. No
  se debe reintroducir la política antigua automáticamente al mezclar historia.

Recomendación provisional: **`tesis-v0.2` como rama canónica**, conservando su
historia y promoviendo la implementación experimental aprobada. Mantener `main`
y el experimento como referencias históricas. Si más adelante se prefiere un
nombre sin versión, esa es otra decisión explícita: no renombrar ahora.

## Secuencia propuesta tras pilotaje y autorización

1. Registrar resultados físicos y revisión de diff; conservar respaldo y hashes
   del trabajo local y de los datos de usuario. Revisar archivos nuevos/ignorados
   para excluir datos personales, logs, `.venv`, modelos descargados y builds.
2. Actualizar referencias remotas sin tocar cambios locales, comparar HEADs y
   verificar trabajo nuevo del equipo. Rehacer merge-base, conteos y diff.
3. Revisar y guardar el trabajo autorizado en commits sobre el experimento,
   manteniendo su autoría real y mensajes que describan resultados/limitaciones.
   No publicar ni confirmar archivos indiscriminadamente con `git add -A`.
4. Preparar una rama de integración temporal, por ejemplo
   `codex/consolidate-headmouse`, solo si el usuario lo autoriza. Partir de la
   versión experimental revisada, integrar primero la última tesis si avanzó,
   luego la historia de main. Usar merges normales para preservar commits y
   autores. No usar reset, squash forzado, rebase publicado ni force-push.
5. Resolver conscientemente la política de failsafe en `control_engine.py`:
   conservar bloqueo/autorización/revocación y detener ante failsafe salvo que
   el equipo apruebe y pruebe otra política. Aunque Git no marque conflicto,
   existe un conflicto semántico. Revisar también requisitos, entrypoints,
   perfiles, rutas y documentación ante cambios remotos.
6. Ejecutar suite completa con código de salida del proceso, smoke nativo,
   arranque/cierre Qt y repetir el pilotaje de las siete condiciones (nariz y
   dos métodos × tres fuentes). Conservar incidentes nativos, no solo `OK`.
7. Revisar diff final y aprobar promoción. Si la historia lo permite, avanzar
   `tesis-v0.2` mediante fast-forward al candidato ya probado; de otro modo
   preparar el merge revisable correspondiente y volver a comprobarlo.
8. Publicar únicamente con autorización. Cambiar rama predeterminada de GitHub
   solo si el usuario lo pide/aprueba. Mantener main/experimento como referencias
   históricas sin borrarlos. Documentar que el desarrollo nuevo usa una sola
   rama canónica y dónde quedó la referencia del experimento aprobado.

No copiar la carpeta experimental encima de main: eso ocultaría diferencias y
autoría. No tratar el árbol local sin commit como si ya estuviera en GitHub.

## Arquitectura de distribución propuesta

Primera candidata: **PyInstaller onedir + Inno Setup**, sujeta a una construcción
real en la fase D. PyInstaller documenta la inclusión del intérprete y soporte de
distribución en carpeta; el usuario final no necesita instalar Python. El build
debe hacerse en Windows con arquitectura y Python fijados, como explica su
[documentación oficial](https://pyinstaller.org/en/stable/operating-mode.html).

Evaluar `pyside6-deploy`/Nuitka como alternativa mediante el mismo smoke y pruebas
de distribución, sin atribuirle menor tamaño, más velocidad ni mayor estabilidad
sin medirlos. Qt documenta esa herramienta en
[pyside6-deploy](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html).
Para empezar, onedir facilita inspeccionar DLL, plugins y modelo y evita el paso
de extracción temporal de onefile; es una decisión de diagnóstico, no un benchmark.

[Inno Setup](https://jrsoftware.org/isinfo.php) ofrece instalación sin privilegios
administrativos y desinstalador. Proponer instalación por usuario, acceso de
Inicio y acceso de escritorio opcional. Mantener AppId estable, versión de app
independiente del schema de perfil, arquitectura x64 explícita y actualización
que sustituya binarios sin tocar datos. No declarar firma digital: no hay
certificado ni instalador firmado en esta entrega.

### Separar recursos y datos ANTES de compilar

La implementación actual usa `config.ROOT` para recursos y varias carpetas de
datos; todavía no es adecuada para instalarse en una carpeta de solo lectura.
La fase D deberá introducir un resolver central, sin reemplazos masivos de rutas:

| Tipo | Destino propuesto |
|---|---|
| Recursos inmutables | Bundle: `desktop/theme.qss`, modelo `face_landmarker.task`, icono, avisos |
| Perfiles/configuración | `%LOCALAPPDATA%\HeadMouse\profiles\` y configuración de usuario |
| Métricas/experimentos/calibración | Subcarpetas de `%LOCALAPPDATA%\HeadMouse\` |
| Logs/backups de migración | `logs/` y `backups/` bajo esa carpeta |
| Modelos opcionales de voz | Caché editable de usuario, separados del modelo facial incluido |

Resolver recursos con `__file__`/mecanismo frozen apropiado según
[PyInstaller runtime information](https://pyinstaller.org/en/stable/runtime-information.html),
y datos mediante la carpeta de usuario. No usar cwd ni exigir `.git` al ejecutar.
Actualizar ProfileStore, ApplicationController, SessionMetrics, ResultStore,
dictation, entrypoints y diagnósticos con pruebas de rutas inyectadas.

Migración propuesta: detectar origen previo explícito, copiar a backup con hashes,
validar JSON, importar sin borrar el origen y sin sobrescribir IDs existentes.
Reportar conflictos y permitir al usuario elegir/renombrar. Registrar un marcador
de migración solo después de verificar lectura y escritura atómica del destino.
La actualización y desinstalación deben preservar datos; no agregar reglas de
desinstalador que eliminen LocalAppData. Probar falta de permisos y disco lleno.
No se ha ejecutado esta migración en la etapa A.

### Archivos de build a preparar en la fase D

- `packaging/headmouse.spec`: entrypoint `app.py`, onedir/windowed, imports
  dinámicos, binarios y recursos explícitos. Nunca recolectar el directorio del
  repositorio entero ni incluir `data/`, backups, perfiles o `.venv` como assets.
- `packaging/build.ps1`: entorno de build separado, versiones fijadas y
  comprobaciones sin desactivar seguridad; resultados y hashes en carpetas de
  build/dist ignoradas. Usar únicamente fuentes oficiales de herramientas.
- `packaging/headmouse.iss`: versión, AppId, usuario actual, icono propio .ico,
  inicio/desinstalación y acceso opcional. La distribución no usará HeadMouse.vbs
  ni dependerá de pythonw.exe instalado por el usuario.
- Manifest de versión/arquitectura, checksum del modelo y lista de componentes.
  Incluir y comprobar plugins Qt Windows, DLL de MediaPipe y bibliotecas nativas
  reales del entorno, OpenCV/NumPy/PyAutoGUI y recursos de estilo.
- Avisos de licencias generados desde los paquetes realmente distribuidos y el
  modelo exacto. Revisar condiciones de PySide6/Qt, MediaPipe/modelo, OpenCV,
  NumPy, PyAutoGUI y demás componentes; la revisión de redistribución queda
  pendiente, no se presupone una licencia única para el bundle entero.

No se generaron estos archivos todavía: el pedido establece primero validar
fuentes, después aprobar integración y luego preparar el instalador.

## Aceptación en Windows limpio (pendiente)

Usar VM/equipo Windows sin Python ni el repositorio; cámara disponible/passthrough
para las pruebas que la requieran. Registrar versión de Windows, DPI, usuario,
permisos, origen y hash del instalador. Comprobar cada paso y guardar resultados:

1. Instalar sin administrador; Inicio y acceso opcional funcionan.
2. Arrancar sin cwd privilegiado ni Git/Python; el modelo facial está incluido.
3. Cámara e inferencia, perfiles, siete condiciones de control y gestos.
4. Calibraciones/diagnóstico seguros, autorización, pausa, failsafe y parada.
5. Pérdida de cámara, fallos de modelo, cierre normal/repetido y logs accesibles.
6. Escritura solo en datos de usuario; nombres/rutas con espacios y acentos.
7. Actualizar conservando perfiles, seis bancos oculares, métricas y configuración.
8. Desinstalar/reinstalar conservando esos datos; sin borrar contenido personal.
9. Verificar avisos y firma real si posteriormente se decide firmar. No desactivar
   Defender/SmartScreen ni presentar una compilación no firmada como firmada.

Una compilación que abre en la PC de desarrollo no satisface esta aceptación.
No existe aún evidencia de instalación, exe autónomo o pruebas en Windows limpio.
