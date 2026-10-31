"""Re-embed chunk rows whose vector is NULL or was made by another embedding model (idempotent; safe to re-run).

  cd backend && python3 scripts/reindex_embeddings.py [--client jft] [--dry-run]

Needs CLIENT_PROFILING_EMBED_URL / _MODEL / _API_KEY (read from the environment or ../.env). Covers cp_note_chunks and
cp_ips_chunks (and cp_guide_chunks without --client). Text and tsvector are untouched; only embedding + embed_model change.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

from app.agents.client_profiling import embeddings  # noqa: E402
from app.agents.client_profiling.store_pg import PostgresStore  # noqa: E402

BATCH = 64


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", help="only this client id (notes + IPS)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    st = embeddings.status()
    if not st["dense"]:
        print("Dense retrieval is OFF: set CLIENT_PROFILING_EMBED_URL, CLIENT_PROFILING_EMBED_MODEL and CLIENT_PROFILING_EMBED_API_KEY.")
        return 2
    store = PostgresStore()
    if not store.vector_enabled:
        print("pgvector / chunk tables unavailable.")
        return 2
    model, total, failed = embeddings.embed_model(), 0, 0
    tables = [("cp_note_chunks", "text"), ("cp_ips_chunks", "text")] + ([] if a.client else [("cp_guide_chunks", "heading || '. ' || text")])
    with store._connect() as conn:
        for table, expr in tables:
            where, params = "(embedding IS NULL OR embed_model IS DISTINCT FROM %s)", [model]
            if a.client and table != "cp_guide_chunks":
                where, params = where + " AND client_id = %s", params + [a.client]
            rows = conn.execute(f"SELECT id, {expr} AS t FROM {table} WHERE {where} ORDER BY id", params).fetchall()
            print(f"{table}: {len(rows)} rows to embed with {model}")
            if a.dry_run:
                continue
            for i in range(0, len(rows), BATCH):
                batch = rows[i:i + BATCH]
                vecs = embeddings.embed_documents([r["t"] for r in batch])
                if vecs is None:
                    failed += len(batch)
                    print(f"  batch {i // BATCH} failed (endpoint error / wrong dimension {embeddings.DIMS}); rows left unchanged")
                    continue
                for r, v in zip(batch, vecs):
                    conn.execute(f"UPDATE {table} SET embedding = %s::vector, embed_model = %s WHERE id = %s",
                                 (embeddings.vector_literal(v), model, r["id"]))
                total += len(batch)
    print(f"done: {total} re-embedded, {failed} failed. status: {store.retrieval_status()}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
