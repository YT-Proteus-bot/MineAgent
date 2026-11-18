"""向量库适配层：一套接口，覆盖内置 SQLite 与主流外部库。

统一接口：
    ensure_collection(name, dim, metric)   建集合 + 维度/模型校验
    upsert(name, items)                    items: [{id, text, vector, metadata}]
    search(name, vector, top_k, where)     -> [{id, text, score, metadata}]
    delete(name, ids) / drop(name) / count(name) / probe()

约定：
- search 的 score 统一成「越大越相似」，各库的 distance 在这里换算。
- 一律懒加载，缺库抛 ProviderUnavailable（带 pip 命令）。
- 维度不一致直接报错并给重建指引，避免「索引用 A 模型、查询用 B 模型」这种灾难。

status=planned 的库还没实现，get_store 会明确告知，而不是静默降级。
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (as_float, as_int, http_json, join_url, lazy_import,
                   load_json_ish, require, split_host_port)
from .base import dist_to_score as _dist_to_score
from .base import match_where as _match_where
from .base import norm_metric as _norm_metric
from .base import safe_ident as _safe_ident
from .base import vec_to_literal as _vec_to_literal
from .catalog import find
from .errors import ProviderCallError, ProviderConfigError


# --------------------------------------------------------------------------- #
# 公共工具
# --------------------------------------------------------------------------- #

class BaseStore:
    """所有向量库适配器的基类。"""

    protocol = "base"
    pip = ""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg or {}
        self.metric = _norm_metric(self.cfg.get("metric", "cosine"))
        self.collection = _safe_ident(self.cfg.get("collection") or "default")
        base_dir = self.cfg.get("base_dir") or os.getcwd()
        self.base_dir = Path(str(base_dir))

    # 子类按需覆盖 ---------------------------------------------------------
    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        raise NotImplementedError

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        raise NotImplementedError

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def delete(self, name: str, ids: List[str]) -> int:
        return 0

    def drop(self, name: str) -> None:
        return None

    def count(self, name: str) -> int:
        return 0

    def probe(self) -> Dict[str, Any]:
        return {"ok": True, "message": f"{self.protocol} 可用"}

    # ------------------------------------------------------------------ 辅助
    def resolve_name(self, name: str = "") -> str:
        return _safe_ident(name or self.collection)

    def _missing(self, module: str, pip: str = "") -> Any:
        return lazy_import(module, pip or self.pip or module)


# --------------------------------------------------------------------------- #
# 内置 SQLite（零依赖兜底，也是默认实现）
# --------------------------------------------------------------------------- #
class SQLiteStore(BaseStore):
    protocol = "sqlite"

    def __init__(self, cfg: Dict[str, Any]) -> None:
        super().__init__(cfg)
        rel = self.cfg.get("path") or ".store.db"
        path = Path(str(rel))
        self.path = path if path.is_absolute() else (self.base_dir / path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        with self._lock:
            if self._conn is None:
                # check_same_thread=False：节点可能在不同线程里执行（超时用线程包装），
                # 适配器实例是共享的，不能把连接绑死在创建它的线程上
                conn = sqlite3.connect(str(self.path), timeout=15,
                                       check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS vector_collections(
                        collection TEXT PRIMARY KEY,
                        dim        INTEGER NOT NULL DEFAULT 0,
                        metric     TEXT NOT NULL DEFAULT 'cosine',
                        model      TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS vector_items(
                        collection TEXT NOT NULL,
                        id         TEXT NOT NULL,
                        text       TEXT NOT NULL DEFAULT '',
                        vector     TEXT NOT NULL,
                        metadata   TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL DEFAULT '',
                        PRIMARY KEY (collection, id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_vector_items_col
                        ON vector_items(collection);
                    """
                )
                conn.commit()
                self._conn = conn
        return self._conn

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        col = self.resolve_name(name)
        row = self.conn.execute(
            "SELECT dim, model FROM vector_collections WHERE collection = ?",
            (col,)).fetchone()
        if row and int(row["dim"] or 0) and dim and int(row["dim"]) != dim:
            raise ProviderConfigError(
                f"集合 {col} 已存在且维度是 {row['dim']}，与当前模型的 {dim} 维不一致",
                hint="换模型必须重建索引：先清空该集合，再用新模型重新入库")
        self.conn.execute(
            "INSERT INTO vector_collections(collection, dim, metric, model, updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(collection) DO UPDATE SET "
            "dim=excluded.dim, metric=excluded.metric, model=excluded.model, "
            "updated_at=excluded.updated_at",
            (col, int(dim or 0), metric or self.metric, model or "", _now()))
        self.conn.commit()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        col = self.resolve_name(name)
        rows = []
        for item in items:
            rows.append((col, str(item.get("id") or _rand_id()), str(item.get("text") or ""),
                         json.dumps([float(x) for x in item.get("vector") or []]),
                         json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                         _now()))
        self.conn.executemany(
            "INSERT INTO vector_items(collection, id, text, vector, metadata, created_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(collection, id) DO UPDATE SET "
            "text=excluded.text, vector=excluded.vector, metadata=excluded.metadata",
            rows)
        self.conn.commit()
        return len(rows)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        col = self.resolve_name(name)
        query = [float(x) for x in vector or []]
        scored: List[Dict[str, Any]] = []
        for row in self.conn.execute(
                "SELECT id, text, vector, metadata FROM vector_items WHERE collection = ?",
                (col,)):
            try:
                vec = json.loads(row["vector"])
            except Exception:  # noqa: BLE001
                continue
            if not vec or len(vec) != len(query):
                continue
            meta = _load_json(row["metadata"])
            if where and not _match_where(meta, where):
                continue
            sim = _similarity(query, vec, self.metric)
            scored.append({"id": row["id"], "text": row["text"],
                           "score": round(sim, 6), "metadata": meta})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max(1, int(top_k))]

    def delete(self, name: str, ids: List[str]) -> int:
        col = self.resolve_name(name)
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"DELETE FROM vector_items WHERE collection = ? AND id IN ({marks})",
            [col, *[str(i) for i in ids]])
        self.conn.commit()
        return cur.rowcount

    def drop(self, name: str) -> None:
        col = self.resolve_name(name)
        self.conn.execute("DELETE FROM vector_items WHERE collection = ?", (col,))
        self.conn.execute("DELETE FROM vector_collections WHERE collection = ?", (col,))
        self.conn.commit()

    def count(self, name: str) -> int:
        col = self.resolve_name(name)
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM vector_items WHERE collection = ?",
            (col,)).fetchone()
        return int(row["n"] if row else 0)

    def probe(self) -> Dict[str, Any]:
        n = self.conn.execute("SELECT COUNT(*) AS n FROM vector_items").fetchone()
        return {"ok": True, "message": f"内置向量表可用（{self.path.name}，共 "
                                       f"{int(n['n'] if n else 0)} 条）"}


