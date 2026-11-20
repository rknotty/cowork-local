# ADR 0003: Brute-force vector search in NumPy, not sqlite-vec

Status: accepted, 2026-11-19.

## Context

The plan (section 12, knowledge step 4) proposes the sqlite-vec extension and
allows brute-force cosine search in NumPy below about 100,000 chunks if
sqlite-vec has no Arm64 Windows build.

## Decision

Vectors are stored as float32 blobs in the same SQLite file as the FTS5 index,
and searched by cosine similarity in NumPy (`knowledge/index.py`).

## Reasons

- A personal document set is far below 100,000 chunks.
- It removes a native SQLite extension from the dependency list. Loading
  extensions also needs `enable_load_extension`, which some Python builds disable.
- Keyword search (FTS5) and vector search are merged by reciprocal rank fusion
  either way, so swapping the vector half later changes one method.

## Consequences

Search cost grows linearly with chunk count. At 50 documents (the plan's exit
test) it is negligible. Re-measure if the index passes 50,000 chunks.
