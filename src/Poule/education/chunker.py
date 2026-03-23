"""HTML chunker for Software Foundations content."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from Poule.education.models import Chunk, ChunkMetadata

SKIP_FILES = {"index.html", "toc.html", "coqindex.html", "deps.html"}

VOLUME_TITLES = {
    "lf": "Logical Foundations",
    "plf": "Programming Language Foundations",
    "vfa": "Verified Functional Algorithms",
    "qc": "QuickChick",
    "secf": "Security Foundations",
    "slf": "Separation Logic Foundations",
    "vc": "Verifiable C",
}


def _token_count(text: str) -> int:
    return len(text.split())


def _extract_text(element) -> str:
    """Extract plain text from an HTML element, stripping tags."""
    if isinstance(element, str):
        return element
    return element.get_text()


def _extract_code_block(code_div) -> str:
    """Extract Coq code text from a <div class='code'> element."""
    text = code_div.get_text()
    # Clean up: collapse multiple spaces but keep newlines
    lines = text.split("\n")
    lines = [line.rstrip() for line in lines]
    # Strip leading/trailing empty lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


class HTMLChunker:
    """Parses Software Foundations HTML and produces section-based chunks."""

    def chunk_file(self, html_path: Path, volume: str) -> list[Chunk]:
        html_path = Path(html_path)
        with open(html_path, encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        volume_title = self._extract_volume_title(soup, volume)
        chapter, chapter_file = self._extract_chapter_info(soup, html_path)

        main = soup.find("div", id="main")
        if not main:
            return []

        # Remove unwanted elements
        for tag_name in ["script"]:
            for tag in main.find_all(tag_name):
                tag.decompose()
        for cls in ["togglescript"]:
            for tag in main.find_all("div", class_=cls):
                tag.decompose()

        # Walk through main content, splitting on section headers
        sections = self._split_sections(main, chapter)
        chunks = self._sections_to_chunks(
            sections, volume, volume_title, chapter, chapter_file
        )

        # Apply size control
        chunks = self._apply_size_control(chunks)

        return chunks

    def chunk_corpus(self, sf_dir: Path) -> list[Chunk]:
        sf_dir = Path(sf_dir)
        all_chunks = []
        for volume in VOLUME_TITLES:
            vol_dir = sf_dir / volume
            if not vol_dir.is_dir():
                continue
            for html_file in sorted(vol_dir.glob("*.html")):
                if html_file.name in SKIP_FILES:
                    continue
                chunks = self.chunk_file(html_file, volume)
                all_chunks.extend(chunks)
        return all_chunks

    def _extract_volume_title(self, soup: BeautifulSoup, volume: str) -> str:
        booktitle = soup.find("div", class_="booktitleinheader")
        if booktitle:
            text = booktitle.get_text().strip()
            # Extract title after "Volume N: "
            match = re.search(r"Volume \d+:\s*(.*)", text)
            if match:
                return match.group(1).strip()
            return text
        return VOLUME_TITLES.get(volume, volume)

    def _extract_chapter_info(self, soup: BeautifulSoup, html_path: Path) -> tuple[str, str]:
        chapter_file = html_path.name
        libtitle = soup.find("h1", class_="libtitle")
        if libtitle:
            # Chapter name is the text before the subtitle span
            chapter = libtitle.get_text().strip()
            subtitle = libtitle.find("span", class_="subtitle")
            if subtitle:
                sub_text = subtitle.get_text().strip()
                chapter = chapter.replace(sub_text, "").strip()
        else:
            chapter = html_path.stem
        return chapter, chapter_file

    def _split_sections(self, main, chapter: str) -> list[dict]:
        """Split main content into sections based on h1-h4.section headers."""
        sections = []
        current_section = {
            "title": chapter,
            "anchor_id": None,
            "level": 0,
            "path": [chapter],
            "prose": [],
            "code_blocks": [],
        }
        # Track section hierarchy for path building
        hierarchy = {0: chapter}

        for child in main.children:
            if not isinstance(child, Tag):
                continue

            # Check if this is a section heading
            heading = None
            anchor_id = None
            if child.name in ("h1", "h2", "h3", "h4") and "section" in child.get("class", []):
                heading = child
            elif child.name == "div" and "doc" in child.get("class", []):
                # Sections may be inside doc divs
                for sub in child.children:
                    if not isinstance(sub, Tag):
                        continue
                    if sub.name == "a" and sub.get("id", "").startswith("lab"):
                        anchor_id = sub.get("id")
                    elif sub.name in ("h1", "h2", "h3", "h4") and "section" in sub.get("class", []):
                        heading = sub
                        break

                if heading is None:
                    # Regular doc div — add as prose
                    text = child.get_text().strip()
                    if text:
                        current_section["prose"].append(text)
                    continue

            if heading is not None:
                # Check for anchor just before this heading
                if anchor_id is None:
                    prev = heading.find_previous_sibling("a")
                    if prev and isinstance(prev, Tag) and prev.get("id", "").startswith("lab"):
                        anchor_id = prev.get("id")

                # Finalize previous section
                if current_section["prose"] or current_section["code_blocks"]:
                    sections.append(current_section)

                level_map = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
                level = level_map.get(heading.name, 1)
                title = heading.get_text().strip()

                # Update hierarchy
                hierarchy[level] = title
                # Remove deeper levels
                for k in list(hierarchy):
                    if k > level:
                        del hierarchy[k]

                path = [hierarchy[k] for k in sorted(hierarchy) if k <= level]

                current_section = {
                    "title": title,
                    "anchor_id": anchor_id,
                    "level": level,
                    "path": path,
                    "prose": [],
                    "code_blocks": [],
                }

                # Collect remaining content from this doc div after the heading
                if child.name == "div":
                    remaining_text = []
                    past_heading = False
                    for sub in child.children:
                        if sub is heading:
                            past_heading = True
                            continue
                        if past_heading and isinstance(sub, Tag):
                            if sub.name not in ("a",) or not sub.get("id", "").startswith("lab"):
                                t = sub.get_text().strip()
                                if t:
                                    remaining_text.append(t)
                        elif past_heading and isinstance(sub, str) and sub.strip():
                            remaining_text.append(sub.strip())
                    if remaining_text:
                        current_section["prose"].append(" ".join(remaining_text))
            elif child.name == "div" and "code" in child.get("class", []):
                code_text = _extract_code_block(child)
                if code_text.strip():
                    current_section["code_blocks"].append(code_text)
                    current_section["prose"].append(code_text)

        # Finalize last section
        if current_section["prose"] or current_section["code_blocks"]:
            sections.append(current_section)

        return sections

    def _sections_to_chunks(
        self,
        sections: list[dict],
        volume: str,
        volume_title: str,
        chapter: str,
        chapter_file: str,
    ) -> list[Chunk]:
        chunks = []
        for sec in sections:
            text = "\n\n".join(sec["prose"])
            if not text.strip():
                continue
            metadata = ChunkMetadata(
                volume=volume,
                volume_title=volume_title,
                chapter=chapter,
                chapter_file=chapter_file,
                section_title=sec["title"],
                section_path=sec["path"],
                anchor_id=sec["anchor_id"],
            )
            chunks.append(
                Chunk(
                    text=text,
                    code_blocks=sec["code_blocks"],
                    metadata=metadata,
                    token_count=_token_count(text),
                )
            )
        return chunks

    def _apply_size_control(self, chunks: list[Chunk]) -> list[Chunk]:
        """Merge small chunks, keep exercises separate."""
        if not chunks:
            return chunks

        result = []
        i = 0
        while i < len(chunks):
            chunk = chunks[i]
            is_exercise = "Exercise" in chunk.metadata.section_title

            if is_exercise:
                result.append(chunk)
                i += 1
                continue

            # Merge small chunks (< 100 tokens) with the next
            if chunk.token_count < 100 and i + 1 < len(chunks):
                next_chunk = chunks[i + 1]
                next_is_exercise = "Exercise" in next_chunk.metadata.section_title
                if not next_is_exercise:
                    merged_text = chunk.text + "\n\n" + next_chunk.text
                    merged_code = chunk.code_blocks + next_chunk.code_blocks
                    merged = Chunk(
                        text=merged_text,
                        code_blocks=merged_code,
                        metadata=ChunkMetadata(
                            volume=chunk.metadata.volume,
                            volume_title=chunk.metadata.volume_title,
                            chapter=chunk.metadata.chapter,
                            chapter_file=chunk.metadata.chapter_file,
                            section_title=chunk.metadata.section_title,
                            section_path=chunk.metadata.section_path,
                            anchor_id=chunk.metadata.anchor_id,
                        ),
                        token_count=_token_count(merged_text),
                    )
                    chunks[i + 1] = merged
                    i += 1
                    continue

            result.append(chunk)
            i += 1

        return result
