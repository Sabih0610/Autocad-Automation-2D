import comtypes.client

try:
    acad = comtypes.client.GetActiveObject("AutoCAD.Application")
    print("Connected to AutoCAD:", acad.Caption)
    print("Active drawing:", acad.ActiveDocument.Name)
except OSError:
    print("ERROR: AutoCAD is not running. Open AutoCAD with a drawing, then try again.")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")