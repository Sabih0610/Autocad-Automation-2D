import comtypes.client
import array
import sys

def point(x, y, z=0.0):
    return array.array('d', [x, y, z])

def connect_to_autocad():
    """Connect to a running AutoCAD instance with clear error messages."""
    try:
        acad = comtypes.client.GetActiveObject("AutoCAD.Application")
    except OSError:
        print("ERROR: AutoCAD is not running.")
        print("Please open AutoCAD and try again.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Could not connect to AutoCAD.")
        print(f"  Reason: {type(e).__name__}: {e}")
        sys.exit(1)

    # Check that a drawing is actually open
    try:
        doc = acad.ActiveDocument
        _ = doc.Name  # touch a property to confirm the doc is real
    except Exception:
        print("ERROR: No drawing is open in AutoCAD.")
        print("Please open or create a drawing (File > New), then try again.")
        sys.exit(1)

    return acad, doc


def main():
    acad, doc = connect_to_autocad()
    model = doc.ModelSpace

    print(f"Connected to: {acad.Caption}")
    print(f"Active drawing: {doc.Name}")

    # Draw a single circle to confirm it still works
    circle = model.AddCircle(point(600, 100), 25.0)
    acad.ZoomExtents()
    print(f"Circle drawn. Handle: {circle.Handle}")


if __name__ == "__main__":
    main()