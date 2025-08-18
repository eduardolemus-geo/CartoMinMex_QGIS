# -*- coding: utf-8 -*-
# CartoMinMex_QGIS — QGIS plugin
# Copyright (C) 2025 Eduardo Lemus
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Este archivo es parte de CartoMinMex_QGIS.
# Se distribuye bajo los términos de la GNU General Public License,
# versión 3 o posterior. ESTE PROGRAMA SE ENTREGA "TAL CUAL", SIN
# GARANTÍA; consulta el archivo LICENSE para más detalles.
# Copia de la licencia: archivo LICENSE incluido en el paquete
# y https://www.gnu.org/licenses/gpl-3.0.en.html

__author__ = "Eduardo Lemus"
__email__ = "eduardo.lemusm@fi.unam.edu"
__license__ = "GPL-3.0-or-later"
__version__ = "1.0.0"

import re, json, os, datetime, traceback
from qgis.PyQt.QtWidgets import QAction, QWidget, QVBoxLayout, QPushButton, QLabel, QDockWidget
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt
from qgis.core import Qgis, QgsMessageLog, QgsSettings, QgsVectorLayer, QgsProject, QgsApplication, QgsDataSourceUri
from qgis.utils import iface
from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
from qgis.PyQt.QtNetwork import QNetworkRequest, QNetworkReply
from qgis.core import QgsNetworkAccessManager
from qgis.utils import showPluginHelp

CATALOGO = "https://serverags1.economia.gob.mx/arcgis/rest/services"
NOMBRE_CONEXION = "SE_Concesiones_Vigentes"
QGIS_CONN_MAPSERVER = "qgis/connections-arcgismapserver/{}/url"
QGIS_CONN_FEATURESERVER = "qgis/connections-arcgisfeatureserver/{}/url"

SETTINGS_NS      = "cartominmex_qgis"
KEY_SERVICE_URL  = f"{SETTINGS_NS}/service_url"
KEY_LAST_SUFFIX  = f"{SETTINGS_NS}/last_suffix"

def _icon_path():
    return os.path.join(os.path.dirname(__file__), "icon.png")

def _msg(txt, level=Qgis.Info, dur=6):
    try:
        iface.messageBar().pushMessage("CartoMinMex", txt, level=level, duration=dur)
    except Exception:
        QgsMessageLog.logMessage(txt, "CartoMinMex", level)

def _logfile_path():
    try:
        base = QgsApplication.qgisSettingsDirPath()
    except Exception:
        base = os.path.expanduser("~")
    logdir = os.path.join(base, "plugins_logs")
    os.makedirs(logdir, exist_ok=True)
    return os.path.join(logdir, "cartominmex_qgis.log")

def _log(text, exc=None):
    try:
        with open(_logfile_path(), "a", encoding="utf-8") as f:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{ts}] {text}\n")
            if exc:
                f.write("TRACE:\n" + "".join(traceback.format_exception(None, exc, exc.__traceback__)) + "\n")
    except Exception:
        pass

def _get_json(url, timeout_ms=20000):
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
        _log(f"Servicio reciente: {best}")
        return best
    except Exception as e:
        _log("Catálogo falló", e)
        return None

def _current_suffix(service_url):
    try:
        js = _get_json(service_url.rstrip('/') + "/legend?f=pjson")
        layers = js.get("layers", [])
        if not layers:
            return ""
        layer_name = layers[0].get("layerName", "")
        m = re.search(r"_(\d{6})$", layer_name)
        return m.group(1) if m else ""
    except Exception as e:
        _log("Legend falló", e)
        return ""

def _write_connections(name, service_url):
    s = QgsSettings()
    s.setValue(QGIS_CONN_MAPSERVER.format(name), service_url)
    s.setValue(QGIS_CONN_FEATURESERVER.format(name), service_url)

def _build_featureserver_uri(service_url, target_crs="EPSG:4326", layer_id="0"):
    uri = QgsDataSourceUri()
    uri.setParam("url", service_url.rstrip("/") + "/" + str(layer_id))
    if target_crs:
        uri.setParam("crs", target_crs)
    return uri.uri()

def _load_layer(service_url):
    uri = _build_featureserver_uri(service_url, "EPSG:4326", "0")
    vlyr = QgsVectorLayer(uri, "CartoMinMex — Concesiones SE/DGM", "arcgisfeatureserver")
    if not vlyr.isValid():
        return False
    QgsProject.instance().addMapLayer(vlyr)
    root = QgsProject.instance().layerTreeRoot()
    node = root.findLayer(vlyr.id())
    if node:
        node.setItemVisibilityChecked(True)
        root.insertChildNode(0, node.clone())
        root.removeChildNode(node)
    return True

class CartoMinMexDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("CartoMinMex_QGIS", parent)
        self.setObjectName("CartoMinMexDock")
        w = QWidget(self)
        lay = QVBoxLayout(w)
        self.lblServicio = JLabelOrNone("Servicio: (no registrado)")
        self.lblCorte = JLabelOrNone("Corte: —")
        self.btnLoad = QPushButton("Cargar CartoMinMex")
        self.btnCheck = QPushButton("Comprobar/Actualizar")
        for wi in (self.lblServicio, self.lblCorte, self.btnLoad, self.btnCheck):
            lay.addWidget(wi)
        lay.addStretch()
        self.setWidget(w)

def JLabelOrNone(text):
    try:
        return QLabel(text)
    except Exception:
        return QLabel()

class CartoMinMexPlugin:
    def __init__(self, iface_):
        self.iface = iface_
        self.action_open = None
        self.help_action = None
        self.dock = None

    def initGui(self):
        self.action_open = QAction(QIcon(_icon_path()), "CartoMinMex_QGIS", self.iface.mainWindow())
        self.action_open.triggered.connect(self._show_dock)
        self.iface.addPluginToMenu("Web", self.action_open)
        self.iface.addToolBarIcon(self.action_open)

        # ---- Ayuda en Help ▸ Plugin Help
        self.help_action = QAction("Ayuda de CartoMinMex", self.iface.mainWindow())
        self.help_action.triggered.connect(lambda: showPluginHelp(filename="help/index"))
        if self.iface.pluginHelpMenu():
            self.iface.pluginHelpMenu().addAction(self.help_action)

    def unload(self):
        try:
            if self.dock:
                self.iface.removeDockWidget(self.dock)
                self.dock = None
            self.iface.removePluginMenu("Web", self.action_open)
            self.iface.removeToolBarIcon(self.action_open)
            if self.help_action and self.iface.pluginHelpMenu():
                self.iface.pluginHelpMenu().removeAction(self.help_action)
        except Exception:
            pass

    def _show_dock(self):
        try:
            if self.dock is None:
                self.dock = CartoMinMexDock(self.iface.mainWindow())
                self.dock.btnLoad.clicked.connect(self.load_cartominmex)
                self.dock.btnCheck.clicked.connect(self.check_update)
                self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
            self._refresh_labels()
            self.dock.show()
            self.dock.raise_()
        except Exception as e:
            _log("Abrir dock falló", e)
            _msg("Error", Qgis.Critical, 6)

    def _refresh_labels(self):
        s = QgsSettings()
        url = s.value(KEY_SERVICE_URL, "", type=str)
        if not url:
            self.dock.lblServicio.setText("Servicio: (no registrado)")
            self.dock.lblCorte.setText("Corte: —")
        else:
            self.dock.lblServicio.setText(f"Servicio: {url}")
            self.dock.lblCorte.setText(f"Corte: {s.value(KEY_LAST_SUFFIX, '', type=str) or '—'}")

    def _ensure_registered(self, latest_url):
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
            _msg("Conexión registrada al último servicio.", Qgis.Success, 6)
            return latest_url, suffix, True
        else:
            return current, s.value(KEY_LAST_SUFFIX, "", type=str), False

    def _discover_updates(self, current_url):
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
        try:
            latest = _latest_concesiones_service()
            current_url, _, _ = self._ensure_registered(latest)
            final_url, new_suffix, status = self._discover_updates(current_url)
            s = QgsSettings()
            if status == "service-updated":
                _write_connections(NOMBRE_CONEXION, final_url)
                s.setValue(KEY_SERVICE_URL, final_url)
                s.setValue(KEY_LAST_SUFFIX, new_suffix)
                _msg("Servicio actualizado a la versión más reciente.", Qgis.Success, 8)
            elif status == "cut-updated":
                s.setValue(KEY_LAST_SUFFIX, new_suffix)
                _msg("Nuevo corte detectado; datos actualizados.", Qgis.Success, 8)
            else:
                _msg("Sin cambios: se usa el corte vigente.", Qgis.Info, 6)
            if self.dock:
                self._refresh_labels()
        except Exception as e:
            _log("check_update excepción", e)
            _msg("Error", Qgis.Critical, 6)

    def load_cartominmex(self):
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
            suf = _current_suffix(current_url)
            if not suf:
                latest = _latest_concesiones_service()
                if latest and latest != current_url:
                    _write_connections(NOMBRE_CONEXION, latest)
                    s.setValue(KEY_SERVICE_URL, latest)
                    s.setValue(KEY_LAST_SUFFIX, _current_suffix(latest))
                    current_url = latest
            if _load_layer(current_url):
                _msg("CartoMinMex cargado y activo.", Qgis.Success, 6)
            else:
                raise RuntimeError("load failed")
            if self.dock:
                self._refresh_labels()
        except Exception as e:
            _log("load_cartominmex excepción", e)
            _msg("Error", Qgis.Critical, 6)
