# -*- coding: utf-8 -*-
# CartoMinMex_QGIS — QGIS plugin
# Copyright (C) 2025 Eduardo Lemus
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This file is part of CartoMinMex_QGIS.
# It is distributed under the terms of the GNU General Public License,
# version 3 or later. THIS PROGRAM IS PROVIDED "AS IS", WITHOUT
# WARRANTY; see the LICENSE file for more details.

"""
CartoMinMex_QGIS: lightweight loader/updater for Mexico mining concessions.

Now opens as a modal dialog (popup) with three actions:
- Cargar CartoMinMex
- Comprobar/Actualizar
- Acerca de (opens packaged help HTML)

Key ideas:
- Discover the latest ArcGIS service under a known catalog.
- Store the chosen service URL and last “cut” (suffix) in QGIS settings.
- Keep UX simple: messages go to QGIS message bar and a minimal logfile.
"""

import re, json, os, datetime, traceback
from qgis.PyQt.QtWidgets import (
    QAction, QWidget, QVBoxLayout, QPushButton, QLabel, QDialog
)
from qgis.PyQt.QtGui import QIcon, QDesktopServices
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    Qgis, QgsMessageLog, QgsSettings, QgsVectorLayer, QgsProject,
    QgsApplication, QgsDataSourceUri
)
from qgis.utils import iface
from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
from qgis.PyQt.QtNetwork import QNetworkRequest, QNetworkReply
from qgis.core import QgsNetworkAccessManager
from qgis.utils import showPluginHelp

# ArcGIS Server catalog where services are listed.
CATALOGO = "https://serverags1.economia.gob.mx/arcgis/rest/services"

# Logical name used for QGIS ArcGIS connection entries.
NOMBRE_CONEXION = "SE_Concesiones_Vigentes"

# QGIS settings keys for ArcGIS connections (MapServer/FeatureServer).
QGIS_CONN_MAPSERVER = "qgis/connections-arcgismapserver/{}/url"
QGIS_CONN_FEATURESERVER = "qgis/connections-arcgisfeatureserver/{}/url"

# Plugin settings namespace and keys.
SETTINGS_NS      = "cartominmex_qgis"
KEY_SERVICE_URL  = f"{SETTINGS_NS}/service_url"   # last used/registered service URL
KEY_LAST_SUFFIX  = f"{SETTINGS_NS}/last_suffix"   # last detected “cut” suffix (yyyymm)

def _icon_path():
    """Return absolute path to the plugin icon."""
    return os.path.join(os.path.dirname(__file__), "icon.png")

def _msg(txt, level=Qgis.Info, dur=6):
    """
    Show a short-lived message in QGIS UI; fall back to message log.
    Keep messages terse and action-oriented (Info/Success/Critical).
    """
    try:
        iface.messageBar().pushMessage("CartoMinMex", txt, level=level, duration=dur)
    except Exception:
        QgsMessageLog.logMessage(txt, "CartoMinMex", level)

def _logfile_path():
    """
    Compute a writable log file path under the QGIS settings dir (user scope).
    Creates the directory if needed.
    """
    try:
        base = QgsApplication.qgisSettingsDirPath()
    except Exception:
        base = os.path.expanduser("~")
    logdir = os.path.join(base, "plugins_logs")
    os.makedirs(logdir, exist_ok=True)
    return os.path.join(logdir, "cartominmex_qgis.log")

def _log(text, exc=None):
    """
    Append a line to the plugin logfile. Include exception trace if provided.
    Never raise from logger; silent on IO errors.
    """
    try:
        with open(_logfile_path(), "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {text}\n")
            if exc:
                f.write("TRACE:\n" + "".join(traceback.format_exception(None, exc, exc.__traceback__)) + "\n")
    except Exception:
        pass

