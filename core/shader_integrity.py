"""
BOOB Player - Shader Constant Integrity Monitor

Detects miscompiled libplacebo shaders by reading libmpv's own debug log.

Background
----------
With `vo=gpu-next` on Direct3D 11, libplacebo generates GLSL, the bundled GLSL
compiler turns it into SPIR-V, and SPIRV-Cross translates that to HLSL. libmpv
logs both the GLSL it generated and the HLSL it ended up with.

The libmpv build shipped in lib/ intermittently corrupts long float literals
(16+ significant digits) while compiling GLSL: the leading characters of the
literal are lost, so e.g.

    GLSL:  const float _f = float(1.000962257385254);     (P010 sample scale)
    HLSL:  ... * 0.00096225738525390625f                  (integer part gone)

    GLSL:  color.rgb *= float(49.261085510253906);        (PQ 10000/203 scale)
    HLSL:  ... * 0.26108551025390625f

Compiled shaders are cached for the lifetime of the video output, so a single
bad compile turns the whole session into a flat purple / red / green / white
frame (most visibly on Dolby Vision, whose IPTPQc2 reshaping multiplies the
error). Nothing in the player's own state differs between a good and a bad run.

This monitor compares every float literal in the translated HLSL against the
"leading characters lost" variants of the long GLSL literals that preceded it.
A hit is a definite miscompile; the engine then rebuilds the video output so
the shaders are compiled again.
"""

import re
import struct
import threading
import time
from collections import OrderedDict
from typing import Callable, Dict, Optional

# libplacebo emits baked constants as `float(<decimal>)`
_GLSL_LITERAL_RE = re.compile(r"float\((\d+\.\d+)\)")
# SPIRV-Cross emits HLSL float literals as `<decimal>f`
_HLSL_LITERAL_RE = re.compile(r"(?<![\w.])(\d+\.\d+(?:[eE][+-]?\d+)?)f\b")
# Numbered source dump line: "[ 25] const float ..."
_SOURCE_LINE_RE = re.compile(r"^\[\s*\d+\]\s")

LIBPLACEBO_LOG_PREFIX = "vo/gpu-next/libplacebo"

# Only literals at least this long take the fragile parsing path.
MIN_SOURCE_DIGITS = 16
# A corrupted value must keep at least this many digits to be considered a
# match, so short everyday constants (0.5, 2.0, ...) can never collide.
MIN_VARIANT_DIGITS = 8


def _f32(value: float) -> Optional[float]:
    """Round a Python float to the nearest IEEE-754 single, as the shader does."""
    try:
        return struct.unpack("<f", struct.pack("<f", value))[0]
    except (OverflowError, struct.error):
        return None


def _significant_digits(digits: str) -> int:
    return len(digits.lstrip("0"))


def corrupted_variants(literal: str) -> Dict[float, str]:
    """
    Return {float32 value: description} for every value `literal` can turn into
    when its leading characters are lost during parsing.

    Two families were observed in the wild:
      * leading digits read as zero, decimal point kept
            1.000962257385254  -> 0.000962257385254
            49.261085510253906 -> 0.261085510253906
      * leading digits read as zero, decimal point lost too
            1.000962257385254  -> 962257385254.0
    """
    if "." not in literal:
        return {}
    whole, frac = literal.split(".", 1)
    digits = whole + frac
    if _significant_digits(digits) < MIN_SOURCE_DIGITS:
        return {}

    correct = _f32(float(literal))
    variants: Dict[float, str] = {}
    for lost in range(1, len(digits)):
        tail = digits[lost:]
        if _significant_digits(tail) < MIN_VARIANT_DIGITS:
            break
        zeroed = "0" * lost + tail
        candidates = (
            (float(zeroed[:len(whole)] + "." + zeroed[len(whole):]), "leading digits dropped"),
            (float(int(tail)), "leading digits and decimal point dropped"),
        )
        for value, why in candidates:
            v32 = _f32(value)
            if v32 is None or v32 == correct:
                continue
            variants.setdefault(v32, why)
    return variants


