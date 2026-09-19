"""Plain records shared by extraction backends; no COM or persistence imports."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DocumentMetadata:
    path: str
    name: str
    units: int
    properties: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class EntityRecord:
    handle: str
    entity_type: str
    layer: str
    tag: str | None = None


@dataclass
class BlockRecord:
    name: str
    handle: str
    is_reference: bool
    attributes: dict = field(default_factory=dict)
    dynamic_properties: list[dict] = field(default_factory=list)


@dataclass
class BoundingBox:
    handle: str
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]
    start: tuple[float, float, float] | None = None
    end: tuple[float, float, float] | None = None
    connection_points: list[tuple[float, float, float]] = field(default_factory=list)


@dataclass(frozen=True)
class RelationshipRecord:
    source_handle: str
    relationship_type: str
    target_handle: str


@dataclass
class DrawingSnapshot:
    document: DocumentMetadata
    entities: list[EntityRecord]
    blocks: list[BlockRecord]
    properties: dict[str, dict]
    relationships: list[RelationshipRecord]
    spatial_data: list[BoundingBox]


class DrawingExtractor(ABC):
    @abstractmethod
    def extract_document(self, source) -> DocumentMetadata: ...

    @abstractmethod
    def extract_entities(self, source) -> list[EntityRecord]: ...

    @abstractmethod
    def extract_blocks(self, source) -> list[BlockRecord]: ...

    @abstractmethod
    def extract_properties(self, source) -> dict[str, dict]: ...

    @abstractmethod
    def extract_relationships(self, source) -> list[RelationshipRecord]: ...

    @abstractmethod
    def extract_spatial_data(self, source) -> list[BoundingBox]: ...

    def extract(self, source) -> DrawingSnapshot:
        return DrawingSnapshot(self.extract_document(source), self.extract_entities(source),
                               self.extract_blocks(source), self.extract_properties(source),
                               self.extract_relationships(source), self.extract_spatial_data(source))