def _get_json(url, timeout_ms=20000):
    """
    Do a blocking GET with QGIS network manager and parse JSON.
    - Uses a small event loop with a single-shot timeout.
    - Raises IOError on network errors; callers handle/report.
    """
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b"User-Agent", b"QGIS-CartoMinMex/1.0.0")
    nam = QgsNetworkAccessManager.instance()
    reply = nam.get(req)
    loop = QEventLoop()
    reply.finished.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec_()
    if reply.error() != QNetworkReply.NoError:
        raise IOError(reply.errorString())
    data = bytes(reply.readAll()).decode("utf-8", "ignore")
    return json.loads(data)

def _latest_concesiones_service():
    """
    Inspect the catalog and pick the newest 'Concesiones_Mineras_Vigentes_YYYY' MapServer.
    Returns full MapServer URL or None on failure.
    """
    try:
        js = _get_json(CATALOGO + "?f=pjson")
        best = None
        best_year = -1
        for svc in js.get("services", []):
            name = svc.get("name", "")
            if name.startswith("Concesiones_Mineras_Vigentes_"):
                m = re.search(r"_(\d{4})$", name)
                if m:
                    y = int(m.group(1))
                    if y > best_year:
                        best_year = y
                        best = f"{CATALOGO}/{name}/MapServer"
        _log(f"Latest service: {best}")
        return best
    except Exception as e:
        _log("Catalog lookup failed", e)
        return None

def _current_suffix(service_url):
    """
    Query the service legend and try to extract a trailing yyyymm suffix
    from the first layer name. Returns '' if unavailable.
    """
    try:
        js = _get_json(service_url.rstrip('/') + "/legend?f=pjson")
        layers = js.get("layers", [])
        if not layers:
            return ""
        layer_name = layers[0].get("layerName", "")
        m = re.search(r"_(\d{6})$", layer_name)
        return m.group(1) if m else ""
    except Exception as e:
        _log("Legend request failed", e)
        return ""

def _write_connections(name, service_url):
    """
    Register both MapServer and FeatureServer URLs into QGIS connection settings.
    Keeps the same base URL for simplicity.
    """
    s = QgsSettings()
    s.setValue(QGIS_CONN_MAPSERVER.format(name), service_url)
    s.setValue(QGIS_CONN_FEATURESERVER.format(name), service_url)

def _build_featureserver_uri(service_url, target_crs="EPSG:4326", layer_id="0"):
    """
    Build a QgsDataSourceUri string for ArcGIS FeatureServer.
    - Defaults to layer 0 in WGS84.
    """
    uri = QgsDataSourceUri()
    uri.setParam("url", service_url.rstrip("/") + "/" + str(layer_id))
    if target_crs:
        uri.setParam("crs", target_crs)
    return uri.uri()

def _load_layer(service_url):
    """
    Load the FeatureServer layer into the current project and move it to top.
    Returns True on success, False otherwise.
    """
    uri = _build_featureserver_uri(service_url, "EPSG:4326", "0")
    vlyr = QgsVectorLayer(uri, "CartoMinMex — Concesiones SE/DGM", "arcgisfeatureserver")
    if not vlyr.isValid():
        return False
    QgsProject.instance().addMapLayer(vlyr)

    # Promote new layer to top of the layer tree (visible, checked).
    root = QgsProject.instance().layerTreeRoot()
    node = root.findLayer(vlyr.id())
    if node:
        node.setItemVisibilityChecked(True)
        root.insertChildNode(0, node.clone())
        root.removeChildNode(node)
    return True

