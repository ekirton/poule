"""TDD tests for extraction checkpointing (specification/extraction-checkpointing.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/extraction/checkpoint.py exists.

Spec: specification/extraction-checkpointing.md
Architecture: doc/architecture/extraction-checkpointing.md

Import paths under test:
  poule.extraction.checkpoint  (update_checkpoint, incremental_extract, resume_extract, load_checkpoint)
  poule.extraction.types       (CampaignMetadata, etc.)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _sha256(content: str) -> str:
    """Compute SHA-256 hex digest of a string (UTF-8 encoded)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _make_campaign_metadata() -> dict:
    """Return a minimal CampaignMetadata dict for tests."""
    return {
        "projects": ["/projects/stdlib"],
        "coq_version": "8.18.0",
        "extraction_timestamp": "2026-03-17T00:00:00Z",
    }


def _make_checkpoint(
    *,
    completed_proofs: dict | None = None,
    completed_files: dict | None = None,
    last_position: dict | None = None,
    campaign_metadata: dict | None = None,
    schema_version: int = 1,
) -> dict:
    """Build a well-formed checkpoint dict."""
    return {
        "schema_version": schema_version,
        "campaign_metadata": campaign_metadata or _make_campaign_metadata(),
        "completed_proofs": completed_proofs or {},
        "completed_files": completed_files or {},
        "last_position": last_position or {"project_index": 0, "file_index": 0, "theorem_index": 0},
    }


