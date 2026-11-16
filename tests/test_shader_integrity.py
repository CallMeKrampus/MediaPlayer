"""
Unit tests for the shader constant integrity monitor.

The log lines below are verbatim libmpv output captured while playing a
Dolby Vision Profile 20 file, from processes that rendered correctly and
from processes that rendered a flat purple / red frame.
"""

import unittest

from core.shader_integrity import (
    LIBPLACEBO_LOG_PREFIX,
    ShaderIntegrityMonitor,
    corrupted_variants,
)
from core.tonemap_engine import TonemapEngine

GLSL_PLANE_SCALE = "[ 25] const float _f = float(1.000962257385254); "
GLSL_PQ_SCALE = "[148] color.rgb *= float(49.261085510253906);"
GLSL_10BIT_SCALE = "[ 26] const float _8004 = float(64.06158447265625); "

HLSL_PLANE_GOOD = "[ 57]     float2 _270 = _268 * 1.00096225738525390625f;"
HLSL_PLANE_BAD_FRACTION = "[ 57]     float2 _270 = _268 * 0.00096225738525390625f;"
HLSL_PLANE_BAD_INTEGER = "[ 57]     float2 _270 = _268 * 962257354752.0f;"
HLSL_PQ_GOOD = "[126]     float3 _633 = _890.xyz * 49.26108551025390625f;"
HLSL_PQ_BAD_TWO_LOST = "[126]     float3 _633 = _890.xyz * 0.26108551025390625f;"
HLSL_PQ_BAD_ONE_LOST = "[126]     float3 _633 = _890.xyz * 9.26108551025390625f;"
HLSL_10BIT_BAD = "[ 47]     _818.x = (4.06158447265625f.xxxx * _34.SampleLevel(__34_sampler, _38, 0.0f)).x;"
HLSL_UNRELATED = (
    "[116]     float3 _1031 = mul(pow(max(_1202 - 0.8359375f.xxx, 0.0f.xxx) / "
    "(18.8515625f.xxx - (_1202 * 18.6875f)), 6.277394771575927734375f.xxx), _55);"
)


class TestCorruptedVariants(unittest.TestCase):
    def test_short_literals_are_never_tracked(self):
        self.assertEqual(corrupted_variants("0.5"), {})
        self.assertEqual(corrupted_variants("18.8515625"), {})
        self.assertEqual(corrupted_variants("0.001953125"), {})

    def test_long_literal_yields_observed_corruptions(self):
        variants = corrupted_variants("1.000962257385254")
        self.assertIn(0.00096225738525390625, variants)
        self.assertIn(962257354752.0, variants)

    def test_correct_value_is_not_a_variant(self):
        variants = corrupted_variants("49.261085510253906")
        self.assertNotIn(49.26108551025390625, variants)
        self.assertIn(0.26108551025390625, variants)
        self.assertIn(9.26108551025390625, variants)

    def test_variants_keep_enough_digits_to_be_unambiguous(self):
        # A long literal whose tail is tiny must not produce everyday constants
        variants = corrupted_variants("1.0000000000000002")
        self.assertNotIn(2.0, variants)
        self.assertNotIn(0.0, variants)


