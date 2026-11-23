"""知识库：全局的文档集合 + 自带向量模型/向量库配置。

一个知识库 = 一批文件 + 一个向量库集合（collection）。
建库时把文件切分、向量化、写进集合；画布上的检索节点通过 collection 用它。

和 provider 的关系：知识库自带 embedding / vector 配置，不依赖某张画布的 provider
（知识库是全局的，画布是局部的，两者不该绑死）。
"""
from __future__ import annotations

import json
import re
import shutil
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import DATA_DIR
from .db import get_conn, now_iso
from .providers import (build_embedding_cfg, build_vector_cfg, embed_texts,
                        find, get_store)
from .providers.errors import ProviderError
from .security import decrypt, encrypt

KNOWLEDGE_DIR = DATA_DIR / "knowledge"
MAX_FILE_BYTES = 30 * 1024 * 1024
TEXT_EXT = {".txt", ".md", ".markdown", ".json", ".csv", ".log", ".yaml", ".yml", ".html"}
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120


class KnowledgeError(ValueError):
    pass


def kb_dir(kb_id: str) -> Path:
    return KNOWLEDGE_DIR / kb_id


def files_dir(kb_id: str) -> Path:
    return kb_dir(kb_id) / "files"


def _row_to_dict(row) -> Dict[str, Any]:
    item = dict(row)
    for key in ("embedding_config", "vector_config", "chunk_config"):
        try:
            item[key] = json.loads(item.get(key) or "{}")
        except json.JSONDecodeError:
            item[key] = {}
    # 密钥永不返回，只报有没有
    item["has_embedding_key"] = bool(item.get("embedding_secret_cipher"))
    item["has_vector_key"] = bool(item.get("vector_secret_cipher"))
    item["has_endpoint_key"] = bool(item.get("endpoint_key_cipher"))
    item.pop("embedding_secret_cipher", None)
    item.pop("vector_secret_cipher", None)
    item.pop("endpoint_key_cipher", None)
    return item


def list_kbs() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_bases ORDER BY updated_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_kb(kb_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)).fetchone()
    return _row_to_dict(row) if row else None


def _collection_name(kb_id: str) -> str:
    return f"kb_{kb_id}"


def create_kb(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise KnowledgeError("知识库名称不能为空")

    kind = str(payload.get("kind") or "builtin").strip().lower()
    template = str(payload.get("template") or "general").strip().lower()
    kb_id = uuid.uuid4().hex[:16]
    ts = now_iso()

    # ---- 外部知识库：不建索引，只存接入信息 ----
    if kind == "external":
        endpoint = str(payload.get("endpoint") or "").strip()
        if not endpoint:
            raise KnowledgeError("填一下外部知识库的检索地址")
        if not endpoint.startswith(("http://", "https://")):
            raise KnowledgeError("检索地址要以 http:// 或 https:// 开头")
        key = str(payload.get("api_key") or "")
        collection = str(payload.get("collection") or "").strip()
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO knowledge_bases("
                "id,name,description,collection,kind,template,endpoint,"
                "endpoint_key_cipher,status,chunk_config,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (kb_id, name, str(payload.get("description") or ""), collection,
                 "external", template, endpoint,
                 encrypt(key) if key else "",
                 "ready", "{}", ts, ts))
        return get_kb(kb_id) or {}

    embedding = payload.get("embedding") or {}
    vector = payload.get("vector") or {}
    emb_provider = str(embedding.get("provider") or "").strip()
    vec_provider = str(vector.get("provider") or "").strip()
    if not emb_provider:
        raise KnowledgeError("要选一个向量模型")
    if not vec_provider:
        raise KnowledgeError("要选一个向量库")
    if find("embedding", emb_provider) is None:
        raise KnowledgeError(f"没有这个向量模型：{emb_provider}")
    if find("vector", vec_provider) is None:
        raise KnowledgeError(f"没有这个向量库：{vec_provider}")

    collection = str(payload.get("collection") or "").strip() or _collection_name(kb_id)
    vector_config = dict(vector.get("config") or {})
    vector_config.setdefault("collection", collection)
    chunk = _chunk_config(payload.get("chunk"))

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO knowledge_bases("
            "id,name,description,collection,kind,template,"
            "embedding_provider,embedding_config,embedding_secret_cipher,"
            "vector_provider,vector_config,vector_secret_cipher,"
            "status,chunk_config,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kb_id, name, str(payload.get("description") or ""), collection,
             "builtin", template,
             emb_provider,
             json.dumps(embedding.get("config") or {}, ensure_ascii=False),
             encrypt(json.dumps(embedding.get("secret") or {})) if embedding.get("secret") else "",
             vec_provider,
             json.dumps(vector_config, ensure_ascii=False),
             encrypt(json.dumps(vector.get("secret") or {})) if vector.get("secret") else "",
             "draft", json.dumps(chunk, ensure_ascii=False), ts, ts))
    files_dir(kb_id).mkdir(parents=True, exist_ok=True)
    return get_kb(kb_id) or {}


