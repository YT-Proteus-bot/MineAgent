"""Provider 层：向量模型 / 向量库 / 数据库的统一接入。

对外只用从这里 import，不要直接引子模块的私有实现。
"""
from __future__ import annotations

from .base import has_module, http_json, lazy_import
from .catalog import (GROUPS, KINDS, default_config, find, items_of,
                      public_catalog, secret_fields)
from .datastore import BaseDB, get_database, probe_data
from .embedding import embed_query, embed_texts
from .embedding import probe as probe_embedding
from .errors import (ProviderCallError, ProviderConfigError, ProviderError,
                     ProviderUnavailable)
from .resolve import build_data_cfg, build_embedding_cfg, build_vector_cfg
from .vectorstore import BaseStore, get_store

__all__ = [
    "GROUPS", "KINDS", "BaseDB", "BaseStore",
    "ProviderCallError", "ProviderConfigError", "ProviderError",
    "ProviderUnavailable",
    "build_data_cfg", "build_embedding_cfg", "build_vector_cfg",
    "default_config", "embed_query", "embed_texts", "find", "get_database",
    "get_store", "has_module", "http_json", "items_of", "lazy_import",
    "probe_data", "probe_embedding", "public_catalog", "secret_fields",
]
