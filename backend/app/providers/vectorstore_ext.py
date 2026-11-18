"""向量库适配层（扩展批次）。

这些适配器和 vectorstore.py 里的实现接口完全一致，只是单独成文件避免主文件过大。
不 import vectorstore，避免循环依赖；共用的工具在 base.py。
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (as_int, dist_to_score as _dist_to_score, http_json,
                   join_url, lazy_import, load_json_ish, match_where as _match_where,
                   norm_metric as _norm_metric, require,
                   safe_ident as _safe_ident, vec_to_literal as _vec_to_literal)
from .errors import ProviderCallError, ProviderConfigError


class ExtStore:
    """扩展适配器的轻量基类（接口与 BaseStore 一致）。"""

    protocol = "ext"

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg or {}
        self.metric = _norm_metric(self.cfg.get("metric", "cosine"))
        self.collection = _safe_ident(self.cfg.get("collection") or "default")
        self.base_dir = Path(str(self.cfg.get("base_dir") or os.getcwd()))

    def resolve_name(self, name: str = "") -> str:
        return _safe_ident(name or self.collection)

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


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _rid() -> str:
    return uuid.uuid4().hex


def _score_vec(a: List[float], b: List[float], metric: str) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    if metric == "dot":
        return dot
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    if metric == "euclidean":
        return 1.0 / (1.0 + math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))))
    return dot / (na * nb)


def _flat_meta(meta: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in (meta or {}).items():
        out[str(key)] = value if isinstance(value, (str, int, float, bool)) else json.dumps(
            value, ensure_ascii=False)
    return out


# --------------------------------------------------------------------------- #
# sqlite-vec（向量索引扩展；元数据仍用普通表存）
# --------------------------------------------------------------------------- #
class SqliteVecStore(ExtStore):
    protocol = "sqlite_vec"
    pip = "sqlite-vec"

    def _path(self) -> Path:
        rel = str(self.cfg.get("path") or ".vec.db")
        p = Path(rel)
        return p if p.is_absolute() else (self.base_dir / p)

    def _conn(self, dim: int = 0):
        sqlite_vec = lazy_import("sqlite_vec", "sqlite-vec")
        self._path().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path()), timeout=15, check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS vec_meta(collection TEXT, id TEXT, text TEXT,"
            " metadata TEXT, PRIMARY KEY(collection, id))")
        conn.commit()
        return conn

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        conn = self._conn(dim)
        try:
            col = self.resolve_name(name)
            table = f"vec_{col}"
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
                f"id TEXT PRIMARY KEY, embedding float[{int(dim)}])")
            conn.commit()
        finally:
            conn.close()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        col = self.resolve_name(name)
        dim = len(items[0].get("vector") or []) if items else 0
        conn = self._conn(dim)
        try:
            table = f"vec_{col}"
            for it in items:
                vid = str(it.get("id") or _rid())
                conn.execute(f"INSERT OR REPLACE INTO {table}(id, embedding) VALUES(?,?)",
                             (vid, json.dumps([float(x) for x in it.get("vector") or []])))
                conn.execute(
                    "INSERT OR REPLACE INTO vec_meta(collection, id, text, metadata) "
                    "VALUES(?,?,?,?)",
                    (col, vid, str(it.get("text") or ""),
                     json.dumps(it.get("metadata") or {}, ensure_ascii=False)))
            conn.commit()
            return len(items)
        finally:
            conn.close()

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        col = self.resolve_name(name)
        conn = self._conn(len(vector))
        try:
            rows = conn.execute(
                f"SELECT id, distance FROM vec_{col} WHERE embedding MATCH ? "
                f"ORDER BY distance LIMIT ?",
                (json.dumps([float(x) for x in vector]), max(1, int(top_k)) * 3),
            ).fetchall()
            out = []
            for vid, dist in rows:
                meta = conn.execute(
                    "SELECT text, metadata FROM vec_meta WHERE collection=? AND id=?",
                    (col, vid)).fetchone()
                if not meta:
                    continue
                md = load_json_ish(meta[1])
                if where and not _match_where(md, where):
                    continue
                out.append({"id": vid, "text": meta[0], "metadata": md,
                            "score": round(_dist_to_score(float(dist), "euclidean"), 6)})
            return out[:max(1, int(top_k))]
        finally:
            conn.close()

    def delete(self, name: str, ids: List[str]) -> int:
        col = self.resolve_name(name)
        conn = self._conn()
        try:
            for vid in ids:
                conn.execute(f"DELETE FROM vec_{col} WHERE id = ?", (str(vid),))
                conn.execute("DELETE FROM vec_meta WHERE collection=? AND id=?",
                             (col, str(vid)))
            conn.commit()
            return len(ids)
        finally:
            conn.close()

    def drop(self, name: str) -> None:
        col = self.resolve_name(name)
        conn = self._conn()
        try:
            conn.execute(f"DROP TABLE IF EXISTS vec_{col}")
            conn.execute("DELETE FROM vec_meta WHERE collection=?", (col,))
            conn.commit()
        finally:
            conn.close()

    def probe(self) -> Dict[str, Any]:
        conn = self._conn()
        conn.close()
        return {"ok": True, "message": f"sqlite-vec 可用（{self._path().name}）"}


# --------------------------------------------------------------------------- #
# DuckDB + VSS
# --------------------------------------------------------------------------- #
class DuckDBStore(ExtStore):
    protocol = "duckdb"
    pip = "duckdb"

    def _conn(self):
        duckdb = lazy_import("duckdb", "duckdb")
        rel = str(self.cfg.get("path") or ".duck.db")
        p = Path(rel)
        path = p if p.is_absolute() else (self.base_dir / p)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(path))
        try:
            conn.execute("INSTALL vss")
            conn.execute("LOAD vss")
            conn.execute("SET hnsw_enable_experimental_persistence = true")
        except Exception:  # noqa: BLE001
            # 老版本或离线环境没有 vss：退化为逐行计算
            pass
        return conn

    def _table(self, name: str) -> str:
        return f"vec_{self.resolve_name(name)}"

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        conn = self._conn()
        try:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table(name)}("
                f"id VARCHAR, text VARCHAR, metadata VARCHAR,"
                f" embedding FLOAT[{max(1, int(dim))}])")
            conn.commit()
        finally:
            conn.close()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        conn = self._conn()
        try:
            table = self._table(name)
            for it in items:
                vec = "[" + ",".join(str(float(x)) for x in it.get("vector") or []) + "]"
                conn.execute(
                    f"INSERT INTO {table} VALUES (?,?,?,?::FLOAT[])",
                    [str(it.get("id") or _rid()), str(it.get("text") or ""),
                     json.dumps(it.get("metadata") or {}, ensure_ascii=False), vec])
            conn.commit()
            return len(items)
        finally:
            conn.close()

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            table = self._table(name)
            lit = "[" + ",".join(str(float(x)) for x in vector) + "]"
            fn = {"cosine": "array_cosine_similarity",
                  "dot": "array_inner_product",
                  "euclidean": "array_distance"}[self.metric]
            order = "DESC" if self.metric in ("cosine", "dot") else "ASC"
            rows = conn.execute(
                f"SELECT id, text, metadata, {fn}(embedding, ?::FLOAT[]) AS d "
                f"FROM {table} ORDER BY d {order} LIMIT ?",
                [lit, max(1, int(top_k))]).fetchall()
            out = []
            for vid, text, meta, dist in rows:
                md = load_json_ish(meta)
                if where and any(md.get(k) != v for k, v in where.items()):
                    continue
                if self.metric == "euclidean":
                    score = _dist_to_score(float(dist), "euclidean")
                else:
                    score = float(dist)
                out.append({"id": vid, "text": text, "metadata": md,
                            "score": round(score, 6)})
            return out
        finally:
            conn.close()

    def count(self, name: str) -> int:
        conn = self._conn()
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {self._table(name)}").fetchone()
            return int(row[0] if row else 0)
        except Exception:  # noqa: BLE001
            return 0
        finally:
            conn.close()

    def drop(self, name: str) -> None:
        conn = self._conn()
        try:
            conn.execute(f"DROP TABLE IF EXISTS {self._table(name)}")
            conn.commit()
        finally:
            conn.close()

    def probe(self) -> Dict[str, Any]:
        conn = self._conn()
        conn.close()
        return {"ok": True, "message": "DuckDB 连接成功（VSS 扩展按需加载）"}


# --------------------------------------------------------------------------- #
# MySQL 家族的 VECTOR 类型（MariaDB 11.7+ / MySQL 9+ / TiDB / OceanBase 等）
# --------------------------------------------------------------------------- #
class MySQLVectorStore(ExtStore):
    protocol = "mysql_vector"
    pip = "pymysql"

    def _connect(self):
        pymysql = lazy_import("pymysql", "pymysql")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"mysql://{dsn}"
        parsed = urllib.parse.urlsplit(raw)
        return pymysql.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            user=urllib.parse.unquote(parsed.username or "root"),
            password=urllib.parse.unquote(parsed.password or ""),
            database=(parsed.path or "/").lstrip("/") or None,
            charset="utf8mb4", connect_timeout=10,
            cursorclass=pymysql.cursors.DictCursor)

    def _table(self, name: str) -> str:
        return f"vec_{self.resolve_name(name)}"

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table(name)}("
                f" id VARCHAR(160) PRIMARY KEY, text LONGTEXT, metadata JSON,"
                f" embedding VECTOR({int(dim)}))")
            conn.commit()
        finally:
            conn.close()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            for it in items:
                cur.execute(
                    f"INSERT INTO {self._table(name)}(id, text, metadata, embedding) "
                    f"VALUES(%s,%s,%s,VEC_FromText(%s)) "
                    f"ON DUPLICATE KEY UPDATE text=VALUES(text), "
                    f"metadata=VALUES(metadata), embedding=VALUES(embedding)",
                    (str(it.get("id") or _rid()), str(it.get("text") or ""),
                     json.dumps(it.get("metadata") or {}, ensure_ascii=False),
                     _vec_to_literal(it.get("vector") or [])))
            conn.commit()
            return len(items)
        finally:
            conn.close()

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            fn = {"cosine": "VEC_DISTANCE_COSINE",
                  "dot": "VEC_DISTANCE_EUCLIDEAN",
                  "euclidean": "VEC_DISTANCE_EUCLIDEAN"}[self.metric]
            sql = (f"SELECT id, text, metadata, {fn}(embedding, VEC_FromText(%s)) AS d "
                   f"FROM {self._table(name)}")
            args: List[Any] = [_vec_to_literal(vector)]
            if where:
                sql += " WHERE JSON_CONTAINS(metadata, %s)"
                args.append(json.dumps(where, ensure_ascii=False))
            sql += " ORDER BY d ASC LIMIT %s"
            args.append(max(1, int(top_k)))
            cur.execute(sql, args)
            out = []
            for row in cur.fetchall():
                md = load_json_ish(row.get("metadata"))
                out.append({"id": row.get("id"), "text": row.get("text") or "",
                            "metadata": md,
                            "score": round(_dist_to_score(float(row.get("d") or 0),
                                                          "cosine"), 6)})
            return out
        finally:
            conn.close()

    def delete(self, name: str, ids: List[str]) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            marks = ",".join(["%s"] * len(ids))
            cur.execute(f"DELETE FROM {self._table(name)} WHERE id IN ({marks})",
                        [str(i) for i in ids])
            conn.commit()
            return len(ids)
        finally:
            conn.close()

    def drop(self, name: str) -> None:
        conn = self._connect()
        try:
            conn.cursor().execute(f"DROP TABLE IF EXISTS {self._table(name)}")
            conn.commit()
        finally:
            conn.close()

    def probe(self) -> Dict[str, Any]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT VERSION() AS v")
            row = cur.fetchone()
            return {"ok": True, "message": f"MySQL 家族连接成功（{row.get('v')}）"}
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# MongoDB Atlas Vector Search
# --------------------------------------------------------------------------- #
class MongoDBVectorStore(ExtStore):
    protocol = "mongodb_vector"
    pip = "pymongo"

    def _collection(self, name: str):
        pymongo = lazy_import("pymongo", "pymongo")
        uri = require(self.cfg, "dsn", label="连接串")
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000)
        db = client[(self.cfg.get("database") or "mineagent")]
        return db[self.resolve_name(name)]

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        # Atlas 的向量索引要在 Atlas 控制台或 Admin API 建，这里只保证集合存在
        self._collection(name)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        coll = self._collection(name)
        docs = [{"_id": str(it.get("id") or _rid()),
                 "text": str(it.get("text") or ""),
                 "metadata": it.get("metadata") or {},
                 "embedding": [float(x) for x in it.get("vector") or []]} for it in items]
        for doc in docs:
            coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        return len(docs)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        coll = self._collection(name)
        stage: Dict[str, Any] = {
            "index": self.cfg.get("index") or "vector_index",
            "path": "embedding",
            "queryVector": [float(x) for x in vector],
            "numCandidates": max(100, int(top_k) * 10),
            "limit": max(1, int(top_k)),
        }
        if where:
            stage["filter"] = where
        rows = coll.aggregate([{"$vectorSearch": stage},
                               {"$addFields": {"score": {"$meta": "vectorSearchScore"}}}])
        return [{"id": str(r.get("_id")), "text": r.get("text", ""),
                 "metadata": r.get("metadata") or {},
                 "score": round(float(r.get("score") or 0), 6)} for r in rows]

    def delete(self, name: str, ids: List[str]) -> int:
        self._collection(name).delete_many({"_id": {"$in": [str(i) for i in ids]}})
        return len(ids)

    def drop(self, name: str) -> None:
        try:
            self._collection(name).drop()
        except Exception:  # noqa: BLE001
            pass

    def probe(self) -> Dict[str, Any]:
        self._collection("default")
        return {"ok": True,
                "message": "MongoDB 连接成功（向量检索需要先在 Atlas 建 vector index）"}


# --------------------------------------------------------------------------- #
# Neo4j 向量索引
# --------------------------------------------------------------------------- #
class Neo4jVectorStore(ExtStore):
    protocol = "neo4j"
    pip = "neo4j"

    def _driver(self):
        neo4j = lazy_import("neo4j", "neo4j")
        uri = require(self.cfg, "uri", label="连接地址")
        return neo4j.GraphDatabase.driver(
            uri, auth=(self.cfg.get("username") or "neo4j",
                       self.cfg.get("password") or ""))

    def _label(self, name: str) -> str:
        col = self.resolve_name(name)
        return col[:1].upper() + col[1:]

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        sim = {"cosine": "cosine", "dot": "dot", "euclidean": "euclidean"}[self.metric]
        driver = self._driver()
        try:
            with driver.session() as s:
                s.run(
                    f"CREATE VECTOR INDEX `{self.resolve_name(name)}_idx` IF NOT EXISTS "
                    f"FOR (n:`{self._label(name)}`) ON (n.embedding) "
                    f"OPTIONS {{indexConfig: {{"
                    f"`vector.dimensions`: $dim, "
                    f"`vector.similarity_function`: $sim}}}}",
                    dim=int(dim), sim=sim)
        finally:
            driver.close()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        driver = self._driver()
        try:
            with driver.session() as s:
                for it in items:
                    s.run(
                        f"MERGE (n:`{self._label(name)}` {{id: $id}}) "
                        f"SET n.text = $text, n.metadata = $meta, n.embedding = $vec",
                        id=str(it.get("id") or _rid()), text=str(it.get("text") or ""),
                        meta=json.dumps(it.get("metadata") or {}, ensure_ascii=False),
                        vec=[float(x) for x in it.get("vector") or []])
            return len(items)
        finally:
            driver.close()

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        driver = self._driver()
        try:
            with driver.session() as s:
                rows = s.run(
                    f"CALL db.index.vector.queryNodes($idx, $k, $vec) "
                    f"YIELD node, score RETURN node.id AS id, node.text AS text, "
                    f"node.metadata AS meta, score",
                    idx=f"{self.resolve_name(name)}_idx",
                    k=max(1, int(top_k)), vec=[float(x) for x in vector]).data()
            out = []
            for row in rows:
                md = load_json_ish(row.get("meta"))
                if where and any(md.get(k) != v for k, v in where.items()):
                    continue
                out.append({"id": row.get("id"), "text": row.get("text") or "",
                            "metadata": md, "score": round(float(row.get("score") or 0), 6)})
            return out
        finally:
            driver.close()

    def delete(self, name: str, ids: List[str]) -> int:
        driver = self._driver()
        try:
            with driver.session() as s:
                s.run(f"MATCH (n:`{self._label(name)}`) WHERE n.id IN $ids DETACH DELETE n",
                      ids=[str(i) for i in ids])
            return len(ids)
        finally:
            driver.close()

    def probe(self) -> Dict[str, Any]:
        driver = self._driver()
        try:
            driver.verify_connectivity()
            return {"ok": True, "message": "Neo4j 连接成功"}
        finally:
            driver.close()


# --------------------------------------------------------------------------- #
# OpenSearch kNN（走 REST，不绑定客户端版本）
# --------------------------------------------------------------------------- #
class OpenSearchStore(ExtStore):
    protocol = "opensearch"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "url", label="服务地址").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        headers = {}
        if self.cfg.get("username"):
            raw = f"{self.cfg['username']}:{self.cfg.get('password') or ''}"
            headers["Authorization"] = "Basic " + base64.b64encode(
                raw.encode("utf-8")).decode("ascii")
        return headers

    @property
    def _index(self) -> str:
        return _safe_ident(self.cfg.get("index") or "mineagent").lower()

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        payload = {"settings": {"index": {"knn": True}},
                   "mappings": {"properties": {
                       "text": {"type": "text"},
                       "metadata": {"type": "object"},
                       "embedding": {"type": "knn_vector", "dimension": int(dim),
                                     "method": {"name": "hnsw", "space_type": {
                                         "cosine": "cosinesimil",
                                         "dot": "innerproduct",
                                         "euclidean": "l2"}[self.metric],
                                         "engine": "lucene"}}}}}
        try:
            http_json(join_url(self._base(), f"{self._index}"), method="GET",
                      headers=self._headers(), timeout=15)
            return
        except ProviderCallError as exc:
            if exc.status != 404:
                raise
        http_json(join_url(self._base(), self._index), payload,
                  headers=self._headers(), timeout=30)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        for it in items:
            http_json(join_url(self._base(), f"{self._index}/_doc/{it.get('id') or _rid()}"),
                      {"text": str(it.get("text") or ""),
                       "metadata": it.get("metadata") or {},
                       "embedding": [float(x) for x in it.get("vector") or []]},
                      method="PUT", headers=self._headers(), timeout=30)
        return len(items)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        body: Dict[str, Any] = {
            "size": max(1, int(top_k)),
            "query": {"knn": {"embedding": {"vector": [float(x) for x in vector],
                                            "k": max(1, int(top_k))}}},
            "_source": ["text", "metadata"],
        }
        if where:
            body["query"] = {"bool": {"must": [body["query"]],
                                      "filter": [{"term": where}]}}
        data = http_json(join_url(self._base(), f"{self._index}/_search"), body,
                         headers=self._headers(), timeout=30)
        hits = ((data.get("hits") or {}).get("hits") or [])
        out = []
        for hit in hits:
            src = hit.get("_source") or {}
            out.append({"id": str(hit.get("_id", "")), "text": src.get("text", ""),
                        "metadata": src.get("metadata") or {},
                        "score": round(float(hit.get("_score") or 0), 6)})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        for vid in ids:
            try:
                http_json(join_url(self._base(), f"{self._index}/_doc/{vid}"), method="DELETE",
                          headers=self._headers(), timeout=15)
            except ProviderCallError:
                continue
        return len(ids)

    def probe(self) -> Dict[str, Any]:
        data = http_json(join_url(self._base(), "_cluster/health"), method="GET",
                         headers=self._headers(), timeout=15)
        return {"ok": True,
                "message": f"OpenSearch 连接成功（状态 {data.get('status', '?')}）"}


# --------------------------------------------------------------------------- #
# ClickHouse
# --------------------------------------------------------------------------- #
class ClickHouseStore(ExtStore):
    protocol = "clickhouse"
    pip = ""

    def _endpoint(self) -> str:
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"http://{dsn}"
        parsed = urllib.parse.urlsplit(raw)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (8443 if scheme == "https" else 8123)
        db = (parsed.path or "/default").lstrip("/") or "default"
        return f"{scheme}://{host}:{port}/?database={urllib.parse.quote(db)}"

    def _auth(self) -> Dict[str, str]:
        dsn = self.cfg.get("dsn") or ""
        parsed = urllib.parse.urlsplit(dsn if "://" in dsn else f"http://{dsn}")
        headers = {"X-ClickHouse-User": urllib.parse.unquote(parsed.username or "default")}
        if parsed.password:
            headers["X-ClickHouse-Key"] = urllib.parse.unquote(parsed.password)
        return headers

    def _execute(self, sql: str, timeout: float = 60.0) -> str:
        import urllib.request
        url = self._endpoint() + "&query=" + urllib.parse.quote(sql)
        req = urllib.request.Request(url, headers=self._auth(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            raise ProviderCallError("ClickHouse 查询失败", status=exc.code,
                                    detail=detail) from exc

    def _table(self, name: str) -> str:
        return f"vec_{self.resolve_name(name)}"

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        self._execute(
            f"CREATE TABLE IF NOT EXISTS {self._table(name)} ("
            f"id String, text String, metadata String,"
            f" embedding Array(Float32)) ENGINE = MergeTree ORDER BY id")

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        for it in items:
            vec = "[" + ",".join(str(float(x)) for x in it.get("vector") or []) + "]"
            self._execute(
                f"INSERT INTO {self._table(name)} VALUES ("
                f"'{_esc(str(it.get('id') or _rid()))}',"
                f"'{_esc(str(it.get('text') or ''))}',"
                f"'{_esc(json.dumps(it.get('metadata') or {}, ensure_ascii=False))}',"
                f"{vec})")
        return len(items)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        lit = "[" + ",".join(str(float(x)) for x in vector) + "]"
        fn = {"cosine": "cosineSimilarity", "dot": "dotProduct",
              "euclidean": "euclideanDistance"}[self.metric]
        order = "DESC" if self.metric in ("cosine", "dot") else "ASC"
        raw = self._execute(
            f"SELECT id, text, metadata, {fn}(embedding, {lit}) AS d "
            f"FROM {self._table(name)} ORDER BY d {order} LIMIT {max(1, int(top_k))} "
            f"FORMAT JSONEachRow")
        out = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            md = load_json_ish(row.get("metadata"))
            if where and any(md.get(k) != v for k, v in where.items()):
                continue
            out.append({"id": row.get("id"), "text": row.get("text") or "",
                        "metadata": md,
                        "score": round(float(row.get("d") or 0), 6)})
        return out

    def probe(self) -> Dict[str, Any]:
        raw = self._execute("SELECT version() FORMAT TabSeparated")
        return {"ok": True, "message": f"ClickHouse 连接成功（{raw.strip()}）"}


def _esc(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("'", "\\'")


# --------------------------------------------------------------------------- #
# Typesense
# --------------------------------------------------------------------------- #
class TypesenseStore(ExtStore):
    protocol = "typesense"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "url", label="服务地址").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"X-TYPESENSE-API-KEY": require(self.cfg, "api_key", label="API Key")}

    @property
    def _coll(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "mineagent")

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        payload = {
            "name": self._coll,
            "fields": [
                {"name": "text", "type": "string"},
                {"name": "metadata", "type": "string"},
                {"name": "embedding", "type": "float[]", "num_dim": int(dim),
                 "vec_dist": {"cosine": "cosine", "dot": "ip",
                              "euclidean": "l2"}[self.metric]},
            ],
        }
        try:
            http_json(join_url(self._base(), f"collections/{self._coll}"),
                      method="GET", headers=self._headers(), timeout=15)
            return
        except ProviderCallError as exc:
            if exc.status != 404:
                raise
        http_json(join_url(self._base(), "collections"), payload,
                  headers=self._headers(), timeout=30)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        lines = []
        for it in items:
            lines.append(json.dumps({
                "id": str(it.get("id") or _rid()),
                "text": str(it.get("text") or ""),
                "metadata": json.dumps(it.get("metadata") or {}, ensure_ascii=False),
                "embedding": [float(x) for x in it.get("vector") or []],
            }, ensure_ascii=False))
        body = "\n".join(lines).encode("utf-8")
        http_json(join_url(self._base(),
                           f"collections/{self._coll}/documents/import?action=upsert"),
                  headers={**self._headers(), "Content-Type": "text/plain"},
                  raw_body=body, method="POST", timeout=60)
        return len(items)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "q": "*",
            "vector_query": "embedding:(" + _vec_to_literal(vector) + f", k:{max(1, int(top_k))})",
        }
        if where:
            payload["filter_by"] = " && ".join(f"{k}:={v}" for k, v in where.items())
        data = http_json(join_url(self._base(), f"collections/{self._coll}/documents/search"),
                         payload, headers=self._headers(), timeout=30)
        out = []
        for hit in data.get("hits") or []:
            doc = hit.get("document") or {}
            md = load_json_ish(doc.get("metadata"))
            dist = float(hit.get("vector_distance") or 0)
            out.append({"id": str(doc.get("id", "")), "text": doc.get("text", ""),
                        "metadata": md,
                        "score": round(_dist_to_score(dist, self.metric), 6)})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        for vid in ids:
            try:
                http_json(join_url(self._base(),
                                   f"collections/{self._coll}/documents/{vid}"),
                          method="DELETE", headers=self._headers(), timeout=15)
            except ProviderCallError:
                continue
        return len(ids)

    def probe(self) -> Dict[str, Any]:
        data = http_json(join_url(self._base(), "health"), method="GET",
                         headers=self._headers(), timeout=15)
        return {"ok": True, "message": f"Typesense 连接成功（{data.get('ok')}）"}


# --------------------------------------------------------------------------- #
# Upstash Vector
# --------------------------------------------------------------------------- #
class UpstashStore(ExtStore):
    protocol = "upstash"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "url", label="REST 地址").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {require(self.cfg, 'token', label='Token')}"}

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        return None  # Upstash 索引在控制台建，维度建索引时定

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        vectors = [{"id": str(it.get("id") or _rid()),
                    "vector": [float(x) for x in it.get("vector") or []],
                    "metadata": {**(it.get("metadata") or {}),
                                 "text": str(it.get("text") or "")}}
                   for it in items]
        http_json(join_url(self._base(), "upsert-data"),
                  {"vectors": vectors}, headers=self._headers(), timeout=60)
        return len(vectors)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "vector": [float(x) for x in vector],
            "topK": max(1, int(top_k)),
            "includeMetadata": True,
        }
        if where:
            payload["filter"] = " && ".join(f"{k} = {json.dumps(v)}"
                                            for k, v in where.items())
        data = http_json(join_url(self._base(), "query-data"), payload,
                         headers=self._headers(), timeout=30)
        out = []
        for row in data.get("result") or []:
            md = dict(row.get("metadata") or {})
            text = md.pop("text", "")
            out.append({"id": str(row.get("id", "")), "text": text, "metadata": md,
                        "score": round(float(row.get("score") or 0), 6)})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        http_json(join_url(self._base(), "delete-data"), {"ids": [str(i) for i in ids]},
                  headers=self._headers(), timeout=30)
        return len(ids)

    def probe(self) -> Dict[str, Any]:
        data = http_json(join_url(self._base(), "info"), method="GET",
                         headers=self._headers(), timeout=15)
        return {"ok": True, "message": f"Upstash Vector 连接成功（{data.get('result', {})}）"}


# --------------------------------------------------------------------------- #
# Turbopuffer
# --------------------------------------------------------------------------- #
class TurbopufferStore(ExtStore):
    protocol = "turbopuffer"
    pip = ""

    def _ns(self) -> str:
        return self.resolve_name(self.cfg.get("namespace") or "mineagent")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {require(self.cfg, 'api_key', label='API Key')}"}

    def _url(self, path: str) -> str:
        return f"https://api.turbopuffer.com/v1/namespaces/{self._ns()}/{path}"

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        return None

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        vectors = [{"id": str(it.get("id") or _rid()),
                    "vector": [float(x) for x in it.get("vector") or []],
                    "attributes": {**(it.get("metadata") or {}),
                                   "text": str(it.get("text") or "")}}
                   for it in items]
        http_json(self._url("vectors"), {"vectors": vectors},
                  headers=self._headers(), timeout=60, method="POST")
        return len(vectors)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "rank_by": ["vector", "ANN", [float(x) for x in vector]],
            "top_k": max(1, int(top_k)),
            "include_attributes": True,
        }
        if where:
            payload["filters"] = where
        data = http_json(self._url("query"), payload, headers=self._headers(),
                         timeout=30, method="POST")
        out = []
        for row in data.get("rows") or []:
            attrs = dict(row.get("attributes") or {})
            text = attrs.pop("text", "")
            out.append({"id": str(row.get("id", "")), "text": text, "metadata": attrs,
                        "score": round(float(row.get("dist") or 0), 6)})
        return out

    def probe(self) -> Dict[str, Any]:
        http_json(self._url("metadata"), method="GET", headers=self._headers(), timeout=15)
        return {"ok": True, "message": "Turbopuffer 连接成功"}


# --------------------------------------------------------------------------- #
# Azure AI Search
# --------------------------------------------------------------------------- #
class AzureSearchStore(ExtStore):
    protocol = "azure_search"
    pip = ""

    API = "2024-07-01"

    def _base(self) -> str:
        endpoint = require(self.cfg, "endpoint", label="Endpoint").rstrip("/")
        return f"{endpoint}/indexes"

    def _headers(self) -> Dict[str, str]:
        return {"api-key": require(self.cfg, "api_key", label="API Key")}

    @property
    def _index(self) -> str:
        return _safe_ident(self.cfg.get("index") or "mineagent").lower()

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        payload = {
            "name": self._index,
            "fields": [
                {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
                {"name": "text", "type": "Edm.String", "searchable": True},
                {"name": "metadata", "type": "Edm.String", "filterable": True},
                {"name": "embedding", "type": "Collection(Edm.Single)",
                 "searchable": True, "dimensions": int(dim),
                 "vectorSearchProfile": "default"},
            ],
            "vectorSearch": {
                "algorithms": [{"name": "hnsw", "kind": "hnsw"}],
                "profiles": [{"name": "default", "algorithm": "hnsw"}],
            },
        }
        url = f"{self._base()}/{self._index}?api-version={self.API}"
        try:
            http_json(url, method="GET", headers=self._headers(), timeout=15)
            return
        except ProviderCallError as exc:
            if exc.status != 404:
                raise
        http_json(url, payload, method="PUT", headers=self._headers(), timeout=30)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        docs = [{"@search.action": "mergeOrUpload",
                 "id": str(it.get("id") or _rid()),
                 "text": str(it.get("text") or ""),
                 "metadata": json.dumps(it.get("metadata") or {}, ensure_ascii=False),
                 "embedding": [float(x) for x in it.get("vector") or []]}
                for it in items]
        http_json(f"{self._base()}/{self._index}/docs/index?api-version={self.API}",
                  {"value": docs}, headers=self._headers(), timeout=60)
        return len(docs)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "search": "*",
            "vectorQueries": [{"kind": "vector", "vector": [float(x) for x in vector],
                               "fields": "embedding", "k": max(1, int(top_k))}],
            "top": max(1, int(top_k)),
            "select": "id,text,metadata",
        }
        if where:
            payload["filter"] = " and ".join(
                f"metadata eq '{json.dumps({k: v}, ensure_ascii=False)}'" for k, v in where.items())
        data = http_json(f"{self._base()}/{self._index}/docs/search?api-version={self.API}",
                         payload, headers=self._headers(), timeout=30)
        out = []
        for row in data.get("value") or []:
            md = load_json_ish(row.get("metadata"))
            out.append({"id": str(row.get("id", "")), "text": row.get("text", ""),
                        "metadata": md,
                        "score": round(float(row.get("@search.score") or 0), 6)})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        docs = [{"@search.action": "delete", "id": str(i)} for i in ids]
        http_json(f"{self._base()}/{self._index}/docs/index?api-version={self.API}",
                  {"value": docs}, headers=self._headers(), timeout=60)
        return len(ids)

    def probe(self) -> Dict[str, Any]:
        http_json(f"{self._base()}?api-version={self.API}", method="GET",
                  headers=self._headers(), timeout=15)
        return {"ok": True, "message": "Azure AI Search 连接成功"}


# --------------------------------------------------------------------------- #
# ArangoDB（3.12+ 有 APPROX_NEAR_COSINE，否则退回客户端计算）
# --------------------------------------------------------------------------- #
class ArangoDBStore(ExtStore):
    protocol = "arangodb"
    pip = "python-arango"

    def _db(self):
        arango = lazy_import("arango", "python-arango", attr="ArangoClient")
        url = require(self.cfg, "url", label="服务地址")
        client = arango(url)
        db = client.db(self.cfg.get("database") or "_system",
                       username=self.cfg.get("username") or "root",
                       password=self.cfg.get("password") or "")
        return db

    @property
    def _coll(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "mineagent")

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        self._db().collection(self._coll)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        docs = [{"_key": str(it.get("id") or _rid()),
                 "text": str(it.get("text") or ""),
                 "metadata": it.get("metadata") or {},
                 "embedding": [float(x) for x in it.get("vector") or []]} for it in items]
        self._db()[self._coll].import_bulk(docs, overwrite_mode="replace")
        return len(docs)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        db = self._db()
        k = max(1, int(top_k))
        aql = (
            f"FOR d IN @@col "
            f"LET s = APPROX_NEAR_COSINE(d.embedding, @vec) "
            f"SORT s DESC LIMIT @k RETURN {{id: d._key, text: d.text, "
            f"metadata: d.metadata, score: s}}"
        )
        try:
            cursor = db.aql.execute(aql, bind_vars={"@col": self._coll, "vec": vector, "k": k})
            rows = list(cursor)
        except Exception:  # noqa: BLE001
            # 老版本没有向量函数：拉回来在客户端算
            rows = []
            for doc in db[self._coll].all():
                rows.append({"id": doc.get("_key"), "text": doc.get("text", ""),
                             "metadata": doc.get("metadata") or {},
                             "score": _score_vec(vector, doc.get("embedding") or [],
                                                 self.metric)})
            rows.sort(key=lambda r: r["score"], reverse=True)
            rows = rows[:k]
        return [{**r, "score": round(float(r.get("score") or 0), 6)} for r in rows]

    def delete(self, name: str, ids: List[str]) -> int:
        for vid in ids:
            try:
                self._db()[self._coll].delete(str(vid))
            except Exception:  # noqa: BLE001
                continue
        return len(ids)

    def probe(self) -> Dict[str, Any]:
        info = self._db().version()
        return {"ok": True, "message": f"ArangoDB 连接成功（{info.get('version', '?')}）"}


# --------------------------------------------------------------------------- #
# Vectara
# --------------------------------------------------------------------------- #
class VectaraStore(ExtStore):
    protocol = "vectara"
    pip = ""

    def _headers(self) -> Dict[str, str]:
        return {"x-api-key": require(self.cfg, "api_key", label="API Key"),
                "Content-Type": "application/json"}

    @property
    def _corpus(self) -> str:
        return require(self.cfg, "corpus_id", label="Corpus ID")

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        return None

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        docs = [{"id": str(it.get("id") or _rid()),
                 "title": str((it.get("metadata") or {}).get("title") or ""),
                 "metadata": it.get("metadata") or {},
                 "sections": [{"text": str(it.get("text") or "")}]} for it in items]
        http_json(f"https://api.vectara.io/v2/corpora/{self._corpus}/documents",
                  {"documents": docs}, headers=self._headers(), timeout=60)
        return len(docs)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # Vectara 自己做向量化，这里用文本检索；纯向量接口需要 corpus 配置归一化
        query = str(self.cfg.get("_query") or "")
        payload = {"query": query or "*", "numResults": max(1, int(top_k))}
        data = http_json(f"https://api.vectara.io/v2/corpora/{self._corpus}/query",
                         payload, headers=self._headers(), timeout=30)
        out = []
        for row in data.get("searchResults") or []:
            out.append({"id": str(row.get("documentId", "")),
                        "text": row.get("text", ""),
                        "metadata": row.get("metadata") or {},
                        "score": round(float(row.get("score") or 0), 6)})
        return out

    def probe(self) -> Dict[str, Any]:
        http_json(f"https://api.vectara.io/v2/corpora/{self._corpus}",
                  method="GET", headers=self._headers(), timeout=15)
        return {"ok": True, "message": "Vectara 连接成功"}


# --------------------------------------------------------------------------- #
# Vespa
# --------------------------------------------------------------------------- #
class VespaStore(ExtStore):
    protocol = "vespa"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "url", label="服务地址").rstrip("/")

    @property
    def _doc_type(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "mineagent")

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        return None  # Schema 需随应用部署

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        for it in items:
            vid = str(it.get("id") or _rid())
            http_json(f"{self._base()}/document/v1/mineagent/{self._doc_type}/docid/{vid}",
                      {"fields": {"text": str(it.get("text") or ""),
                                  "metadata": json.dumps(it.get("metadata") or {},
                                                         ensure_ascii=False),
                                  "embedding": [float(x) for x in it.get("vector") or []]}},
                      method="POST", timeout=30)
        return len(items)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        yql = (f"select * from {self._doc_type} where "
               f"{{targetHits:{max(1, int(top_k))}}}nearestNeighbor(embedding, qvec)")
        payload = {
            "yql": yql,
            "input.query(qvec)": [float(x) for x in vector],
            "hits": max(1, int(top_k)),
        }
        data = http_json(f"{self._base()}/search/", payload,
                         headers={"Content-Type": "application/json"}, timeout=30)
        out = []
        for hit in ((data.get("root") or {}).get("children") or []):
            fields = hit.get("fields") or {}
            out.append({"id": str(fields.get("id") or hit.get("id", "")),
                        "text": fields.get("text", ""),
                        "metadata": load_json_ish(fields.get("metadata")),
                        "score": round(float(hit.get("relevance") or 0), 6)})
        return out

    def probe(self) -> Dict[str, Any]:
        http_json(f"{self._base()}/ApplicationStatus", method="GET", timeout=15)
        return {"ok": True, "message": "Vespa 连接成功"}


# --------------------------------------------------------------------------- #
# SurrealDB
# --------------------------------------------------------------------------- #
class SurrealDBStore(ExtStore):
    protocol = "surrealdb"
    pip = "surrealdb"

    def _endpoint(self) -> str:
        url = require(self.cfg, "url", label="服务地址")
        if url.startswith("ws"):
            url = url.replace("ws://", "http://").replace("wss://", "https://")
        return url.split("/rpc")[0].rstrip("/")

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.get("username"):
            raw = f"{self.cfg['username']}:{self.cfg.get('password') or ''}"
            headers["Authorization"] = "Basic " + base64.b64encode(
                raw.encode("utf-8")).decode("ascii")
        headers["Surreal-NS"] = self.cfg.get("namespace") or "mineagent"
        headers["Surreal-DB"] = self.cfg.get("database") or "mineagent"
        return headers

    @property
    def _table(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "vectors")

    def _sql(self, statement: str, timeout: float = 30.0) -> Any:
        return http_json(f"{self._endpoint()}/sql", statement,
                         headers=self._headers(), raw_body=statement.encode("utf-8"),
                         timeout=timeout)

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        self._sql(f"DEFINE TABLE IF NOT EXISTS {self._table} SCHEMAFULL; "
                  f"DEFINE FIELD IF NOT EXISTS text ON {self._table} TYPE string; "
                  f"DEFINE FIELD IF NOT EXISTS metadata ON {self._table} TYPE object; "
                  f"DEFINE FIELD IF NOT EXISTS embedding ON {self._table} "
                  f"TYPE array<float>;")

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        for it in items:
            self._sql(
                f"CREATE {self._table}:{json.dumps(str(it.get('id') or _rid()))} "
                f"CONTENT {{text: {json.dumps(str(it.get('text') or ''))}, "
                f"metadata: {json.dumps(it.get('metadata') or {}, ensure_ascii=False)}, "
                f"embedding: {json.dumps([float(x) for x in it.get('vector') or []])}}};")
        return len(items)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        lit = json.dumps([float(x) for x in vector])
        rows = self._sql(
            f"SELECT id, text, metadata, vector::similarity::cosine(embedding, {lit}) AS score "
            f"FROM {self._table} ORDER BY score DESC LIMIT {max(1, int(top_k))};")
        out = []
        for row in (rows or []):
            if not isinstance(row, dict) or row.get("status") == "ERR":
                continue
            for item in row.get("result") or []:
                out.append({"id": str(item.get("id", "")), "text": item.get("text", ""),
                            "metadata": item.get("metadata") or {},
                            "score": round(float(item.get("score") or 0), 6)})
        return out

    def probe(self) -> Dict[str, Any]:
        self._sql("SELECT 1;")
        return {"ok": True, "message": "SurrealDB 连接成功"}


# --------------------------------------------------------------------------- #
# Couchbase（SQL++ 向量检索）
# --------------------------------------------------------------------------- #
class CouchbaseStore(ExtStore):
    protocol = "couchbase"
    pip = "couchbase"

    def _cluster(self):
        cb = lazy_import("couchbase", "couchbase")
        conn = require(self.cfg, "url", label="连接串")
        opts = cb.ClusterOptions(
            cb.PasswordAuthenticator(username=self.cfg.get("username") or "Administrator",
                                     password=self.cfg.get("password") or ""))
        cluster = cb.Cluster.connect(conn, opts)
        bucket = self.cfg.get("bucket") or "mineagent"
        return cluster, cluster.bucket(bucket), bucket

    @property
    def _scope(self) -> str:
        return self.cfg.get("scope") or "_default"

    @property
    def _coll(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "mineagent")

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        cluster, _, bucket = self._cluster()
        try:
            cluster.query(
                f"CREATE COLLECTION `{bucket}`.`{self._scope}`.`{self._coll}` IF NOT EXISTS")
        except Exception:  # noqa: BLE001
            pass

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        cluster, _, bucket = self._cluster()
        for it in items:
            vid = str(it.get("id") or _rid())
            cluster.query(
                f"UPSERT INTO `{bucket}`.`{self._scope}`.`{self._coll}` "
                f"(KEY, VALUE) VALUES ($key, $val)",
                {"key": vid, "val": {"id": vid, "text": str(it.get("text") or ""),
                                     "metadata": it.get("metadata") or {},
                                     "embedding": [float(x) for x in it.get("vector") or []]}})
        return len(items)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        cluster, _, bucket = self._cluster()
        fn = "APPROX_VECTOR_DISTANCE"
        rows = cluster.query(
            f"SELECT id, text, metadata, "
            f"{fn}(embedding, $vec, {json.dumps('cosine')}) AS d "
            f"FROM `{bucket}`.`{self._scope}`.`{self._coll}` "
            f"ORDER BY d ASC LIMIT $k",
            {"vec": [float(x) for x in vector], "k": max(1, int(top_k))})
        out = []
        for row in rows:
            md = row.get("metadata") or {}
            if where and any(md.get(k) != v for k, v in where.items()):
                continue
            out.append({"id": str(row.get("id", "")), "text": row.get("text", ""),
                        "metadata": md,
                        "score": round(_dist_to_score(float(row.get("d") or 0), "cosine"), 6)})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        cluster, _, bucket = self._cluster()
        for vid in ids:
            cluster.query(f"DELETE FROM `{bucket}`.`{self._scope}`.`{self._coll}` WHERE id = $id",
                          {"id": str(vid)})
        return len(ids)

    def probe(self) -> Dict[str, Any]:
        cluster, _, _ = self._cluster()
        ping = getattr(cluster, "ping", None)
        if callable(ping):
            ping()
        return {"ok": True, "message": "Couchbase 连接成功"}


# --------------------------------------------------------------------------- #
# Oracle AI Vector Search
# --------------------------------------------------------------------------- #
class OracleVectorStore(ExtStore):
    protocol = "oracle_vector"
    pip = "oracledb"

    def _connect(self):
        oracledb = lazy_import("oracledb", "oracledb")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"oracle://{dsn}"
        parsed = urllib.parse.urlsplit(raw)
        user = urllib.parse.unquote(parsed.username or "")
        password = urllib.parse.unquote(parsed.password or "")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 1521
        service = (parsed.path or "/").lstrip("/") or "ORCL"
        return oracledb.connect(user=user, password=password,
                                dsn=f"{host}:{port}/{service}")

    def _table(self, name: str) -> str:
        return _safe_ident(self.cfg.get("table") or self.resolve_name(name)).upper()

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"BEGIN EXECUTE IMMEDIATE 'CREATE TABLE {self._table(name)} ("
                f"id VARCHAR2(160) PRIMARY KEY, text CLOB, metadata CLOB,"
                f" embedding VECTOR({int(dim)}, FLOAT32))'; "
                f"EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;")
            conn.commit()
        finally:
            conn.close()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            for it in items:
                cur.execute(
                    f"MERGE INTO {self._table(name)} t USING (SELECT :1 AS id FROM dual) s "
                    f"ON (t.id = s.id) WHEN MATCHED THEN UPDATE SET text = :2, "
                    f"metadata = :3, embedding = TO_VECTOR(:4) "
                    f"WHEN NOT MATCHED THEN INSERT (id, text, metadata, embedding) "
                    f"VALUES (:1, :2, :3, TO_VECTOR(:4))",
                    [str(it.get("id") or _rid()), str(it.get("text") or ""),
                     json.dumps(it.get("metadata") or {}, ensure_ascii=False),
                     _vec_to_literal(it.get("vector") or [])])
            conn.commit()
            return len(items)
        finally:
            conn.close()

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT id, text, metadata, "
                f"VECTOR_DISTANCE(embedding, TO_VECTOR(:1), COSINE) AS d "
                f"FROM {self._table(name)} ORDER BY d FETCH FIRST :2 ROWS ONLY",
                [_vec_to_literal(vector), max(1, int(top_k))])
            out = []
            for row in cur.fetchall():
                md = load_json_ish(row[2])
                out.append({"id": row[0], "text": row[1] or "", "metadata": md,
                            "score": round(_dist_to_score(float(row[3] or 0), "cosine"), 6)})
            return out
        finally:
            conn.close()

    def probe(self) -> Dict[str, Any]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
            row = cur.fetchone()
            return {"ok": True, "message": f"Oracle 连接成功（{row[0] if row else '?'}）"}
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# SAP HANA Vector
# --------------------------------------------------------------------------- #
class HANAStore(ExtStore):
    protocol = "hana_vector"
    pip = "hdbcli"

    def _connect(self):
        hdbcli = lazy_import("hdbcli", "hdbcli", attr="dbapi")
        return hdbcli.connect(
            address=require(self.cfg, "host", label="Host"),
            port=int(self.cfg.get("port") or 443),
            user=self.cfg.get("username") or "",
            password=self.cfg.get("password") or "",
            encrypt="true")

    def _table(self, name: str) -> str:
        return _safe_ident(self.cfg.get("table") or self.resolve_name(name)).upper()

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"CREATE TABLE {self._table(name)} ("
                f"ID NVARCHAR(160) PRIMARY KEY, TEXT NCLOB, METADATA NCLOB,"
                f" EMBEDDING REAL_VECTOR)")
            conn.commit()
        except Exception:  # noqa: BLE001
            pass
        finally:
            conn.close()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            for it in items:
                cur.execute(
                    f"UPSERT {self._table(name)} (ID, TEXT, METADATA, EMBEDDING) "
                    f"VALUES (?, ?, ?, TO_REAL_VECTOR(?)) WITH PRIMARY KEY",
                    (str(it.get("id") or _rid()), str(it.get("text") or ""),
                     json.dumps(it.get("metadata") or {}, ensure_ascii=False),
                     _vec_to_literal(it.get("vector") or [])))
            conn.commit()
            return len(items)
        finally:
            conn.close()

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT ID, TEXT, METADATA, "
                f"COSINE_SIMILARITY(EMBEDDING, TO_REAL_VECTOR(?)) AS S "
                f"FROM {self._table(name)} ORDER BY S DESC LIMIT ?",
                (_vec_to_literal(vector), max(1, int(top_k))))
            out = []
            for row in cur.fetchall():
                out.append({"id": row[0], "text": row[1] or "",
                            "metadata": load_json_ish(row[2]),
                            "score": round(float(row[3] or 0), 6)})
            return out
        finally:
            conn.close()

    def probe(self) -> Dict[str, Any]:
        conn = self._connect()
        conn.close()
        return {"ok": True, "message": "SAP HANA 连接成功"}


# --------------------------------------------------------------------------- #
# Vertex AI Vector Search（REST + 访问令牌）
# --------------------------------------------------------------------------- #
class VertexVectorStore(ExtStore):
    protocol = "vertex_vector"
    pip = ""

    def _url(self, action: str) -> str:
        project = require(self.cfg, "project", label="Project ID")
        location = self.cfg.get("location") or "us-central1"
        endpoint = require(self.cfg, "index_endpoint", label="Index Endpoint")
        return (f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
                f"/locations/{location}/indexEndpoints/{endpoint}:{action}")

    def _headers(self) -> Dict[str, str]:
        token = require(self.cfg, "api_key", label="访问令牌")
        return {"Authorization": f"Bearer {token}"}

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        return None  # 索引与部署在控制台建

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        datapoints = [{"datapoint_id": str(it.get("id") or _rid()),
                       "feature_vector": [float(x) for x in it.get("vector") or []]}
                      for it in items]
        http_json(self._url("upsertDatapoints"), {"datapoints": datapoints},
                  headers=self._headers(), timeout=60)
        return len(datapoints)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload = {
            "deployed_index_id": require(self.cfg, "deployed_index",
                                         label="Deployed Index ID"),
            "queries": [{"datapoint_id": "q", "feature_vector":
                         [float(x) for x in vector], "approximate_neighbors_count":
                         max(1, int(top_k))}],
            "return_full_datapoint": False,
        }
        data = http_json(self._url("findNeighbors"), payload,
                         headers=self._headers(), timeout=60)
        out = []
        for neighbor in (((data.get("nearestNeighbors") or [{}])[0]).get("neighbors") or []):
            out.append({"id": str(neighbor.get("datapointId", "")),
                        "text": "", "metadata": {},
                        "score": round(float(neighbor.get("distance") or 0), 6)})
        return out

    def probe(self) -> Dict[str, Any]:
        http_json(self._url("findNeighbors"),
                  {"deployed_index_id": self.cfg.get("deployed_index") or "",
                   "queries": []}, headers=self._headers(), timeout=20)
        return {"ok": True, "message": "Vertex AI 连接成功"}


# --------------------------------------------------------------------------- #
# DashVector（阿里云）
# --------------------------------------------------------------------------- #
class DashVectorStore(ExtStore):
    protocol = "dashvector"
    pip = "dashvector"

    def _client(self):
        dv = lazy_import("dashvector", "dashvector")
        return dv.Client(api_key=require(self.cfg, "api_key", label="API Key"),
                         endpoint=require(self.cfg, "endpoint", label="Endpoint"))

    @property
    def _coll_name(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "mineagent")

    def _dv_metric(self):
        dv = lazy_import("dashvector", "dashvector")
        mapping = {"cosine": "cosine", "dot": "dotproduct", "euclidean": "euclidean"}
        return getattr(dv.Metric, mapping[self.metric])

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        client = self._client()
        got = client.get(self._coll_name)
        if getattr(got, "code", -1) == 0:
            return
        created = client.create(self._coll_name, dimension=int(dim),
                                metric=self._dv_metric(), dtype=float)
        if getattr(created, "code", 0) != 0:
            raise ProviderCallError(
                f"DashVector 建集合失败：{getattr(created, 'message', '')}")

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        dv = lazy_import("dashvector", "dashvector")
        coll = self._client().get(self._coll_name)
        docs = [dv.Doc(str(it.get("id") or _rid()),
                       vector=[float(x) for x in it.get("vector") or []],
                       fields={**(it.get("metadata") or {}),
                               "text": str(it.get("text") or "")})
                for it in items]
        result = coll.insert(docs)
        if getattr(result, "code", 0) != 0:
            raise ProviderCallError(
                f"DashVector 写入失败：{getattr(result, 'message', '')}")
        return len(docs)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        coll = self._client().get(self._coll_name)
        kwargs: Dict[str, Any] = {
            "vector": [float(x) for x in vector],
            "topk": max(1, int(top_k)),
            "output_fields": ["text"],
            "include_vector": False,
        }
        if where:
            kwargs["filter"] = " AND ".join(f"{k}='{v}'" for k, v in where.items())
        result = coll.query(**kwargs)
        out = []
        for doc in (getattr(result, "output", None) or []):
            fields = dict(getattr(doc, "fields", {}) or {})
            text = str(fields.pop("text", ""))
            out.append({"id": str(getattr(doc, "id", "")), "text": text,
                        "metadata": fields,
                        "score": round(float(getattr(doc, "score", 0) or 0), 6)})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        coll = self._client().get(self._coll_name)
        coll.delete(ids=[str(i) for i in ids])
        return len(ids)

    def drop(self, name: str) -> None:
        try:
            self._client().delete(self._coll_name)
        except Exception:  # noqa: BLE001
            pass

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        result = client.get(self._coll_name)
        return {"ok": True, "message": "DashVector 连接成功"}


# --------------------------------------------------------------------------- #
# 腾讯云 VectorDB
# --------------------------------------------------------------------------- #
class TencentVectorStore(ExtStore):
    protocol = "tencent_vectordb"
    pip = "tcvectordb"

    def _client(self):
        tc = lazy_import("tcvectordb", "tcvectordb", attr="VectorDBClient")
        return tc(url=require(self.cfg, "url", label="访问地址"),
                  username=self.cfg.get("username") or "root",
                  key=require(self.cfg, "api_key", label="Key"))

    def _database(self):
        return self.cfg.get("database") or "mineagent"

    @property
    def _coll_name(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "mineagent")

    def _coll(self):
        client = self._client()
        db = client.database(self._database())
        return db.collection(self._coll_name)

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        client = self._client()
        try:
            client.create_database(self._database())
        except Exception:  # noqa: BLE001
            pass
        db = client.database(self._database())
        try:
            db.describe_collection(self._coll_name)
            return
        except Exception:  # noqa: BLE001
            pass
        db.create_collection(self._coll_name, int(dim),
                             index_type="HNSW", metric_type=self.metric.upper())

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        tc = lazy_import("tcvectordb", "tcvectordb", attr="Document")
        coll = self._coll()
        docs = [tc(id=str(it.get("id") or _rid()),
                   vector=[float(x) for x in it.get("vector") or []],
                   data={**(it.get("metadata") or {}),
                         "text": str(it.get("text") or "")})
                for it in items]
        coll.upsert(documents=docs)
        return len(docs)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        coll = self._coll()
        kwargs: Dict[str, Any] = {
            "vectors": [[float(x) for x in vector]],
            "limit": max(1, int(top_k)),
            "output_fields": ["text"],
        }
        if where:
            kwargs["filter"] = " and ".join(f"{k}='{v}'" for k, v in where.items())
        result = coll.search(**kwargs)
        out = []
        for hit in (result or []):
            for doc in (getattr(hit, "documents", None) or []):
                data = dict(getattr(doc, "data", {}) or {})
                text = str(data.pop("text", ""))
                out.append({"id": str(getattr(doc, "id", "")), "text": text,
                            "metadata": data,
                            "score": round(float(getattr(doc, "score", 0) or 0), 6)})
        return out

    def delete(self, name: str, ids: List[str]) -> int:
        self._coll().delete(ids=[str(i) for i in ids])
        return len(ids)

    def drop(self, name: str) -> None:
        try:
            self._client().database(self._database()).drop_collection(self._coll_name)
        except Exception:  # noqa: BLE001
            pass

    def probe(self) -> Dict[str, Any]:
        self._client().database(self._database())
        return {"ok": True, "message": "腾讯云 VectorDB 连接成功"}


# --------------------------------------------------------------------------- #
# 百度向量数据库（Mochow）
# --------------------------------------------------------------------------- #
class BaiduVectorStore(ExtStore):
    protocol = "baidu_vectordb"
    pip = "pymochow"

    def _client(self):
        mochow = lazy_import("pymochow.mochow_client", "pymochow", attr="MochowClient")
        conf_mod = lazy_import("pymochow.configuration", "pymochow",
                               attr="Configuration")
        cred_mod = lazy_import("pymochow.auth.bce_credentials", "pymochow",
                               attr="BceCredentials")
        account = require(self.cfg, "account", label="账号")
        api_key = require(self.cfg, "api_key", label="API Key")
        endpoint = require(self.cfg, "url", label="访问地址")
        config = conf_mod(credentials=cred_mod(account, api_key), endpoint=endpoint)
        return mochow(config)

    @property
    def _table_name(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "mineagent")

    def _table(self):
        client = self._client()
        db = client.database(self.cfg.get("database") or "mineagent")
        return db.table(self._table_name)

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        client = self._client()
        db_name = self.cfg.get("database") or "mineagent"
        try:
            client.create_database(db_name)
        except Exception:  # noqa: BLE001
            pass
        db = client.database(db_name)
        try:
            db.describe_table(self._table_name)
            return
        except Exception:  # noqa: BLE001
            pass
        from pymochow.model.schema import Field, Schema, VectorIndex  # type: ignore
        from pymochow.model.enum import FieldType, IndexType, MetricType  # type: ignore
        schema = Schema(fields=[
            Field("id", FieldType.STRING, primary_key=True),
            Field("text", FieldType.STRING),
            Field("metadata", FieldType.STRING),
            Field("vector", FieldType.FLOAT_VECTOR, dimension=int(dim)),
        ], indexes=[VectorIndex(
            index_name="vector_idx", field="vector", index_type=IndexType.HNSW,
            metric_type=getattr(MetricType, self.metric.upper()))])
        db.create_table(self._table_name, schema)

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        rows = [{"id": str(it.get("id") or _rid()),
                 "text": str(it.get("text") or ""),
                 "metadata": json.dumps(it.get("metadata") or {}, ensure_ascii=False),
                 "vector": [float(x) for x in it.get("vector") or []]}
                for it in items]
        self._table().upsert(rows=rows)
        return len(rows)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        result = self._table().search(
            vector=[float(x) for x in vector], limit=max(1, int(top_k)),
            output_fields=["id", "text", "metadata"])
        out = []
        for row in (getattr(result, "rows", None) or []):
            data = dict(row)
            out.append({"id": str(data.get("id", "")),
                        "text": str(data.get("text", "")),
                        "metadata": load_json_ish(data.get("metadata")),
                        "score": round(float(data.get("score", 0) or 0), 6)})
        return out

    def probe(self) -> Dict[str, Any]:
        self._client().database(self.cfg.get("database") or "mineagent")
        return {"ok": True, "message": "百度向量数据库连接成功"}


# --------------------------------------------------------------------------- #
# 火山引擎 VikingDB
# --------------------------------------------------------------------------- #
class VikingDBStore(ExtStore):
    protocol = "vikingdb"
    pip = "volcengine"

    def _service(self):
        vk = lazy_import("volcengine.viking_db", "volcengine", attr="VikingDBService")
        return vk(host=require(self.cfg, "host", label="访问地址"),
                  region=self.cfg.get("region") or "cn-beijing",
                  ak=require(self.cfg, "ak", label="Access Key"),
                  sk=require(self.cfg, "sk", label="Secret Key"))

    @property
    def _coll_name(self) -> str:
        return self.resolve_name(self.cfg.get("collection") or "mineagent")

    def _coll(self):
        return self._service().get_collection(self._coll_name)

    def ensure_collection(self, name: str, dim: int, metric: str = "",
                          model: str = "") -> None:
        # 集合与索引在控制台建，这里只确认能取到
        self._coll()

    def upsert(self, name: str, items: List[Dict[str, Any]]) -> int:
        vk = lazy_import("volcengine.viking_db", "volcengine", attr="Data")
        coll = self._coll()
        docs = [vk(id=str(it.get("id") or _rid()),
                   fields={**(it.get("metadata") or {}),
                           "text": str(it.get("text") or "")},
                   vector=[float(x) for x in it.get("vector") or []])
                for it in items]
        coll.upsert_data(docs)
        return len(docs)

    def search(self, name: str, vector: List[float], top_k: int = 4,
               where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        coll = self._coll()
        rows = coll.search_by_vector(
            vector=[float(x) for x in vector], limit=max(1, int(top_k)),
            output_fields=["text"])
        out = []
        for row in (rows or []):
            fields = dict(getattr(row, "fields", {}) or {})
            text = str(fields.pop("text", ""))
            out.append({"id": str(getattr(row, "id", "")), "text": text,
                        "metadata": fields,
                        "score": round(float(getattr(row, "score", 0) or 0), 6)})
        return out

    def probe(self) -> Dict[str, Any]:
        self._coll()
        return {"ok": True, "message": "VikingDB 连接成功"}