def update_kb(kb_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    current = get_kb(kb_id)
    if not current:
        raise KnowledgeError("知识库不存在")
    sets: List[str] = []
    values: List[Any] = []
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise KnowledgeError("名称不能为空")
        sets.append("name = ?")
        values.append(name)
    if "description" in payload:
        sets.append("description = ?")
        values.append(str(payload.get("description") or ""))
    for key, cipher_key in (("embedding", "embedding_secret_cipher"),
                            ("vector", "vector_secret_cipher")):
        block = payload.get(key)
        if not isinstance(block, dict):
            continue
        if block.get("provider"):
            sets.append(f"{key}_provider = ?")
            values.append(str(block["provider"]))
        if isinstance(block.get("config"), dict):
            sets.append(f"{key}_config = ?")
            values.append(json.dumps(block["config"], ensure_ascii=False))
        if isinstance(block.get("secret"), dict) and block["secret"]:
            sets.append(f"{cipher_key} = ?")
            values.append(encrypt(json.dumps(block["secret"])))
    if not sets:
        return current
    sets.append("updated_at = ?")
    values.append(now_iso())
    values.append(kb_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id = ?", values)
    return get_kb(kb_id) or {}


def delete_kb(kb_id: str) -> bool:
    current = get_kb(kb_id)
    if not current:
        return False
    # 外部知识库没有本地集合，不用 drop
    if current.get("kind") != "external" and current.get("collection"):
        try:
            _open_store(kb_id).drop(current.get("collection"))
        except Exception:  # noqa: BLE001
            pass
    with get_conn() as conn:
        conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
    shutil.rmtree(kb_dir(kb_id), ignore_errors=True)
    return True


# --------------------------------------------------------------------------- #
# 文件
# --------------------------------------------------------------------------- #
_SAFE_NAME = re.compile(r"[^\w.\-\u4e00-\u9fff]")


def safe_filename(name: str) -> str:
    base = Path(name or "file").name
    return (_SAFE_NAME.sub("_", base).strip("._") or "file")[:120]


def list_files(kb_id: str) -> List[Dict[str, Any]]:
    base = files_dir(kb_id)
    if not base.exists():
        return []
    out = []
    for path in sorted(base.iterdir()):
        if path.is_file():
            out.append({"name": path.name, "size": path.stat().st_size,
                        "ext": path.suffix.lower()})
    return out


def save_file(kb_id: str, filename: str, data: bytes) -> Dict[str, Any]:
    if not get_kb(kb_id):
        raise KnowledgeError("知识库不存在")
    if not data:
        raise KnowledgeError("文件是空的")
    if len(data) > MAX_FILE_BYTES:
        raise KnowledgeError(f"单个文件超过 {MAX_FILE_BYTES // 1024 // 1024}MB")
    base = files_dir(kb_id)
    base.mkdir(parents=True, exist_ok=True)
    name = safe_filename(filename)
    target = base / name
    stem, suffix = target.stem, target.suffix
    index = 2
    while target.exists():
        target = base / f"{stem}_{index}{suffix}"
        index += 1
    target.write_bytes(data)
    _touch(kb_id)
    return {"name": target.name, "size": len(data), "ext": target.suffix.lower()}


def delete_file(kb_id: str, name: str) -> bool:
    safe = safe_filename(name)
    target = files_dir(kb_id) / safe
    if not target.is_file():
        return False
    target.unlink()
    _touch(kb_id)
    return True


def _touch(kb_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE knowledge_bases SET updated_at = ? WHERE id = ?",
                     (now_iso(), kb_id))


# --------------------------------------------------------------------------- #
# 切分与读取
# --------------------------------------------------------------------------- #
def _chunk_config(raw: Any) -> Dict[str, Any]:
    """分段设置：分隔符 / 最大长度 / 重叠长度。"""
    cfg = dict(raw or {}) if isinstance(raw, dict) else {}
    size = cfg.get("size")
    overlap = cfg.get("overlap")
    return {
        "separator": str(cfg.get("separator") or "\n"),
        "size": max(120, min(int(size), 4000)) if isinstance(size, (int, float)) else CHUNK_SIZE,
        "overlap": max(0, min(int(overlap), 800)) if isinstance(overlap, (int, float)) else CHUNK_OVERLAP,
    }


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise KnowledgeError("读 PDF 需要 pypdf：pip install pypdf") from exc
        return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        try:
            import docx
        except ImportError as exc:
            raise KnowledgeError(
                "读 docx 需要 python-docx：pip install python-docx") from exc
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    if suffix in TEXT_EXT:
        return path.read_text(encoding="utf-8", errors="replace")
    raise KnowledgeError(f"不支持的文件类型：{suffix or path.name}")


def _chunks(text: str, config: Optional[Dict[str, Any]] = None) -> List[str]:
    """按分隔符切段，再把小段拼到接近 size，相邻块留 overlap。

    和 Dify 的「通用分段」思路一致：先尊重分隔符的语义边界，再控制长度。
    """
    cfg = _chunk_config(config)
    size = cfg["size"]
    overlap = cfg["overlap"]
    separator = cfg["separator"] or "\n"

    clean = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not clean:
        return []

    pieces = [p.strip() for p in clean.split(separator)] if separator else [clean]
    pieces = [p for p in pieces if p]
    if not pieces:
        return []

    out: List[str] = []
    buffer = ""
    for piece in pieces:
        # 单段就超长：硬切
        while len(piece) > size:
            head, piece = piece[:size], piece[size:]
            if buffer:
                out.append(buffer)
                buffer = ""
            out.append(head)
        if not buffer:
            buffer = piece
        elif len(buffer) + 1 + len(piece) <= size:
            buffer += separator + piece
        else:
            out.append(buffer)
            tail = buffer[-overlap:] if overlap and len(buffer) > overlap else ""
            buffer = (tail + separator + piece).strip() if tail else piece

    if buffer:
        out.append(buffer)

    # 全是空白片段的情况兜底
    final = [c for c in (s.strip() for s in out) if c]
    return final


# --------------------------------------------------------------------------- #
# 建索引
# --------------------------------------------------------------------------- #
def _secret_of(row, key: str) -> Dict[str, Any]:
    raw = row.get(key) or ""
    if not raw:
        return {}
    try:
        return json.loads(decrypt(raw) or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _embedding_record(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": "embedding", "provider": row.get("embedding_provider"),
            "config": row.get("embedding_config") or {},
            "secret": _secret_of(row, "embedding_secret_cipher")}


def _vector_record(row: Dict[str, Any]) -> Dict[str, Any]:
    cfg = dict(row.get("vector_config") or {})
    cfg.setdefault("collection", row.get("collection"))
    return {"kind": "vector", "provider": row.get("vector_provider"),
            "config": cfg, "secret": _secret_of(row, "vector_secret_cipher")}


def _open_store(kb_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)).fetchone()
    if not row:
        raise KnowledgeError("知识库不存在")
    item = dict(row)
    for key in ("embedding_config", "vector_config"):
        try:
            item[key] = json.loads(item.get(key) or "{}")
        except json.JSONDecodeError:
            item[key] = {}
    cfg = build_vector_cfg(_vector_record(item), str(kb_dir(kb_id)))
    return get_store(cfg)


def _set_status(kb_id: str, status: str, **extra: Any) -> None:
    sets = ["status = ?", "updated_at = ?"]
    values: List[Any] = [status, now_iso()]
    for key, value in extra.items():
        sets.append(f"{key} = ?")
        values.append(value)
    values.append(kb_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE knowledge_bases SET {', '.join(sets)} WHERE id = ?",
                     values)


def build(kb_id: str) -> Dict[str, Any]:
    """把已上传的文件切分、向量化、写进向量库。"""
    current = get_kb(kb_id)
    if not current:
        raise KnowledgeError("知识库不存在")
    if current.get("kind") == "external":
        raise KnowledgeError("外部知识库不用建索引，它直接查对方的数据")
    files = list_files(kb_id)
    if not files:
        raise KnowledgeError("先上传一些文件再建库")

    _set_status(kb_id, "building", error="")
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)).fetchone()
        record = dict(row)
        for key in ("embedding_config", "vector_config", "chunk_config"):
            try:
                record[key] = json.loads(record.get(key) or "{}")
            except json.JSONDecodeError:
                record[key] = {}

        emb_cfg = build_embedding_cfg(_embedding_record(record))
        store = _open_store(kb_id)
        collection = record.get("collection") or _collection_name(kb_id)
        chunk_cfg = record.get("chunk_config") or {}

        items: List[Dict[str, Any]] = []
        for meta in files:
            path = files_dir(kb_id) / meta["name"]
            try:
                text = _read_text(path)
            except KnowledgeError as exc:
                _set_status(kb_id, "failed", error=f"{meta['name']}：{exc}")
                raise
            for idx, piece in enumerate(_chunks(text, chunk_cfg)):
                items.append({
                    "id": f"{meta['name']}::{idx}",
                    "text": piece,
                    "metadata": {"file": meta["name"], "chunk": idx,
                                 "kb": kb_id},
                })

        if not items:
            _set_status(kb_id, "failed", error="文件里没有可用的文本")
            raise KnowledgeError("文件里没有可用的文本")

        vectors = embed_texts(emb_cfg, [it["text"] for it in items])
        if len(vectors) != len(items):
            raise KnowledgeError(
                f"向量条数不匹配：{len(vectors)} vs {len(items)}")
        for item, vec in zip(items, vectors):
            item["vector"] = vec

        dim = len(vectors[0]) if vectors else 0
        store.ensure_collection(collection, dim, record.get("metric") or "cosine",
                                str(emb_cfg.get("model") or ""))
        written = store.upsert(collection, items)

        _set_status(kb_id, "ready", file_count=len(files), chunk_count=written,
                    error="")
        return {"ok": True, "files": len(files), "chunks": written, "dim": dim}
    except ProviderError as exc:
        message = str(exc)[:300]
        _set_status(kb_id, "failed", error=message)
        raise KnowledgeError(f"调用向量服务失败：{message}") from exc
    except Exception as exc:  # noqa: BLE001
        if not isinstance(exc, KnowledgeError):
            _set_status(kb_id, "failed", error=str(exc)[:300])
            raise KnowledgeError(f"建库失败：{exc}") from exc
        raise


