import comtypes.client

# Connect to running AutoCAD
acad = comtypes.client.GetActiveObject("AutoCAD.Application")
doc = acad.ActiveDocument
model = doc.ModelSpace

# AutoCAD COM expects coordinates as a 3-element array of doubles
# We use a small helper to build that
import array
def point(x, y, z=0.0):
    return array.array('d', [x, y, z])

# Draw a circle: center (100, 100), radius 50
center = point(100, 100)
radius = 50.0
circle = model.AddCircle(center, radius)

# Zoom to show what we drew
acad.ZoomExtents()

print(f"Circle drawn at (100, 100) with radius {radius}")
print(f"Circle handle: {circle.Handle}")