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

from .cartominmex_qgis import CartoMinMexPlugin

def classFactory(iface):
    return CartoMinMexPlugin(iface)