# --------------------------------------------------------------------------- #
# Chroma
# --------------------------------------------------------------------------- #
class ChromaStore(BaseStore):
    protocol = "chroma"
    pip = "chromadb"

    def _client(self):
        chromadb = self._missing("chromadb")
        url = (self.cfg.get("url") or "").strip()
        if url:
            parts = urllib.parse.urlsplit(url if "://" in url else f"http://{url}")
            kwargs: Dict[str, Any] = {
                "host": parts.hostname or "127.0.0.1",
                "port": parts.port or (443 if parts.scheme == "https" else 8000),
                "ssl": parts.scheme == "https",
            }
            if self.cfg.get("api_key"):
                kwargs["headers"] = {"Authorization": f"Bearer {self.cfg['api_key']}"}
            if self.cfg.get("tenant"):
                kwargs["tenant"] = self.cfg["tenant"]
            if self.cfg.get("database"):
                kwargs["database"] = self.cfg["database"]
            return chromadb.HttpClient(**kwargs)
        persist = (self.cfg.get("persist_directory") or "").strip()
        path = Path(persist) if persist else (self.base_dir / ".chroma")
        if not path.is_absolute():
            path = self.base_dir / path
        path.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(path))

    def _collection(self, name: str, dim: int = 0, create: bool = True):
        client = self._client()
        col = self.resolve_name(name)
        # Chroma 的 hnsw:space 用 cosine / l2 / ip
        space = {"cosine": "cosine", "dot": "ip", "euclidean": "l2"}[self.metric]
        try:
            return client.get_collection(col)
        except Exception:  # noqa: BLE001
            if not create:
                raise
            return client.create_collection(col, metadata={"hnsw:space": space})

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        self._collection(name, dim, create=True)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        col = self._collection(name)
        ids = [str(it.get("id") or _rand_id()) for it in items]
        col.upsert(
            ids=ids,
            embeddings=[[float(x) for x in it.get("vector") or []] for it in items],
            documents=[str(it.get("text") or "") for it in items],
            metadatas=[_flat_meta(it.get("metadata")) for it in items],
        )
        return len(ids)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        col = self._collection(name, create=False)
        kwargs: Dict[str, Any] = {
            "query_embeddings": [[float(x) for x in vector]],
            "n_results": max(1, int(top_k)),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        res = col.query(**kwargs)
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out = []
        for i, vid in enumerate(ids):
            dist = dists[i] if i < len(dists) else 0.0
            out.append({
                "id": vid,
                "text": docs[i] if i < len(docs) else "",
                "score": round(_dist_to_score(dist, self.metric), 6),
                "metadata": metas[i] if i < len(metas) else {},
            })
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        col = self._collection(name, create=False)
        col.delete(ids=[str(i) for i in ids])
        return len(ids)

    def drop(self, name: str) -> None:
        self._client().delete_collection(self.resolve_name(name))

    def count(self, name: str) -> int:
        return int(self._collection(name, create=False).count())

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        names = [c.name for c in client.list_collections()]
        mode = "远程" if self.cfg.get("url") else "本地"
        return {"ok": True, "message": f"Chroma 连接成功（{mode}），现有 {len(names)} 个集合"}


# --------------------------------------------------------------------------- #
# PostgreSQL + pgvector
# --------------------------------------------------------------------------- #
class PgVectorStore(BaseStore):
    protocol = "pgvector"
    pip = "psycopg2-binary"

    def _connect(self):
        dsn = require(self.cfg, "dsn", label="连接串")
        try:
            psycopg2 = lazy_import("psycopg2", "psycopg2-binary")
            return psycopg2.connect(dsn, connect_timeout=10)
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ == "ProviderUnavailable":
                psycopg = lazy_import("psycopg", "psycopg[binary]")
                return psycopg.connect(dsn, connect_timeout=10)
            raise

    @property
    def table(self) -> str:
        return _safe_ident(self.cfg.get("table") or "mineagent_vectors")

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self.table}("
                "  collection TEXT NOT NULL,"
                "  id TEXT NOT NULL,"
                "  text TEXT NOT NULL DEFAULT '',"
                "  embedding vector,"
                "  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,"
                "  PRIMARY KEY (collection, id))")
            # 维度校验：pgvector 的列没有固定维度限制，这里靠元信息比对
            cur.execute(
                f"SELECT atttypmod FROM pg_attribute WHERE attrelid = "
                f"'{self.table}'::regclass AND attname = 'embedding'")
            ops = {"cosine": "vector_cosine_ops", "dot": "vector_ip_ops",
                   "euclidean": "vector_l2_ops"}[self.metric]
            idx = f"{self.table}_emb_idx"
            index_kind = (self.cfg.get("index") or "hnsw").lower()
            if index_kind == "hnsw":
                cur.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON {self.table} "
                            f"USING hnsw (embedding {ops})")
            elif index_kind == "ivfflat":
                cur.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON {self.table} "
                            f"USING ivfflat (embedding {ops}) WITH (lists = 100)")
            conn.commit()
        finally:
            conn.close()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            for it in items:
                cur.execute(
                    f"INSERT INTO {self.table}(collection, id, text, embedding, metadata) "
                    "VALUES(%s,%s,%s,%s::vector,%s::jsonb) "
                    "ON CONFLICT (collection, id) DO UPDATE SET "
                    "text=EXCLUDED.text, embedding=EXCLUDED.embedding, "
                    "metadata=EXCLUDED.metadata",
                    (self.resolve_name(name), str(it.get("id") or _rand_id()),
                     str(it.get("text") or ""),
                     _vec_to_literal(it.get("vector") or []),
                     json.dumps(it.get("metadata") or {}, ensure_ascii=False)))
            conn.commit()
            return len(items)
        finally:
            conn.close()

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        operator = {"cosine": "<=>", "dot": "<#>", "euclidean": "<->"}[self.metric]
        col = self.resolve_name(name)
        params: List[Any] = [_vec_to_literal(vector), col]
        sql = (f"SELECT id, text, metadata, embedding {operator} %s::vector AS dist "
               f"FROM {self.table} WHERE collection = %s")
        if where:
            sql += " AND metadata @> %s::jsonb"
            params.append(json.dumps(where, ensure_ascii=False))
        sql += " ORDER BY dist ASC LIMIT %s"
        params.append(max(1, int(top_k)))
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            out = []
            for row in cur.fetchall():
                dist = float(row[3])
                out.append({"id": row[0], "text": row[1], "metadata": _load_json(row[2]),
                            "score": round(_dist_to_score(dist, self.metric), 6)})
            return out
        finally:
            conn.close()

    def delete(self, name: str, ids: List[str]) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM {self.table} WHERE collection = %s AND id = ANY(%s)",
                        (self.resolve_name(name), [str(i) for i in ids]))
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def drop(self, name: str) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM {self.table} WHERE collection = %s",
                        (self.resolve_name(name),))
            conn.commit()
        finally:
            conn.close()

    def count(self, name: str) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {self.table} WHERE collection = %s",
                        (self.resolve_name(name),))
            return int(cur.fetchone()[0])
        finally:
            conn.close()

    def probe(self) -> Dict[str, Any]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            row = cur.fetchone()
            if not row:
                return {"ok": False, "message": "连上了 PostgreSQL，但没有安装 pgvector 扩展",
                        "hint": "在库里执行：CREATE EXTENSION vector;"}
            return {"ok": True, "message": f"PostgreSQL + pgvector {row[0]} 连接成功"}
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Qdrant
# --------------------------------------------------------------------------- #
class QdrantStore(BaseStore):
    protocol = "qdrant"
    pip = "qdrant-client"

    def _client(self):
        qc = self._missing("qdrant_client")
        url = require(self.cfg, "url", label="服务地址")
        kwargs: Dict[str, Any] = {"url": url, "timeout": 30}
        if self.cfg.get("api_key"):
            kwargs["api_key"] = self.cfg["api_key"]
        return qc.QdrantClient(**kwargs)

    @property
    def _distance(self):
        qc = self._missing("qdrant_client")
        return {"cosine": qc.models.Distance.COSINE,
                "dot": qc.models.Distance.DOT,
                "euclidean": qc.models.Distance.EUCLID}[self.metric]

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        qc = self._missing("qdrant_client")
        client = self._client()
        col = self.resolve_name(name)
        try:
            client.get_collection(col)
            return
        except Exception:  # noqa: BLE001
            pass
        client.create_collection(
            collection_name=col,
            vectors_config=qc.models.VectorParams(size=int(dim), distance=self._distance))

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        qc = self._missing("qdrant_client")
        client = self._client()
        points = []
        for it in items:
            payload = {**(it.get("metadata") or {}), "text": str(it.get("text") or "")}
            points.append(qc.models.PointStruct(
                id=str(it.get("id") or _rand_id()),
                vector=[float(x) for x in it.get("vector") or []],
                payload=payload))
        client.upsert(collection_name=self.resolve_name(name), points=points)
        return len(points)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        qc = self._missing("qdrant_client")
        client = self._client()
        col = self.resolve_name(name)
        qfilter = None
        if where:
            must = [qc.models.FieldCondition(key=k, match=qc.models.MatchValue(value=v))
                    for k, v in where.items()]
            qfilter = qc.models.Filter(must=must)
        limit = max(1, int(top_k))
        # 新版用 query_points，旧版只有 search
        if hasattr(client, "query_points"):
            res = client.query_points(collection_name=col, query=vector,
                                      limit=limit, query_filter=qfilter,
                                      with_payload=True).points
        else:
            res = client.search(collection_name=col, query_vector=vector,
                                limit=limit, query_filter=qfilter)
        out = []
        for hit in res:
            payload = dict(getattr(hit, "payload", {}) or {})
            text = payload.pop("text", "")
            out.append({"id": str(getattr(hit, "id", "")), "text": text,
                        "score": round(float(getattr(hit, "score", 0.0)), 6),
                        "metadata": payload})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        qc = self._missing("qdrant_client")
        client = self._client()
        client.delete(collection_name=self.resolve_name(name),
                      points_selector=qc.models.PointIdsList(points=[str(i) for i in ids]))
        return len(ids)

    def drop(self, name: str) -> None:
        self._client().delete_collection(self.resolve_name(name))

    def count(self, name: str) -> int:
        info = self._client().get_collection(self.resolve_name(name))
        return int(getattr(info, "points_count", 0) or 0)

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        cols = client.get_collections().collections
        return {"ok": True, "message": f"Qdrant 连接成功，现有 {len(cols)} 个集合"}


