# Auditoría y plan v0.3

Se inspeccionaron todos los fuentes, tests, configuración y documentos de v0.2
antes de editar. Base: 33 tests aprobados; rama `tesis-v0.2`, con cambios de v0.2
sin commit que se conservan. Modelo local y entorno nativo ya preparados.

## Decisiones

- Mantener motores, fórmulas nasales, contratos legacy y scripts CLI.
- `ApplicationController` puro: dueño de perfil, sesión, estados, calibración,
  diagnóstico y experimentos. Widgets solo presentan snapshots y envían comandos.
- Adaptador Qt: QObject en QThread, comandos mediante señales encoladas y timer
  del worker. Captura continúa en VisionEngine. No bloquear interfaz con startup,
  joins, inferencia o persistencia. Snapshot de preview de capacidad uno.
- Control real solo tras confirmación, con revocación inmediata mediante Event,
  parada grande y atajo local F8/Escape. Sin importación PyAutoGUI al abrir.
- Perfiles borrador explícitos, nombre visible separado del ID estable. Renombrar
  el nombre no rompe resultados antiguos; eliminar requiere confirmación.
- Configuración extiende dataclasses existentes: sensibilidad X/Y opcional con
  fallback al valor legacy, UI y mapeos en settings del mismo perfil.
- ActionMapping reconoce identidad de gesto separada del nombre legacy de evento;
  conservar defaults y validar lista cerrada, sin macros.
- Wizard puro reutiliza Samples/build_calibration/CalibrationValidation.
- Experimentos y jitter puros: simulación dentro de ventana, JSONL local sin
  fotos. Guardar trayectoria de cursor y estadísticos; distinguir simulación y SO.
- Pruebas por etapa, regresiones v0.2 y tests Qt offscreen con hardware simulado;
  inspección visual de pantallas sintéticas, nunca afirmar validación física.

## Etapas / evidencia requerida

A auditoría y tests base; B controlador/estados; C ventana+preview; D CRUD perfiles;
E wizard y validación; F diagnóstico sin SO; G configuración persistente;
H mappings y acciones; I estrategia nasal idéntica; J adquisición+jitter+JSONL;
K métricas; L suite completa, smoke nativo/Qt, documentación y reporte.

Fuentes Qt consultadas: [QThread](https://doc.qt.io/qtforpython-6.10/PySide6/QtCore/QThread.html),
[thread affinity](https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-threads-qobject.html),
[QImage](https://doc.qt.io/qtforpython-6.10/PySide6/QtGui/QImage.html).
