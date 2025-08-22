# Changelog
Todos los cambios notables de este proyecto.

## [1.0.0] - 2025-08-18
### Added
- Panel con botones “Cargar CartoMinMex” y “Comprobar/Actualizar”.
- Registro automático de conexión al servicio SE/DGM.

### Changed
- (Cuando migres) `urllib` → `QgsNetworkAccessManager` para respetar proxy de QGIS.

### Fixed
- Manejo de errores y logs en `%APPDATA%/QGIS/.../plugins_logs`.

[1.1.0] - 2025-08-22
### Added
- Interfaz como ventana modal (popup) al abrir el plugin.
- Botón “Acerca de” que abre la ayuda local (help/index-es.html).

Changed
- Apertura de ayuda vía QDesktopServices; fallback a index.html.

Fixed
- Rutas de ayuda que no abrían en algunas instalaciones.