_HIT_KEYS = ("records", "results", "data", "documents", "hits", "items")


def _normalize_hits(payload: Any) -> List[Dict[str, Any]]:
    """把外部检索接口的返回统一成 [{text, score, metadata}]。

    不同系统字段名差很多（Dify 用 records[].segment.content，有些用 results[].content），
    这里按已知的几种形状宽松解析，认不出来就返回空。
    """
    rows: List[Any] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in _HIT_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
    out: List[Dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            if isinstance(item, str) and item.strip():
                out.append({"text": item, "score": 0, "metadata": {}})
            continue
        segment = item.get("segment") if isinstance(item.get("segment"), dict) else {}
        text = (item.get("text") or item.get("content") or item.get("page_content")
                or item.get("chunk") or segment.get("content") or "")
        score = item.get("score") or item.get("similarity") or segment.get("score") or 0
        metadata = item.get("metadata") or segment.get("document") or {}
        if str(text).strip():
            out.append({"text": str(text), "score": score, "metadata": metadata})
    return out


def _search_external(kb: Dict[str, Any], query: str, top_k: int) -> List[Dict[str, Any]]:
    endpoint = str(kb.get("endpoint") or "").strip()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT endpoint_key_cipher FROM knowledge_bases WHERE id = ?",
            (kb["id"],)).fetchone()
    key = decrypt(row["endpoint_key_cipher"]) if row and row["endpoint_key_cipher"] else ""

    body = {
        "query": query,
        "top_k": top_k,
        "retrieval_model": {"top_k": top_k, "score_threshold_enabled": False},
    }
    headers = {"Content-Type": "application/json", "User-Agent": "MineAgent-KB"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise KnowledgeError(
            f"外部知识库返回 {exc.code}：{detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise KnowledgeError(f"连不上外部知识库：{exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KnowledgeError("外部知识库返回的不是 JSON") from exc
    return _normalize_hits(payload)


def search(kb_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """测试检索：给一句话，返回最相近的片段。"""
    current = get_kb(kb_id)
    if not current:
        raise KnowledgeError("知识库不存在")
    if not (query or "").strip():
        raise KnowledgeError("查询内容为空")

    if current.get("kind") == "external":
        return _search_external(current, query, top_k)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM knowledge_bases WHERE id = ?", (kb_id,)).fetchone()
    record = dict(row)
    for key in ("embedding_config", "vector_config"):
        try:
            record[key] = json.loads(record.get(key) or "{}")
        except json.JSONDecodeError:
            record[key] = {}

    emb_cfg = build_embedding_cfg(_embedding_record(record))
    vectors = embed_texts(emb_cfg, [query], input_type="query")
    if not vectors:
        return []
    store = _open_store(kb_id)
    return store.search(record.get("collection") or _collection_name(kb_id),
                        vectors[0], top_k=top_k)
