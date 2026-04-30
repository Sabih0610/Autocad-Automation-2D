"""Demo: draw a few shapes using the reusable AutoCAD client."""

from src.autocad_client import safe_connect


def main():
    cad = safe_connect()
    print(f"Connected to: {cad.caption}")
    print(f"Active drawing: {cad.drawing_name}")

    cad.add_circle(100, 100, 50)
    cad.add_line(0, 0, 200, 200)
    cad.add_rectangle(300, 0, 500, 150)
    cad.add_text("Hello from autocad_client", 0, 300, height=20)

    cad.zoom_extents()
    print("Drew circle, line, rectangle, and text. See AutoCAD.")


if __name__ == "__main__":
    main()