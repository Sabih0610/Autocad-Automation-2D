from pydantic import BaseModel, ConfigDict, Field


DEFAULT_SYMBOL_PROMPT = (
    "Add pump P-101 at coordinates 500, 250 "
    "on layer P-EQUIPMENT for cooling water."
)


class JobResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = Field(..., description="True when the requested job completed successfully.")
    message: str | None = Field(
        default=None,
        description="Optional human-readable summary message for the job result.",
    )


class TitleBlockUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawings_folder: str = Field(
        default=r"E:\RC-Projects",
        description="Folder containing the DWG files to scan for matching title blocks.",
    )
    file_pattern: str = Field(
        default="drawing_*.dwg",
        description="Glob pattern used to select the DWG files to process inside drawings_folder.",
    )
    title_block_name: str = Field(
        default="TITLE_BLOCK_TEST",
        description="Exact AutoCAD block name to locate in each drawing before updating attributes.",
    )
    updates: dict[str, str] = Field(
        default_factory=lambda: {
            "REV": "G",
            "DATE": "2026-05-01",
            "DRAWN_BY": "S. AAMIR",
        },
        description="Mapping of title block attribute tags to the text values that should be written.",
    )
    dry_run: bool = Field(
        default=True,
        description="When true, preview changes only. Set false only when you want AutoCAD to save the updates.",
    )


class LineListExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drawings_folder: str = Field(
        default=r"E:\RC-Projects",
        description="Folder containing the target P&ID DWG file to read from AutoCAD.",
    )
    target_file: str = Field(
        default="pid_001.dwg",
        description="Drawing filename inside drawings_folder that contains the line list blocks to extract.",
    )
    line_block_name: str = Field(
        default="LINE_BLOCK_TEST",
        description="Exact AutoCAD block name that represents a line list entry in the drawing.",
    )


class PlaceSymbolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(
        default=DEFAULT_SYMBOL_PROMPT,
        description="Natural-language drafting instruction that the AI planner converts into a symbol placement spec.",
    )
    execute: bool = Field(
        default=False,
        description="When false, run dry-run validation only. Set true to insert the planned symbol into the active drawing.",
    )


class ConsistencyCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pid_path: str = Field(
        default=r"E:\RC-Projects\pid_001.dwg",
        description="Full path to the P&ID DWG file that should be compared against the Excel line list.",
    )
    excel_path: str = Field(
        default="",
        description="Optional full path to the Excel line list. Leave blank to auto-select the latest clean generated line list in outputs/.",
    )
    use_ai_explanation: bool = Field(
        default=True,
        description="When true, generate the optional AI explanation files. Set false to return deterministic comparison results only.",
    )


class PIDGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(
        ...,
        description="Natural-language P&ID request.",
    )
    drawing_style: str = Field(
        default="clean schematic P&ID",
        description="Style instruction for the P&ID component planner.",
    )


class PIDApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., description="Token returned by /api/pid/generate.")
    save: bool = Field(
        default=False,
        description="Whether to save the active AutoCAD drawing after execution.",
    )
    target_dwg_path: str | None = Field(
        default=None,
        description="Optional DWG path to open before execution. If omitted, active drawing is used.",
    )


class CAD3DGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(
        default=None,
        description="Optional natural-language 3D CAD request.",
    )
    drawing_style: str = Field(
        default="simple clean 3D equipment layout",
        description="Style instruction for the 3D CAD scene planner.",
    )
    example_name: str = Field(
        default="simple_component_layout",
        description=(
            "Name of deterministic 3D component example to generate if prompt "
            "is not provided or AI fallback is needed."
        ),
    )


class CAD3DApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., description="Token returned by /api/cad3d/generate.")
    save: bool = Field(
        default=False,
        description="Whether to save the active AutoCAD drawing after execution.",
    )
    target_dwg_path: str | None = Field(
        default=None,
        description="Optional DWG path to open before execution. If omitted, active drawing is used.",
    )


class CAD3DEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., description="Natural-language CAD3D scene edit request.")
    token: str | None = Field(
        default=None,
        description="Optional source CAD3D scene token. If omitted, latest scene state is used.",
    )
    execute: bool = Field(
        default=False,
        description="When true, execute the edited scene into AutoCAD after storing it.",
    )
    save: bool = Field(
        default=False,
        description="Whether to save the active AutoCAD drawing after edited-scene execution.",
    )
    target_dwg_path: str | None = Field(
        default=None,
        description="Optional DWG path to open before edited-scene execution.",
    )
    create_new_token: bool = Field(
        default=True,
        description="When true, store the edited scene under a new token.",
    )
