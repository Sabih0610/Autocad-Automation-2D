import comtypes.client
import array

def point(x, y, z=0.0):
    return array.array('d', [x, y, z])

# Connect
acad = comtypes.client.GetActiveObject("AutoCAD.Application")
doc = acad.ActiveDocument
model = doc.ModelSpace

# 1. Line — from (0, 0) to (200, 200)
line = model.AddLine(point(0, 0), point(200, 200))
print(f"Line drawn. Handle: {line.Handle}")

# 2. Rectangle as a closed polyline — 4 corners + back to start
# Polyline takes a flat array of coordinates: x1,y1,x2,y2,...
corners = array.array('d', [
    300, 0,
    500, 0,
    500, 150,
    300, 150
])
poly = model.AddLightWeightPolyline(corners)
poly.Closed = True
print(f"Rectangle drawn. Handle: {poly.Handle}")

# 3. Text — at position (0, 250), height 20
text = model.AddText("Hello AutoCAD from Python", point(0, 250), 20.0)
print(f"Text drawn. Handle: {text.Handle}")

# Zoom to show everything
acad.ZoomExtents()

print("\nAll shapes drawn. Switch to AutoCAD to view.")