class TestShaderIntegrityMonitor(unittest.TestCase):
    def setUp(self):
        self.hits = []
        self.monitor = ShaderIntegrityMonitor(self.hits.append)

    def feed(self, *lines, prefix=LIBPLACEBO_LOG_PREFIX):
        for line in lines:
            self.monitor.feed("debug", prefix, line)

    def test_correct_compile_reports_nothing(self):
        self.feed(GLSL_PLANE_SCALE, GLSL_PQ_SCALE, HLSL_PLANE_GOOD, HLSL_PQ_GOOD, HLSL_UNRELATED)
        self.assertEqual(self.hits, [])
        self.assertEqual(self.monitor.miscompile_count, 0)

    def test_detects_dropped_integer_part(self):
        self.feed(GLSL_PLANE_SCALE, HLSL_PLANE_BAD_FRACTION)
        self.assertEqual(len(self.hits), 1)
        self.assertEqual(self.hits[0]["expected"], "1.000962257385254")
        self.assertEqual(self.hits[0]["compiled"], "0.00096225738525390625")

    def test_detects_dropped_decimal_point(self):
        self.feed(GLSL_PLANE_SCALE, HLSL_PLANE_BAD_INTEGER)
        self.assertEqual(len(self.hits), 1)
        self.assertEqual(self.hits[0]["compiled"], "962257354752.0")

    def test_detects_one_and_two_lost_digits(self):
        self.feed(GLSL_PQ_SCALE, HLSL_PQ_BAD_TWO_LOST, HLSL_PQ_BAD_ONE_LOST)
        self.assertEqual([h["compiled"] for h in self.hits],
                         ["0.26108551025390625", "9.26108551025390625"])

    def test_detects_software_decode_plane_scale(self):
        self.feed(GLSL_10BIT_SCALE, HLSL_10BIT_BAD)
        self.assertEqual(len(self.hits), 1)
        self.assertEqual(self.hits[0]["expected"], "64.06158447265625")

    def test_ignores_other_log_components_and_non_source_lines(self):
        self.feed(GLSL_PLANE_SCALE)
        self.feed(HLSL_PLANE_BAD_FRACTION, prefix="cplayer")
        self.feed("Spent 0.484 ms translating SPIR-V to HLSL", "")
        self.assertEqual(self.hits, [])

    def test_hlsl_without_matching_glsl_is_ignored(self):
        self.feed(HLSL_PLANE_BAD_FRACTION)
        self.assertEqual(self.hits, [])

    def test_literal_legitimately_present_in_glsl_is_not_reported(self):
        # If libplacebo itself emits the "corrupted" value, it is not corruption
        self.feed(GLSL_PQ_SCALE, "[ 12] const float _a = float(0.26108551025390625);", HLSL_PQ_BAD_TWO_LOST)
        self.assertEqual(self.hits, [])

    def test_reset_forgets_literals_and_bumps_generation(self):
        self.feed(GLSL_PLANE_SCALE)
        generation = self.monitor.generation
        self.monitor.reset()
        self.assertEqual(self.monitor.generation, generation + 1)
        self.feed(HLSL_PLANE_BAD_FRACTION)
        self.assertEqual(self.hits, [])

    def test_report_carries_generation(self):
        self.monitor.reset()
        self.feed(GLSL_PLANE_SCALE, HLSL_PLANE_BAD_FRACTION)
        self.assertEqual(self.hits[0]["generation"], self.monitor.generation)

    def test_callback_errors_do_not_propagate(self):
        def boom(_info):
            raise RuntimeError("consumer failed")
        monitor = ShaderIntegrityMonitor(boom)
        monitor.feed("debug", LIBPLACEBO_LOG_PREFIX, GLSL_PLANE_SCALE)
        monitor.feed("debug", LIBPLACEBO_LOG_PREFIX, HLSL_PLANE_BAD_FRACTION)
        self.assertEqual(monitor.miscompile_count, 1)


class TestCompileActivityTracking(unittest.TestCase):
    """The engine keeps the picture blanked until the shader compiler is idle."""

    def setUp(self):
        self.monitor = ShaderIntegrityMonitor()

    def feed(self, text):
        self.monitor.feed("debug", LIBPLACEBO_LOG_PREFIX, text)

    def test_idle_monitor_is_quiet(self):
        self.assertTrue(self.monitor.is_quiet(0.15))

    def test_not_quiet_while_a_compile_is_in_flight(self):
        self.feed("fragment shader source:")
        self.assertTrue(self.monitor.compile_in_flight)
        self.assertFalse(self.monitor.is_quiet(0.0))

    def test_not_quiet_right_after_a_compile_finishes(self):
        self.feed("fragment shader source:")
        self.feed("Spent 2.023 ms translating HLSL to DXBC")
        self.assertFalse(self.monitor.compile_in_flight)
        self.assertEqual(self.monitor.compiles_done, 1)
        self.assertFalse(self.monitor.is_quiet(60.0))
        self.assertTrue(self.monitor.is_quiet(0.0))

    def test_reset_clears_in_flight_compile(self):
        self.feed("vertex shader source:")
        self.monitor.reset()
        self.assertFalse(self.monitor.compile_in_flight)


class TestSdrOutputOnlyOverride(unittest.TestCase):
    def tearDown(self):
        TonemapEngine.sdr_output_only = False

    def test_display_reported_as_sdr_when_renderer_cannot_present_hdr(self):
        TonemapEngine.sdr_output_only = True
        self.assertFalse(TonemapEngine.is_display_hdr())


if __name__ == "__main__":
    unittest.main()
