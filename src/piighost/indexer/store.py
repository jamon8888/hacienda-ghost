from __future__ import annotations

import re
from pathlib import Path

from piighost.indexer.filters import QueryFilter

_SAFE_DOC_ID_RE = re.compile(r"^[0-9a-f]{1,64}$")


class ChunkStore:
    def __init__(self, lance_path: Path) -> None:
        self._lance_path = lance_path
        self._meta_mode: bool = False
        self._meta: list[dict] = []
        self._db = None
        self._tbl = None

    def upsert_chunks(
        self,
        doc_id: str,
        file_path: str,
        texts: list[str],
        vectors: list[list[float]],
    ) -> None:
        has_vectors = any(v for v in vectors)
        if not has_vectors:
            self._meta_mode = True
            self._meta = [r for r in self._meta if r["doc_id"] != doc_id]
            for i, text in enumerate(texts):
                self._meta.append(
                    {
                        "doc_id": doc_id,
                        "file_path": file_path,
                        "chunk_id": f"{doc_id}:{i}",
                        "chunk": text,
                    }
                )
            return

        import lancedb
        import pyarrow as pa

        self._lance_path.mkdir(parents=True, exist_ok=True)
        if self._db is None:
            self._db = lancedb.connect(str(self._lance_path))

        dim = len(vectors[0])
        records = [
            {
                "doc_id": doc_id,
                "file_path": file_path,
                "chunk_id": f"{doc_id}:{i}",
                "chunk": text,
                "vector": vec,
            }
            for i, (text, vec) in enumerate(zip(texts, vectors))
        ]
        table_name = "chunks"
        if table_name in self._db.list_tables().tables:
            tbl = self._db.open_table(table_name)
            tbl.delete(f"doc_id = '{doc_id}'")
            tbl.add(records)
        else:
            schema = pa.schema(
                [
                    pa.field("doc_id", pa.string()),
                    pa.field("file_path", pa.string()),
                    pa.field("chunk_id", pa.string()),
                    pa.field("chunk", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), dim)),
                ]
            )
            self._tbl = self._db.create_table(table_name, data=records, schema=schema)

    def delete_doc(self, doc_id: str) -> None:
        if self._meta_mode:
            self._meta = [r for r in self._meta if r["doc_id"] != doc_id]
            return
        if self._db is None:
            return
        table_name = "chunks"
        if table_name not in self._db.list_tables().tables:
            return
        tbl = self._db.open_table(table_name)
        if not _SAFE_DOC_ID_RE.fullmatch(doc_id):
            raise ValueError("unsafe doc_id format")
        tbl.delete(f"doc_id = '{doc_id}'")

    def _ensure_db_for_read(self) -> bool:
        """Lazily open the LanceDB connection on read paths.

        ``upsert_chunks`` initializes ``self._db`` when it writes the
        first chunk in this process. But on a daemon restart (or any
        process that READS before WRITING), ``self._db`` stays ``None``
        and ``all_records`` / ``vector_search`` return empty even though
        the chunks are persisted on disk. Open the connection here when
        the lance directory already exists.

        Returns True if a usable db is available after this call.
        """
        if self._db is not None:
            return True
        if not self._lance_path.exists():
            return False
        try:
            import lancedb
        except ImportError:
            return False
        try:
            self._db = lancedb.connect(str(self._lance_path))
        except Exception:
            return False
        return True

    def all_records(self) -> list[dict]:
        if self._meta_mode:
            return list(self._meta)
        if not self._ensure_db_for_read():
            return []
        table_name = "chunks"
        if table_name not in self._db.list_tables().tables:
            return []
        tbl = self._db.open_table(table_name)
        rows = tbl.to_arrow().to_pylist()
        return [{k: v for k, v in r.items() if k != "vector"} for r in rows]

    def chunks_for_doc_ids(self, doc_ids: list[str]) -> list[dict]:
        """Return all chunk records whose ``doc_id`` is in the given list.

        Used by ``subject_access`` (to build excerpts) and
        ``forget_subject`` (to find chunks needing rewrite).

        Returns plain dicts (no ``vector`` field for read-only callers).
        """
        if not doc_ids:
            return []
        if self._meta_mode:
            return [dict(r) for r in self._meta if r["doc_id"] in doc_ids]
        if not self._ensure_db_for_read():
            return []
        table_name = "chunks"
        if table_name not in self._db.list_tables().tables:
            return []
        tbl = self._db.open_table(table_name)
        # Validate doc_ids against the safe-id pattern to avoid SQL injection
        # in the Lance WHERE clause.
        safe_ids = []
        for d in doc_ids:
            if not _SAFE_DOC_ID_RE.fullmatch(d):
                raise ValueError(f"unsafe doc_id format: {d!r}")
            safe_ids.append(d)
        in_clause = ", ".join(f"'{d}'" for d in safe_ids)
        rows = tbl.search().where(f"doc_id IN ({in_clause})").to_list()
        return [{k: v for k, v in r.items() if k != "vector"} for r in rows]

    def update_chunks(
        self, updates: list[tuple[dict, str, list[float]]],
    ) -> None:
        """Update existing chunks in place.

        ``updates`` is a list of ``(chunk_record, new_text, new_vector)``
        tuples. ``chunk_record`` is the dict you got from
        ``chunks_for_doc_ids`` — it carries the ``chunk_id``,
        ``doc_id``, and ``file_path`` we need to rewrite the entry
        while preserving identity at the (doc_id, chunk_id) level.

        For LanceDB, in-place update is achieved via DELETE + INSERT
        on the chunk_id, so the row keeps the same chunk_id from the
        consumer's perspective. For ``_meta_mode``, mutate the
        in-memory list in place.
        """
        if not updates:
            return
        if self._meta_mode:
            for record, new_text, _new_vec in updates:
                target_id = record.get("chunk_id")
                target_doc = record.get("doc_id")
                for r in self._meta:
                    if r.get("chunk_id") == target_id and r.get("doc_id") == target_doc:
                        r["chunk"] = new_text
                        break
            return
        if not self._ensure_db_for_read():
            return
        table_name = "chunks"
        if table_name not in self._db.list_tables().tables:
            return
        tbl = self._db.open_table(table_name)
        for record, new_text, new_vector in updates:
            chunk_id = record.get("chunk_id")
            doc_id = record.get("doc_id")
            if not chunk_id or not doc_id:
                continue
            if not _SAFE_DOC_ID_RE.fullmatch(doc_id):
                raise ValueError(f"unsafe doc_id format: {doc_id!r}")
            # chunk_id format is "{doc_id}:{i}" — escape single quotes
            esc_chunk_id = chunk_id.replace("'", "''")
            tbl.delete(f"chunk_id = '{esc_chunk_id}'")
            new_record = {
                "doc_id": doc_id,
                "file_path": record.get("file_path", ""),
                "chunk_id": chunk_id,
                "chunk": new_text,
                "vector": new_vector,
            }
            tbl.add([new_record])

    def vector_search(
        self,
        embedding: list[float],
        *,
        k: int = 5,
        filter: QueryFilter | None = None,
    ) -> list[dict]:
        if self._meta_mode or not embedding:
            return []
        if not self._ensure_db_for_read():
            return []
        table_name = "chunks"
        if table_name not in self._db.list_tables().tables:
            return []
        tbl = self._db.open_table(table_name)
        search = tbl.search(embedding)
        if filter is not None and not filter.is_empty():
            where = filter.to_lance_where()
            if where:
                search = search.where(where)
        results = search.limit(k).to_list()
        return [{k: v for k, v in r.items() if k != "vector"} for r in results]
