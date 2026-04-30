# Vessel Output Format Decision

## Purpose

The vessel generator produces engineering drawings from parametric vessel data.

The generator uses two output formats:

1. DXF
2. DWG

DXF is used as the internal/intermediate generated drawing format.

DWG is used as the final company/drafter deliverable format.

---

## Why DXF is generated first

The parametric vessel drawing layer uses `ezdxf`.

`ezdxf` is used because:

- it is pure Python
- it does not require AutoCAD to be installed or running
- it is fast for development and testing
- it allows deterministic geometry generation
- it works well for lines, circles, ellipses, layers, text, and dimensions
- it keeps the parametric layer independent from AutoCAD COM

This separation is important.

The vessel generator should be able to produce a valid drawing without depending on AutoCAD at every step.

---

## Why DWG is generated through AutoCAD COM

DWG is AutoCAD's native drawing format.

`ezdxf` cannot write DWG because DWG is a proprietary Autodesk format.

The reliable way to create DWG is:

1. generate DXF with `ezdxf`
2. open the DXF in AutoCAD
3. use AutoCAD's native `SaveAs()` operation to save the file as DWG

This is handled through AutoCAD COM automation.

AutoCAD owns the DWG format, so AutoCAD is the safest converter.

---

## Target DWG version

The default target DWG version is:

```text
DWG 2018