class CartoMinMexDialog(QDialog):
    """Minimal modal dialog with current service/cut and three actions."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CartoMinMexDialog")
        self.setWindowTitle("CartoMinMex_QGIS")
        self.setWindowIcon(QIcon(_icon_path()))
        self.setWindowModality(Qt.ApplicationModal)

        w = QWidget(self)
        lay = QVBoxLayout(w)

        self.lblServicio = JLabelOrNone("Servicio: (not registered)")
        self.lblCorte    = JLabelOrNone("Cut: —")

        self.btnLoad  = QPushButton("Cargar CartoMinMex")
        self.btnCheck = QPushButton("Comprobar/Actualizar")
        self.btnAbout = QPushButton("Acerca de")

        for wi in (self.lblServicio, self.lblCorte, self.btnLoad, self.btnCheck, self.btnAbout):
            lay.addWidget(wi)
        lay.addStretch()

        self.setLayout(lay)

def JLabelOrNone(text):
    """Create a QLabel safely; fallback path avoids crashes on rare UI issues."""
    try:
        return QLabel(text)
    except Exception:
        return QLabel()

class CartoMinMexPlugin:
    """QGIS plugin entry point: wires actions, dialog, and update/load logic."""
    def __init__(self, iface_):
        self.iface = iface_
        self.action_open = None
        self.help_action = None
        self.dlg = None

    def initGui(self):
        """
        Add toolbar/menu action to open the modal dialog.
        Also register a Help action under the Plugin Help menu.
        """
        self.action_open = QAction(QIcon(_icon_path()), "CartoMinMex_QGIS", self.iface.mainWindow())
        self.action_open.triggered.connect(self._show_dialog)
        self.iface.addPluginToMenu("Web", self.action_open)
        self.iface.addToolBarIcon(self.action_open)

        # Help entry under Help ▸ Plugin Help (opens packaged help/index.html).
        self.help_action = QAction("Ayuda de CartoMinMex", self.iface.mainWindow())
        self.help_action.triggered.connect(lambda: showPluginHelp())
        if self.iface.pluginHelpMenu():
            self.iface.pluginHelpMenu().addAction(self.help_action)

    def unload(self):
        """Cleanly remove actions when the plugin is unloaded."""
        try:
            if self.dlg:
                self.dlg.close()
                self.dlg = None
            self.iface.removePluginMenu("Web", self.action_open)
            self.iface.removeToolBarIcon(self.action_open)
            if self.help_action and self.iface.pluginHelpMenu():
                self.iface.pluginHelpMenu().removeAction(self.help_action)
        except Exception:
            # Never fail during unload.
            pass

    def _open_help_in_browser(self):
        """Construye la ruta al archivo de ayuda y lo abre en el navegador."""
        try:
            # Obtiene el directorio donde se encuentra el plugin
            plugin_dir = os.path.dirname(__file__)
            # Construye la ruta completa al archivo HTML
            help_file_path = os.path.join(plugin_dir, "help", "index.html")

            if os.path.exists(help_file_path):
                # Abre el archivo en el navegador web predeterminado
                QDesktopServices.openUrl(QUrl.fromLocalFile(help_file_path))
            else:
                _msg("No se encontró el archivo de ayuda.", level=Qgis.Critical)
        except Exception as e:
            _log("Fallo al abrir el archivo de ayuda", e)
            _msg("Error al intentar abrir la ayuda.", level=Qgis.Critical)

    def _ensure_dialog(self):
        """Create the dialog lazily and wire up buttons."""
        if self.dlg is None:
            self.dlg = CartoMinMexDialog(self.iface.mainWindow())
            self.dlg.btnLoad.clicked.connect(self.load_cartominmex)
            self.dlg.btnCheck.clicked.connect(self.check_update)
            self.dlg.btnAbout.clicked.connect(self._open_help_in_browser)

    def _show_dialog(self):
        """
        Bring up the modal dialog. Refresh labels before showing.
        Uses exec_() for true modal behavior.
        """
        try:
            self._ensure_dialog()
            self._refresh_labels()
            self.dlg.exec_()
        except Exception as e:
            _log("Dialog open failed", e)
            _msg("Error", Qgis.Critical, 6)

    def _refresh_labels(self):
        """Update dialog labels from persisted settings."""
        if not self.dlg:
            return
        s = QgsSettings()
        url = s.value(KEY_SERVICE_URL, "", type=str)
        if not url:
            self.dlg.lblServicio.setText("Servicio: (not registered)")
            self.dlg.lblCorte.setText("Cut: —")
        else:
            self.dlg.lblServicio.setText(f"Servicio: {url}")
            self.dlg.lblCorte.setText(f"Cut: {s.value(KEY_LAST_SUFFIX, '', type=str) or '—'}")

    def _ensure_registered(self, latest_url):
        """
        Ensure there is a valid registered service:
        - If current is invalid/missing, register the latest and store suffix.
        - Return (url, suffix, did_register_bool).
        """
        s = QgsSettings()
        current = s.value(KEY_SERVICE_URL, "", type=str)
        if current and not _current_suffix(current):
            current = ""
        if not current:
            if not latest_url:
                raise RuntimeError("no service")
            _write_connections(NOMBRE_CONEXION, latest_url)
            s.setValue(KEY_SERVICE_URL, latest_url)
            suffix = _current_suffix(latest_url)
            s.setValue(KEY_LAST_SUFFIX, suffix)
            _msg("Connection registered to the latest service.", Qgis.Success, 6)
            return latest_url, suffix, True
        else:
            return current, s.value(KEY_LAST_SUFFIX, "", type=str), False

    def _discover_updates(self, current_url):
        """
        Compare current vs latest service and cut:
        - If a newer service exists, mark as 'service-updated'.
        - Else, if cut changed, mark as 'cut-updated'.
        - Else 'no-change'.
        Returns (url_to_use, new_suffix, status_string).
        """
        latest_url = _latest_concesiones_service()
        if latest_url and latest_url != current_url:
            return latest_url, _current_suffix(latest_url), "service-updated"
        new_suffix = _current_suffix(current_url) if current_url else ""
        s = QgsSettings()
        old_suffix = s.value(KEY_LAST_SUFFIX, "", type=str)
        if new_suffix and new_suffix != old_suffix:
            return current_url, new_suffix, "cut-updated"
        return current_url, new_suffix, "no-change"

    def check_update(self):
        """
        Main update workflow:
        - Ensure a registered service exists.
        - Detect service/cut changes and persist updates.
        - Refresh dialog labels and notify the user.
        """
        try:
            latest = _latest_concesiones_service()
            current_url, _, _ = self._ensure_registered(latest)
            final_url, new_suffix, status = self._discover_updates(current_url)
            s = QgsSettings()
            if status == "service-updated":
                _write_connections(NOMBRE_CONEXION, final_url)
                s.setValue(KEY_SERVICE_URL, final_url)
                s.setValue(KEY_LAST_SUFFIX, new_suffix)
                _msg("Service updated to the most recent version.", Qgis.Success, 8)
            elif status == "cut-updated":
                s.setValue(KEY_LAST_SUFFIX, new_suffix)
                _msg("New cut detected; data updated.", Qgis.Success, 8)
            else:
                _msg("No changes: using the current cut.", Qgis.Info, 6)
            self._refresh_labels()
        except Exception as e:
            _log("check_update exception", e)
            _msg("Error", Qgis.Critical, 6)

    def load_cartominmex(self):
        """
        Load the active layer:
        - Register latest service if none stored.
        - Heal stale cuts by switching to the latest service if needed.
        - Add FeatureServer layer to the project and surface to top.
        """
        try:
            s = QgsSettings()
            current_url = s.value(KEY_SERVICE_URL, "", type=str)
            if not current_url:
                latest = _latest_concesiones_service()
                if not latest:
                    raise RuntimeError("no service")
                _write_connections(NOMBRE_CONEXION, latest)
                s.setValue(KEY_SERVICE_URL, latest)
                s.setValue(KEY_LAST_SUFFIX, _current_suffix(latest))
                current_url = latest

            # If stored service looks stale (no suffix), try switching to latest.
            suf = _current_suffix(current_url)
            if not suf:
                latest = _latest_concesiones_service()
                if latest and latest != current_url:
                    _write_connections(NOMBRE_CONEXION, latest)
                    s.setValue(KEY_SERVICE_URL, latest)
                    s.setValue(KEY_LAST_SUFFIX, _current_suffix(latest))
                    current_url = latest

            if _load_layer(current_url):
                _msg("CartoMinMex loaded and active.", Qgis.Success, 6)
            else:
                raise RuntimeError("load failed")

            self._refresh_labels()
        except Exception as e:
            _log("load_cartominmex exception", e)
            _msg("Error", Qgis.Critical, 6)
