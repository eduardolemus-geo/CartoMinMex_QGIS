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
Plugin bootstrap module.

Responsibilities:
- Expose `classFactory(iface)` as the QGIS entry point.
- Defer all heavy logic to the main plugin class to keep startup fast.
- Keep imports light and side effects minimal.
"""

# Import the main plugin class from the local package.
# Using a relative import avoids issues when the plugin is moved/packaged.
from .cartominmex_qgis import CartoMinMexPlugin


def classFactory(iface):
    """
    QGIS calls this to instantiate the plugin.

    Parameters
    ----------
    iface : qgis.gui.QgsInterface
        The QGIS interface object provided by the host application.

    Returns
    -------
    CartoMinMexPlugin
        A fully constructed plugin instance. Heavy initialization should be
        done inside the plugin's `initGui()` rather than here.
    """
    return CartoMinMexPlugin(iface)