# --------------------------------------------------------------------------- #
# Milvus / Zilliz
# --------------------------------------------------------------------------- #
class MilvusStore(BaseStore):
    protocol = "milvus"
    pip = "pymilvus"

    def _client(self):
        pm = self._missing("pymilvus")
        uri = require(self.cfg, "uri", label="服务地址")
        kwargs: Dict[str, Any] = {"uri": uri}
        if self.cfg.get("token"):
            kwargs["token"] = self.cfg["token"]
        if self.cfg.get("db_name"):
            kwargs["db_name"] = self.cfg["db_name"]
        return pm.MilvusClient(**kwargs)

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        client = self._client()
        col = self.resolve_name(name)
        if client.has_collection(col):
            return
        metric_type = {"cosine": "COSINE", "dot": "IP",
                       "euclidean": "L2"}[self.metric]
        client.create_collection(
            collection_name=col, dimension=int(dim), metric_type=metric_type,
            auto_id=False, id_type="varchar", max_length=512,
            enable_dynamic_field=True)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        client = self._client()
        rows = []
        for it in items:
            rows.append({
                "id": str(it.get("id") or _rand_id()),
                "vector": [float(x) for x in it.get("vector") or []],
                "text": str(it.get("text") or ""),
                "metadata": json.dumps(it.get("metadata") or {}, ensure_ascii=False),
            })
        client.upsert(collection_name=self.resolve_name(name), data=rows)
        return len(rows)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        client = self._client()
        expr = ""
        if where:
            expr = " and ".join(
                f'metadata like "%{k}%{v}%"' for k, v in where.items())
        res = client.search(
            collection_name=self.resolve_name(name),
            data=[[float(x) for x in vector]],
            limit=max(1, int(top_k)),
            output_fields=["text", "metadata"],
            filter=expr or "",
        )
        out = []
        for group in res or []:
            for hit in group:
                entity = hit.get("entity") or {}
                out.append({
                    "id": str(hit.get("id", "")),
                    "text": entity.get("text", ""),
                    "score": round(float(hit.get("distance", 0.0)), 6),
                    "metadata": _load_json(entity.get("metadata")),
                })
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        client = self._client()
        client.delete(collection_name=self.resolve_name(name),
                      ids=[str(i) for i in ids])
        return len(ids)

    def drop(self, name: str) -> None:
        self._client().drop_collection(self.resolve_name(name))

    def count(self, name: str) -> int:
        client = self._client()
        stats = client.get_collection_stats(self.resolve_name(name))
        return int(stats.get("row_count", 0) or 0)

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        cols = client.list_collections()
        return {"ok": True, "message": f"Milvus 连接成功，现有 {len(cols)} 个集合"}


