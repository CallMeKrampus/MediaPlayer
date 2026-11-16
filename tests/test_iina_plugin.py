import json
import os
import unittest
import zipfile


class TestIINAPlugin(unittest.TestCase):
    """
    Validates the structure, metadata, shader integrity, and packaging
    of the Dolby Vision Profile 5 to SDR Tonemapper IINA plugin.
    """

    @classmethod
    def setUpClass(cls):
        cls.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cls.plugin_dir = os.path.join(cls.repo_root, "plugins", "iina-plugin-dv-tonemap")
        cls.package_path = os.path.join(cls.repo_root, "plugins", "iina-plugin-dv-tonemap.iinaplgz")
        cls.mpv_script_dir = os.path.join(cls.repo_root, "plugins", "mpv-script")

    def test_01_info_json_validity(self):
        """Verify Info.json contains all required IINA plugin fields and permissions."""
        info_path = os.path.join(self.plugin_dir, "Info.json")
        self.assertTrue(os.path.isfile(info_path), "Info.json must exist")

        with open(info_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("name"), "Dolby Vision Tonemapper")
        self.assertEqual(data.get("identifier"), "io.iina.plugin.dv-tonemap")
        self.assertEqual(data.get("version"), "1.0.0")
        self.assertEqual(data.get("entry"), "main.js")
        self.assertEqual(data.get("preferencesPage"), "preferences.html")

        # Verify permissions
        permissions = data.get("permissions", [])
        self.assertIn("show-osd", permissions)
        self.assertIn("file-system", permissions)

        # Verify default preferences
        defaults = data.get("preferenceDefaults", {})
        self.assertTrue(defaults.get("enabled"))
        self.assertEqual(defaults.get("mode"), "auto")
        self.assertEqual(defaults.get("target"), "sdr")
        self.assertEqual(defaults.get("algorithm"), "clip")

    def test_02_main_js_logic_and_apis(self):
        """Verify main.js includes detection, property mapping, and IINA API hooks."""
        main_js_path = os.path.join(self.plugin_dir, "main.js")
        self.assertTrue(os.path.isfile(main_js_path), "main.js must exist")

        with open(main_js_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check required IINA modules
        for mod in ["core", "mpv", "event", "menu", "preferences", "file", "utils"]:
            self.assertIn(mod, content, f"Module '{mod}' should be referenced in main.js")

        # Check detection logic
        self.assertIn("video-params/colormatrix", content)
        self.assertIn("dvh1", content)
        self.assertIn("dvhe", content)
        self.assertIn("isDolbyVisionProfile5", content)

        # Check tonemapping properties
        self.assertIn("tone-mapping", content)
        self.assertIn("target-prim", content)
        self.assertIn("gamut-mapping-mode", content)
        self.assertIn("glsl-shaders", content)

        # Check event registration
        self.assertIn("iina.file-loaded", content)
        self.assertIn("mpv.video-params.changed", content)

    def test_03_preferences_html_bindings(self):
        """Verify preferences.html defines proper IINA data binding attributes."""
        pref_path = os.path.join(self.plugin_dir, "preferences.html")
        self.assertTrue(os.path.isfile(pref_path), "preferences.html must exist")

        with open(pref_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('data-pref-key="enabled"', content)
        self.assertIn('data-pref-key="mode"', content)
        self.assertIn('data-pref-key="target"', content)
        self.assertIn('data-pref-key="algorithm"', content)
        self.assertIn('data-pref-key="show_osd"', content)
        self.assertIn("IPTPQc2", content)

    def test_04_glsl_shader_math_and_hooks(self):
        """Verify the GLSL shader defines proper MPV hooks and colorspace matrices."""
        shader_path = os.path.join(self.plugin_dir, "shaders", "dolby_vision_p5.glsl")
        self.assertTrue(os.path.isfile(shader_path), "Shader file must exist")

        with open(shader_path, "r", encoding="utf-8") as f:
            glsl = f.read()

        # Hooks
        self.assertIn("//!HOOK MAIN", glsl)
        self.assertIn("//!BIND HOOKED", glsl)
        self.assertIn("vec4 hook()", glsl)

        # ST 2084 PQ coefficients
        self.assertIn("2610.0", glsl)
        self.assertIn("2523.0", glsl)
        self.assertIn("3424.0", glsl)

        # IPTPQc2 -> LMS matrix
        self.assertIn("0.097569", glsl)
        self.assertIn("0.133217", glsl)
        self.assertIn("0.676890", glsl)

        # LMS -> BT.2020 matrix
        self.assertIn("3.224645", glsl)
        self.assertIn("1.678015", glsl)

        # BT.2020 -> Rec.709 matrix
        self.assertIn("1.6605", glsl)
        self.assertIn("1.1329", glsl)
        self.assertIn("1.1187", glsl)

    def test_05_iinaplgz_archive_integrity(self):
        """Verify the .iinaplgz package is a valid zip archive with forward-slash paths."""
        self.assertTrue(os.path.isfile(self.package_path), "iina-plugin-dv-tonemap.iinaplgz must exist")

        with zipfile.ZipFile(self.package_path, "r") as zf:
            namelist = zf.namelist()
            self.assertIn("Info.json", namelist)
            self.assertIn("main.js", namelist)
            self.assertIn("preferences.html", namelist)
            self.assertIn("README.md", namelist)
            self.assertIn("shaders/dolby_vision_p5.glsl", namelist)

            # Ensure NO Windows backslashes in archive path names
            for name in namelist:
                self.assertNotIn("\\", name, f"Path '{name}' in zip should not contain backslashes")

    def test_06_standalone_mpv_lua_script(self):
        """Verify the standalone mpv Lua script fallback."""
        lua_path = os.path.join(self.mpv_script_dir, "dv_p5_tonemap.lua")
        self.assertTrue(os.path.isfile(lua_path), "Lua script must exist")

        with open(lua_path, "r", encoding="utf-8") as f:
            lua = f.read()

        self.assertIn("is_dv_p5", lua)
        self.assertIn("apply_dv_tonemap", lua)
        self.assertIn("restore_props", lua)
        self.assertIn("target-prim", lua)
        self.assertIn("bt.709", lua)


if __name__ == "__main__":
    unittest.main()
