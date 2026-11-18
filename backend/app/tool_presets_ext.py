"""扩展工具预设：从 LangChain / CrewAI / Dify / Coze / OpenAI 的工具集里挑出来的常用能力。

加工具的原则：
1. 能在项目内独立跑（只用标准库或明确可装的轻量包），不依赖平台运行时；
2. 需要外部 key 的，在 description 里写清楚要配什么；
3. preview（run(ctx)）和 native（原生函数体）两套都要给，保证两条路径行为一致。

每项字段：
    label / description / params / args / preview / native
"""
from __future__ import annotations

from typing import Any, Dict

EXT_PRESETS: Dict[str, Dict[str, Any]] = {}


def _add(name: str, label: str, description: str, args: str,
         preview: str, native: str, params: Any = None) -> None:
    EXT_PRESETS[name] = {
        "label": label,
        "description": description,
        "params": params or [],
        "args": args,
        "preview": preview.strip(),
        "native": native.strip("\n"),
    }


# --------------------------------------------------------------------------- #
# 知识检索类（对应 LangChain: WikipediaQueryRun / ArxivQueryRun / PubMed）
# --------------------------------------------------------------------------- #
_add(
    "wikipedia", "维基百科", "查维基百科词条摘要（免费、无需 key，适合事实型问题）。",
    "query: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """维基百科：按标题查摘要，返回前 2000 字。"""
    import json
    import urllib.parse
    import urllib.request

    q = (ctx.params.get("query") or ctx.text).strip()
    if not q:
        return "维基百科查询需要关键词"
    lang = ctx.params.get("lang") or "zh"
    base = f"https://{lang}.wikipedia.org/w/api.php"
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "extracts",
        "exintro": 1, "explaintext": 1, "redirects": 1, "titles": q,
    })
    req = urllib.request.Request(f"{base}?{params}",
                                 headers={"User-Agent": "MineAgent/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        text = page.get("extract") or ""
        if text:
            return f"# {page.get('title', q)}\\n\\n{text[:2000]}"
    return f"没有找到「{q}」的词条（语言：{lang}）"
''',
    '''
    import json
    import urllib.parse
    import urllib.request

    lang = "zh"
    base = f"https://{lang}.wikipedia.org/w/api.php"
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "prop": "extracts",
        "exintro": 1, "explaintext": 1, "redirects": 1, "titles": query,
    })
    req = urllib.request.Request(f"{base}?{params}",
                                 headers={"User-Agent": "MineAgent/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        text = page.get("extract") or ""
        if text:
            return f"# {page.get('title', query)}\\n\\n{text[:2000]}"
    return f"没有找到「{query}」的词条（语言：zh）"
''',
    [{"key": "query", "label": "查询词", "default": ""}],
)

_add(
    "arxiv", "arXiv 论文", "按关键词搜 arXiv 论文，返回标题、作者、摘要和链接（免费）。",
    "query: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """arXiv：返回前 5 篇论文的标题、作者与摘要。"""
    import re
    import urllib.parse
    import urllib.request
    import xml.etree.ElementTree as ET

    q = (ctx.params.get("query") or ctx.text).strip()
    if not q:
        return "arXiv 查询需要关键词"
    limit = int(ctx.params.get("limit") or 5)
    url = ("http://export.arxiv.org/api/query?"
           + urllib.parse.urlencode({"search_query": f"all:{q}", "start": 0,
                                     "max_results": limit}))
    with urllib.request.urlopen(url, timeout=25) as r:
        raw = r.read().decode("utf-8", "replace")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(raw)
    out = []
    for entry in root.findall("a:entry", ns):
        title = re.sub(r"\\s+", " ", (entry.findtext("a:title", "", ns) or "")).strip()
        summary = re.sub(r"\\s+", " ", (entry.findtext("a:summary", "", ns) or "")).strip()
        link = entry.findtext("a:id", "", ns) or ""
        authors = ", ".join(
            a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)
        )[:120]
        out.append(f"### {title}\\n- 作者：{authors}\\n- 链接：{link}\\n- 摘要：{summary[:400]}")
    return "\\n\\n".join(out) if out else f"arXiv 没有搜到「{q}」"
''',
    '''
    import re
    import urllib.parse
    import urllib.request
    import xml.etree.ElementTree as ET

    limit = 5
    url = ("http://export.arxiv.org/api/query?"
           + urllib.parse.urlencode({"search_query": f"all:{query}", "start": 0,
                                     "max_results": limit}))
    with urllib.request.urlopen(url, timeout=25) as r:
        raw = r.read().decode("utf-8", "replace")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(raw)
    out = []
    for entry in root.findall("a:entry", ns):
        title = re.sub(r"\\s+", " ", (entry.findtext("a:title", "", ns) or "")).strip()
        summary = re.sub(r"\\s+", " ", (entry.findtext("a:summary", "", ns) or "")).strip()
        link = entry.findtext("a:id", "", ns) or ""
        authors = ", ".join(
            a.findtext("a:name", "", ns) for a in entry.findall("a:author", ns)
        )[:120]
        out.append(f"### {title}\\n- 作者：{authors}\\n- 链接：{link}\\n- 摘要：{summary[:400]}")
    return "\\n\\n".join(out) if out else f"arXiv 没有搜到「{query}」"
''',
    [{"key": "query", "label": "关键词", "default": ""},
     {"key": "limit", "label": "返回篇数", "default": 5}],
)

_add(
    "pubmed", "PubMed 文献", "查 PubMed 医学文献摘要（NCBI 公共接口，免费）。",
    "query: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """PubMed：先按关键词拿 id，再取摘要。"""
    import json
    import urllib.parse
    import urllib.request

    q = (ctx.params.get("query") or ctx.text).strip()
    if not q:
        return "PubMed 查询需要关键词"
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    search = f"{base}/esearch.fcgi?" + urllib.parse.urlencode({
        "db": "pubmed", "term": q, "retmode": "json", "retmax": 5})
    with urllib.request.urlopen(search, timeout=20) as r:
        ids = json.loads(r.read().decode("utf-8", "replace")).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return f"PubMed 没有搜到「{q}」"
    fetch = f"{base}/esummary.fcgi?" + urllib.parse.urlencode({
        "db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    with urllib.request.urlopen(fetch, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace")).get("result", {})
    out = []
    for pid in ids:
        item = data.get(pid) or {}
        if not item:
            continue
        out.append(f"### {item.get('title', '')}\\n"
                   f"- 期刊：{item.get('fulljournalname', '')} {item.get('pubdate', '')}\\n"
                   f"- 链接：https://pubmed.ncbi.nlm.nih.gov/{pid}/")
    return "\\n\\n".join(out)
''',
    '''
    import json
    import urllib.parse
    import urllib.request

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    search = f"{base}/esearch.fcgi?" + urllib.parse.urlencode({
        "db": "pubmed", "term": query, "retmode": "json", "retmax": 5})
    with urllib.request.urlopen(search, timeout=20) as r:
        ids = json.loads(r.read().decode("utf-8", "replace")).get("esearchresult", {}).get("idlist", [])
    if not ids:
        return f"PubMed 没有搜到「{query}」"
    fetch = f"{base}/esummary.fcgi?" + urllib.parse.urlencode({
        "db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    with urllib.request.urlopen(fetch, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace")).get("result", {})
    out = []
    for pid in ids:
        item = data.get(pid) or {}
        if not item:
            continue
        out.append(f"### {item.get('title', '')}\\n"
                   f"- 期刊：{item.get('fulljournalname', '')} {item.get('pubdate', '')}\\n"
                   f"- 链接：https://pubmed.ncbi.nlm.nih.gov/{pid}/")
    return "\\n\\n".join(out)
''',
    [{"key": "query", "label": "关键词", "default": ""}],
)

# --------------------------------------------------------------------------- #
# 网络与站点类（对应 CrewAI: ScrapeWebsiteTool / Dify: 网页解析 / Coze: 网页插件）
# --------------------------------------------------------------------------- #
_add(
    "jina_reader", "网页转 Markdown", "用 Jina Reader 把任意 URL 转成干净 Markdown（免费额度，无需 key）。",
    "url: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Jina Reader：r.jina.ai/<url> 直接返回正文 markdown。"""
    import urllib.request

    url = (ctx.params.get("url") or ctx.text).strip()
    if not url:
        return "需要一个 URL"
    target = url if url.startswith("http") else f"https://{url}"
    req = urllib.request.Request(f"https://r.jina.ai/{target}",
                                 headers={"User-Agent": "MineAgent/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        text = r.read().decode("utf-8", "replace")
    limit = int(ctx.params.get("limit") or 8000)
    return text[:limit]
''',
    '''
    import urllib.request

    target = url if url.startswith("http") else f"https://{url}"
    req = urllib.request.Request(f"https://r.jina.ai/{target}",
                                 headers={"User-Agent": "MineAgent/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        text = r.read().decode("utf-8", "replace")
    return text[:8000]
''',
    [{"key": "url", "label": "网址", "default": ""},
     {"key": "limit", "label": "最多字符", "default": 8000}],
)

_add(
    "scrape_links", "提取网页链接", "抓取页面并提取所有链接（含锚文本），可按关键词过滤。",
    "url: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """提取页面里的 <a href>，返回 标题 → 链接 列表。"""
    import html as _html
    import re
    import urllib.parse
    import urllib.request

    url = (ctx.params.get("url") or ctx.text).strip()
    if not url:
        return "需要一个 URL"
    target = url if url.startswith("http") else f"https://{url}"
    req = urllib.request.Request(target, headers={"User-Agent": "MineAgent/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        page = r.read().decode("utf-8", "replace")
    keyword = (ctx.params.get("keyword") or "").strip().lower()
    limit = int(ctx.params.get("limit") or 30)
    out, seen = [], set()
    for href, text in re.findall(r'<a[^>]+href=["\\']([^"\\']+)["\\'][^>]*>(.*?)</a>',
                                 page, re.I | re.S):
        link = urllib.parse.urljoin(target, href)
        title = re.sub(r"<[^>]+>", "", text)
        title = _html.unescape(re.sub(r"\\s+", " ", title)).strip()
        if not title or link in seen:
            continue
        if keyword and keyword not in (title + link).lower():
            continue
        seen.add(link)
        out.append(f"- [{title[:80]}]({link})")
        if len(out) >= limit:
            break
    return "\\n".join(out) if out else "页面里没有提取到链接"
''',
    '''
    import html as _html
    import re
    import urllib.parse
    import urllib.request

    target = url if url.startswith("http") else f"https://{url}"
    req = urllib.request.Request(target, headers={"User-Agent": "MineAgent/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        page = r.read().decode("utf-8", "replace")
    out, seen = [], set()
    for href, text in re.findall(r'<a[^>]+href=["\\']([^"\\']+)["\\'][^>]*>(.*?)</a>',
                                 page, re.I | re.S):
        link = urllib.parse.urljoin(target, href)
        title = re.sub(r"<[^>]+>", "", text)
        title = _html.unescape(re.sub(r"\\s+", " ", title)).strip()
        if not title or link in seen:
            continue
        seen.add(link)
        out.append(f"- [{title[:80]}]({link})")
        if len(out) >= 30:
            break
    return "\\n".join(out) if out else "页面里没有提取到链接"
''',
    [{"key": "url", "label": "网址", "default": ""},
     {"key": "keyword", "label": "链接需含关键词", "default": ""},
     {"key": "limit", "label": "最多条数", "default": 30}],
)

_add(
    "rss_feed", "RSS 订阅", "读取 RSS / Atom 源的最新条目（标题、时间、链接）。",
    "url: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """解析 RSS / Atom，返回前 N 条。"""
    import re
    import urllib.request
    import xml.etree.ElementTree as ET

    url = (ctx.params.get("url") or ctx.text).strip()
    if not url:
        return "需要一个 RSS 地址"
    limit = int(ctx.params.get("limit") or 10)
    req = urllib.request.Request(url, headers={"User-Agent": "MineAgent/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode("utf-8", "replace")
    root = ET.fromstring(raw)
    items = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry")
    out = []
    for it in items[:limit]:
        title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link = (it.findtext("link") or it.findtext("{http://www.w3.org/2005/Atom}link") or "").strip()
        date = (it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()
        desc = (it.findtext("description") or it.findtext("{http://www.w3.org/2005/Atom}summary") or "")
        desc = re.sub(r"<[^>]+>", "", desc).strip()[:200]
        out.append(f"### {title}\\n- 时间：{date}\\n- 链接：{link}\\n- 摘要：{desc}")
    return "\\n\\n".join(out) if out else "这个源里没有条目"
''',
    '''
    import re
    import urllib.request
    import xml.etree.ElementTree as ET

    req = urllib.request.Request(url, headers={"User-Agent": "MineAgent/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode("utf-8", "replace")
    root = ET.fromstring(raw)
    items = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry")
    out = []
    for it in items[:10]:
        title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
        link = (it.findtext("link") or it.findtext("{http://www.w3.org/2005/Atom}link") or "").strip()
        date = (it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()
        desc = (it.findtext("description") or it.findtext("{http://www.w3.org/2005/Atom}summary") or "")
        desc = re.sub(r"<[^>]+>", "", desc).strip()[:200]
        out.append(f"### {title}\\n- 时间：{date}\\n- 链接：{link}\\n- 摘要：{desc}")
    return "\\n\\n".join(out) if out else "这个源里没有条目"
''',
    [{"key": "url", "label": "RSS 地址", "default": ""},
     {"key": "limit", "label": "返回条数", "default": 10}],
)

_add(
    "open_meteo", "天气查询", "查城市当前天气与未来三天预报（Open-Meteo，免费无需 key）。",
    "city: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """先用城市名查经纬度，再取天气。"""
    import json
    import urllib.parse
    import urllib.request

    city = (ctx.params.get("city") or ctx.text).strip()
    if not city:
        return "需要城市名"
    geo = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": city, "count": 1, "language": "zh"})
    with urllib.request.urlopen(geo, timeout=20) as r:
        hits = json.loads(r.read().decode("utf-8", "replace")).get("results") or []
    if not hits:
        return f"没找到城市：{city}"
    loc = hits[0]
    wx = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": loc["latitude"], "longitude": loc["longitude"],
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "auto", "forecast_days": 3,
    })
    with urllib.request.urlopen(wx, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    cur = data.get("current") or {}
    codes = {0: "晴", 1: "多云", 2: "多云", 3: "阴", 45: "雾", 51: "毛毛雨",
             61: "小雨", 63: "中雨", 65: "大雨", 71: "小雪", 80: "阵雨",
             95: "雷阵雨"}
    lines = [f"# {loc.get('name')} 天气",
             f"- 当前：{codes.get(cur.get('weather_code'), cur.get('weather_code'))} "
             f"{cur.get('temperature_2m')}°C，湿度 {cur.get('relative_humidity_2m')}%，"
             f"风速 {cur.get('wind_speed_10m')} km/h"]
    daily = data.get("daily") or {}
    for i, day in enumerate(daily.get("time") or []):
        lines.append(f"- {day}：{daily['temperature_2m_min'][i]} ~ "
                     f"{daily['temperature_2m_max'][i]}°C，"
                     f"{codes.get(daily['weather_code'][i], daily['weather_code'][i])}")
    return "\\n".join(lines)
''',
    '''
    import json
    import urllib.parse
    import urllib.request

    geo = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": city, "count": 1, "language": "zh"})
    with urllib.request.urlopen(geo, timeout=20) as r:
        hits = json.loads(r.read().decode("utf-8", "replace")).get("results") or []
    if not hits:
        return f"没找到城市：{city}"
    loc = hits[0]
    wx = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": loc["latitude"], "longitude": loc["longitude"],
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "auto", "forecast_days": 3,
    })
    with urllib.request.urlopen(wx, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    cur = data.get("current") or {}
    codes = {0: "晴", 1: "多云", 2: "多云", 3: "阴", 45: "雾", 51: "毛毛雨",
             61: "小雨", 63: "中雨", 65: "大雨", 71: "小雪", 80: "阵雨",
             95: "雷阵雨"}
    lines = [f"# {loc.get('name')} 天气",
             f"- 当前：{codes.get(cur.get('weather_code'), cur.get('weather_code'))} "
             f"{cur.get('temperature_2m')}°C，湿度 {cur.get('relative_humidity_2m')}%，"
             f"风速 {cur.get('wind_speed_10m')} km/h"]
    daily = data.get("daily") or {}
    for i, day in enumerate(daily.get("time") or []):
        lines.append(f"- {day}：{daily['temperature_2m_min'][i]} ~ "
                     f"{daily['temperature_2m_max'][i]}°C，"
                     f"{codes.get(daily['weather_code'][i], daily['weather_code'][i])}")
    return "\\n".join(lines)
''',
    [{"key": "city", "label": "城市", "default": ""}],
)

_add(
    "dns_lookup", "DNS 解析", "查域名的 A / AAAA / MX / TXT 记录（本地解析，无需 key）。",
    "domain: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """DNS：默认查 A 记录。"""
    import socket

    domain = (ctx.params.get("domain") or ctx.text).strip()
    if not domain:
        return "需要域名"
    record = (ctx.params.get("record") or "A").upper()
    try:
        if record == "A":
            infos = socket.getaddrinfo(domain, None, socket.AF_INET)
            ips = sorted({i[4][0] for i in infos})
            return f"{domain} 的 A 记录：\\n" + "\\n".join(f"- {ip}" for ip in ips)
        if record == "AAAA":
            infos = socket.getaddrinfo(domain, None, socket.AF_INET6)
            ips = sorted({i[4][0] for i in infos})
            return f"{domain} 的 AAAA 记录：\\n" + "\\n".join(f"- {ip}" for ip in ips)
        return f"本地解析只支持 A / AAAA，当前是 {record}"
    except Exception as exc:  # noqa: BLE001
        return f"解析失败：{exc}"
''',
    '''
    import socket

    if record == "AAAA":
        infos = socket.getaddrinfo(domain, None, socket.AF_INET6)
        return f"{domain} 的 AAAA 记录：\\n" + "\\n".join(
            f"- {ip}" for ip in sorted({i[4][0] for i in infos}))
    infos = socket.getaddrinfo(domain, None, socket.AF_INET)
    return f"{domain} 的 A 记录：\\n" + "\\n".join(
        f"- {ip}" for ip in sorted({i[4][0] for i in infos}))
''',
    [{"key": "domain", "label": "域名", "default": ""},
     {"key": "record", "label": "记录类型", "default": "A"}],
)

_add(
    "ip_info", "IP 归属地", "查 IP 的国家、地区、ISP（ip-api.com，免费）。",
    "ip: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """IP 归属：不传 ip 就查本机出口 IP。"""
    import json
    import urllib.request

    ip = (ctx.params.get("ip") or ctx.text).strip()
    url = f"http://ip-api.com/json/{ip}?lang=zh-CN" if ip else "http://ip-api.com/json/?lang=zh-CN"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    if data.get("status") != "success":
        return f"查询失败：{data.get('message', '')}"
    return (f"- IP：{data.get('query')}\\n- 国家/地区：{data.get('country')} {data.get('regionName')} "
            f"{data.get('city')}\\n- ISP：{data.get('isp')}\\n- 时区：{data.get('timezone')}")
''',
    '''
    import json
    import urllib.request

    url = f"http://ip-api.com/json/{ip}?lang=zh-CN" if ip else "http://ip-api.com/json/?lang=zh-CN"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    if data.get("status") != "success":
        return f"查询失败：{data.get('message', '')}"
    return (f"- IP：{data.get('query')}\\n- 国家/地区：{data.get('country')} {data.get('regionName')} "
            f"{data.get('city')}\\n- ISP：{data.get('isp')}\\n- 时区：{data.get('timezone')}")
''',
    [{"key": "ip", "label": "IP（留空查本机）", "default": ""}],
)

# --------------------------------------------------------------------------- #
# 本地实用类（对应 OpenAI Code Interpreter / Claude 工具集）
# --------------------------------------------------------------------------- #
_add(
    "python_repl", "Python 执行", "在子进程里跑一段 Python，返回 stdout / stderr（对应 LangChain PythonREPL）。",
    "code: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Python 执行：超时 30 秒，只返回最后 4000 字。"""
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    code = (ctx.params.get("code") or ctx.text).strip()
    if not code:
        return "需要一段 Python 代码"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "snippet.py"
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run([sys.executable, str(path)], capture_output=True,
                                  text=True, timeout=30, encoding="utf-8",
                                  errors="replace")
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode != 0:
                return f"执行失败（退出码 {proc.returncode}）\\n{err[-2000:]}"
            return out[-4000:] or "(代码执行成功，没有输出)"
        except subprocess.TimeoutExpired:
            return "执行超时（30 秒）"
''',
    '''
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "snippet.py"
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run([sys.executable, str(path)], capture_output=True,
                                  text=True, timeout=30, encoding="utf-8",
                                  errors="replace")
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode != 0:
                return f"执行失败（退出码 {proc.returncode}）\\n{err[-2000:]}"
            return out[-4000:] or "(代码执行成功，没有输出)"
        except subprocess.TimeoutExpired:
            return "执行超时（30 秒）"
''',
    [{"key": "code", "label": "Python 代码", "default": ""}],
)

_add(
    "hash_text", "哈希计算", "算 md5 / sha1 / sha256，常用于校验与去重。",
    "text: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """哈希：默认 sha256。"""
    import hashlib

    text = ctx.params.get("text") or ctx.text
    algo = (ctx.params.get("algo") or "sha256").lower()
    h = hashlib.new(algo)
    h.update(str(text).encode("utf-8"))
    return f"{algo}: {h.hexdigest()}"
''',
    '''
    import hashlib

    algo = "sha256"
    h = hashlib.new(algo)
    h.update(str(text).encode("utf-8"))
    return f"{algo}: {h.hexdigest()}"
''',
    [{"key": "text", "label": "文本", "default": ""},
     {"key": "algo", "label": "算法", "default": "sha256"}],
)

_add(
    "base64_codec", "Base64 编解码", "Base64 编码或解码（支持 URL-safe）。",
    "text: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Base64：action=encode / decode。"""
    import base64

    text = ctx.params.get("text") or ctx.text
    action = (ctx.params.get("action") or "encode").lower()
    if action == "decode":
        raw = base64.urlsafe_b64decode(str(text) + "=" * (-len(str(text)) % 4))
        return raw.decode("utf-8", "replace")
    return base64.urlsafe_b64encode(str(text).encode("utf-8")).decode("ascii")
''',
    '''
    import base64

    if action == "decode":
        raw = base64.urlsafe_b64decode(str(text) + "=" * (-len(str(text)) % 4))
        return raw.decode("utf-8", "replace")
    return base64.urlsafe_b64encode(str(text).encode("utf-8")).decode("ascii")
''',
    [{"key": "text", "label": "文本", "default": ""},
     {"key": "action", "label": "encode / decode", "default": "encode"}],
)

_add(
    "uuid_gen", "生成 UUID", "生成指定数量的 UUID4。",
    "count: int",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """UUID：默认生成 1 个。"""
    import uuid

    n = max(1, min(int(ctx.params.get("count") or 1), 100))
    return "\\n".join(str(uuid.uuid4()) for _ in range(n))
''',
    '''
    import uuid

    return "\\n".join(str(uuid.uuid4()) for _ in range(1))
''',
    [{"key": "count", "label": "数量", "default": 1}],
)

_add(
    "regex_extract", "正则提取", "用正则从文本里抽出所有匹配（可只取第 1 个分组）。",
    "pattern: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """正则提取：返回匹配列表。"""
    import re

    pattern = ctx.params.get("pattern") or ""
    if not pattern:
        return "需要正则表达式"
    text = str(ctx.params.get("text") or ctx.text)
    flags = re.I if str(ctx.params.get("ignore_case", "")).lower() in ("1", "true", "yes") else 0
    group = ctx.params.get("group")
    hits = []
    for m in re.finditer(pattern, text, flags):
        hits.append(m.group(int(group)) if group not in (None, "") else m.group(0))
    if not hits:
        return "没有匹配"
    return "\\n".join(str(h) for h in hits[:200])
''',
    '''
    import re

    hits = [m.group(0) for m in re.finditer(pattern, str(text))]
    return "\\n".join(hits[:200]) if hits else "没有匹配"
''',
    [{"key": "pattern", "label": "正则", "default": ""},
     {"key": "text", "label": "文本（留空用上游）", "default": ""},
     {"key": "group", "label": "取第几个分组", "default": ""},
     {"key": "ignore_case", "label": "忽略大小写", "default": ""}],
)

_add(
    "diff_text", "文本对比", "比较两段文本，输出逐行差异（类似 unified diff）。",
    "old: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """文本对比：old / new 两段。"""
    import difflib

    old = str(ctx.params.get("old") or "")
    new = str(ctx.params.get("new") or ctx.text or "")
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(),
                                fromfile="old", tofile="new", lineterm="")
    text = "\\n".join(diff)
    return text[:4000] if text else "两段文本完全一致"
''',
    '''
    import difflib

    diff = difflib.unified_diff(str(old).splitlines(), str(new).splitlines(),
                                fromfile="old", tofile="new", lineterm="")
    text = "\\n".join(diff)
    return text[:4000] if text else "两段文本完全一致"
''',
    [{"key": "old", "label": "原文", "default": ""},
     {"key": "new", "label": "新文（留空用上游）", "default": ""}],
)

_add(
    "markdown_to_html", "Markdown 转 HTML", "把 Markdown 渲染成 HTML 片段。",
    "text: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """MD → HTML：优先用 markdown 库，没有就做最小转换。"""
    import re

    text = str(ctx.params.get("text") or ctx.text)
    try:
        import markdown  # type: ignore
        return markdown.markdown(text, extensions=["extra", "tables"])
    except ImportError:
        pass
    html = re.sub(r"^### (.+)$", r"<h3>\\1</h3>", text, flags=re.M)
    html = re.sub(r"^## (.+)$", r"<h2>\\1</h2>", html, flags=re.M)
    html = re.sub(r"^# (.+)$", r"<h1>\\1</h1>", html, flags=re.M)
    html = re.sub(r"\\*\\*(.+?)\\*\\*", r"<strong>\\1</strong>", html)
    html = re.sub(r"\\*(.+?)\\*", r"<em>\\1</em>", html)
    html = re.sub(r"`(.+?)`", r"<code>\\1</code>", html)
    html = re.sub(r"\\n{2,}", "</p><p>", html)
    return f"<p>{html}</p>"
''',
    '''
    import re

    text = str(text)
    try:
        import markdown  # type: ignore
        return markdown.markdown(text, extensions=["extra", "tables"])
    except ImportError:
        pass
    html = re.sub(r"^### (.+)$", r"<h3>\\1</h3>", text, flags=re.M)
    html = re.sub(r"^## (.+)$", r"<h2>\\1</h2>", html, flags=re.M)
    html = re.sub(r"^# (.+)$", r"<h1>\\1</h1>", html, flags=re.M)
    html = re.sub(r"\\*\\*(.+?)\\*\\*", r"<strong>\\1</strong>", html)
    html = re.sub(r"\\*(.+?)\\*", r"<em>\\1</em>", html)
    html = re.sub(r"`(.+?)`", r"<code>\\1</code>", html)
    html = re.sub(r"\\n{2,}", "</p><p>", html)
    return f"<p>{html}</p>"
''',
    [{"key": "text", "label": "Markdown", "default": ""}],
)

_add(
    "html_to_text", "HTML 转纯文本", "去掉标签、脚本和样式，只留可读正文。",
    "html: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """HTML → 文本：去 script/style/标签，压空白。"""
    import html as _html
    import re

    raw = str(ctx.params.get("html") or ctx.text)
    raw = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\\s*/?>|</p>|</div>|</li>", "\\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", "", raw)
    text = _html.unescape(text)
    text = re.sub(r"[ \\t]+", " ", text)
    text = re.sub(r"\\n{3,}", "\\n\\n", text)
    return text.strip()[:8000]
''',
    '''
    import html as _html
    import re

    raw = str(html)
    raw = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\\s*/?>|</p>|</div>|</li>", "\\n", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", "", raw)
    text = _html.unescape(text)
    text = re.sub(r"[ \\t]+", " ", text)
    text = re.sub(r"\\n{3,}", "\\n\\n", text)
    return text.strip()[:8000]
''',
    [{"key": "html", "label": "HTML", "default": ""}],
)

_add(
    "csv_query", "CSV 查询", "把 CSV 当表查：支持列筛选、排序、取前 N 行（纯标准库）。",
    "path: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """CSV：读文件，按 where / order_by / limit 处理。"""
    import csv
    from pathlib import Path

    path = (ctx.params.get("path") or "").strip()
    if not path:
        return "需要 CSV 路径"
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    if not p.exists():
        return f"找不到 CSV：{p}"
    limit = int(ctx.params.get("limit") or 50)
    where_col = (ctx.params.get("where_col") or "").strip()
    where_val = (ctx.params.get("where_val") or "").strip()
    order_by = (ctx.params.get("order_by") or "").strip()
    with p.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f))
    if where_col and where_col in (rows[0] if rows else {}):
        rows = [r for r in rows if where_val.lower() in str(r.get(where_col, "")).lower()]
    if order_by and rows and order_by in rows[0]:
        rows.sort(key=lambda r: str(r.get(order_by, "")))
    rows = rows[:limit]
    if not rows:
        return "筛选后没有数据"
    head = list(rows[0].keys())
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in head) + " |")
    return "\\n".join(lines)
''',
    '''
    import csv
    from pathlib import Path

    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    if not p.exists():
        return f"找不到 CSV：{p}"
    with p.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f))[:50]
    if not rows:
        return "CSV 里没有数据"
    head = list(rows[0].keys())
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in head) + " |")
    return "\\n".join(lines)
''',
    [{"key": "path", "label": "CSV 路径", "default": ""},
     {"key": "limit", "label": "返回行数", "default": 50},
     {"key": "where_col", "label": "筛选列", "default": ""},
     {"key": "where_val", "label": "筛选值", "default": ""},
     {"key": "order_by", "label": "排序列", "default": ""}],
)

# --------------------------------------------------------------------------- #
# 文档解析类（对应 OpenAI File search / Dify 文档处理）
# --------------------------------------------------------------------------- #
_add(
    "pdf_extract", "PDF 抽文本", "从 PDF 里抽取文本（需要 pypdf）。",
    "path: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """PDF：按页拼接文本。"""
    from pathlib import Path

    path = (ctx.params.get("path") or ctx.text).strip()
    if not path:
        return "需要 PDF 路径"
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    if not p.exists():
        return f"找不到文件：{p}"
    try:
        from pypdf import PdfReader
    except ImportError:
        return "读 PDF 需要 pypdf：pip install pypdf"
    pages = PdfReader(str(p)).pages
    limit = int(ctx.params.get("pages") or 0) or len(pages)
    text = "\\n\\n".join((pg.extract_text() or "") for pg in pages[:limit])
    return text[:12000] or "(PDF 里没有抽到文本)"
''',
    '''
    from pathlib import Path

    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    if not p.exists():
        return f"找不到文件：{p}"
    try:
        from pypdf import PdfReader
    except ImportError:
        return "读 PDF 需要 pypdf：pip install pypdf"
    pages = PdfReader(str(p)).pages
    text = "\\n\\n".join((pg.extract_text() or "") for pg in pages)
    return text[:12000] or "(PDF 里没有抽到文本)"
''',
    [{"key": "path", "label": "PDF 路径", "default": ""},
     {"key": "pages", "label": "前几页（0=全部）", "default": 0}],
)

_add(
    "docx_extract", "Word 抽文本", "从 .docx 里抽取段落文本（需要 python-docx）。",
    "path: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Word：按段落拼接。"""
    from pathlib import Path

    path = (ctx.params.get("path") or ctx.text).strip()
    if not path:
        return "需要 docx 路径"
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    if not p.exists():
        return f"找不到文件：{p}"
    try:
        import docx
    except ImportError:
        return "读 docx 需要 python-docx：pip install python-docx"
    text = "\\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    return text[:12000] or "(文档里没有段落)"
''',
    '''
    from pathlib import Path

    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent / p
    if not p.exists():
        return f"找不到文件：{p}"
    try:
        import docx
    except ImportError:
        return "读 docx 需要 python-docx：pip install python-docx"
    text = "\\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    return text[:12000] or "(文档里没有段落)"
''',
    [{"key": "path", "label": "docx 路径", "default": ""}],
)

# --------------------------------------------------------------------------- #
# 通知类（对应 Coze / Dify 的消息推送插件；只需 webhook URL）
# --------------------------------------------------------------------------- #
_add(
    "webhook_send", "Webhook 推送", "向任意 Webhook 发一条消息（Slack / 飞书 / 钉钉 / Discord 通用）。",
    "url: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Webhook：按目标格式拼 body 再 POST。"""
    import json
    import urllib.request

    url = ctx.params.get("url") or ""
    if not url:
        return "需要 webhook 地址"
    text = str(ctx.params.get("text") or ctx.text)
    kind = (ctx.params.get("kind") or "feishu").lower()
    if kind == "slack":
        body = {"text": text}
    elif kind == "discord":
        body = {"content": text}
    elif kind == "dingtalk":
        body = {"msgtype": "text", "text": {"content": text}}
    else:  # feishu / 自定义
        body = {"msg_type": "text", "content": {"text": text}}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return f"已推送（HTTP {r.status}）"
''',
    '''
    import json
    import urllib.request

    body = {"msg_type": "text", "content": {"text": str(text)}}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return f"已推送（HTTP {r.status}）"
''',
    [{"key": "url", "label": "Webhook 地址", "default": ""},
     {"key": "text", "label": "内容（留空用上游）", "default": ""},
     {"key": "kind", "label": "feishu/slack/discord/dingtalk", "default": "feishu"}],
)

_add(
    "github_api", "GitHub API", "查仓库 / issue / PR / 用户（免费，有 token 可提高额度）。",
    "path: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """GitHub：path 形如 repos/openai/openai-python（不带前导斜杠也行）。"""
    import json
    import os
    import urllib.request

    path = (ctx.params.get("path") or ctx.text).strip().lstrip("/")
    if not path:
        return "需要 GitHub API 路径，例如 repos/openai/openai-python"
    token = os.environ.get("GITHUB_TOKEN") or ctx.params.get("token") or ""
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"User-Agent": "MineAgent/1.0",
                                          "Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    if isinstance(data, dict):
        keep = {k: data[k] for k in ("full_name", "description", "stargazers_count",
                                     "forks_count", "open_issues_count", "html_url",
                                     "title", "state", "user", "login") if k in data}
        return json.dumps(keep or data, ensure_ascii=False, indent=2)[:4000]
    return json.dumps(data, ensure_ascii=False, indent=2)[:4000]
''',
    '''
    import json
    import os
    import urllib.request

    path = str(path).strip().lstrip("/")
    token = os.environ.get("GITHUB_TOKEN") or ""
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"User-Agent": "MineAgent/1.0",
                                          "Accept": "application/vnd.github+json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    return json.dumps(data, ensure_ascii=False, indent=2)[:4000]
''',
    [{"key": "path", "label": "API 路径", "default": "repos/openai/openai-python"},
     {"key": "token", "label": "Token（可选）", "default": ""}],
)

# --------------------------------------------------------------------------- #
# 需要第三方 key 的（CrewAI / LangChain 生态里最常见的几个）
# --------------------------------------------------------------------------- #
_add(
    "tavily_search", "Tavily 搜索", "Tavily 深度搜索，返回带来源的摘要（需要 TAVILY_API_KEY）。",
    "query: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Tavily：对应 LangChain 的 TavilySearchResults。"""
    import json
    import os
    import urllib.request

    key = os.environ.get("TAVILY_API_KEY") or ctx.params.get("api_key") or ""
    if not key:
        return "需要 TAVILY_API_KEY（https://tavily.com 申请后填进 .env）"
    q = (ctx.params.get("query") or ctx.text).strip()
    body = json.dumps({"api_key": key, "query": q,
                       "max_results": int(ctx.params.get("max_results") or 5),
                       "include_answer": True}).encode("utf-8")
    req = urllib.request.Request("https://api.tavily.com/search", data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out = [f"**{data.get('answer', '')}**"] if data.get("answer") else []
    for item in data.get("results", []):
        out.append(f"### {item.get('title')}\\n{item.get('content', '')[:300]}\\n"
                   f"- 来源：{item.get('url')}")
    return "\\n\\n".join(out) or "没有结果"
''',
    '''
    import json
    import os
    import urllib.request

    key = os.environ.get("TAVILY_API_KEY") or ""
    if not key:
        return "需要 TAVILY_API_KEY（https://tavily.com 申请后填进 .env）"
    body = json.dumps({"api_key": key, "query": query,
                       "max_results": 5, "include_answer": True}).encode("utf-8")
    req = urllib.request.Request("https://api.tavily.com/search", data=body,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out = [f"**{data.get('answer', '')}**"] if data.get("answer") else []
    for item in data.get("results", []):
        out.append(f"### {item.get('title')}\\n{item.get('content', '')[:300]}\\n"
                   f"- 来源：{item.get('url')}")
    return "\\n\\n".join(out) or "没有结果"
''',
    [{"key": "query", "label": "查询", "default": ""},
     {"key": "max_results", "label": "条数", "default": 5},
     {"key": "api_key", "label": "API Key（或用环境变量）", "default": ""}],
)

_add(
    "serper_search", "Google 搜索", "Serper.dev 的 Google 搜索结果（需要 SERPER_API_KEY）。",
    "query: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """Serper：对应 CrewAI 的 SerperApiTool。"""
    import json
    import os
    import urllib.request

    key = os.environ.get("SERPER_API_KEY") or ctx.params.get("api_key") or ""
    if not key:
        return "需要 SERPER_API_KEY（https://serper.dev 申请）"
    q = (ctx.params.get("query") or ctx.text).strip()
    body = json.dumps({"q": q, "num": 10}).encode("utf-8")
    req = urllib.request.Request("https://google.serper.dev/search", data=body,
                                 method="POST",
                                 headers={"X-API-KEY": key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out = []
    if data.get("answerBox", {}).get("answer"):
        out.append(f"**{data['answerBox']['answer']}**")
    for item in data.get("organic", [])[:8]:
        out.append(f"### {item.get('title')}\\n{item.get('snippet', '')}\\n- {item.get('link')}")
    return "\\n\\n".join(out) or "没有结果"
''',
    '''
    import json
    import os
    import urllib.request

    key = os.environ.get("SERPER_API_KEY") or ""
    if not key:
        return "需要 SERPER_API_KEY（https://serper.dev 申请）"
    body = json.dumps({"q": query, "num": 10}).encode("utf-8")
    req = urllib.request.Request("https://google.serper.dev/search", data=body,
                                 method="POST",
                                 headers={"X-API-KEY": key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out = []
    for item in data.get("organic", [])[:8]:
        out.append(f"### {item.get('title')}\\n{item.get('snippet', '')}\\n- {item.get('link')}")
    return "\\n\\n".join(out) or "没有结果"
''',
    [{"key": "query", "label": "查询", "default": ""},
     {"key": "api_key", "label": "API Key（或用环境变量）", "default": ""}],
)

_add(
    "wolfram_alpha", "WolframAlpha", "数学 / 知识计算（需要 WOLFRAM_APP_ID）。",
    "query: str",
    '''
from runtime_sdk import NodeContext


def run(ctx: NodeContext):
    """WolframAlpha：short answers API。"""
    import os
    import urllib.parse
    import urllib.request

    app_id = os.environ.get("WOLFRAM_APP_ID") or ctx.params.get("app_id") or ""
    if not app_id:
        return "需要 WOLFRAM_APP_ID（https://products.wolframalpha.com/api）"
    q = (ctx.params.get("query") or ctx.text).strip()
    url = "https://api.wolframalpha.com/v1/result?" + urllib.parse.urlencode(
        {"appid": app_id, "i": q})
    with urllib.request.urlopen(url, timeout=25) as r:
        return r.read().decode("utf-8", "replace")[:2000]
''',
    '''
    import os
    import urllib.parse
    import urllib.request

    app_id = os.environ.get("WOLFRAM_APP_ID") or ""
    if not app_id:
        return "需要 WOLFRAM_APP_ID（https://products.wolframalpha.com/api）"
    url = "https://api.wolframalpha.com/v1/result?" + urllib.parse.urlencode(
        {"appid": app_id, "i": query})
    with urllib.request.urlopen(url, timeout=25) as r:
        return r.read().decode("utf-8", "replace")[:2000]
''',
    [{"key": "query", "label": "计算式 / 问题", "default": ""},
     {"key": "app_id", "label": "AppID（或用环境变量）", "default": ""}],
)