# --------------------------------------------------------------------------- #
# Weaviate（走 REST，不绑定 client 版本）
# --------------------------------------------------------------------------- #
class WeaviateStore(BaseStore):
    protocol = "weaviate"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "url", label="服务地址").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        headers = {}
        if self.cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {self.cfg['api_key']}"
        return headers

    def _class_name(self, name: str) -> str:
        col = self.resolve_name(name)
        return col[:1].upper() + col[1:]

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        cls = self._class_name(name)
        try:
            http_json(join_url(self._base(), f"v1/schema/{cls}"), method="GET",
                      headers=self._headers(), timeout=15)
            return
        except ProviderCallError as exc:
            if exc.status != 404:
                raise
        http_json(join_url(self._base(), "v1/schema"), {
            "class": cls,
            "vectorizer": "none",
            "vectorIndexConfig": {"distance": {"cosine": "cosine", "dot": "dot",
                                               "euclidean": "l2-squared"}[self.metric]},
            "properties": [
                {"name": "text", "dataType": ["text"]},
                {"name": "metadata", "dataType": ["text"]},
            ],
        }, headers=self._headers(), timeout=20)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        cls = self._class_name(name)
        objects = [{
            "class": cls,
            "id": _uuid5(str(it.get("id") or _rand_id())),
            "vector": [float(x) for x in it.get("vector") or []],
            "properties": {"text": str(it.get("text") or ""),
                           "metadata": json.dumps(it.get("metadata") or {},
                                                  ensure_ascii=False)},
        } for it in items]
        http_json(join_url(self._base(), "v1/batch/objects"), {"objects": objects},
                  headers=self._headers(), timeout=60)
        return len(objects)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        cls = self._class_name(name)
        query = ("{Get {" + cls + "(nearVector: {vector: "
                 + _vec_to_literal(vector) + "}, limit: " + str(max(1, int(top_k)))
                 + ") {text metadata _additional {id distance}}}}")
        data = http_json(join_url(self._base(), "v1/graphql"), {"query": query},
                         headers=self._headers(), timeout=30)
        rows = (((data.get("data") or {}).get("Get") or {}).get(cls) or [])
        out = []
        for row in rows:
            extra = row.get("_additional") or {}
            dist = float(extra.get("distance") or 0.0)
            out.append({"id": str(extra.get("id", "")), "text": row.get("text", ""),
                        "score": round(_dist_to_score(dist, self.metric), 6),
                        "metadata": _load_json(row.get("metadata"))})
        out.sort(key=lambda x: x["score"], reverse=True)
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        cls = self._class_name(name)
        for vid in ids:
            try:
                http_json(join_url(self._base(), f"v1/objects/{cls}/{_uuid5(str(vid))}"),
                          method="DELETE", headers=self._headers(), timeout=15)
            except ProviderCallError:
                continue
        return len(ids)

    def drop(self, name: str) -> None:
        try:
            http_json(join_url(self._base(), f"v1/schema/{self._class_name(name)}"),
                      method="DELETE", headers=self._headers(), timeout=20)
        except ProviderCallError:
            pass

    def probe(self) -> Dict[str, Any]:
        data = http_json(join_url(self._base(), "v1/meta"), method="GET",
                         headers=self._headers(), timeout=15)
        version = data.get("version", "unknown")
        return {"ok": True, "message": f"Weaviate 连接成功（版本 {version}）"}


