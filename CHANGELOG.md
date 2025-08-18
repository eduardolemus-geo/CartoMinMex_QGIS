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
