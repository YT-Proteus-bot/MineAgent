"""数据库（数据源 / 存储）枚举清单。

这里指「作为 Agent 的数据源或读写存储」的数据库，和向量库是两回事：
向量库存的是向量，这里存的是业务数据、文档、图关系、缓存和时序指标。

status 与向量库一致：ready = 已实现，planned = 已列入、适配器后续补齐。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .catalog_common import F


def _ds(pid: str, label: str, group: str, protocol: str, pip: str,
        placeholder: str, *, status: str = "planned", help_text: str = "",
        extra: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """绝大多数数据库一个连接串就够了，这里统一生成字段，特殊的用 extra 追加。"""
    if status == "planned" and pid in _READY_IDS:
        status = "ready"
    fields = [F("dsn", "连接串", required=True, secret=True, placeholder=placeholder)]
    if extra:
        fields.extend(extra)
    return {
        "id": pid, "label": label, "group": group, "protocol": protocol,
        "status": status, "pip": pip, "fields": fields, "help": help_text,
    }


# 已有适配器的条目：协议实现见 datastore.py / datastore_ext.py。
# 往这里加一个 id，前端下拉里它就从「即将支持」变成可选。
_READY_IDS = {
    # 复用 postgres / mysql / mongodb / bolt / redis 协议
    "gaussdb", "greenplum", "redshift", "age", "timescaledb", "questdb",
    "mariadb", "tidb", "oceanbase", "polardb",
    "documentdb", "memgraph", "valkey",
    # 独立协议
    "arangodb", "bigquery", "cassandra", "scylla", "clickhouse", "couchbase",
    "couchdb", "databricks", "dgraph", "duckdb", "dynamodb", "etcd",
    "firestore", "janusgraph", "hbase", "hive", "hugegraph", "influxdb",
    "memcached", "nebula", "oracle", "prometheus", "snowflake", "sqlserver",
    "tdengine", "tigergraph", "trino", "presto", "tugraph",
}


DATA: List[Dict[str, Any]] = [
    # ---------------------------------------------------------------- 内置
    {
        "id": "sqlite", "label": "内置 SQLite", "group": "builtin",
        "protocol": "sqlite", "status": "ready", "pip": "", "fields": [
            F("path", "数据库文件", default="./.store.db",
              help_text="相对路径以生成的项目目录为基准"),
            F("readonly", "只读", default="true", options=["true", "false"]),
        ],
        "help": "零依赖。sql_query 节点默认就用它，适合本地小数据和演示。",
    },

    # ------------------------------------------------------------ 关系型
    _ds("postgres", "PostgreSQL", "relational", "postgres", "psycopg[binary]",
        "postgresql://user:pass@127.0.0.1:5432/dbname",
        status="ready", help_text="最常用的业务库；装了 pgvector 后也能兼作向量库。"),
    _ds("mysql", "MySQL", "relational", "mysql", "pymysql",
        "mysql://user:pass@127.0.0.1:3306/dbname",
        status="ready"),
    _ds("mariadb", "MariaDB", "relational", "mysql", "pymysql",
        "mysql://user:pass@127.0.0.1:3306/dbname"),
    _ds("sqlserver", "SQL Server", "relational", "sqlserver", "pyodbc",
        "mssql+pyodbc://user:pass@host:1433/db?driver=ODBC+Driver+18"),
    _ds("oracle", "Oracle", "relational", "oracle", "oracledb",
        "oracle://user:pass@127.0.0.1:1521/?service_name=ORCL"),
    _ds("clickhouse", "ClickHouse", "relational", "clickhouse", "clickhouse-connect",
        "http://user:pass@127.0.0.1:8123/dbname",
        help_text="分析型，适合大宽表统计。"),
    _ds("duckdb", "DuckDB", "relational", "duckdb", "duckdb",
        "./analytics.duckdb", help_text="嵌入式分析库，读 parquet / csv 很方便。"),
    _ds("tidb", "TiDB", "relational", "mysql", "pymysql",
        "mysql://user:pass@127.0.0.1:4000/dbname"),
    _ds("oceanbase", "OceanBase", "relational", "mysql", "pymysql",
        "mysql://user:pass@127.0.0.1:2881/dbname"),
    _ds("gaussdb", "华为云 GaussDB", "relational", "postgres", "psycopg[binary]",
        "postgresql://user:pass@host:5432/dbname"),
    _ds("polardb", "阿里云 PolarDB", "relational", "mysql", "pymysql",
        "mysql://user:pass@host:3306/dbname"),
    _ds("greenplum", "Greenplum", "relational", "postgres", "psycopg[binary]",
        "postgresql://user:pass@host:5432/dbname"),
    _ds("redshift", "Amazon Redshift", "relational", "postgres", "psycopg[binary]",
        "postgresql://user:pass@host:5439/dbname"),
    _ds("snowflake", "Snowflake", "relational", "snowflake", "snowflake-connector-python",
        "snowflake://user:pass@account/db/schema"),
    _ds("bigquery", "Google BigQuery", "relational", "bigquery", "google-cloud-bigquery",
        "bigquery://project/dataset"),
    _ds("databricks", "Databricks", "relational", "databricks", "databricks-sql-connector",
        "databricks://token@host:443/path"),
    _ds("trino", "Trino", "relational", "trino", "trino",
        "trino://user@host:8080/catalog/schema"),
    _ds("presto", "Presto", "relational", "trino", "presto-python-client",
        "presto://user@host:8080/catalog/schema"),
    _ds("hive", "Hive", "relational", "hive", "pyhive",
        "hive://host:10000/dbname"),

    # ------------------------------------------------------------ 文档型
    _ds("mongodb", "MongoDB", "document", "mongodb", "pymongo",
        "mongodb://user:pass@127.0.0.1:27017/dbname",
        status="ready", extra=[F("database", "Database", default="mineagent")]),
    _ds("couchbase", "Couchbase", "document", "couchbase", "couchbase",
        "couchbase://user:pass@127.0.0.1/bucket",
        extra=[F("bucket", "Bucket", default="mineagent")]),
    _ds("firestore", "Google Firestore", "document", "firestore",
        "google-cloud-firestore", "project-id",
        extra=[F("project", "Project ID", required=True)]),
    _ds("documentdb", "AWS DocumentDB", "document", "mongodb", "pymongo",
        "mongodb://user:pass@host:27017/?tls=true&tlsCAFile=global-bundle.pem"),
    _ds("arangodb", "ArangoDB", "document", "arangodb", "python-arango",
        "http://127.0.0.1:8529", extra=[F("collection", "集合名", default="mineagent")]),
    _ds("couchdb", "CouchDB", "document", "couchdb", "couchdb",
        "http://user:pass@127.0.0.1:5984/dbname"),

    # ---------------------------------------------------------------- 图
    _ds("neo4j", "Neo4j", "graph", "neo4j", "neo4j",
        "bolt://user:pass@127.0.0.1:7687",
        status="ready", help_text="graph_query 节点用它跑 Cypher。"),
    _ds("nebula", "NebulaGraph", "graph", "nebula", "nebula3-python",
        "graphd:9669", extra=[F("space", "图空间", default="mineagent")]),
    _ds("tigergraph", "TigerGraph", "graph", "tigergraph", "pyTigerGraph",
        "https://127.0.0.1:14240", extra=[F("graph", "图名", default="mineagent")]),
    _ds("janusgraph", "JanusGraph", "graph", "gremlin", "gremlinpython",
        "ws://127.0.0.1:8182/gremlin"),
    _ds("memgraph", "Memgraph", "graph", "bolt", "neo4j",
        "bolt://user:pass@127.0.0.1:7687"),
    _ds("dgraph", "Dgraph", "graph", "dgraph", "pydgraph",
        "127.0.0.1:9080"),
    _ds("age", "Apache AGE", "graph", "postgres", "psycopg[binary]",
        "postgresql://user:pass@127.0.0.1:5432/dbname",
        help_text="Postgres 扩展，用 Cypher 查询，复用 psycopg 连接。"),
    _ds("hugegraph", "HugeGraph", "graph", "hugegraph", "hugegraph-python-client",
        "http://127.0.0.1:8080"),
    _ds("tugraph", "TuGraph", "graph", "tugraph", "pyTugraph", "127.0.0.1:9090"),

    # -------------------------------------------------------- KV / 缓存
    _ds("redis", "Redis", "kv", "redis", "redis",
        "redis://127.0.0.1:6379/0",
        status="ready", help_text="cache_lookup / kv_store 节点用它。"),
    _ds("valkey", "Valkey", "kv", "redis", "redis",
        "redis://127.0.0.1:6379/0", help_text="协议与 Redis 兼容，复用同一个适配器。"),
    _ds("memcached", "Memcached", "kv", "memcached", "pymemcache",
        "127.0.0.1:11211"),
    _ds("etcd", "etcd", "kv", "etcd", "etcd3", "127.0.0.1:2379"),
    _ds("dynamodb", "Amazon DynamoDB", "kv", "dynamodb", "boto3",
        "dynamodb://region", extra=[F("table", "表名", default="mineagent")]),
    _ds("cassandra", "Cassandra", "kv", "cassandra", "cassandra-driver",
        "cassandra://user:pass@127.0.0.1:9042/keyspace"),
    _ds("scylla", "ScyllaDB", "kv", "cassandra", "cassandra-driver",
        "cassandra://user:pass@127.0.0.1:9042/keyspace"),
    _ds("hbase", "HBase", "kv", "hbase", "happybase",
        "127.0.0.1:9090", extra=[F("table", "表名", default="mineagent")]),

    # ---------------------------------------------------------------- 时序
    _ds("influxdb", "InfluxDB", "timeseries", "influxdb", "influxdb-client",
        "http://127.0.0.1:8086",
        extra=[F("token", "Token", secret=True), F("org", "Org"), F("bucket", "Bucket")]),
    _ds("timescaledb", "TimescaleDB", "timeseries", "postgres", "psycopg[binary]",
        "postgresql://user:pass@127.0.0.1:5432/dbname",
        help_text="Postgres 扩展，直接复用 psycopg。"),
    _ds("tdengine", "TDengine", "timeseries", "tdengine", "taospy",
        "taos://user:pass@127.0.0.1:6030/dbname"),
    _ds("prometheus", "Prometheus", "timeseries", "prometheus", "requests",
        "http://127.0.0.1:9090", help_text="走 HTTP /api/v1/query，无额外依赖。"),
    _ds("questdb", "QuestDB", "timeseries", "postgres", "psycopg[binary]",
        "postgresql://admin:quest@127.0.0.1:8812/qdb"),
]


PROTOCOL_LABELS = {
    "sqlite": "内置 SQLite",
    "postgres": "PostgreSQL 协议",
    "mysql": "MySQL 协议",
    "sqlserver": "SQL Server / ODBC",
    "oracle": "Oracle",
    "clickhouse": "ClickHouse HTTP",
    "duckdb": "DuckDB",
    "snowflake": "Snowflake",
    "bigquery": "BigQuery",
    "databricks": "Databricks SQL",
    "trino": "Trino / Presto",
    "hive": "Hive",
    "mongodb": "MongoDB 协议",
    "couchbase": "Couchbase",
    "firestore": "Firestore",
    "arangodb": "ArangoDB",
    "couchdb": "CouchDB",
    "neo4j": "Neo4j Bolt",
    "bolt": "Bolt",
    "nebula": "NebulaGraph",
    "tigergraph": "TigerGraph",
    "gremlin": "Gremlin",
    "dgraph": "Dgraph",
    "hugegraph": "HugeGraph",
    "tugraph": "TuGraph",
    "redis": "Redis RESP",
    "memcached": "Memcached",
    "etcd": "etcd v3",
    "dynamodb": "DynamoDB",
    "cassandra": "Cassandra CQL",
    "hbase": "HBase Thrift",
    "influxdb": "InfluxDB",
    "tdengine": "TDengine",
    "prometheus": "Prometheus HTTP",
}
