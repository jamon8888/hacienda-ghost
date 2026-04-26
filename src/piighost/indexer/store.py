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
