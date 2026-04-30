"""Minimal fluids.piping lookup smoke test."""

from __future__ import annotations

from fluids import piping


def _print_pipe_lookup(nps: float) -> None:
    _, pipe_id_m, pipe_od_m, pipe_wall_m = piping.nearest_pipe(NPS=nps, schedule="40")
    print(
        f"NPS {nps:g} Sch 40 -> "
        f"OD: {pipe_od_m * 1000.0:.3f} mm, "
        f"ID: {pipe_id_m * 1000.0:.3f} mm, "
        f"Wall: {pipe_wall_m * 1000.0:.3f} mm"
    )


def main() -> None:
    _print_pipe_lookup(2.0)
    _print_pipe_lookup(6.0)
    _print_pipe_lookup(8.0)


if __name__ == "__main__":
    main()