# --------------------------------------------------------------------------- #
# LanceDB
# --------------------------------------------------------------------------- #
class LanceDBStore(BaseStore):
    protocol = "lancedb"
    pip = "lancedb"

    def _db(self):
        lancedb = self._missing("lancedb")
        uri = str(self.cfg.get("uri") or "./.lancedb")
        if "://" not in uri:
            path = Path(uri)
            uri = str(path if path.is_absolute() else (self.base_dir / path))
        return lancedb.connect(uri)

    def _table(self, name: str):
        db = self._db()
        col = self.resolve_name(name)
        names = list(db.table_names())
        if col in names:
            return db.open_table(col)
        return None

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        # LanceDB 在第一次写入时建表，这里只做存在性检查
        if self._table(name) is None:
            self._pending_dim = int(dim)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        db = self._db()
        col = self.resolve_name(name)
        rows = [{
            "id": str(it.get("id") or _rand_id()),
            "vector": [float(x) for x in it.get("vector") or []],
            "text": str(it.get("text") or ""),
            "metadata": json.dumps(it.get("metadata") or {}, ensure_ascii=False),
        } for it in items]
        if col in list(db.table_names()):
            db.open_table(col).add(rows)
        else:
            db.create_table(col, data=rows)
        return len(rows)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        table = self._table(name)
        if table is None:
            return []
        metric = {"cosine": "cosine", "dot": "dot", "euclidean": "l2"}[self.metric]
        query = table.search([float(x) for x in vector]).metric(metric).limit(
            max(1, int(top_k)))
        rows = query.to_list()
        out = []
        for row in rows:
            dist = float(row.get("_distance", 0.0))
            out.append({"id": str(row.get("id", "")), "text": row.get("text", ""),
                        "score": round(_dist_to_score(dist, self.metric), 6),
                        "metadata": _load_json(row.get("metadata"))})
        return out

    def count(self, name: str) -> int:
        table = self._table(name)
        return int(table.count_rows()) if table is not None else 0

    def drop(self, name: str) -> None:
        try:
            self._db().drop_table(self.resolve_name(name))
        except Exception:  # noqa: BLE001
            pass

    def probe(self) -> Dict[str, Any]:
        db = self._db()
        return {"ok": True, "message": f"LanceDB 连接成功，现有 {len(db.table_names())} 张表"}


