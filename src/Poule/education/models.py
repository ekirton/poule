"""Data models for the textbook retrieval system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChunkMetadata:
    volume: str
    volume_title: str
    chapter: str
    chapter_file: str
    section_title: str
    section_path: list[str] = field(default_factory=list)
    anchor_id: str | None = None


@dataclass
class Chunk:
    text: str
    code_blocks: list[str]
    metadata: ChunkMetadata
    token_count: int


@dataclass
class EducationSearchResult:
    text: str
    code_blocks: list[str]
    metadata: ChunkMetadata
    score: float
    location: str
    browser_path: str
