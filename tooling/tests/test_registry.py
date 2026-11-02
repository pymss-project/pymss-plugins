from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tooling.scripts.generate_registry import ROOT, render_registry
from tooling.scripts.studio_requirements import studio_requirements


class PluginRegistryTests(unittest.TestCase):
    def test_catalog_is_generated_from_package_metadata(self):
        self.assertEqual(render_registry(), json.loads((ROOT / "registry.json").read_text(encoding="utf-8")))
        self.assertNotIn("audio_gain", render_registry())

    def test_release_catalog_requires_an_immutable_source(self):
        with self.assertRaisesRegex(ValueError, "immutable commit"):
            render_registry(release=True)
        commit = "a" * 40
        catalog = render_registry(ref=commit, release=True)
        self.assertTrue(all(row["ref"] == commit for name, row in catalog.items() if not name.startswith("_")))

    def test_each_plugin_owns_its_backend_and_ui_sources(self):
        self.assertFalse((ROOT / "tool_runtime").exists())
        for project in (ROOT / "plugins").glob("*/pyproject.toml"):
            with self.subTest(plugin=project.parent.name):
                self.assertFalse((project.parent / "_tool").exists())
                self.assertTrue((project.parent / "ui/src").is_dir())
                self.assertTrue((project.parent / "ui/dist/index.html").is_file())

    def test_invalid_metadata_does_not_silently_disappear_from_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "tooling").mkdir()
            (root / "tooling/catalog.toml").write_text((ROOT / "tooling/catalog.toml").read_text())
            plugin = root / "plugins/example"
            plugin.mkdir(parents=True)
            (plugin / "pyproject.toml").write_text('''
[project]
version = "1.0.0"
[tool.pymss.plugin]
id = "example.plugin"
[tool.pymss.studio]
category = "invalid"
''')
            with self.assertRaisesRegex(ValueError, "category"):
                render_registry(root)

    def _catalog_root(self, temporary: str, plugins: dict[str, str]) -> Path:
        root = Path(temporary)
        (root / "tooling").mkdir()
        (root / "tooling/catalog.toml").write_text((ROOT / "tooling/catalog.toml").read_text(encoding="utf-8"), encoding="utf-8")
        for name, manifest in plugins.items():
            (root / "plugins" / name).mkdir(parents=True)
            (root / "plugins" / name / "pyproject.toml").write_text(manifest, encoding="utf-8")
        return root

    def test_provider_plugin_without_studio_metadata_is_listed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._catalog_root(temporary, {"provider": '''
[project]
version = "1.0.0"
description = "Example model provider"
keywords = ["provider", "models"]
[tool.pymss.plugin]
id = "example.provider"
api_version = 2
[[tool.pymss.plugin.providers]]
id = "example.provider.models"
'''})
            row = render_registry(root)["example.provider"]
            self.assertEqual(row["operations"], [])
            self.assertEqual(row["description"], "Example model provider")
            self.assertEqual(row["tags"], ["provider", "models"])
            self.assertIsNone(row["category"])
            self.assertEqual(row["locales"], {})
            self.assertEqual(row["requirements"], studio_requirements({}))
            # A pure provider has no operation descriptions to snapshot.
            self.assertEqual(render_registry(root, ref="a" * 40, release=True)["example.provider"]["ref"], "a" * 40)

    def test_release_still_requires_snapshots_for_declared_operations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._catalog_root(temporary, {"operation": '''
[project]
version = "1.0.0"
[tool.pymss.plugin]
id = "example.operation"
api_version = 2
[[tool.pymss.plugin.operations]]
id = "example.operation.run"
'''})
            self.assertEqual(render_registry(root)["example.operation"]["operations"], ["example.operation.run"])
            with self.assertRaisesRegex(ValueError, "snapshot"):
                render_registry(root, ref="a" * 40, release=True)

    def test_studio_category_is_optional_but_views_keep_sdk_checks(self):
        manifest = '''
[project]
version = "1.0.0"
[tool.pymss.plugin]
id = "example.studio"
api_version = 2
[tool.pymss.studio]
sdk_version = 1
'''
        with tempfile.TemporaryDirectory() as temporary:
            row = render_registry(self._catalog_root(temporary, {"studio": manifest}))["example.studio"]
            self.assertIsNone(row["category"])
            self.assertEqual(row["requirements"]["sdkVersion"], 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = self._catalog_root(temporary, {"studio": manifest.replace("sdk_version = 1", '[[tool.pymss.studio.views]]\nid = "tool"')})
            with self.assertRaisesRegex(ValueError, "sdk_version"):
                render_registry(root)

    def test_plugins_without_studio_keep_manifest_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self._catalog_root(temporary, {"provider": '''
[project]
version = "1.0.0"
[tool.pymss.plugin]
id = "example.provider"
api_version = 1
'''})
            with self.assertRaisesRegex(ValueError, "api_version 2"):
                render_registry(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = self._catalog_root(temporary, {"provider": '''
[project]
version = "1.0.0"
keywords = "provider"
[tool.pymss.plugin]
id = "example.provider"
api_version = 2
'''})
            with self.assertRaisesRegex(ValueError, "tags"):
                render_registry(root)
