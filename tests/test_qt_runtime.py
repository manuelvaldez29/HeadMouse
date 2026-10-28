"""Regresión de plugins macOS ocultos; no cámara ni backend de entrada."""
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from desktop.qt_runtime import prepare_qt_platform_plugins


class QtRuntimeTests(unittest.TestCase):
    def test_other_platform_does_not_change_environment(self):
        with patch('desktop.qt_runtime.sys.platform','win32'), patch.dict(os.environ):
            before=dict(os.environ)
            self.assertIsNone(prepare_qt_platform_plugins())
            self.assertEqual(dict(os.environ),before)

    def test_explicit_plugin_path_is_respected(self):
        with patch('desktop.qt_runtime.sys.platform','darwin'), patch.dict(os.environ,QT_QPA_PLATFORM_PLUGIN_PATH='/custom/plugins'):
            self.assertIsNone(prepare_qt_platform_plugins())
            self.assertEqual(os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'],'/custom/plugins')

    @unittest.skipUnless(sys.platform=='darwin','UF_HIDDEN requiere macOS')
    def test_hidden_plugins_are_copied_visible_without_altering_originals(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ):
            from PySide6.QtCore import QLibraryInfo
            os.environ.pop('QT_QPA_PLATFORM_PLUGIN_PATH',None)
            source=Path(root)/'platforms';source.mkdir()
            plugin=source/'libqcocoa.dylib';plugin.write_bytes(b'synthetic plugin')
            os.chflags(plugin,stat.UF_HIDDEN)
            with patch.object(QLibraryInfo,'path',return_value=root):
                target=prepare_qt_platform_plugins()
            self.addCleanup(shutil.rmtree,target,ignore_errors=True)
            self.assertEqual((target/plugin.name).read_bytes(),plugin.read_bytes())
            self.assertFalse((target/plugin.name).stat().st_flags & stat.UF_HIDDEN)
            self.assertTrue(plugin.stat().st_flags & stat.UF_HIDDEN)
            self.assertEqual(os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'],str(target))
