"""向量库枚举清单。

status 有两档：
- ready    当前版本已经实现适配器，可配可用
- planned  已列入清单，适配器在后续阶段补齐（前端会标「即将支持」并禁用）

新增一个库 = 加一个 entry；如果它属于已有的某套协议，连 adapter 都不用写。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .catalog_common import F

VEC: List[Dict[str, Any]] = [
    # ---------------------------------------------------------------- 内置
    {
        "id": "sqlite", "label": "内置 SQLite 向量表", "group": "builtin",
        "protocol": "sqlite", "status": "ready", "pip": "", "fields": [
            F("collection", "集合名", default="default"),
            F("metric", "距离度量", default="cosine", options=["cosine", "dot", "euclidean"]),
        ],
        "help": "零依赖、零配置，项目目录下的 .store.db。适合演示和小数据量；上万条后请换外部库。",
    },

    # ------------------------------------------------------ 开源自部署 / 本地
    {
        "id": "chroma", "label": "Chroma", "group": "self_hosted",
        "protocol": "chroma", "status": "ready", "pip": "chromadb", "fields": [
            F("persist_directory", "本地持久化目录",
              placeholder="留空则用项目内 .chroma，填了优先用本地模式"),
            F("url", "服务地址", placeholder="http://127.0.0.1:8000（连远程时填）"),
            F("api_key", "API Key", secret=True, placeholder="Chroma Cloud 时填"),
            F("tenant", "Tenant", default="default_tenant"),
            F("database", "Database", default="default_database"),
            F("collection", "集合名", default="default"),
        ],
        "help": "上手最快。本地零服务即可跑，也可以直连 Chroma Server / Chroma Cloud。",
    },
    {
        "id": "pgvector", "label": "pgvector（PostgreSQL 扩展）", "group": "self_hosted",
        "protocol": "pgvector", "status": "ready", "pip": "psycopg2-binary psycopg[binary]", "fields": [
            F("dsn", "连接串", required=True,
              placeholder="postgresql://user:pass@127.0.0.1:5432/dbname"),
            F("table", "表名", default="mineagent_vectors"),
            F("collection", "集合名", default="default",
              help_text="落在同一张表里用 collection 列区分"),
            F("metric", "距离度量", default="cosine", options=["cosine", "l2", "ip"]),
            F("index", "索引类型", default="hnsw", options=["hnsw", "ivfflat", "none"]),
        ],
        "help": "已经有 Postgres 时的首选：不用多引一个数据库。需先 CREATE EXTENSION vector;",
    },
    {
        "id": "qdrant", "label": "Qdrant", "group": "self_hosted",
        "protocol": "qdrant", "status": "ready", "pip": "qdrant-client", "fields": [
            F("url", "服务地址", required=True, placeholder="http://127.0.0.1:6333"),
            F("api_key", "API Key", secret=True, placeholder="自建通常留空"),
            F("collection", "集合名", default="mineagent"),
            F("metric", "距离度量", default="cosine", options=["cosine", "dot", "euclid"]),
        ],
        "help": "Rust 写的，单机性能好、过滤能力强，自建和云都用同一套协议。",
    },
    {
        "id": "milvus", "label": "Milvus", "group": "self_hosted",
        "protocol": "milvus", "status": "ready", "pip": "pymilvus", "fields": [
            F("uri", "服务地址", required=True, placeholder="http://127.0.0.1:19530"),
            F("token", "Token", secret=True, placeholder="user:password 或 空"),
            F("collection", "集合名", default="mineagent"),
            F("metric", "距离度量", default="COSINE", options=["COSINE", "L2", "IP"]),
            F("db_name", "Database", default="default"),
        ],
        "help": "十亿级向量的工业选择。需要先起 etcd + minio + milvus 三个容器。",
    },
    {
        "id": "weaviate", "label": "Weaviate", "group": "self_hosted",
        "protocol": "weaviate", "status": "ready", "pip": "weaviate-client", "fields": [
            F("url", "服务地址", required=True, placeholder="http://127.0.0.1:8080"),
            F("api_key", "API Key", secret=True, placeholder="匿名访问留空"),
            F("collection", "集合名", default="Mineagent"),
            F("metric", "距离度量", default="cosine", options=["cosine", "dot", "l2-squared"]),
        ],
        "help": "自带混合检索（向量 + BM25）与生成模块，适合直接做 RAG。",
    },
    {
        "id": "lancedb", "label": "LanceDB", "group": "self_hosted",
        "protocol": "lancedb", "status": "ready", "pip": "lancedb", "fields": [
            F("uri", "存储目录或 URI", required=True, placeholder="./.lancedb"),
            F("collection", "表名", default="mineagent"),
            F("metric", "距离度量", default="cosine", options=["cosine", "l2", "dot"]),
        ],
        "help": "嵌入式列存，不需要起服务，适合本地大规模。",
    },
    {
        "id": "faiss", "label": "FAISS", "group": "self_hosted",
        "protocol": "faiss", "status": "ready", "pip": "faiss-cpu", "fields": [
            F("index_path", "索引文件路径", required=True, placeholder="./.faiss/index.bin"),
            F("collection", "集合名", default="default"),
            F("metric", "距离度量", default="cosine", options=["cosine", "l2", "ip"]),
        ],
        "help": "纯内存索引 + 落盘。没有过滤能力，元数据要自己另存。",
    },
    {
        "id": "elasticsearch", "label": "Elasticsearch", "group": "self_hosted",
        "protocol": "elasticsearch", "status": "ready", "pip": "elasticsearch", "fields": [
            F("url", "服务地址", required=True, placeholder="http://127.0.0.1:9200"),
            F("username", "用户名", default="elastic"),
            F("password", "密码", secret=True),
            F("index", "索引名", default="mineagent"),
            F("metric", "距离度量", default="cosine", options=["cosine", "dot_product", "l2_norm"]),
        ],
        "help": "dense_vector 字段 + kNN 检索，已有 ES 集群时复用最划算。",
    },
    {
        "id": "redis", "label": "Redis（RediSearch）", "group": "self_hosted",
        "protocol": "redis", "status": "ready", "pip": "redis", "fields": [
            F("url", "连接串", required=True, placeholder="redis://127.0.0.1:6379/0"),
            F("collection", "索引名", default="mineagent"),
            F("metric", "距离度量", default="cosine", options=["cosine", "l2", "ip"]),
        ],
        "help": "需要 Redis Stack 或已加载 RediSearch 模块。",
    },
    {
        "id": "opensearch", "label": "OpenSearch", "group": "self_hosted",
        "protocol": "opensearch", "status": "ready", "pip": "opensearch-py", "fields": [
            F("url", "服务地址", required=True, placeholder="http://127.0.0.1:9200"),
            F("username", "用户名"), F("password", "密码", secret=True),
            F("index", "索引名", default="mineagent"),
        ],
    },
    {
        "id": "typesense", "label": "Typesense", "group": "self_hosted",
        "protocol": "typesense", "status": "ready", "pip": "typesense", "fields": [
            F("url", "服务地址", required=True, placeholder="http://127.0.0.1:8108"),
            F("api_key", "API Key", secret=True, required=True),
            F("collection", "集合名", default="mineagent"),
        ],
    },
    {
        "id": "vespa", "label": "Vespa", "group": "self_hosted",
        "protocol": "vespa", "status": "ready", "pip": "pyvespa", "fields": [
            F("url", "服务地址", required=True, placeholder="http://127.0.0.1:8080"),
            F("api_key", "API Key", secret=True), F("collection", "Schema 名", default="mineagent"),
        ],
    },
    {
        "id": "pgvecto_rs", "label": "pgvecto.rs", "group": "self_hosted",
        "protocol": "pgvector", "status": "ready", "pip": "psycopg[binary]", "fields": [
            F("dsn", "连接串", required=True), F("table", "表名", default="mineagent_vectors"),
            F("collection", "集合名", default="default"),
        ],
    },
    {
        "id": "mariadb_vector", "label": "MariaDB Vector", "group": "self_hosted",
        "protocol": "mysql_vector", "status": "ready", "pip": "mariadb", "fields": [
            F("dsn", "连接串", required=True, placeholder="mysql://user:pass@127.0.0.1:3306/db"),
            F("table", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "sqlite_vec", "label": "sqlite-vec", "group": "self_hosted",
        "protocol": "sqlite_vec", "status": "ready", "pip": "sqlite-vec", "fields": [
            F("path", "数据库文件", default="./.vec.db"),
            F("collection", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "duckdb_vss", "label": "DuckDB VSS", "group": "self_hosted",
        "protocol": "duckdb", "status": "ready", "pip": "duckdb", "fields": [
            F("path", "数据库文件", default="./.duck.db"),
            F("collection", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "surrealdb", "label": "SurrealDB", "group": "self_hosted",
        "protocol": "surrealdb", "status": "ready", "pip": "surrealdb", "fields": [
            F("url", "服务地址", required=True, placeholder="ws://127.0.0.1:8000/rpc"),
            F("username", "用户名", default="root"), F("password", "密码", secret=True),
            F("namespace", "命名空间", default="mineagent"), F("collection", "表名", default="vectors"),
        ],
    },
    {
        "id": "singlestore", "label": "SingleStore", "group": "self_hosted",
        "protocol": "mysql_vector", "status": "ready", "pip": "pymysql", "fields": [
            F("dsn", "连接串", required=True), F("table", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "clickhouse", "label": "ClickHouse", "group": "self_hosted",
        "protocol": "clickhouse", "status": "ready", "pip": "clickhouse-connect", "fields": [
            F("dsn", "连接串", required=True, placeholder="http://user:pass@127.0.0.1:8123/db"),
            F("table", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "doris", "label": "Apache Doris", "group": "self_hosted",
        "protocol": "mysql_vector", "status": "ready", "pip": "pymysql", "fields": [
            F("dsn", "连接串", required=True), F("table", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "starrocks", "label": "StarRocks", "group": "self_hosted",
        "protocol": "mysql_vector", "status": "ready", "pip": "pymysql", "fields": [
            F("dsn", "连接串", required=True), F("table", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "neo4j_vector", "label": "Neo4j（向量索引）", "group": "self_hosted",
        "protocol": "neo4j", "status": "ready", "pip": "neo4j", "fields": [
            F("uri", "连接地址", required=True, placeholder="bolt://127.0.0.1:7687"),
            F("username", "用户名", default="neo4j"), F("password", "密码", secret=True),
            F("collection", "索引名", default="mineagent"),
        ],
    },
    {
        "id": "couchbase", "label": "Couchbase", "group": "self_hosted",
        "protocol": "couchbase", "status": "ready", "pip": "couchbase", "fields": [
            F("url", "连接串", required=True),
            F("username", "用户名"), F("password", "密码", secret=True),
            F("collection", "集合名", default="mineagent"),
        ],
    },
    {
        "id": "arangodb", "label": "ArangoDB", "group": "self_hosted",
        "protocol": "arangodb", "status": "ready", "pip": "python-arango", "fields": [
            F("url", "服务地址", required=True, placeholder="http://127.0.0.1:8529"),
            F("username", "用户名", default="root"), F("password", "密码", secret=True),
            F("collection", "集合名", default="mineagent"),
        ],
    },

    # ------------------------------------------------------------ 云托管
    {
        "id": "pinecone", "label": "Pinecone", "group": "cloud",
        "protocol": "pinecone", "status": "ready", "pip": "pinecone", "fields": [
            F("api_key", "API Key", secret=True, required=True),
            F("index_host", "Index Host", required=True,
              placeholder="https://xxx-xxxx.svc.aped-4627-b74a.pinecone.io"),
            F("collection", "Namespace", default="default"),
            F("metric", "距离度量", default="cosine", options=["cosine", "dotproduct", "euclidean"]),
        ],
        "help": "Serverless 索引要填控制台给的 Index Host，不是 api.pinecone.io。",
    },
    {
        "id": "zilliz", "label": "Zilliz Cloud（Milvus）", "group": "cloud",
        "protocol": "zilliz", "status": "ready", "pip": "pymilvus", "fields": [
            F("uri", "集群地址", required=True,
              placeholder="https://in03-xxxx.serverless.aws-eu-central-1.cloud.zilliz.com"),
            F("token", "API Key", secret=True, required=True),
            F("collection", "集合名", default="mineagent"),
            F("metric", "距离度量", default="COSINE", options=["COSINE", "L2", "IP"]),
        ],
        "help": "Milvus 的全托管版，协议一致，换 uri + token 即可。",
    },
    {
        "id": "qdrant_cloud", "label": "Qdrant Cloud", "group": "cloud",
        "protocol": "qdrant", "status": "ready", "pip": "qdrant-client", "fields": [
            F("url", "集群地址", required=True, placeholder="https://xxx.cloud.qdrant.io:6333"),
            F("api_key", "API Key", secret=True, required=True),
            F("collection", "集合名", default="mineagent"),
            F("metric", "距离度量", default="cosine", options=["cosine", "dot", "euclid"]),
        ],
    },
    {
        "id": "weaviate_cloud", "label": "Weaviate Cloud", "group": "cloud",
        "protocol": "weaviate", "status": "ready", "pip": "weaviate-client", "fields": [
            F("url", "集群地址", required=True, placeholder="https://xxx.weaviate.network"),
            F("api_key", "API Key", secret=True, required=True),
            F("collection", "集合名", default="Mineagent"),
            F("metric", "距离度量", default="cosine", options=["cosine", "dot", "l2-squared"]),
        ],
    },
    {
        "id": "vectara", "label": "Vectara", "group": "cloud",
        "protocol": "vectara", "status": "ready", "pip": "", "fields": [
            F("api_key", "API Key", secret=True, required=True),
            F("customer_id", "Customer ID", required=True),
            F("corpus_id", "Corpus ID", required=True),
        ],
    },
    {
        "id": "turbopuffer", "label": "Turbopuffer", "group": "cloud",
        "protocol": "turbopuffer", "status": "ready", "pip": "turbopuffer", "fields": [
            F("api_key", "API Key", secret=True, required=True),
            F("namespace", "Namespace", default="mineagent"),
        ],
    },
    {
        "id": "upstash", "label": "Upstash Vector", "group": "cloud",
        "protocol": "upstash", "status": "ready", "pip": "upstash-vector", "fields": [
            F("url", "REST 地址", required=True), F("token", "Token", secret=True, required=True),
            F("namespace", "Namespace", default="mineagent"),
        ],
    },
    {
        "id": "azure_search", "label": "Azure AI Search", "group": "cloud",
        "protocol": "azure_search", "status": "ready", "pip": "azure-search-documents", "fields": [
            F("endpoint", "Endpoint", required=True, placeholder="https://xxx.search.windows.net"),
            F("api_key", "API Key", secret=True, required=True),
            F("index", "索引名", default="mineagent"),
        ],
    },
    {
        "id": "opensearch_serverless", "label": "AWS OpenSearch Serverless", "group": "cloud",
        "protocol": "opensearch", "status": "ready", "pip": "opensearch-py", "fields": [
            F("url", "Collection Endpoint", required=True),
            F("username", "用户名"), F("password", "密码", secret=True),
            F("index", "索引名", default="mineagent"),
        ],
    },
    {
        "id": "vertex_vector", "label": "Vertex AI Vector Search", "group": "cloud",
        "protocol": "vertex_vector", "status": "ready", "pip": "google-cloud-aiplatform", "fields": [
            F("project", "Project ID", required=True), F("location", "Region", default="us-central1"),
            F("index_endpoint", "Index Endpoint", required=True),
            F("deployed_index", "Deployed Index ID", required=True),
        ],
    },
    {
        "id": "dashvector", "label": "阿里云 DashVector", "group": "cloud",
        "protocol": "dashvector", "status": "ready", "pip": "dashvector", "fields": [
            F("api_key", "API Key", secret=True, required=True),
            F("endpoint", "Endpoint", required=True,
              placeholder="https://xxx.dashvector.cn-hangzhou.aliyuncs.com"),
            F("collection", "集合名", default="mineagent"),
        ],
    },
    {
        "id": "tencent_vectordb", "label": "腾讯云 向量数据库", "group": "cloud",
        "protocol": "tencent_vectordb", "status": "ready", "pip": "tcvectordb", "fields": [
            F("url", "访问地址", required=True), F("username", "用户名", default="root"),
            F("api_key", "Key", secret=True, required=True),
            F("collection", "集合名", default="mineagent"),
        ],
    },
    {
        "id": "baidu_vectordb", "label": "百度 向量数据库", "group": "cloud",
        "protocol": "baidu_vectordb", "status": "ready", "pip": "pymochow", "fields": [
            F("url", "访问地址", required=True), F("account", "账号", required=True),
            F("api_key", "API Key", secret=True, required=True),
            F("collection", "集合名", default="mineagent"),
        ],
    },
    {
        "id": "vikingdb", "label": "火山引擎 VikingDB", "group": "cloud",
        "protocol": "vikingdb", "status": "ready", "pip": "volcengine", "fields": [
            F("ak", "Access Key", secret=True, required=True),
            F("sk", "Secret Key", secret=True, required=True),
            F("region", "Region", default="cn-beijing"),
            F("collection", "集合名", default="mineagent"),
        ],
    },
    {
        "id": "gaussdb_vector", "label": "华为云 GaussDB（向量）", "group": "cloud",
        "protocol": "pgvector", "status": "ready", "pip": "psycopg[binary]", "fields": [
            F("dsn", "连接串", required=True), F("table", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "mongodb_atlas_vector", "label": "MongoDB Atlas Vector Search", "group": "cloud",
        "protocol": "mongodb_vector", "status": "ready", "pip": "pymongo", "fields": [
            F("uri", "连接串", required=True), F("database", "Database", default="mineagent"),
            F("collection", "集合名", default="vectors"), F("index", "索引名", default="vector_index"),
        ],
    },
    {
        "id": "cosmos_mongo_vcore", "label": "Azure Cosmos DB (Mongo vCore)", "group": "cloud",
        "protocol": "mongodb_vector", "status": "ready", "pip": "pymongo", "fields": [
            F("uri", "连接串", required=True), F("database", "Database", default="mineagent"),
            F("collection", "集合名", default="vectors"), F("index", "索引名", default="vector_index"),
        ],
    },
    {
        "id": "oracle_ai_vector", "label": "Oracle AI Vector Search", "group": "cloud",
        "protocol": "oracle_vector", "status": "ready", "pip": "oracledb", "fields": [
            F("dsn", "连接串", required=True), F("table", "表名", default="MINEAGENT_VECTORS"),
        ],
    },
    {
        "id": "sap_hana", "label": "SAP HANA Vector", "group": "cloud",
        "protocol": "hana_vector", "status": "ready", "pip": "hdbcli", "fields": [
            F("host", "Host", required=True), F("port", "Port", default=443),
            F("username", "用户名"), F("password", "密码", secret=True),
            F("table", "表名", default="MINEAGENT_VECTORS"),
        ],
    },
    {
        "id": "tidb_vector", "label": "TiDB Vector", "group": "cloud",
        "protocol": "mysql_vector", "status": "ready", "pip": "pymysql", "fields": [
            F("dsn", "连接串", required=True), F("table", "表名", default="mineagent_vectors"),
        ],
    },
    {
        "id": "oceanbase", "label": "OceanBase（向量）", "group": "cloud",
        "protocol": "mysql_vector", "status": "ready", "pip": "pymysql", "fields": [
            F("dsn", "连接串", required=True), F("table", "表名", default="mineagent_vectors"),
        ],
    },
]


PROTOCOL_LABELS = {
    "sqlite": "内置 SQLite",
    "chroma": "Chroma",
    "pgvector": "PostgreSQL + pgvector",
    "qdrant": "Qdrant REST",
    "milvus": "Milvus / Zilliz",
    "weaviate": "Weaviate",
    "lancedb": "LanceDB",
    "faiss": "FAISS",
    "elasticsearch": "Elasticsearch kNN",
    "redis": "Redis RediSearch",
    "opensearch": "OpenSearch kNN",
    "typesense": "Typesense",
    "vespa": "Vespa",
    "mysql_vector": "MySQL 家族向量",
    "sqlite_vec": "sqlite-vec",
    "duckdb": "DuckDB VSS",
    "surrealdb": "SurrealDB",
    "clickhouse": "ClickHouse",
    "neo4j": "Neo4j 向量索引",
    "couchbase": "Couchbase",
    "arangodb": "ArangoDB",
    "pinecone": "Pinecone",
    "zilliz": "Zilliz Cloud",
    "vectara": "Vectara",
    "turbopuffer": "Turbopuffer",
    "upstash": "Upstash Vector",
    "azure_search": "Azure AI Search",
    "vertex_vector": "Vertex AI Vector Search",
    "dashvector": "DashVector",
    "tencent_vectordb": "腾讯云向量数据库",
    "baidu_vectordb": "百度向量数据库",
    "vikingdb": "VikingDB",
    "mongodb_vector": "MongoDB Atlas Vector",
    "oracle_vector": "Oracle AI Vector",
    "hana_vector": "SAP HANA Vector",
}
