# Inventario de HeadMouse para Windows

Base integrada `tesis-v0.2`, commit `9833bba`. La distribución 0.5.0 se construye sobre esa base y las modificaciones locales de empaquetado. El lock de Python 3.12 y el manifiesto de modelos fijan las versiones de compilación.

| Función | Código y recursos | Ejecución |
| --- | --- | --- |
| Nariz, Ojos y gestos | OpenCV, MediaPipe Face Landmarker, NumPy, `vision_engine`, `tracking`, `gaze_*`, `gesture_*` | Cámara, CPU, sin red |
| Calibración, validación y control | `calibration_*`, `adaptive_calibration`, `ocular_profiles`, `control_engine`, PyAutoGUI | Calibraciones y bancos de gestos por método y perfil. Filtrado de fijaciones, recentrado, arrastre por guiño, labios para scroll, cejas y besito opcional |
| Escritorio | PySide6, tema QSS, iconos, ventanas auxiliares, UI Automation para dictado | Menú de perfiles, dos métodos, mini cámara y aviso de dictado |
| Perfiles, diagnóstico y experimentos | `profiles`, `user_storage`, `runtime_diagnostics`, `metrics`, `experiment_engine` | JSON y registros locales. Incluye análisis y exportación de sesiones |
| Bandeja e inicio | `desktop/resident.py`, `windows_session.py`, `single_instance.py`, `startup_preferences.py` | HKCU Run opcional, bloqueo de sesión, F8, exclusión entre instancias |
| Dictado y calibración de voz | `dictation.py`, `voice_calibration.py`, `speaker.py` | Micrófono, inferencia local, huella de voz por perfil y teclas en campo editable autorizado |

## Componentes y modelos

Los tamaños de modelos indican bytes de pesos sin comprimir. El inventario de compilación registra el tamaño de archivos de cada distribución instalada y sus dependencias declaradas.

| Dependencia o recurso | Versión | Función y requisitos nativos | Tamaño | Licencia / atribución | Instalador |
| --- | --- | --- | ---: | --- | --- |
| CPython | 3.12.6 x64 | Intérprete y DLL de runtime | Inventario de archivos | PSF | PyInstaller onedir |
| MediaPipe y Face Landmarker | 1.1.1, float16/1 | Inferencia y landmarks, LiteRT/XNNPACK | 3.758.596 modelo | Apache 2.0 para los modelos según sus fichas | `models/face_landmarker.task` |
| OpenCV contrib | 5.0.0.93 | Cámara DirectShow/MSMF y procesamiento | Inventario | Apache 2.0, avisos de componentes incluidos | DLL y bindings |
| NumPy | 2.5.4 | Señal ocular y audio | Inventario | BSD-3-Clause y avisos del wheel | PyInstaller |
| PySide6, shiboken6 y Qt | 6.12.0 | GUI, plugins Qt, IPC | Inventario | LGPLv3 y licencias de los componentes Qt | DLL separadas y plugins |
| PyAutoGUI | 0.9.54 | Cursor y acciones Win32 | Inventario | BSD-3-Clause | PyInstaller |
| faster-whisper / CTranslate2 | 1.2.1 / 4.8.2 | Transcripción en CPU int8, DLL de CTranslate2 | Inventario | MIT | Paquetes y binarios |
| Whisper tiny / base / small / medium | Revisiones en `model_sources.json` | Pesos multilingües, tokenizer, vocabulario y configuración | 75.538.270 / 145.217.532 / 483.546.902 / 1.527.906.378 | OpenAI y conversión de SYSTRAN, MIT | `models/whisper/<modelo>` |
| Silero VAD / ONNX Runtime | VAD v6 del wheel / 1.31.0 | Detección de habla por trama | Inventario | MIT | ONNX en faster-whisper y DLL |
| WeSpeaker ResNet34 VoxCeleb / sherpa-onnx | SHA-256 en manifiesto / 1.13.8 | Embedding de 256 valores, ONNX Runtime del wheel de sherpa | 26.534.365 modelo | Atribución a WeSpeaker y conversión de k2-fsa. CC BY 4.0 según documentación del modelo VoxCeleb y Apache 2.0 según la ficha del publicador | `models/speaker`, sherpa-onnx y sus DLL |
| sounddevice / PortAudio | 0.5.6 / DLL del wheel | Dispositivos de entrada y captura mono | Inventario | MIT / licencia PortAudio | DLL x64 y CFFI |
| comtypes | 1.4.17 | UIAutomationCore.dll y SendInput de Windows | Inventario | MIT | Python y API de Windows |
| PyAV / FFmpeg | 19.0.1 / bibliotecas del wheel | Import de faster-whisper y decodificación | Inventario | BSD-3-Clause / licencia de la compilación FFmpeg | Extensiones y DLL del wheel |
| Tokenizers, Hugging Face Hub y dependencias | Lock de compilación | Tokenización local y descarga gráfica para reparar recursos | Inventario | Metadatos y avisos del wheel | PyInstaller |
| Inno Setup / PyInstaller | 7.1.1 / 6.22.3 | Compilación del instalador y ejecutable | Herramientas de compilación | Licencia Inno / GPL con excepción del bootloader | Se usa el motor de instalación y el bootloader |

El uso normal de todos los modelos de la tabla es local. La conexión se usa al preparar el entorno de compilación o si se elige reparar un modelo faltante desde la interfaz. El audio de calibración y dictado se procesa en memoria. El perfil guarda métricas, revisión, modelo y huella opcional, y puede contener datos personales.

## Fuentes y licencias

- [Ficha y modelos de Face Landmarker de Google](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker)
- [Whisper original y licencia MIT](https://github.com/openai/whisper) y [conversión CTranslate2 de SYSTRAN](https://huggingface.co/Systran/faster-whisper-small).
- [Silero VAD](https://github.com/snakers4/silero-vad).
- [Modelos preentrenados de WeSpeaker](https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md), [ficha ResNet34](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34) y [exportación de k2-fsa](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models). Se conserva el ONNX de k2-fsa, sin cambios en los pesos.
- [Qt para Python](https://code.qt.io/cgit/pyside/pyside-setup.git/) y [fuentes de Qt](https://download.qt.io/official_releases/qt/). Las DLL de Qt se cargan dinámicamente y se entregan como archivos separados.
- [PyAV y fuentes de compilación](https://github.com/PyAV-Org/PyAV), [licencias de FFmpeg](https://ffmpeg.org/legal.html).

Los avisos originales de las ruedas se incluyen en `_internal/licenses`. Los modelos y sus revisiones se fijan en `packaging/model_sources.json`.