class ShaderIntegrityMonitor:
    """
    Feed with libmpv log messages (python-mpv `log_handler` signature). Calls
    `on_miscompile(info)` when the translated HLSL contains a corrupted constant.

    Thread-safe; `feed` is cheap for messages that are not shader source lines.
    """

    MAX_TRACKED_LITERALS = 512

    def __init__(self, on_miscompile: Optional[Callable[[Dict[str, object]], None]] = None):
        self.on_miscompile = on_miscompile
        self._lock = threading.Lock()
        # float32 corrupted value -> (source literal, description)
        self._variants: "OrderedDict[float, tuple]" = OrderedDict()
        # float32 values that legitimately appear in generated GLSL
        self._legit: "OrderedDict[float, None]" = OrderedDict()
        self._seen_literals: "OrderedDict[str, None]" = OrderedDict()
        self.miscompile_count = 0
        self.last_info: Optional[Dict[str, object]] = None
        # Shader compile activity, so the engine can tell when the burst of
        # compiles that follows opening a file has finished.
        self.compile_in_flight = False
        self.compiles_done = 0
        self.last_activity = 0.0
        # Incremented by reset(); lets consumers discard reports about a
        # video output that has since been rebuilt.
        self.generation = 0

    def reset(self):
        """Forget tracked literals (call when the video output is rebuilt)."""
        with self._lock:
            self._variants.clear()
            self._legit.clear()
            self._seen_literals.clear()
            self.generation += 1
            self.compile_in_flight = False

    def feed(self, level: str, prefix: str, text: str):
        if prefix != LIBPLACEBO_LOG_PREFIX or not text:
            return
        if text[0] != "[":
            if "shader source:" in text:
                self.compile_in_flight = True
                self.last_activity = time.monotonic()
            elif "translating HLSL to DXBC" in text:
                self.compile_in_flight = False
                self.compiles_done += 1
                self.last_activity = time.monotonic()
            return
        if not _SOURCE_LINE_RE.match(text):
            return

        hit = None
        with self._lock:
            for literal in _GLSL_LITERAL_RE.findall(text):
                self._track_literal(literal)
            if self._variants and "f" in text:
                for token in _HLSL_LITERAL_RE.findall(text):
                    try:
                        value = _f32(float(token))
                    except ValueError:
                        continue
                    if value is None or value in self._legit:
                        continue
                    match = self._variants.get(value)
                    if match:
                        source, why = match
                        hit = {
                            "expected": source,
                            "compiled": token,
                            "reason": why,
                            "hlsl_line": text.strip()[:200],
                            "generation": self.generation,
                        }
                        break
            if hit:
                self.miscompile_count += 1
                self.last_info = hit

        if hit and self.on_miscompile:
            try:
                self.on_miscompile(hit)
            except Exception:
                pass

    def is_quiet(self, seconds: float) -> bool:
        """True when no shader is being compiled and none finished within `seconds`."""
        return (not self.compile_in_flight) and (time.monotonic() - self.last_activity) >= seconds

    def _track_literal(self, literal: str):
        try:
            legit = _f32(float(literal))
        except ValueError:
            return
        if legit is not None:
            self._legit[legit] = None
            self._legit.move_to_end(legit)
            while len(self._legit) > self.MAX_TRACKED_LITERALS * 4:
                self._legit.popitem(last=False)
        if literal in self._seen_literals:
            return
        self._seen_literals[literal] = None
        while len(self._seen_literals) > self.MAX_TRACKED_LITERALS:
            self._seen_literals.popitem(last=False)
        for value, why in corrupted_variants(literal).items():
            self._variants[value] = (literal, why)
        while len(self._variants) > self.MAX_TRACKED_LITERALS * 64:
            self._variants.popitem(last=False)
