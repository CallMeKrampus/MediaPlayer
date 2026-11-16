"""
BOOB Player - Render defect watchdog sampler.

Grabs a decoded frame in a background thread and classifies it as normal or as
one of the known corrupted-render signatures (solid white, blue/purple, green,
red). Nothing is logged or written anywhere; the result goes to `on_defect`.
"""

import threading
from typing import Callable, Optional


class FrameSampler:
    @staticmethod
    def sample(
        player,
        time_pos: float,
        on_defect: Optional[Callable[[str, float], None]] = None,
    ):
        if not player or not getattr(player, "vo_configured", False):
            return
        if getattr(player, "seeking", False) or getattr(player, "_mpv_is_seeking", False):
            return

        def _worker():
            try:
                import numpy as np
                if getattr(player, "seeking", False) or getattr(player, "_mpv_is_seeking", False):
                    return
                try:
                    res = player.command("screenshot-raw")
                except Exception:
                    return
                if not (res and isinstance(res, dict) and "data" in res and "w" in res and "h" in res):
                    return

                w = int(res["w"])
                h = int(res["h"])
                stride = int(res.get("stride", w * 4))
                arr = np.frombuffer(res["data"], dtype=np.uint8).reshape((h, stride // 4, 4))[:, :w, :3]
                center = arr[int(h * 0.25):int(h * 0.75), int(w * 0.25):int(w * 0.75)]
                b_mean = float(center[:, :, 0].mean())
                g_mean = float(center[:, :, 1].mean())
                r_mean = float(center[:, :, 2].mean())
                arr_min = float(arr.min())

                # Opening logos are saturated on purpose; never classify them
                if time_pos < 5.0:
                    return

                status = None
                if b_mean > 238.0 and g_mean > 238.0 and r_mean > 238.0 and arr_min > 220.0:
                    status = "DEFECT: SOLID WHITE"
                elif b_mean > 80.0 and (b_mean / max(r_mean, 0.1)) > 3.0 and (b_mean / max(g_mean, 0.1)) > 2.0 and (r_mean + g_mean + b_mean) > 100.0:
                    status = "DEFECT: BLUE / PURPLE DOMINANCE"
                elif g_mean > 85.0 and (g_mean / max(r_mean, 0.1)) > 7.0 and (g_mean / max(b_mean, 0.1)) > 1.8 and (r_mean + g_mean + b_mean) > 100.0:
                    status = "DEFECT: FLUORESCENT GREEN"
                elif r_mean > 180.0 and (r_mean / max(b_mean, 0.1)) > 3.0 and (r_mean / max(g_mean, 0.1)) > 3.0:
                    status = "DEFECT: RED DOMINANCE / BLOWOUT"

                if status and on_defect:
                    try:
                        on_defect(status, time_pos)
                    except Exception:
                        pass
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()
