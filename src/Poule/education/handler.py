"""MCP tool handler for education_context."""

from __future__ import annotations

import json


def handle_education_context(
    ctx,
    *,
    query: str,
    limit: int = 3,
    volume: str | None = None,
) -> dict:
    """Handle the education_context MCP tool call."""
    if ctx.education_rag is None or not ctx.education_rag.is_available():
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "error": "EDUCATION_UNAVAILABLE",
                        "message": "Education database not found or not loaded.",
                    }),
                }
            ],
            "isError": True,
        }

    # Clamp limit
    limit = max(1, min(limit, 10))

    results = ctx.education_rag.search(
        query, limit=limit, volume_filter=volume
    )

    formatted = []
    for r in results:
        formatted.append({
            "text": r.text,
            "code_blocks": r.code_blocks,
            "location": r.location,
            "browser_path": r.browser_path,
            "score": round(r.score, 4),
        })

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"results": formatted}),
            }
        ],
        "isError": False,
    }
