"""Strict property-edit contracts, separate from geometry-creation commands."""
import json
from jsonschema import Draft7Validator


def variant(command, required, properties, **rules):
    return {"type": "object", "additionalProperties": False,
            "required": ["command", "target_dwg_path", *required],
            "properties": {"command": {"const": command},
                           "target_dwg_path": {"type": "string", "minLength": 1}, **properties}, **rules}


STRING = {"type": "string", "minLength": 1}
OPERATION_VARIANTS = [
    variant("RESIZE_COMPONENT", ["handle", "dimension"], {
        "handle": STRING, "dimension": {"enum": ["length", "radius"]},
        "delta_mm": {"type": "number"}, "value_mm": {"type": "number", "exclusiveMinimum": 0}},
        oneOf=[{"required": ["delta_mm"]}, {"required": ["value_mm"]}]),
    variant("SET_ENTITY_PROPERTY", ["handle", "property", "value"], {
        "handle": STRING, "property": {"enum": ["color", "layer", "linetype", "text", "attribute"]},
        "value": {}, "attribute_tag": STRING},
        allOf=[{"if": {"properties": {"property": {"const": "color"}}},
                "then": {"properties": {"value": {"type": "integer", "minimum": 0, "maximum": 256}}},
                "else": {"properties": {"value": {"type": "string"}}}},
               {"if": {"properties": {"property": {"const": "attribute"}}},
                "then": {"required": ["attribute_tag"]}, "else": {"not": {"required": ["attribute_tag"]}}}]),
    variant("SET_DOCUMENT_PROPERTY", ["property", "value"], {
        "property": {"enum": ["title", "author", "subject", "keywords", "comments", "revision", "custom"]},
        "value": {"type": "string"}, "key": STRING},
        allOf=[{"if": {"properties": {"property": {"const": "custom"}}},
                "then": {"required": ["key"]}, "else": {"not": {"required": ["key"]}}}]),
    variant("SET_LAYER_COLOR", ["layer", "color"], {
        "layer": STRING, "color": {"type": "integer", "minimum": 1, "maximum": 255}}),
    variant("RENAME_FILE", ["new_name"], {
        "new_name": {"type": "string", "pattern": r'^[^\\/:*?"<>|]+\.(dwg|dxf)$'}}),
]
OPERATION_SCHEMA = {"$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "object", "oneOf": OPERATION_VARIANTS}
OPERATION_TYPES = {v["properties"]["command"]["const"] for v in OPERATION_VARIANTS}


def validate_operation(operation):
    json.dumps(operation, allow_nan=False)
    Draft7Validator(OPERATION_SCHEMA).validate(operation)
    return operation
