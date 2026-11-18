"""数据库适配层：把「业务/文档/图/缓存/时序库」统一成一套可调用接口。

统一接口只有四个方法：
    probe()                    连接测试
    query(statement, params)   读（SQL / Cypher / 命令 / filter JSON）
    write(statement, params)   写
    collections()              列出可用的库/表/索引

statement 的具体语法由数据库类型决定，节点里的代码按类型调用。
一律懒加载；缺库抛 ProviderUnavailable（带 pip 命令）。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import as_int, lazy_import, require
from .catalog import find
from .errors import ProviderCallError, ProviderConfigError

_READ_ONLY = re.compile(r"^\s*(select|with|show|describe|desc|explain)\b", re.I)


class BaseDB:
    protocol = "base"
    pip = ""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg or {}
        self.base_dir = Path(str(self.cfg.get("base_dir") or "."))

    def probe(self) -> Dict[str, Any]:
        raise NotImplementedError

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        raise NotImplementedError

    def collections(self) -> List[str]:
        return []

    def _missing(self, module: str, pip: str = "") -> Any:
        return lazy_import(module, pip or self.pip or module)

    def _guard_read(self, statement: str) -> str:
        if not _READ_ONLY.match(statement or ""):
            raise ProviderConfigError(
                "query 只接受读语句",
                hint="写操作请用 write()，避免误删生产数据")
        return statement.strip().rstrip(";")


# --------------------------------------------------------------------------- #
# 内置 SQLite
# --------------------------------------------------------------------------- #
class SQLiteDB(BaseDB):
    protocol = "sqlite"

    def _path(self) -> Path:
        rel = str(self.cfg.get("path") or ".store.db")
        path = Path(rel)
        return path if path.is_absolute() else (self.base_dir / path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path()), timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def probe(self) -> Dict[str, Any]:
        path = self._path()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return {"ok": True,
                    "message": f"SQLite 可用（{path.name}，{len(rows)} 张表）"}
        finally:
            conn.close()

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        sql = self._guard_read(statement)
        conn = self._conn()
        try:
            cur = conn.execute(sql, params or [])
            return [dict(row) for row in cur.fetchall()[:max(1, as_int(limit, 100))]]
        finally:
            conn.close()

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        conn = self._conn()
        try:
            cur = conn.execute(statement, params or [])
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def collections(self) -> List[str]:
        conn = self._conn()
        try:
            return [row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# PostgreSQL 家族（postgres / greenplum / redshift / gaussdb / timescaledb）
# --------------------------------------------------------------------------- #
class PostgresDB(BaseDB):
    protocol = "postgres"
    pip = "psycopg[binary]"

    def _connect(self):
        dsn = require(self.cfg, "dsn", label="连接串")
        try:
            psycopg = lazy_import("psycopg", "psycopg[binary]")
            return psycopg.connect(dsn, connect_timeout=10)
        except Exception as exc:  # noqa: BLE001
            if exc.__class__.__name__ != "ProviderUnavailable":
                raise
            psycopg2 = lazy_import("psycopg2", "psycopg2-binary")
            return psycopg2.connect(dsn, connect_timeout=10)

    def probe(self) -> Dict[str, Any]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT version()")
            version = str(cur.fetchone()[0]).split(",")[0]
            return {"ok": True, "message": f"PostgreSQL 连接成功（{version}）"}
        finally:
            conn.close()

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        sql = self._guard_read(statement)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params or [])
            cols = [d[0] for d in (cur.description or [])]
            return [dict(zip(cols, row)) for row in cur.fetchall()[:max(1, as_int(limit, 100))]]
        finally:
            conn.close()

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(statement, params or [])
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def collections(self) -> List[str]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' ORDER BY table_name")
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# MySQL 家族（mysql / mariadb / tidb / oceanbase / polardb / doris / starrocks）
# --------------------------------------------------------------------------- #
class MySQLDB(BaseDB):
    protocol = "mysql"
    pip = "pymysql"

    def _connect(self):
        pymysql = self._missing("pymysql")
        dsn = require(self.cfg, "dsn", label="连接串")
        parsed = _parse_dsn(dsn, default_port=3306)
        return pymysql.connect(
            host=parsed["host"], port=parsed["port"], user=parsed["user"],
            password=parsed["password"], database=parsed["database"],
            charset="utf8mb4", connect_timeout=10, cursorclass=pymysql.cursors.DictCursor)

    def probe(self) -> Dict[str, Any]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT VERSION() AS v")
            return {"ok": True, "message": f"MySQL 协议连接成功（{cur.fetchone()['v']}）"}
        finally:
            conn.close()

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        sql = self._guard_read(statement)
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(sql, params or ())
            return list(cur.fetchall()[:max(1, as_int(limit, 100))])
        finally:
            conn.close()

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(statement, params or ())
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def collections(self) -> List[str]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SHOW TABLES")
            return [list(row.values())[0] for row in cur.fetchall()]
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# MongoDB（mongodb / documentdb / cosmos vcore / arangodb 的文档面）
# --------------------------------------------------------------------------- #
class MongoDB(BaseDB):
    protocol = "mongodb"
    pip = "pymongo"

    def _client(self):
        pymongo = self._missing("pymongo")
        uri = require(self.cfg, "dsn", label="连接串")
        return pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000)

    @property
    def _db(self):
        name = (self.cfg.get("database") or "mineagent").strip() or "mineagent"
        return self._client()[name]

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        info = client.server_info()
        return {"ok": True, "message": f"MongoDB 连接成功（{info.get('version', '?')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        # statement 可以是 {"collection": "xxx", "filter": {...}} 的 JSON，
        # 也可以直接是 collection 名（表示查全部）
        spec = _json_spec(statement)
        coll = (spec.get("collection") or self.cfg.get("collection")
                or "default")
        flt = spec.get("filter") or {}
        projection = spec.get("projection") or None
        cursor = self._db[coll].find(flt, projection).limit(max(1, as_int(
            spec.get("limit", limit), limit)))
        return [_clean_doc(doc) for doc in cursor]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        spec = _json_spec(statement)
        coll = spec.get("collection") or self.cfg.get("collection") or "default"
        docs = spec.get("documents") or ([] if params is None else params)
        if isinstance(docs, dict):
            docs = [docs]
        return len(self._db[coll].insert_many(list(docs or [])).inserted_ids)

    def collections(self) -> List[str]:
        return list(self._db.list_collection_names())


# --------------------------------------------------------------------------- #
# Redis（redis / valkey）
# --------------------------------------------------------------------------- #
class RedisDB(BaseDB):
    protocol = "redis"
    pip = "redis"

    def _client(self):
        redis_mod = self._missing("redis")
        url = require(self.cfg, "dsn", label="连接串")
        return redis_mod.from_url(url, socket_connect_timeout=8,
                                  socket_timeout=15, decode_responses=True)

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        info = client.info()
        return {"ok": True,
                "message": f"Redis 连接成功（v{info.get('redis_version', '?')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        # statement 是一个命令，例如 "GET key" / "HGETALL key" / "SCAN 0 MATCH *"
        parts = _split_command(statement)
        if not parts:
            return []
        result = self._client().execute_command(*parts)
        if isinstance(result, dict):
            return [result]
        if isinstance(result, (list, tuple)):
            return [{"value": item} for item in result[:max(1, as_int(limit, 100))]]
        return [{"value": result}]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        parts = _split_command(statement)
        if not parts:
            return 0
        return int(self._client().execute_command(*parts) or 0)

    def collections(self) -> List[str]:
        return [str(k) for k in self._client().scan_iter("*", count=100)]


# --------------------------------------------------------------------------- #
# Neo4j（neo4j / memgraph / bolt）
# --------------------------------------------------------------------------- #
class Neo4jDB(BaseDB):
    protocol = "neo4j"
    pip = "neo4j"

    def _driver(self):
        neo4j = self._missing("neo4j")
        uri = require(self.cfg, "uri", label="连接地址")
        return neo4j.GraphDatabase.driver(
            uri, auth=(self.cfg.get("username") or "neo4j",
                       self.cfg.get("password") or ""))

    def probe(self) -> Dict[str, Any]:
        driver = self._driver()
        try:
            driver.verify_connectivity()
            return {"ok": True, "message": "Neo4j 连接成功"}
        finally:
            driver.close()

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        driver = self._driver()
        try:
            with driver.session() as session:
                result = session.run(statement or "", params or {})
                return [dict(record) for record in result][
                    :max(1, as_int(limit, 100))]
        finally:
            driver.close()

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        driver = self._driver()
        try:
            with driver.session() as session:
                result = session.run(statement or "", params or {})
                summary = result.consume()
                return int(getattr(summary, "counters", {}).get(
                    "nodes_created", 0)) if summary else 0
        finally:
            driver.close()

    def collections(self) -> List[str]:
        try:
            rows = self.query("CALL db.labels()", limit=200)
            return [str(list(r.values())[0]) for r in rows]
        except Exception:  # noqa: BLE001
            return []


# --------------------------------------------------------------------------- #
# 工厂
# --------------------------------------------------------------------------- #
_PROTOCOLS = {
    "sqlite": SQLiteDB,
    "postgres": PostgresDB,
    "mysql": MySQLDB,
    "mongodb": MongoDB,
    "redis": RedisDB,
    "neo4j": Neo4jDB,
    "bolt": Neo4jDB,
}


def get_database(cfg: Dict[str, Any]) -> BaseDB:
    protocol = (cfg.get("protocol") or "").strip().lower()
    if not protocol:
        provider_id = (cfg.get("provider") or "").strip()
        item = find("data", provider_id) if provider_id else None
        protocol = (item or {}).get("protocol", "sqlite")
    impl = _PROTOCOLS.get(protocol)
    if impl is None:
        item = find("data", protocol) or {}
        status = item.get("status", "planned")
        if status == "planned":
            raise ProviderConfigError(
                f"数据源「{item.get('label') or protocol}」已列入清单，适配器还没实现",
                hint="先用已支持的：内置 SQLite / PostgreSQL / MySQL / MongoDB / Redis / Neo4j")
        raise ProviderConfigError(f"未知的数据源协议：{protocol}")
    return impl(cfg)


def probe_data(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return get_database(cfg).probe()


def supported_protocols() -> List[str]:
    return sorted(_PROTOCOLS)


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _parse_dsn(dsn: str, default_port: int = 3306) -> Dict[str, Any]:
    import urllib.parse
    raw = dsn if "://" in dsn else f"mysql://{dsn}"
    parsed = urllib.parse.urlsplit(raw)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or default_port,
        "user": urllib.parse.unquote(parsed.username or "root"),
        "password": urllib.parse.unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/") or None,
    }


def _json_spec(statement: str) -> Dict[str, Any]:
    text = (statement or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError as exc:
            raise ProviderConfigError("JSON 写法有误", hint=str(exc)) from exc
    return {"collection": text}


def _split_command(statement: str) -> List[str]:
    return [part for part in (statement or "").split() if part]


def _clean_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """把 Mongo 的 ObjectId / datetime 转成可 JSON 序列化的值。"""
    out: Dict[str, Any] = {}
    for key, value in (doc or {}).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = {k: (str(v) if not isinstance(
                v, (str, int, float, bool)) and v is not None else v)
                for k, v in value.items()}
        else:
            out[key] = str(value)
    return out


# --------------------------------------------------------------------------- #
# 扩展批次：把 datastore_ext.py 里的适配器注册进来
# （放在文件末尾，避免与 ext 模块形成循环导入）
# --------------------------------------------------------------------------- #
from .datastore_ext import (ArangoDBDB, BigQueryDB, CassandraDB,  # noqa: E402
                            ClickHouseDB, CouchDBDB, CouchbaseDB,
                            DatabricksDB, DgraphDB, DuckDBDB, DynamoDBDB,
                            EtcdDB, FirestoreDB, GremlinDB, HBaseDB, HiveDB,
                            HugeGraphDB, InfluxDBDB, MemcachedDB, NebulaDB,
                            OracleDB, PrometheusDB, SnowflakeDB, SQLServerDB,
                            TDengineDB, TigerGraphDB, TrinoDB, TuGraphDB)

_PROTOCOLS.update({
    "clickhouse": ClickHouseDB,
    "duckdb": DuckDBDB,
    "prometheus": PrometheusDB,
    "influxdb": InfluxDBDB,
    "couchdb": CouchDBDB,
    "arangodb": ArangoDBDB,
    "dgraph": DgraphDB,
    "tugraph": TuGraphDB,
    "tigergraph": TigerGraphDB,
    "sqlserver": SQLServerDB,
    "oracle": OracleDB,
    "snowflake": SnowflakeDB,
    "databricks": DatabricksDB,
    "trino": TrinoDB,
    "hive": HiveDB,
    "tdengine": TDengineDB,
    "bigquery": BigQueryDB,
    "memcached": MemcachedDB,
    "etcd": EtcdDB,
    "dynamodb": DynamoDBDB,
    "cassandra": CassandraDB,
    "hbase": HBaseDB,
    "couchbase": CouchbaseDB,
    "firestore": FirestoreDB,
    "gremlin": GremlinDB,
    "nebula": NebulaDB,
    "hugegraph": HugeGraphDB,
})
