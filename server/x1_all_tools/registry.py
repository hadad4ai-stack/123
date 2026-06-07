from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

Json = dict[str, Any]
Handler = Callable[..., Any]

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Json
    handler: Handler
    examples: list[Mapping[str, Any]] = field(default_factory=list)

    def manifest(self) -> Json:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "examples": list(self.examples),
        }

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if "." not in spec.name:
            raise ValueError("Tool name must be namespaced, e.g. shell.run")
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            available = ", ".join(sorted(self._tools))
            raise KeyError(f"Unknown tool: {name}. Available: {available}")
        return self._tools[name]

    def list(self) -> list[ToolSpec]:
        return [self._tools[name] for name in sorted(self._tools)]

    def manifest(self) -> list[Json]:
        return [tool.manifest() for tool in self.list()]

def object_schema(properties: Mapping[str, Mapping[str, Any]], required: list[str] | None = None, additional: bool = False) -> Json:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": required or [],
        "additionalProperties": additional,
    }

def validate(schema: Mapping[str, Any], args: Mapping[str, Any]) -> None:
    if schema.get("type") != "object":
        return
    if not isinstance(args, Mapping):
        raise TypeError("arguments must be an object")
    props = schema.get("properties", {})
    required = schema.get("required", [])
    additional = schema.get("additionalProperties", True)
    for key in required:
        if key not in args:
            raise ValueError(f"missing required argument: {key}")
    if additional is False:
        unknown = sorted(set(args) - set(props))
        if unknown:
            raise ValueError(f"unknown argument(s): {', '.join(unknown)}")
    for key, value in args.items():
        if key not in props:
            continue
        expected = props[key].get("type")
        if expected and not _ok_type(value, expected):
            raise TypeError(f"{key} must be {expected}, got {type(value).__name__}")
        if "enum" in props[key] and value not in props[key]["enum"]:
            raise ValueError(f"{key} must be one of {props[key]['enum']}")

def _ok_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_ok_type(value, item) for item in expected)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "null":
        return value is None
    return True