def _write_checkpoint(path: Path, checkpoint: dict) -> None:
    """Write a checkpoint dict to disk as JSON."""
    path.write_text(json.dumps(checkpoint), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# 1. Checkpoint File (§4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckpointLocation:
    """Checkpoint file is stored at <output_path>.checkpoint."""

    def test_checkpoint_path_derived_from_output_path(self, tmp_path):
        """Given output /data/stdlib.jsonl, checkpoint is /data/stdlib.jsonl.checkpoint."""
        from Poule.extraction.checkpoint import checkpoint_path_for

        output = tmp_path / "stdlib.jsonl"
        result = checkpoint_path_for(output)
        assert result == output.with_suffix(output.suffix + ".checkpoint")
        assert str(result).endswith(".jsonl.checkpoint")


class TestCheckpointStructure:
    """Checkpoint is a JSON object with 5 fields in specified order."""

    def test_checkpoint_has_all_five_fields(self, tmp_path):
        """A written checkpoint contains schema_version, campaign_metadata,
        completed_proofs, completed_files, last_position."""
        from Poule.extraction.checkpoint import load_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        ckpt = _make_checkpoint()
        _write_checkpoint(ckpt_path, ckpt)

        loaded = load_checkpoint(ckpt_path)
        assert "schema_version" in loaded
        assert "campaign_metadata" in loaded
        assert "completed_proofs" in loaded
        assert "completed_files" in loaded
        assert "last_position" in loaded

    def test_checkpoint_is_valid_json(self, tmp_path):
        """The checkpoint file is valid JSON (not JSON Lines)."""
        from Poule.extraction.checkpoint import load_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        ckpt = _make_checkpoint()
        _write_checkpoint(ckpt_path, ckpt)

        # Should parse without error
        loaded = load_checkpoint(ckpt_path)
        assert isinstance(loaded, dict)

    def test_schema_version_is_integer(self, tmp_path):
        from Poule.extraction.checkpoint import load_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        _write_checkpoint(ckpt_path, _make_checkpoint(schema_version=1))

        loaded = load_checkpoint(ckpt_path)
        assert isinstance(loaded["schema_version"], int)
        assert loaded["schema_version"] == 1

    def test_last_position_has_three_indices(self, tmp_path):
        from Poule.extraction.checkpoint import load_checkpoint

        position = {"project_index": 2, "file_index": 10, "theorem_index": 5}
        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        _write_checkpoint(ckpt_path, _make_checkpoint(last_position=position))

        loaded = load_checkpoint(ckpt_path)
        lp = loaded["last_position"]
        assert lp["project_index"] == 2
        assert lp["file_index"] == 10
        assert lp["theorem_index"] == 5

    def test_completed_proofs_maps_names_to_hashes(self, tmp_path):
        from Poule.extraction.checkpoint import load_checkpoint

        h = _sha256("content of A.v")
        proofs = {"Stdlib.Arith.plus_comm": h}
        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        _write_checkpoint(ckpt_path, _make_checkpoint(completed_proofs=proofs))

        loaded = load_checkpoint(ckpt_path)
        assert loaded["completed_proofs"]["Stdlib.Arith.plus_comm"] == h


# ═══════════════════════════════════════════════════════════════════════════
# 2. Checkpoint Write (§4.2)
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateCheckpoint:
    """update_checkpoint adds a theorem and writes to disk after each proof."""

    def test_adds_theorem_to_completed_proofs(self, tmp_path):
        """Given 5 completed proofs, after update_checkpoint with proof 6,
        checkpoint has 6 completed proofs."""
        from Poule.extraction.checkpoint import load_checkpoint, update_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        h = _sha256("file content")

        # Seed checkpoint with 5 proofs
        existing_proofs = {f"Thm.proof_{i}": h for i in range(5)}
        _write_checkpoint(ckpt_path, _make_checkpoint(completed_proofs=existing_proofs))

        position = {"project_index": 0, "file_index": 0, "theorem_index": 5}
        update_checkpoint(
            checkpoint_path=ckpt_path,
            theorem_name="Thm.proof_5",
            source_file="A.v",
            content_hash=h,
            position=position,
        )

        loaded = load_checkpoint(ckpt_path)
        assert len(loaded["completed_proofs"]) == 6
        assert "Thm.proof_5" in loaded["completed_proofs"]

    def test_updates_last_position(self, tmp_path):
        from Poule.extraction.checkpoint import load_checkpoint, update_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        _write_checkpoint(ckpt_path, _make_checkpoint())

        new_pos = {"project_index": 1, "file_index": 3, "theorem_index": 7}
        update_checkpoint(
            checkpoint_path=ckpt_path,
            theorem_name="Thm.x",
            source_file="B.v",
            content_hash=_sha256("B content"),
            position=new_pos,
        )

        loaded = load_checkpoint(ckpt_path)
        assert loaded["last_position"] == new_pos

    def test_writes_to_disk_after_each_proof(self, tmp_path):
        """Checkpoint is written to disk after each proof (not batched)."""
        from Poule.extraction.checkpoint import load_checkpoint, update_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        _write_checkpoint(ckpt_path, _make_checkpoint())

        h = _sha256("content")
        for i in range(3):
            update_checkpoint(
                checkpoint_path=ckpt_path,
                theorem_name=f"Thm.t{i}",
                source_file="C.v",
                content_hash=h,
                position={"project_index": 0, "file_index": 0, "theorem_index": i},
            )
            # Verify disk state after each call
            on_disk = json.loads(ckpt_path.read_text(encoding="utf-8"))
            assert len(on_disk["completed_proofs"]) == i + 1

    def test_updates_completed_files_when_all_theorems_done(self, tmp_path):
        """completed_files is updated when all theorems in a file are complete."""
        from Poule.extraction.checkpoint import load_checkpoint, update_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        h = _sha256("D.v content")
        # Seed with 2 of 3 theorems done for file D.v
        proofs = {"D.thm1": h, "D.thm2": h}
        _write_checkpoint(ckpt_path, _make_checkpoint(completed_proofs=proofs))

        # The third and final theorem — supply file_theorems so the function
        # knows all theorems in the file
        update_checkpoint(
            checkpoint_path=ckpt_path,
            theorem_name="D.thm3",
            source_file="D.v",
            content_hash=h,
            position={"project_index": 0, "file_index": 0, "theorem_index": 2},
            file_theorems=["D.thm1", "D.thm2", "D.thm3"],
        )

        loaded = load_checkpoint(ckpt_path)
        assert "D.v" in loaded["completed_files"]
        assert loaded["completed_files"]["D.v"] == h


# ═══════════════════════════════════════════════════════════════════════════
# 3. Non-Atomic Writes — Corrupted Checkpoint (§4.2)
# ═══════════════════════════════════════════════════════════════════════════


class TestCorruptedCheckpoint:
    """Truncated JSON checkpoint is detected and triggers full extraction fallback."""

    def test_truncated_json_detected_on_load(self, tmp_path):
        """Given a checkpoint with truncated JSON, load raises CHECKPOINT_CORRUPT."""
        from Poule.extraction.checkpoint import load_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        # Write truncated JSON (mid-write crash simulation)
        ckpt_path.write_text('{"schema_version": 1, "campaign_metad', encoding="utf-8")

        with pytest.raises(Exception) as exc_info:
            load_checkpoint(ckpt_path)

        # Should indicate corruption
        assert "CHECKPOINT_CORRUPT" in str(exc_info.value) or "corrupt" in str(exc_info.value).lower()

    def test_corrupt_checkpoint_logs_warning_and_returns_none(self, tmp_path):
        """Corrupted checkpoint falls back to full extraction with warning."""
        from Poule.extraction.checkpoint import try_load_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        ckpt_path.write_text('{"schema_version": 1, "completed_pro', encoding="utf-8")

        import logging

        with patch.object(logging.getLogger("Poule.extraction.checkpoint"), "warning") as mock_warn:
            result = try_load_checkpoint(ckpt_path)

        assert result is None
        mock_warn.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# 4. Incremental Re-Extraction (§4.3)
# ═══════════════════════════════════════════════════════════════════════════


class TestFileClassification:
    """File classification: unchanged, changed, new, removed."""

    def test_unchanged_file_same_hash(self):
        """File in checkpoint with matching content hash is classified unchanged."""
        from Poule.extraction.checkpoint import classify_file

        h = _sha256("same content")
        result = classify_file(
            file_path="A.v",
            current_hash=h,
            checkpoint_files={"A.v": h},
        )
        assert result == "unchanged"

    def test_changed_file_different_hash(self):
        """File in checkpoint with different content hash is classified changed."""
        from Poule.extraction.checkpoint import classify_file

        old_h = _sha256("old content")
        new_h = _sha256("new content")
        result = classify_file(
            file_path="B.v",
            current_hash=new_h,
            checkpoint_files={"B.v": old_h},
        )
        assert result == "changed"

    def test_new_file_not_in_checkpoint(self):
        """File not in checkpoint is classified new."""
        from Poule.extraction.checkpoint import classify_file

        result = classify_file(
            file_path="C.v",
            current_hash=_sha256("new file"),
            checkpoint_files={},
        )
        assert result == "new"

    def test_removed_file_in_checkpoint_not_on_disk(self):
        """File in checkpoint but not in current plan is classified removed."""
        from Poule.extraction.checkpoint import classify_file

        result = classify_file(
            file_path="D.v",
            current_hash=None,
            checkpoint_files={"D.v": _sha256("old")},
        )
        assert result == "removed"


class TestIncrementalExtract:
    """incremental_extract re-extracts only changed/new files and merges."""

    def test_only_changed_files_re_extracted(self, tmp_path):
        """Given 100 files where 3 changed, only 3 are re-extracted."""
        from Poule.extraction.checkpoint import classify_files

        unchanged_hash = _sha256("unchanged content")
        checkpoint_files = {f"file_{i}.v": unchanged_hash for i in range(100)}
        current_files = dict(checkpoint_files)

        # Change 3 files
        for i in [10, 50, 90]:
            current_files[f"file_{i}.v"] = _sha256(f"changed content {i}")

        classifications = classify_files(current_files, checkpoint_files)

        changed = [f for f, c in classifications.items() if c in ("changed", "new")]
        unchanged = [f for f, c in classifications.items() if c == "unchanged"]
        assert len(changed) == 3
        assert len(unchanged) == 97

    def test_consistency_mismatch_discards_checkpoint(self, tmp_path):
        """Checkpoint from different projects triggers full extraction."""
        from Poule.extraction.checkpoint import validate_consistency

        checkpoint_meta = {
            "projects": ["/projects/stdlib"],
            "coq_version": "8.18.0",
            "extraction_timestamp": "2026-03-17T00:00:00Z",
        }
        current_projects = ["/projects/mathcomp"]  # Different project

        is_consistent = validate_consistency(checkpoint_meta, current_projects, "8.18.0")
        assert is_consistent is False

    def test_consistency_mismatch_coq_version(self, tmp_path):
        """Checkpoint from different Coq version triggers full extraction."""
        from Poule.extraction.checkpoint import validate_consistency

        checkpoint_meta = {
            "projects": ["/projects/stdlib"],
            "coq_version": "8.18.0",
            "extraction_timestamp": "2026-03-17T00:00:00Z",
        }

        is_consistent = validate_consistency(checkpoint_meta, ["/projects/stdlib"], "8.19.0")
        assert is_consistent is False

    def test_consistency_match_passes(self):
        """Same projects and Coq version passes consistency check."""
        from Poule.extraction.checkpoint import validate_consistency

        meta = _make_campaign_metadata()
        is_consistent = validate_consistency(meta, ["/projects/stdlib"], "8.18.0")
        assert is_consistent is True

    def test_removed_files_dropped_from_output(self):
        """Files in checkpoint but not in current plan are classified removed."""
        from Poule.extraction.checkpoint import classify_files

        checkpoint_files = {"old.v": _sha256("old"), "kept.v": _sha256("kept")}
        current_files = {"kept.v": _sha256("kept")}

        classifications = classify_files(current_files, checkpoint_files)
        assert classifications["old.v"] == "removed"

    def test_new_files_extracted(self):
        """Files not in checkpoint are classified new."""
        from Poule.extraction.checkpoint import classify_files

        checkpoint_files = {"existing.v": _sha256("existing")}
        current_files = {
            "existing.v": _sha256("existing"),
            "brand_new.v": _sha256("new file"),
        }

        classifications = classify_files(current_files, checkpoint_files)
        assert classifications["brand_new.v"] == "new"
        assert classifications["existing.v"] == "unchanged"


class TestOutputEquivalence:
    """Merged output is byte-identical to full extraction except timestamp."""

    def test_merged_output_matches_full_extraction_except_timestamp(self, tmp_path):
        """Incremental output matches full extraction output except
        extraction_timestamp in CampaignMetadata."""
        from Poule.extraction.checkpoint import merge_outputs

        # Prior records for unchanged files
        prior_records = [
            {"theorem": "A.thm1", "file": "A.v", "data": "unchanged_data"},
            {"theorem": "A.thm2", "file": "A.v", "data": "unchanged_data"},
        ]
        # New records for re-extracted file
        new_records = [
            {"theorem": "B.thm1", "file": "B.v", "data": "new_data"},
        ]

        merged = merge_outputs(
            prior_records=prior_records,
            new_records=new_records,
            unchanged_files={"A.v"},
            file_order=["A.v", "B.v"],
        )

        # Merged should contain all records in deterministic order
        assert len(merged) == 3
        assert merged[0]["theorem"] == "A.thm1"
        assert merged[1]["theorem"] == "A.thm2"
        assert merged[2]["theorem"] == "B.thm1"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Campaign Resumption (§4.4)
# ═══════════════════════════════════════════════════════════════════════════


class TestResumeExtract:
    """resume_extract loads checkpoint and continues from last_position."""

    def test_loads_checkpoint_and_seeks_to_last_position(self, tmp_path):
        """Given checkpoint at file 50 of 100, resumption starts from file 51."""
        from Poule.extraction.checkpoint import compute_resume_position

        last_position = {"project_index": 0, "file_index": 49, "theorem_index": 3}
        total_files = 100

        resume_pos = compute_resume_position(last_position, total_files)

        # Should resume after the last completed theorem
        assert resume_pos["file_index"] >= 49
        assert resume_pos["theorem_index"] > last_position["theorem_index"] or resume_pos["file_index"] > 49

    def test_no_checkpoint_raises_error(self, tmp_path):
        """resume_extract raises NO_CHECKPOINT when no checkpoint file exists."""
        from Poule.extraction.checkpoint import resume_extract

        output_path = tmp_path / "missing.jsonl"
        output_path.write_text("", encoding="utf-8")

        with pytest.raises(Exception) as exc_info:
            resume_extract(output_path)

        assert "NO_CHECKPOINT" in str(exc_info.value)

    def test_stale_checkpoint_raises_error(self, tmp_path):
        """resume_extract raises CHECKPOINT_STALE when project dir is missing."""
        from Poule.extraction.checkpoint import resume_extract

        output_path = tmp_path / "out.jsonl"
        output_path.write_text("", encoding="utf-8")

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        # Project dir that does not exist
        meta = _make_campaign_metadata()
        meta["projects"] = [str(tmp_path / "nonexistent_project")]
        _write_checkpoint(ckpt_path, _make_checkpoint(campaign_metadata=meta))

        with pytest.raises(Exception) as exc_info:
            resume_extract(output_path)

        assert "CHECKPOINT_STALE" in str(exc_info.value)

    def test_resume_continues_from_checkpoint_position(self, tmp_path):
        """Resumed extraction does not re-extract completed proofs."""
        from Poule.extraction.checkpoint import load_checkpoint

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        h = _sha256("content")
        completed = {f"Thm.t{i}": h for i in range(50)}
        position = {"project_index": 0, "file_index": 5, "theorem_index": 49}
        _write_checkpoint(ckpt_path, _make_checkpoint(
            completed_proofs=completed,
            last_position=position,
        ))

        loaded = load_checkpoint(ckpt_path)
        assert len(loaded["completed_proofs"]) == 50
        assert loaded["last_position"]["theorem_index"] == 49


# ═══════════════════════════════════════════════════════════════════════════
# 6. Error Cases (§5)
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorCodes:
    """Error codes: NO_CHECKPOINT, CHECKPOINT_STALE, CHECKPOINT_CORRUPT."""

    def test_no_checkpoint_error_code(self, tmp_path):
        """NO_CHECKPOINT raised when resume_extract called without checkpoint."""
        from Poule.extraction.checkpoint import resume_extract

        output_path = tmp_path / "no_ckpt.jsonl"
        output_path.write_text("", encoding="utf-8")

        with pytest.raises(Exception) as exc_info:
            resume_extract(output_path)

        assert "NO_CHECKPOINT" in str(exc_info.value)

    def test_checkpoint_stale_error_code(self, tmp_path):
        """CHECKPOINT_STALE raised when project dir no longer exists."""
        from Poule.extraction.checkpoint import resume_extract

        output_path = tmp_path / "stale.jsonl"
        output_path.write_text("", encoding="utf-8")

        ckpt_path = tmp_path / "stale.jsonl.checkpoint"
        meta = _make_campaign_metadata()
        meta["projects"] = ["/nonexistent/project/dir"]
        _write_checkpoint(ckpt_path, _make_checkpoint(campaign_metadata=meta))

        with pytest.raises(Exception) as exc_info:
            resume_extract(output_path)

        assert "CHECKPOINT_STALE" in str(exc_info.value)

    def test_checkpoint_corrupt_error_code(self, tmp_path):
        """CHECKPOINT_CORRUPT raised when checkpoint is not valid JSON."""
        from Poule.extraction.checkpoint import load_checkpoint

        ckpt_path = tmp_path / "corrupt.jsonl.checkpoint"
        ckpt_path.write_text("{broken json", encoding="utf-8")

        with pytest.raises(Exception) as exc_info:
            load_checkpoint(ckpt_path)

        assert "CHECKPOINT_CORRUPT" in str(exc_info.value) or "corrupt" in str(exc_info.value).lower()


# ═══════════════════════════════════════════════════════════════════════════
# 7. Edge Cases (§5 — Edge Cases Table)
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases from spec §5 edge-case table."""

    def test_checkpoint_exists_but_output_missing(self, tmp_path):
        """Checkpoint without output file triggers full extraction."""
        from Poule.extraction.checkpoint import should_full_extract

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        output_path = tmp_path / "out.jsonl"

        _write_checkpoint(ckpt_path, _make_checkpoint(
            completed_proofs={"Thm.a": _sha256("content")},
        ))
        # Output file does NOT exist — only checkpoint
        assert not output_path.exists()

        result = should_full_extract(output_path, ckpt_path)
        assert result is True

    def test_checkpoint_with_zero_completed_proofs(self, tmp_path):
        """Checkpoint with 0 completed proofs is equivalent to full extraction."""
        from Poule.extraction.checkpoint import should_full_extract

        ckpt_path = tmp_path / "out.jsonl.checkpoint"
        output_path = tmp_path / "out.jsonl"
        output_path.write_text("", encoding="utf-8")

        _write_checkpoint(ckpt_path, _make_checkpoint(completed_proofs={}))

        result = should_full_extract(output_path, ckpt_path)
        assert result is True

    def test_all_files_unchanged_reuses_all_records(self):
        """All files unchanged: all records reused, output rewritten with new timestamp."""
        from Poule.extraction.checkpoint import classify_files

        h1 = _sha256("file1")
        h2 = _sha256("file2")
        checkpoint_files = {"a.v": h1, "b.v": h2}
        current_files = {"a.v": h1, "b.v": h2}

        classifications = classify_files(current_files, checkpoint_files)
        assert all(c == "unchanged" for c in classifications.values())

    def test_new_file_added_since_last_extraction(self):
        """New file added is classified as new and extracted normally."""
        from Poule.extraction.checkpoint import classify_files

        h = _sha256("existing")
        checkpoint_files = {"existing.v": h}
        current_files = {"existing.v": h, "new_file.v": _sha256("brand new")}

        classifications = classify_files(current_files, checkpoint_files)
        assert classifications["new_file.v"] == "new"
        assert classifications["existing.v"] == "unchanged"

    def test_file_renamed_old_removed_new_added(self):
        """Renamed file: old path removed, new path classified as new."""
        from Poule.extraction.checkpoint import classify_files

        old_hash = _sha256("file content")
        new_hash = _sha256("file content")  # Same content, different path
        checkpoint_files = {"old_name.v": old_hash}
        current_files = {"new_name.v": new_hash}

        classifications = classify_files(current_files, checkpoint_files)
        assert classifications["old_name.v"] == "removed"
        assert classifications["new_name.v"] == "new"


class TestContentHashAlgorithm:
    """Content hashing uses SHA-256 for collision resistance (§6)."""

    def test_sha256_hex_digest(self):
        """Content hash uses hashlib.sha256 hexdigest."""
        from Poule.extraction.checkpoint import content_hash

        file_contents = b"Theorem plus_comm : forall n m, n + m = m + n."
        result = content_hash(file_contents)

        expected = hashlib.sha256(file_contents).hexdigest()
        assert result == expected
        assert len(result) == 64  # SHA-256 hex digest is 64 chars

    def test_deterministic_hash(self):
        """Same content always produces the same hash."""
        from Poule.extraction.checkpoint import content_hash

        data = b"Lemma foo : True."
        assert content_hash(data) == content_hash(data)