# --------------------------------------------------------------------------- #
# FAISS（索引 + 旁路元数据 json）
# --------------------------------------------------------------------------- #
class FAISSStore(BaseStore):
    protocol = "faiss"
    pip = "faiss-cpu"

    def _paths(self):
        rel = str(self.cfg.get("index_path") or ".faiss/index.bin")
        path = Path(rel)
        if not path.is_absolute():
            path = self.base_dir / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path, path.with_suffix(path.suffix + ".meta.json")

    def _load(self, dim: int = 0):
        faiss = self._missing("faiss")
        numpy = self._missing("numpy")
        index_path, meta_path = self._paths()
        if index_path.exists() and dim <= 0:
            index = faiss.read_index(str(index_path))
        else:
            if dim <= 0:
                raise ProviderConfigError("FAISS 索引还不存在，首次建库需要知道向量维度",
                                          hint="先做一次向量化，或把 dim 填上")
            base = (faiss.IndexFlatIP(int(dim)) if self.metric == "dot"
                    else faiss.IndexFlatL2(int(dim)))
            index = base
        meta = _load_json(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else []
        return faiss, numpy, index, meta, index_path, meta_path

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        faiss, numpy, index, meta, index_path, meta_path = self._load(dim)
        faiss.write_index(index, str(index_path))
        if not meta_path.exists():
            meta_path.write_text("[]", encoding="utf-8")

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        faiss, numpy, index, meta, index_path, meta_path = self._load(
            len(items[0].get("vector") or []) if items else 0)
        vectors = []
        for it in items:
            vec = [float(x) for x in it.get("vector") or []]
            if self.metric == "cosine":
                norm = math.sqrt(sum(v * v for v in vec)) or 1.0
                vec = [v / norm for v in vec]
            vectors.append(vec)
            meta.append({"id": str(it.get("id") or _rand_id()),
                         "text": str(it.get("text") or ""),
                         "metadata": it.get("metadata") or {}})
        if vectors:
            index.add(numpy.asarray(vectors, dtype="float32"))
        faiss.write_index(index, str(index_path))
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return len(vectors)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        faiss, numpy, index, meta, _, _ = self._load()
        if index.ntotal == 0:
            return []
        query = [float(x) for x in vector]
        if self.metric == "cosine":
            norm = math.sqrt(sum(v * v for v in query)) or 1.0
            query = [v / norm for v in query]
        k = max(1, int(top_k))
        distances, indices = index.search(numpy.asarray([query], dtype="float32"), k)
        out = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(meta):
                continue
            row = meta[idx]
            if where and not _match_where(row.get("metadata") or {}, where):
                continue
            score = float(dist) if self.metric == "dot" else _dist_to_score(
                float(dist), self.metric)
            out.append({"id": row.get("id", ""), "text": row.get("text", ""),
                        "score": round(score, 6), "metadata": row.get("metadata") or {}})
        return out

    def count(self, name: str) -> int:
        try:
            _, _, index, _, _, _ = self._load()
            return int(index.ntotal)
        except Exception:  # noqa: BLE001
            return 0

    def probe(self) -> Dict[str, Any]:
        self._missing("faiss")
        self._missing("numpy")
        index_path, _ = self._paths()
        return {"ok": True, "message": f"FAISS 可用（索引文件 {index_path.name}）"}


# --------------------------------------------------------------------------- #
# Pinecone
# --------------------------------------------------------------------------- #
class PineconeStore(BaseStore):
    protocol = "pinecone"
    pip = "pinecone"

    def _index(self):
        pc_mod = self._missing("pinecone")
        api_key = require(self.cfg, "api_key", label="API Key")
        host = require(self.cfg, "index_host", label="Index Host")
        client = (getattr(pc_mod, "Pinecone", None) or pc_mod)(api_key=api_key)
        return client.Index(host=host)

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        # Serverless 索引在控制台建，这里只校验 namespace 可写
        return None

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        index = self._index()
        vectors = []
        for it in items:
            vectors.append({
                "id": str(it.get("id") or _rand_id()),
                "values": [float(x) for x in it.get("vector") or []],
                "metadata": {**(it.get("metadata") or {}),
                             "text": str(it.get("text") or "")},
            })
        index.upsert(vectors=vectors, namespace=self.resolve_name(name))
        return len(vectors)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        index = self._index()
        res = index.query(vector=[float(x) for x in vector],
                          top_k=max(1, int(top_k)),
                          include_metadata=True,
                          filter=where or None,
                          namespace=self.resolve_name(name))
        out = []
        for match in (res.get("matches") or []):
            meta = dict(match.get("metadata") or {})
            text = meta.pop("text", "")
            out.append({"id": str(match.get("id", "")), "text": text,
                        "score": round(float(match.get("score", 0.0)), 6),
                        "metadata": meta})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        self._index().delete(ids=[str(i) for i in ids],
                             namespace=self.resolve_name(name))
        return len(ids)

    def drop(self, name: str) -> None:
        try:
            self._index().delete(delete_all=True,
                                 namespace=self.resolve_name(name))
        except Exception:  # noqa: BLE001
            pass

    def probe(self) -> Dict[str, Any]:
        index = self._index()
        stats = index.describe_index_stats()
        total = stats.get("total_vector_count", 0)
        return {"ok": True, "message": f"Pinecone 连接成功，索引内共 {total} 条向量"}


# --------------------------------------------------------------------------- #
# Elasticsearch
# --------------------------------------------------------------------------- #
class ElasticsearchStore(BaseStore):
    protocol = "elasticsearch"
    pip = "elasticsearch"

    def _client(self):
        es_mod = self._missing("elasticsearch")
        url = require(self.cfg, "url", label="服务地址")
        kwargs: Dict[str, Any] = {"hosts": [url], "request_timeout": 30}
        if self.cfg.get("username"):
            kwargs["basic_auth"] = (self.cfg["username"], self.cfg.get("password") or "")
        return es_mod.Elasticsearch(**kwargs)

    @property
    def index(self) -> str:
        return _safe_ident(self.cfg.get("index") or "mineagent").lower()

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        client = self._client()
        similarity = {"cosine": "cosine", "dot": "dot_product",
                      "euclidean": "l2_norm"}[self.metric]
        if client.indices.exists(index=self.index):
            return
        client.indices.create(index=self.index, mappings={"properties": {
            "text": {"type": "text"},
            "metadata": {"type": "object"},
            "embedding": {"type": "dense_vector", "dims": int(dim),
                          "index": True, "similarity": similarity},
        }})

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        client = self._client()
        for it in items:
            client.index(index=self.index,
                         id=str(it.get("id") or _rand_id()),
                         document={"text": str(it.get("text") or ""),
                                   "metadata": it.get("metadata") or {},
                                   "embedding": [float(x) for x in it.get("vector") or []]},
                         refresh=False)
        client.indices.refresh(index=self.index)
        return len(items)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        client = self._client()
        knn: Dict[str, Any] = {"field": "embedding",
                               "query_vector": [float(x) for x in vector],
                               "k": max(1, int(top_k)),
                               "num_candidates": max(50, int(top_k) * 10)}
        if where:
            knn["filter"] = {"term": where}
        res = client.search(index=self.index, knn=knn, source=["text", "metadata"])
        out = []
        for hit in res.get("hits", {}).get("hits", []):
            src = hit.get("_source") or {}
            out.append({"id": str(hit.get("_id", "")), "text": src.get("text", ""),
                        "score": round(float(hit.get("_score", 0.0)), 6),
                        "metadata": src.get("metadata") or {}})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        client = self._client()
        for vid in ids:
            try:
                client.delete(index=self.index, id=str(vid))
            except Exception:  # noqa: BLE001
                continue
        return len(ids)

    def count(self, name: str) -> int:
        try:
            return int(self._client().count(index=self.index).get("count", 0))
        except Exception:  # noqa: BLE001
            return 0

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        info = client.info()
        return {"ok": True,
                "message": f"Elasticsearch 连接成功（{info.get('version', {}).get('number', '?')}）"}


# --------------------------------------------------------------------------- #
# Redis（RediSearch 向量索引）
# --------------------------------------------------------------------------- #
class RedisStore(BaseStore):
    protocol = "redis"
    pip = "redis"

    def _client(self):
        redis_mod = self._missing("redis")
        url = require(self.cfg, "url", label="连接串")
        return redis_mod.from_url(url, socket_connect_timeout=8,
                                  socket_timeout=20, decode_responses=False)

    @property
    def index_name(self) -> str:
        return _safe_ident(self.cfg.get("collection") or self.collection)

    def _prefix(self, name: str) -> str:
        return f"{self.resolve_name(name)}:"

    def _blob(self, vec: List[float]) -> bytes:
        import struct
        return struct.pack(f"<{len(vec)}f", *[float(x) for x in vec])

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        client = self._client()
        try:
            client.execute_command("FT.INFO", self.index_name)
            return
        except Exception:  # noqa: BLE001
            pass
        dist = {"cosine": "COSINE", "dot": "IP", "euclidean": "L2"}[self.metric]
        client.execute_command(
            "FT.CREATE", self.index_name, "ON", "HASH",
            "PREFIX", "1", self._prefix(name),
            "SCHEMA",
            "id", "TAG",
            "text", "TEXT",
            "metadata", "TEXT",
            "vec", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", str(int(dim)),
            "DISTANCE_METRIC", dist,
        )

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        client = self._client()
        prefix = self._prefix(name)
        for it in items:
            vid = str(it.get("id") or _rand_id())
            vec = [float(x) for x in it.get("vector") or []]
            client.hset(prefix + vid, mapping={
                "id": vid,
                "text": str(it.get("text") or ""),
                "metadata": json.dumps(it.get("metadata") or {}, ensure_ascii=False),
                "vec": self._blob(vec),
            })
        return len(items)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        client = self._client()
        limit = max(1, int(top_k))
        k = limit * 3 if where else limit
        query = f"*=>[KNN {k} @vec $BLOB AS score]"
        raw = client.execute_command(
            "FT.SEARCH", self.index_name, query,
            "PARAMS", "2", "BLOB", self._blob(vector),
            "SORTBY", "score", "DIALECT", "2")

        out: List[Dict[str, Any]] = []
        for i in range(1, len(raw or []), 2):
            fields = raw[i + 1] if i + 1 < len(raw) else []
            row: Dict[str, Any] = {}
            for j in range(0, len(fields), 2):
                key = _as_text(fields[j])
                row[key] = fields[j + 1] if j + 1 < len(fields) else b""
            dist = float(_as_text(row.pop("score", b"0")) or 0)
            md = _load_json(_as_text(row.get("metadata", b"")))
            if where and not _match_where(md, where):
                continue
            out.append({"id": _as_text(row.get("id", b"")),
                        "text": _as_text(row.get("text", b"")),
                        "metadata": md,
                        "score": round(_dist_to_score(dist, self.metric), 6)})
            if len(out) >= limit:
                break
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        client = self._client()
        prefix = self._prefix(name)
        for vid in ids:
            client.delete(prefix + str(vid))
        return len(ids)

    def drop(self, name: str) -> None:
        try:
            self._client().execute_command("FT.DROPINDEX", self.index_name, "DD")
        except Exception:  # noqa: BLE001
            pass

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        info = client.info()
        return {"ok": True,
                "message": f"Redis 连接成功（v{_as_text(info.get('redis_version', '?'))}）"}


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return "" if value is None else str(value)


# --------------------------------------------------------------------------- #
# 工厂
# --------------------------------------------------------------------------- #
_PROTOCOLS = {
    "sqlite": SQLiteStore,
    "chroma": ChromaStore,
    "pgvector": PgVectorStore,
    "qdrant": QdrantStore,
    "milvus": MilvusStore,
    "zilliz": MilvusStore,
    "weaviate": WeaviateStore,
    "lancedb": LanceDBStore,
    "faiss": FAISSStore,
    "pinecone": PineconeStore,
    "elasticsearch": ElasticsearchStore,
    "redis": RedisStore,
}


def get_store(cfg: Dict[str, Any]) -> BaseStore:
    """按 cfg.protocol 造一个适配器。cfg 里建议带 base_dir（生成项目目录）。"""
    protocol = (cfg.get("protocol") or "").strip().lower()
    if not protocol:
        provider_id = (cfg.get("provider") or "").strip()
        item = find("vector", provider_id) if provider_id else None
        protocol = (item or {}).get("protocol", "sqlite")
    impl = _PROTOCOLS.get(protocol)
    if impl is None:
        item = find("vector", protocol) or {}
        status = item.get("status", "planned")
        if status == "planned":
            raise ProviderConfigError(
                f"向量库「{item.get('label') or protocol}」已列入清单，但适配器还没实现",
                hint="先换一个已支持的库（内置 SQLite / Chroma / Qdrant / pgvector / Milvus 等）")
        raise ProviderConfigError(f"未知的向量库协议：{protocol}")
    return impl(cfg)


def supported_protocols() -> List[str]:
    return sorted(_PROTOCOLS)


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _rand_id() -> str:
    import uuid
    return uuid.uuid4().hex


def _uuid5(seed: str) -> str:
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def _load_json(raw: Any) -> Any:
    if raw is None:
        return {}
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}


