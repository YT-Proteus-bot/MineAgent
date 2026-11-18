"""数据源适配层（扩展批次）。

接口与 datastore.py 一致：probe / query / write / collections。
statement 的语法随数据库而定（SQL / AQL / DQL / PromQL / Flux / Mango JSON）。
不 import datastore，避免循环依赖。
"""
from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (as_int, http_json, join_url, lazy_import, load_json_ish,
                   require)
from .errors import ProviderCallError, ProviderConfigError


class ExtDB:
    """扩展数据源适配器的轻量基类。"""

    protocol = "ext"

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg or {}
        self.base_dir = Path(str(self.cfg.get("base_dir") or os.getcwd()))

    def probe(self) -> Dict[str, Any]:
        raise NotImplementedError

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        raise NotImplementedError

    def collections(self) -> List[str]:
        return []


# --------------------------------------------------------------------------- #
# ClickHouse（HTTP 接口）
# --------------------------------------------------------------------------- #
class ClickHouseDB(ExtDB):
    protocol = "clickhouse"
    pip = ""

    def _parts(self):
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"http://{dsn}"
        p = urllib.parse.urlsplit(raw)
        scheme = p.scheme or "http"
        host = p.hostname or "127.0.0.1"
        port = p.port or (8443 if scheme == "https" else 8123)
        db = (p.path or "/default").lstrip("/") or "default"
        headers = {"X-ClickHouse-User": urllib.parse.unquote(p.username or "default")}
        if p.password:
            headers["X-ClickHouse-Key"] = urllib.parse.unquote(p.password)
        return f"{scheme}://{host}:{port}/?database={urllib.parse.quote(db)}", headers

    def _run(self, sql: str, fmt: str = "JSONEachRow", timeout: float = 60.0) -> str:
        import urllib.error
        import urllib.request
        base, headers = self._parts()
        url = base + "&query=" + urllib.parse.quote(sql.rstrip().rstrip(";") +
                                                    (f" FORMAT {fmt}" if fmt and "FORMAT" not in sql.upper() else ""))
        req = urllib.request.Request(url, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            raise ProviderCallError("ClickHouse 请求失败", status=exc.code,
                                    detail=detail) from exc

    def probe(self) -> Dict[str, Any]:
        version = self._run("SELECT version()", fmt="TabSeparated").strip()
        return {"ok": True, "message": f"ClickHouse 连接成功（{version}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        raw = self._run(statement)
        rows = []
        for line in raw.splitlines():
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= max(1, as_int(limit, 100)):
                break
        return rows

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self._run(statement, fmt="")
        return 1

    def collections(self) -> List[str]:
        raw = self._run("SHOW TABLES", fmt="TabSeparated")
        return [line.strip() for line in raw.splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# DuckDB
# --------------------------------------------------------------------------- #
class DuckDBDB(ExtDB):
    protocol = "duckdb"
    pip = "duckdb"

    def _conn(self):
        duckdb = lazy_import("duckdb", "duckdb")
        rel = str(self.cfg.get("dsn") or "./analytics.duckdb")
        p = Path(rel)
        path = p if p.is_absolute() else (self.base_dir / p)
        path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(path))

    def probe(self) -> Dict[str, Any]:
        conn = self._conn()
        try:
            v = conn.execute("SELECT version()").fetchone()
            return {"ok": True, "message": f"DuckDB 连接成功（{v[0] if v else '?'}）"}
        finally:
            conn.close()

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._conn()
        try:
            cur = conn.execute(statement, params or [])
            cols = [d[0] for d in (cur.description or [])]
            return [dict(zip(cols, row)) for row in cur.fetchmany(max(1, as_int(limit, 100)))]
        finally:
            conn.close()

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        conn = self._conn()
        try:
            conn.execute(statement, params or [])
            return 1
        finally:
            conn.close()

    def collections(self) -> List[str]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables").fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Prometheus（PromQL over HTTP）
# --------------------------------------------------------------------------- #
class PrometheusDB(ExtDB):
    protocol = "prometheus"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "dsn", label="服务地址").rstrip("/")

    def _get(self, path: str, params: Dict[str, Any], timeout: float = 30.0) -> Any:
        url = join_url(self._base(), path) + "?" + urllib.parse.urlencode(params)
        return http_json(url, method="GET", timeout=timeout)

    def probe(self) -> Dict[str, Any]:
        data = self._get("/api/v1/status/buildinfo", {})
        info = (data or {}).get("data") or {}
        return {"ok": True, "message": f"Prometheus 连接成功（{info.get('version', '?')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        data = self._get("/api/v1/query", {"query": statement})
        result = ((data or {}).get("data") or {}).get("result") or []
        out = []
        for row in result[:max(1, as_int(limit, 100))]:
            metric = dict(row.get("metric") or {})
            value = row.get("value") or [None, None]
            out.append({"metric": metric, "timestamp": value[0], "value": value[1]})
        return out

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        raise ProviderConfigError("Prometheus 是只读时序库，不支持写入",
                                  hint="需要写入请用 Prometheus 的 remote_write 或 Pushgateway")

    def collections(self) -> List[str]:
        data = self._get("/api/v1/label/__name__/values", {})
        return list(((data or {}).get("data") or []))[:200]


# --------------------------------------------------------------------------- #
# InfluxDB 2.x（Flux over HTTP）
# --------------------------------------------------------------------------- #
class InfluxDBDB(ExtDB):
    protocol = "influxdb"
    pip = ""

    def _cfg(self):
        url = require(self.cfg, "dsn", label="服务地址").rstrip("/")
        token = self.cfg.get("token") or self.cfg.get("api_key") or ""
        org = self.cfg.get("org") or ""
        return url, token, org

    def _headers(self) -> Dict[str, str]:
        _, token, _ = self._cfg()
        headers = {"Content-Type": "application/vnd.flux"}
        if token:
            headers["Authorization"] = f"Token {token}"
        return headers

    def probe(self) -> Dict[str, Any]:
        url, _, _ = self._cfg()
        data = http_json(join_url(url, "health"), method="GET", timeout=15)
        return {"ok": True, "message": f"InfluxDB 连接成功（{data.get('status', '?')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        url, _, org = self._cfg()
        endpoint = join_url(url, "api/v2/query") + "?" + urllib.parse.urlencode(
            {"org": org})
        raw = http_json(endpoint, headers=self._headers(),
                        raw_body=(statement or "").encode("utf-8"),
                        timeout=60)
        # Flux 的 CSV 响应被 http_json 解析会失败，这里兜底用原始文本
        if isinstance(raw, dict):
            return [raw]
        return []

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        url, _, _ = self._cfg()
        http_json(join_url(url, "api/v2/write"), headers={},
                  raw_body=(statement or "").encode("utf-8"), method="POST", timeout=30)
        return 1

    def collections(self) -> List[str]:
        return []


# --------------------------------------------------------------------------- #
# CouchDB（Mango 查询）
# --------------------------------------------------------------------------- #
class CouchDBDB(ExtDB):
    protocol = "couchdb"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "dsn", label="连接串").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        raw = self.cfg.get("dsn") or ""
        p = urllib.parse.urlsplit(raw if "://" in raw else f"http://{raw}")
        headers = {}
        if p.username:
            import base64
            token = f"{urllib.parse.unquote(p.username)}:{urllib.parse.unquote(p.password or '')}"
            headers["Authorization"] = "Basic " + base64.b64encode(
                token.encode("utf-8")).decode("ascii")
        return headers

    def probe(self) -> Dict[str, Any]:
        data = http_json(self._base(), method="GET", headers=self._headers(), timeout=15)
        return {"ok": True, "message": f"CouchDB 连接成功（{data.get('version', '?')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        spec = load_json_ish(statement)
        if not isinstance(spec, dict):
            spec = {"selector": {}}
        spec.setdefault("limit", max(1, as_int(limit, 100)))
        data = http_json(join_url(self._base(), "_find"), spec,
                         headers=self._headers(), timeout=30)
        return list(data.get("docs") or [])

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        doc = load_json_ish(statement)
        if not isinstance(doc, dict):
            raise ProviderConfigError("写入需要传一个 JSON 文档")
        http_json(self._base(), doc, headers=self._headers(), method="POST", timeout=30)
        return 1

    def collections(self) -> List[str]:
        data = http_json(join_url(self._base(), "_all_dbs"), method="GET",
                         headers=self._headers(), timeout=15)
        return list(data) if isinstance(data, list) else []


# --------------------------------------------------------------------------- #
# ArangoDB（AQL）
# --------------------------------------------------------------------------- #
class ArangoDBDB(ExtDB):
    protocol = "arangodb"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "dsn", label="连接串").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        import base64
        user = self.cfg.get("username") or "root"
        pwd = self.cfg.get("password") or ""
        token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def _cursor(self, aql: str, bind: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        db = self.cfg.get("database") or "_system"
        url = f"{self._base()}/_db/{urllib.parse.quote(db)}/_api/cursor"
        data = http_json(url, {"query": aql, "bindVars": bind or {},
                               "batchSize": max(1, as_int(self.cfg.get("batch"), 100))},
                         headers=self._headers(), timeout=60)
        return list(data.get("result") or [])

    def probe(self) -> Dict[str, Any]:
        data = http_json(f"{self._base()}/_api/version", method="GET",
                         headers=self._headers(), timeout=15)
        return {"ok": True, "message": f"ArangoDB 连接成功（{data.get('version', '?')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        rows = self._cursor(statement, params if isinstance(params, dict) else {})
        return rows[:max(1, as_int(limit, 100))]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self._cursor(statement, params if isinstance(params, dict) else {})
        return 1

    def collections(self) -> List[str]:
        db = self.cfg.get("database") or "_system"
        url = f"{self._base()}/_db/{urllib.parse.quote(db)}/_api/collection"
        data = http_json(url, method="GET", headers=self._headers(), timeout=15)
        return [c.get("name", "") for c in (data.get("result") or [])]


# --------------------------------------------------------------------------- #
# Dgraph（DQL / gRPC-over-HTTP）
# --------------------------------------------------------------------------- #
class DgraphDB(ExtDB):
    protocol = "dgraph"
    pip = ""

    def _base(self) -> str:
        dsn = require(self.cfg, "dsn", label="连接串")
        return dsn if "://" in dsn else f"http://{dsn}"

    def probe(self) -> Dict[str, Any]:
        data = http_json(join_url(self._base(), "health"), method="GET", timeout=15)
        return {"ok": True, "message": f"Dgraph 连接成功（{data.get('status', '?')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        data = http_json(join_url(self._base(), "query"), raw_body=(statement or "").encode("utf-8"),
                         headers={"Content-Type": "application/dql"}, timeout=30)
        rows = ((data or {}).get("data") or {})
        out: List[Dict[str, Any]] = []
        for key, value in rows.items():
            if isinstance(value, list):
                for item in value[:max(1, as_int(limit, 100))]:
                    out.append({"root": key, "node": item})
            else:
                out.append({"root": key, "node": value})
        return out

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        data = http_json(join_url(self._base(), "mutate"),
                         raw_body=(statement or "").encode("utf-8"), timeout=30)
        return int((data or {}).get("uids", {}).__len__() or 1)


# --------------------------------------------------------------------------- #
# TuGraph（Cypher over HTTP）
# --------------------------------------------------------------------------- #
class TuGraphDB(ExtDB):
    protocol = "tugraph"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "dsn", label="连接串").rstrip("/")

    def probe(self) -> Dict[str, Any]:
        data = http_json(join_url(self._base(), "info"), method="GET", timeout=15)
        return {"ok": True, "message": f"TuGraph 连接成功（{data}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        data = http_json(join_url(self._base(), "cypher"), {"script": statement},
                         timeout=30)
        rows = ((data or {}).get("result") or [])
        return [{"row": r} for r in rows[:max(1, as_int(limit, 100))]]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self.query(statement)
        return 1


# --------------------------------------------------------------------------- #
# TigerGraph（RESTPP）
# --------------------------------------------------------------------------- #
class TigerGraphDB(ExtDB):
    protocol = "tigergraph"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "dsn", label="连接串").rstrip("/")

    def _headers(self) -> Dict[str, str]:
        token = self.cfg.get("api_key") or self.cfg.get("token") or ""
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _graph(self) -> str:
        return self.cfg.get("graph") or "mineagent"

    def probe(self) -> Dict[str, Any]:
        data = http_json(f"{self._base()}/restpp/echo", method="GET",
                         headers=self._headers(), timeout=15)
        return {"ok": True, "message": f"TigerGraph 连接成功（{data.get('message', 'ok')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        data = http_json(
            f"{self._base()}/restpp/query/{self._graph()}/{statement}",
            params or {}, headers=self._headers(), timeout=60)
        rows = (data or {}).get("results") or []
        return [{"result": r} for r in rows[:max(1, as_int(limit, 100))]]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self.query(statement, params)
        return 1


# --------------------------------------------------------------------------- #
# 通用 DB-API 适配器（PEP 249）：SQL Server / Oracle / Snowflake / Databricks / Trino / Hive / TDengine
# --------------------------------------------------------------------------- #
def _dbapi_rows(cursor, limit: int) -> List[Dict[str, Any]]:
    cols = [d[0] for d in (cursor.description or [])]
    rows = cursor.fetchmany(max(1, as_int(limit, 100)))
    return [dict(zip(cols, row)) for row in rows]


class _DBAPI(ExtDB):
    pip = ""

    def _connect(self):
        raise NotImplementedError

    def _version_sql(self) -> str:
        return "SELECT 1"

    def probe(self) -> Dict[str, Any]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(self._version_sql())
            row = cur.fetchone()
            return {"ok": True, "message": f"{self.protocol} 连接成功（{row[0] if row else 'ok'}）"}
        finally:
            conn.close()

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(statement, params or ())
            return _dbapi_rows(cur, limit)
        finally:
            conn.close()

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(statement, params or ())
            conn.commit()
            return int(cur.rowcount or 1)
        finally:
            conn.close()


class SQLServerDB(_DBAPI):
    protocol = "sqlserver"
    pip = "pyodbc"

    def _connect(self):
        pyodbc = lazy_import("pyodbc", "pyodbc")
        dsn = require(self.cfg, "dsn", label="连接串")
        return pyodbc.connect(dsn, timeout=10)

    def _version_sql(self) -> str:
        return "SELECT @@VERSION"

    def collections(self) -> List[str]:
        try:
            return [r.get("name", "") for r in self.query(
                "SELECT name FROM sys.tables ORDER BY name", limit=200)]
        except Exception:  # noqa: BLE001
            return []


class OracleDB(_DBAPI):
    protocol = "oracle"
    pip = "oracledb"

    def _connect(self):
        oracledb = lazy_import("oracledb", "oracledb")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"oracle://{dsn}"
        p = urllib.parse.urlsplit(raw)
        host = p.hostname or "127.0.0.1"
        port = p.port or 1521
        service = (p.path or "/ORCL").lstrip("/")
        return oracledb.connect(
            user=urllib.parse.unquote(p.username or ""),
            password=urllib.parse.unquote(p.password or ""),
            dsn=f"{host}:{port}/{service}")

    def _version_sql(self) -> str:
        return "SELECT banner FROM v$version WHERE ROWNUM = 1"

    def collections(self) -> List[str]:
        try:
            return [r.get("TABLE_NAME", "") for r in self.query(
                "SELECT table_name FROM user_tables ORDER BY table_name", limit=200)]
        except Exception:  # noqa: BLE001
            return []


class SnowflakeDB(_DBAPI):
    protocol = "snowflake"
    pip = "snowflake-connector-python"

    def _connect(self):
        sf = lazy_import("snowflake.connector", "snowflake-connector-python")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"snowflake://{dsn}"
        p = urllib.parse.urlsplit(raw)
        parts = [x for x in (p.path or "").split("/") if x]
        return sf.connect(
            user=urllib.parse.unquote(p.username or ""),
            password=urllib.parse.unquote(p.password or ""),
            account=p.hostname or "",
            database=parts[0] if parts else None,
            schema=parts[1] if len(parts) > 1 else None)

    def _version_sql(self) -> str:
        return "SELECT CURRENT_VERSION()"


class DatabricksDB(_DBAPI):
    protocol = "databricks"
    pip = "databricks-sql-connector"

    def _connect(self):
        dc = lazy_import("databricks.sql", "databricks-sql-connector")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"databricks://{dsn}"
        p = urllib.parse.urlsplit(raw)
        return dc.connect(
            server_hostname=p.hostname or "",
            http_path=(p.path or "/").lstrip("/") and ("/" + (p.path or "").lstrip("/")),
            access_token=self.cfg.get("api_key") or urllib.parse.unquote(p.password or ""))

    def _version_sql(self) -> str:
        return "SELECT version()"


class TrinoDB(_DBAPI):
    protocol = "trino"
    pip = "trino"

    def _connect(self):
        trino = lazy_import("trino", "trino", attr="dbapi")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"trino://{dsn}"
        p = urllib.parse.urlsplit(raw)
        return trino.connect(
            host=p.hostname or "127.0.0.1", port=p.port or 8080,
            user=urllib.parse.unquote(p.username or "trino"),
            catalog=(p.path or "/").lstrip("/").split("/")[0] or None)

    def _version_sql(self) -> str:
        return "SELECT version()"


class HiveDB(_DBAPI):
    protocol = "hive"
    pip = "pyhive"

    def _connect(self):
        hive = lazy_import("pyhive.hive", "pyhive")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"hive://{dsn}"
        p = urllib.parse.urlsplit(raw)
        return hive.Connection(host=p.hostname or "127.0.0.1", port=p.port or 10000,
                               database=(p.path or "/default").lstrip("/") or "default")

    def _version_sql(self) -> str:
        return "SELECT version()"


class TDengineDB(_DBAPI):
    protocol = "tdengine"
    pip = "taospy"

    def _connect(self):
        taos = lazy_import("taos", "taospy")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"taos://{dsn}"
        p = urllib.parse.urlsplit(raw)
        return taos.connect(host=p.hostname or "127.0.0.1", port=p.port or 6030,
                            user=urllib.parse.unquote(p.username or "root"),
                            password=urllib.parse.unquote(p.password or "taosdata"),
                            database=(p.path or "/").lstrip("/") or None)

    def _version_sql(self) -> str:
        return "SELECT server_version()"


# --------------------------------------------------------------------------- #
# BigQuery（google-cloud-bigquery）
# --------------------------------------------------------------------------- #
class BigQueryDB(ExtDB):
    protocol = "bigquery"
    pip = "google-cloud-bigquery"

    def _client(self):
        bq = lazy_import("google.cloud.bigquery", "google-cloud-bigquery",
                         attr="Client")
        project = self.cfg.get("project") or None
        return bq(project=project)

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        return {"ok": True, "message": f"BigQuery 连接成功（项目 {client.project}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        client = self._client()
        job = client.query(statement)
        rows = list(job.result(max_results=max(1, as_int(limit, 100))))
        return [dict(r.items()) for r in rows]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        client = self._client()
        client.query(statement).result()
        return 1

    def collections(self) -> List[str]:
        try:
            client = self._client()
            return [d.dataset_id for d in client.list_datasets(max_results=100)]
        except Exception:  # noqa: BLE001
            return []


# --------------------------------------------------------------------------- #
# Memcached
# --------------------------------------------------------------------------- #
class MemcachedDB(ExtDB):
    protocol = "memcached"
    pip = "pymemcache"

    def _client(self):
        pymemcache = lazy_import("pymemcache", "pymemcache", attr="Client")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"memcached://{dsn}"
        p = urllib.parse.urlsplit(raw)
        return pymemcache.Client((p.hostname or "127.0.0.1", p.port or 11211))

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        client.set("mineagent_ping", "1")
        ok = client.get("mineagent_ping") == b"1"
        return {"ok": ok, "message": "Memcached 连接成功" if ok else "Memcached 读写异常"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        value = self._client().get(str(statement))
        return [{"key": statement, "value": value.decode("utf-8", "replace")
                 if isinstance(value, bytes) else value}]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        # statement 形如 "key=value"
        key, _, val = str(statement).partition("=")
        self._client().set(key.strip(), val.encode("utf-8"))
        return 1


# --------------------------------------------------------------------------- #
# etcd v3
# --------------------------------------------------------------------------- #
class EtcdDB(ExtDB):
    protocol = "etcd"
    pip = "etcd3"

    def _client(self):
        etcd3 = lazy_import("etcd3", "etcd3", attr="client")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"http://{dsn}"
        p = urllib.parse.urlsplit(raw)
        return etcd3.client(host=p.hostname or "127.0.0.1", port=p.port or 2379)

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        client.status()
        return {"ok": True, "message": "etcd 连接成功"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        client = self._client()
        prefix = str(statement or "")
        if prefix:
            pairs = client.get_prefix(prefix, limit=max(1, as_int(limit, 100)))
        else:
            pairs = client.get_all(limit=max(1, as_int(limit, 100)))
        return [{"key": k.decode("utf-8", "replace"), "value": v.decode("utf-8", "replace")}
                for k, v in pairs]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        key, _, val = str(statement).partition("=")
        self._client().put(key.strip(), val)
        return 1


# --------------------------------------------------------------------------- #
# DynamoDB
# --------------------------------------------------------------------------- #
class DynamoDBDB(ExtDB):
    protocol = "dynamodb"
    pip = "boto3"

    def _resource(self):
        boto3 = lazy_import("boto3", "boto3")
        dsn = require(self.cfg, "dsn", label="连接串")
        region = (dsn.split("://")[-1] if "://" in dsn else dsn).strip("/") or "us-east-1"
        kwargs: Dict[str, Any] = {"region_name": region}
        if self.cfg.get("api_key"):
            kwargs["aws_access_key_id"] = self.cfg["api_key"]
        if self.cfg.get("secret"):
            kwargs["aws_secret_access_key"] = self.cfg["secret"]
        return boto3.resource("dynamodb", **kwargs)

    def _table(self):
        return self._resource().Table(self.cfg.get("table") or "mineagent")

    def probe(self) -> Dict[str, Any]:
        self._table().table_status
        return {"ok": True, "message": "DynamoDB 连接成功"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        spec = load_json_ish(statement)
        if not isinstance(spec, dict):
            raise ProviderConfigError("DynamoDB 查询要传 JSON：{\"KeyConditionExpression\": ...}")
        rows = self._table().scan(Limit=max(1, as_int(limit, 100)), **spec)
        return list(rows.get("Items") or [])

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        item = load_json_ish(statement)
        if not isinstance(item, dict):
            raise ProviderConfigError("DynamoDB 写入要传一个 JSON 文档")
        self._table().put_item(Item=item)
        return 1


# --------------------------------------------------------------------------- #
# Cassandra / ScyllaDB
# --------------------------------------------------------------------------- #
class CassandraDB(ExtDB):
    protocol = "cassandra"
    pip = "cassandra-driver"

    def _session(self):
        cluster_mod = lazy_import("cassandra.cluster", "cassandra-driver",
                                  attr="Cluster")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"cassandra://{dsn}"
        p = urllib.parse.urlsplit(raw)
        cluster = cluster_mod([p.hostname or "127.0.0.1"], port=p.port or 9042)
        return cluster.connect((p.path or "/").lstrip("/") or None)

    def probe(self) -> Dict[str, Any]:
        session = self._session()
        session.execute("SELECT release_version FROM system.local")
        return {"ok": True, "message": "Cassandra 连接成功"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        rows = self._session().execute(statement, params or [])
        return [dict(r._asdict()) for r in rows][:max(1, as_int(limit, 100))]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self._session().execute(statement, params or [])
        return 1


# --------------------------------------------------------------------------- #
# HBase（Thrift）
# --------------------------------------------------------------------------- #
class HBaseDB(ExtDB):
    protocol = "hbase"
    pip = "happybase"

    def _conn(self):
        hb = lazy_import("happybase", "happybase")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"hbase://{dsn}"
        p = urllib.parse.urlsplit(raw)
        return hb.Connection(p.hostname or "127.0.0.1", p.port or 9090)

    def probe(self) -> Dict[str, Any]:
        tables = list(self._conn().tables())
        return {"ok": True, "message": f"HBase 连接成功，{len(tables)} 张表"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        spec = load_json_ish(statement)
        table_name = spec.get("table") or self.cfg.get("table") or "mineagent"
        row = spec.get("row") or ""
        table = self._conn().table(table_name)
        if row:
            data = table.row(str(row))
            return [{"row": row, "data": {k.decode(): v.decode("utf-8", "replace")
                                          for k, v in data.items()}}]
        out = []
        for key, data in table.scan(limit=max(1, as_int(limit, 100))):
            out.append({"row": key.decode(), "data": {k.decode(): v.decode("utf-8", "replace")
                                                      for k, v in data.items()}})
        return out

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        spec = load_json_ish(statement)
        table = self._conn().table(spec.get("table") or self.cfg.get("table") or "mineagent")
        table.put(str(spec.get("row") or ""), spec.get("data") or {})
        return 1


# --------------------------------------------------------------------------- #
# Couchbase（SQL++）
# --------------------------------------------------------------------------- #
class CouchbaseDB(ExtDB):
    protocol = "couchbase"
    pip = "couchbase"

    def _cluster(self):
        cb = lazy_import("couchbase", "couchbase")
        conn = require(self.cfg, "dsn", label="连接串")
        raw = conn if "://" in conn else f"couchbase://{conn}"
        opts = cb.ClusterOptions(
            cb.PasswordAuthenticator(username=self.cfg.get("username") or "Administrator",
                                     password=self.cfg.get("password") or ""))
        return cb.Cluster.connect(raw, opts)

    def probe(self) -> Dict[str, Any]:
        cluster = self._cluster()
        return {"ok": True, "message": "Couchbase 连接成功"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        cluster = self._cluster()
        rows = cluster.query(statement)
        return [dict(r) for r in rows][:max(1, as_int(limit, 100))]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self._cluster().query(statement)
        return 1


# --------------------------------------------------------------------------- #
# Firestore
# --------------------------------------------------------------------------- #
class FirestoreDB(ExtDB):
    protocol = "firestore"
    pip = "google-cloud-firestore"

    def _client(self):
        fb = lazy_import("google.cloud.firestore", "google-cloud-firestore",
                         attr="Client")
        project = require(self.cfg, "project", label="Project ID")
        return fb(project=project)

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        list(client.collections())
        return {"ok": True, "message": "Firestore 连接成功"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        spec = load_json_ish(statement)
        coll = spec.get("collection") or self.cfg.get("collection") or "default"
        docs = self._client().collection(coll).limit(
            max(1, as_int(limit, 100))).stream()
        return [{"id": d.id, **d.to_dict()} for d in docs]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        spec = load_json_ish(statement)
        coll = spec.get("collection") or self.cfg.get("collection") or "default"
        doc = spec.get("document") or {}
        self._client().collection(coll).add(doc)
        return 1

    def collections(self) -> List[str]:
        try:
            return [c.id for c in self._client().collections()]
        except Exception:  # noqa: BLE001
            return []


# --------------------------------------------------------------------------- #
# Gremlin（JanusGraph / TinkerPop）
# --------------------------------------------------------------------------- #
class GremlinDB(ExtDB):
    protocol = "gremlin"
    pip = "gremlinpython"

    def _client(self):
        gm = lazy_import("gremlin_python.driver.driver",
                         "gremlinpython", attr="DriverRemoteConnection")
        dsn = require(self.cfg, "dsn", label="连接串")
        return gm(dsn)

    def probe(self) -> Dict[str, Any]:
        client = self._client()
        client.submit("g.V().limit(1)").all().result()
        client.close()
        return {"ok": True, "message": "Gremlin 连接成功"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        client = self._client()
        try:
            rows = client.submit(statement).all().result()
            return [{"result": r} for r in rows[:max(1, as_int(limit, 100))]]
        finally:
            client.close()

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self.query(statement)
        return 1


# --------------------------------------------------------------------------- #
# NebulaGraph
# --------------------------------------------------------------------------- #
class NebulaDB(ExtDB):
    protocol = "nebula"
    pip = "nebula3-python"

    def _pool(self):
        nebula = lazy_import("nebula3.gclient.net", "nebula3-python", attr="SessionPool")
        dsn = require(self.cfg, "dsn", label="连接串")
        raw = dsn if "://" in dsn else f"nebula://{dsn}"
        p = urllib.parse.urlsplit(raw)
        return nebula((p.hostname or "127.0.0.1", p.port or 9669),
                      self.cfg.get("username") or "root",
                      self.cfg.get("password") or "nebula")

    def _run(self, statement: str) -> Any:
        pool = self._pool()
        session = pool.get_session(self.cfg.get("username") or "root",
                                   self.cfg.get("password") or "nebula")
        try:
            space = self.cfg.get("space")
            if space:
                session.execute(f"USE `{space}`")
            return session.execute(statement)
        finally:
            pool.release(session)

    def probe(self) -> Dict[str, Any]:
        result = self._run("SHOW SPACES")
        return {"ok": bool(getattr(result, "is_succeeded", lambda: True)()),
                "message": "NebulaGraph 连接成功"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        result = self._run(statement)
        rows = result.rows() if hasattr(result, "rows") else []
        return [{"row": list(r)} for r in rows[:max(1, as_int(limit, 100))]]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self._run(statement)
        return 1


# --------------------------------------------------------------------------- #
# HugeGraph
# --------------------------------------------------------------------------- #
class HugeGraphDB(ExtDB):
    protocol = "hugegraph"
    pip = ""

    def _base(self) -> str:
        return require(self.cfg, "dsn", label="连接串").rstrip("/")

    def _graph(self) -> str:
        return self.cfg.get("graph") or "hugegraph"

    def probe(self) -> Dict[str, Any]:
        data = http_json(join_url(self._base(), "apis/version"), method="GET", timeout=15)
        return {"ok": True, "message": f"HugeGraph 连接成功（{data.get('version', '?')}）"}

    def query(self, statement: str, params: Optional[Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        data = http_json(
            join_url(self._base(),
                     f"graphs/{self._graph()}/graph/traversers/cypher"),
            {"cypher": statement, "limit": max(1, as_int(limit, 100))}, timeout=60)
        return [{"row": r} for r in ((data or {}).get("data") or [])]

    def write(self, statement: str, params: Optional[Any] = None) -> int:
        self.query(statement)
        return 1
