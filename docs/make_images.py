"""The README's figures, from a real INGV ShakeMap.

    uv run --group docs python docs/make_images.py

Downloads the grid of the Mw 5.5 of 23 October 2026 in the southern Tyrrhenian
(event 47606532) with the package's own client, and draws its peak ground
acceleration. Nothing is hand-made: re-running it on another event id draws
that event.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patheffects
from matplotlib.colors import LogNorm

from ingv_shakemap import IngvClient

EVENT = sys.argv[1] if len(sys.argv) > 1 else "47606532"
OUT = Path(__file__).parent / "images"


async def main() -> None:
    async with IngvClient() as client:
        grid = await client.shakemap(EVENT)
    if grid is None:
        raise SystemExit(f"no ShakeMap for event {EVENT}")
    pga_g = grid.column("PGA") / 100.0
    w, s, e, n = grid.bbox
    for theme, fg, bg in (("light", "#1f2328", "#ffffff"), ("dark", "#e6edf3", "#0d1117")):
        fig, ax = plt.subplots(figsize=(8, 5.6), dpi=150, facecolor=bg)
        ax.set_facecolor(bg)
        im = ax.imshow(
            np.clip(pga_g, 1e-4, None),
            extent=(w, e, s, n),
            origin="upper",
            cmap="inferno",
            norm=LogNorm(vmin=1e-3, vmax=max(pga_g.max(), 1e-2)),
            aspect=1 / np.cos(np.radians((s + n) / 2)),
        )
        ax.plot(grid.event.longitude, grid.event.latitude, marker="*", ms=14, color="#2ea043",
                markeredgecolor=bg)  # fmt: skip
        halo = [patheffects.withStroke(linewidth=2.5, foreground="#000000")]
        for name, lon, lat, dx in (("Palermo", 13.36, 38.12, 4), ("Messina", 15.55, 38.19, 4),
                                   ("Cosenza", 16.25, 39.30, -78)):  # fmt: skip
            if w <= lon <= e and s <= lat <= n:
                ax.plot(lon, lat, "o", ms=3, color="#ffffff", markeredgecolor="#000000")
                g = grid.pga_g(lon, lat) or 0.0
                ax.annotate(f"{name}  {g:.3f} g", (lon, lat), xytext=(dx, 4),
                            textcoords="offset points", color="#ffffff", fontsize=8,
                            path_effects=halo)  # fmt: skip
        cb = fig.colorbar(im, ax=ax, shrink=0.85)
        cb.set_label("Peak ground acceleration (g)", color=fg)
        cb.ax.tick_params(colors=fg)
        ev = grid.event
        ax.set_title(
            f"INGV ShakeMap {ev.id}: M{ev.magnitude} {ev.description}, "
            f"{ev.time:%d %b %Y %H:%M} UTC ({grid.map_status})",
            color=fg, fontsize=9,
        )  # fmt: skip
        ax.tick_params(colors=fg, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(fg)
        fig.tight_layout()
        fig.savefig(OUT / f"pga-{theme}.png", facecolor=bg)
        plt.close(fig)
    print(f"wrote {OUT}/pga-light.png and pga-dark.png; max PGA {pga_g.max():.3f} g")


asyncio.run(main())