def _flat_meta(meta: Any) -> Dict[str, Any]:
    """Chroma 只接受标量元数据，嵌套值先压成字符串。"""
    out: Dict[str, Any] = {}
    for key, value in (meta or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[str(key)] = value
        else:
            out[str(key)] = json.dumps(value, ensure_ascii=False)
    return out


def _similarity(a: List[float], b: List[float], metric: str) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    if metric == "dot":
        return dot
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    if metric == "euclidean":
        dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
        return 1.0 / (1.0 + dist)
    return dot / (na * nb)

# --------------------------------------------------------------------------- #
# 扩展批次：把 vectorstore_ext.py 里的适配器注册进来
# （放在文件末尾，避免与 ext 模块形成循环导入）
# --------------------------------------------------------------------------- #
from .vectorstore_ext import (ArangoDBStore, AzureSearchStore,  # noqa: E402
                              BaiduVectorStore, ClickHouseStore, CouchbaseStore,
                              DashVectorStore, DuckDBStore, HANAStore,
                              MongoDBVectorStore, MySQLVectorStore,
                              Neo4jVectorStore, OpenSearchStore, OracleVectorStore,
                              SqliteVecStore, SurrealDBStore, TencentVectorStore,
                              TurbopufferStore, TypesenseStore, UpstashStore,
                              VectaraStore, VertexVectorStore, VespaStore,
                              VikingDBStore)

_PROTOCOLS.update({
    "sqlite_vec": SqliteVecStore,
    "duckdb": DuckDBStore,
    "mysql_vector": MySQLVectorStore,
    "mongodb_vector": MongoDBVectorStore,
    "neo4j": Neo4jVectorStore,
    "opensearch": OpenSearchStore,
    "clickhouse": ClickHouseStore,
    "typesense": TypesenseStore,
    "upstash": UpstashStore,
    "turbopuffer": TurbopufferStore,
    "azure_search": AzureSearchStore,
    "arangodb": ArangoDBStore,
    "vectara": VectaraStore,
    "vespa": VespaStore,
    "surrealdb": SurrealDBStore,
    "couchbase": CouchbaseStore,
    "oracle_vector": OracleVectorStore,
    "hana_vector": HANAStore,
    "vertex_vector": VertexVectorStore,
    "dashvector": DashVectorStore,
    "tencent_vectordb": TencentVectorStore,
    "baidu_vectordb": BaiduVectorStore,
    "vikingdb": VikingDBStore,
})
