"""
Knowledge Graph API — standalone module.
Parses [[wiki-links]], #tags, title keywords, content keywords, and folder
proximity from Obsidian vault to build a rich knowledge graph.
"""
import os
import re
from collections import Counter, defaultdict
from fastapi import APIRouter

router = APIRouter()

VAULT_ROOT = os.path.normpath(os.path.expanduser("~/Documents/Obsidian Vault"))

# Dirs to scan (relative to vault root)
SCAN_DIRS = ["Bookmarks", "Kanban", "Notes", "People", "Research", "TaskLog", "Workspace"]

# ── Stopwords (English + Chinese common) ──────────────────────────────────────
STOPWORDS: set[str] = {
    # English
    "the","be","to","of","and","a","in","that","have","i","it","for","not","on",
    "with","he","as","you","do","at","this","but","his","by","from","they","we",
    "say","her","she","or","an","will","my","one","all","would","there","their",
    "what","so","up","out","if","about","who","get","which","go","me","when",
    "make","can","like","time","no","just","him","know","take","people","into",
    "year","your","good","some","could","them","see","other","than","then","now",
    "look","only","come","its","over","think","also","back","after","use","two",
    "how","our","work","first","well","way","even","new","want","because","any",
    "these","give","day","most","us","is","are","was","were","been","has","had",
    "did","does","doing","done","am","being","very","much","more","many","such",
    "own","should","may","might","must","shall","need","still","each","every",
    "both","few","those","same","too","here","where","why","while","through",
    "before","between","after","again","under","last","never","always","often",
    "since","during","without","within","along","across","against","already",
    "really","thing","things","something","anything","nothing","everything",
    # Chinese
    "的","了","在","是","我","有","和","就","不","人","都","一","一个","上","也",
    "很","到","说","要","去","你","会","着","没有","看","好","自己","这","他","她",
    "它","们","那","被","从","把","让","对","没","能","吗","吧","还","什么","但",
    "下","可以","这个","之","而","所以","因为","如果","虽然","但是","不过","那么",
    "怎么","哪","谁","多","大","小","中","更","最","已","已经","正在","将","与",
    "及","等","个","些","其","此","该","每","各","另","这些","那些","里面","通过",
    "进行","使用","可以","需要","我们","他们","它们","不是","或者","以及",
}

# Short/generic keywords to skip when matching titles
_TITLE_STOPWORDS: set[str] = {
    "a","an","the","and","or","but","in","on","at","to","for","of","with","by",
    "is","it","its","my","no","not","so","up","us","we","do","go","he","me","as",
    "progress","notes","note","log","task","doc","docs","file","index","readme",
    "md","tmp","temp","test","draft","wip","todo","archive","untitled",
}


def _title_keywords(name: str) -> set[str]:
    """Extract meaningful keywords from a file name (hyphen/space separated)."""
    parts = re.split(r"[-_\s]+", name.lower())
    return {p for p in parts if len(p) >= 2 and p not in _TITLE_STOPWORDS}


def _extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """Return the top-N highest-frequency words from *text*, filtering stopwords."""
    # Tokenise: sequences of alphabetic / CJK / digit characters
    tokens = re.findall(r"[a-zA-Z\u4e00-\u9fff][\w\u4e00-\u9fff-]*", text.lower())
    # Count, skip stopwords & very short tokens
    counter = Counter(t for t in tokens if t not in STOPWORDS and len(t) >= 2)
    return [w for w, _ in counter.most_common(top_n)]


# Edge type → display colour (rgba for vis-network)
EDGE_COLORS: dict[str, str] = {
    "link":    "rgba(100,116,139,0.30)",
    "tag":     "rgba(59,130,246,0.30)",
    "keyword": "rgba(16,185,129,0.25)",
    "folder":  "rgba(100,116,139,0.10)",
}


def _walk_md(base: str, rel_dir: str) -> list[str]:
    """Return relative paths of all .md files under rel_dir."""
    results = []
    abs_dir = os.path.join(base, rel_dir)
    if not os.path.isdir(abs_dir):
        return results
    for root, _, files in os.walk(abs_dir):
        for f in files:
            if f.endswith(".md"):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, base)
                results.append(rel)
    return results


def _parse_links_and_tags(content: str) -> tuple[list[str], list[str]]:
    """Extract [[wiki-links]], file refs, and #tags from markdown content."""
    # Wiki links: [[Target]] or [[Target|Display]]
    links = re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]", content)

    # File references: paths like Notes/xxx.md or Kanban/xxx
    file_refs = re.findall(
        r"(?:Notes|Kanban|Bookmarks|People|Research|TaskLog|Workspace|PlanPipeline)/[\w\u4e00-\u9fff-]+(?:-[\w\u4e00-\u9fff-]+)*(?:\.md)?",
        content,
    )
    links.extend(file_refs)

    # Tags: #tag (not inside code blocks)
    cleaned = re.sub(r"`[^`]+`", "", content)
    cleaned = re.sub(r"```[\s\S]*?```", "", cleaned)
    tags = re.findall(r"(?:^|\s)#([a-zA-Z0-9_\u4e00-\u9fff][\w\u4e00-\u9fff-]*)", cleaned)
    return links, tags


def _resolve_link(link_target: str, all_files: set[str]) -> str | None:
    """Try to resolve a [[link target]] to an actual vault path."""
    # Direct match
    if link_target in all_files:
        return link_target
    # Match by filename (with or without .md)
    for ext in ["", ".md"]:
        for f in all_files:
            if os.path.basename(f) == link_target + ext:
                return f
            if f.endswith("/" + link_target + ext):
                return f
    return None


def build_graph() -> dict:
    """Build the full knowledge graph from vault files."""
    all_files: set[str] = set()
    for d in SCAN_DIRS:
        all_files.update(_walk_md(VAULT_ROOT, d))

    # Read all files, extract metadata
    file_data: dict[str, dict] = {}
    for rel_path in sorted(all_files):
        abs_path = os.path.join(VAULT_ROOT, rel_path)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        links, tags = _parse_links_and_tags(content)

        # Extract folder and display name
        folder = os.path.dirname(rel_path)
        name = os.path.splitext(os.path.basename(rel_path))[0]

        # Remove frontmatter from content for title extraction
        body = content
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
        if fm_match:
            body = fm_match.group(2)

        file_data[rel_path] = {
            "id": rel_path,
            "name": name,
            "folder": folder,
            "tags": list(set(tags)),
            "links": links,
            "size": len(content),
            "body": body,
            "title_kw": _title_keywords(name),
            "content_kw": _extract_keywords(body, top_n=10),
        }

    # Build edges: resolve links to actual files
    edges = []
    edge_set = set()
    for src_id, data in file_data.items():
        for link_target in data["links"]:
            resolved = _resolve_link(link_target, all_files)
            if resolved and resolved != src_id:
                edge_key = tuple(sorted([src_id, resolved]))
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append({"from": src_id, "to": resolved, "type": "link"})

    # Build tag-based edges (shared tags → connection)
    tag_files: dict[str, list[str]] = defaultdict(list)
    for fid, data in file_data.items():
        for tag in data["tags"]:
            tag_files[tag].append(fid)

    for tag, files in tag_files.items():
        if len(files) > 1:
            for i in range(len(files)):
                for j in range(i + 1, len(files)):
                    edge_key = tuple(sorted([files[i], files[j]]))
                    if edge_key not in edge_set:
                        edge_set.add(edge_key)
                        edges.append({"from": files[i], "to": files[j], "type": "tag", "tag": tag})

    # ── Title keyword matching ─────────────────────────────────────────────
    file_ids = list(file_data.keys())
    for i in range(len(file_ids)):
        for j in range(i + 1, len(file_ids)):
            fa, fb = file_data[file_ids[i]], file_data[file_ids[j]]
            common = fa["title_kw"] & fb["title_kw"]
            if common:
                edge_key = tuple(sorted([file_ids[i], file_ids[j]]))
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append({
                        "from": file_ids[i],
                        "to": file_ids[j],
                        "type": "keyword",
                        "source": "title",
                        "words": sorted(common),
                    })

    # ── Content keyword overlap ────────────────────────────────────────────
    for i in range(len(file_ids)):
        for j in range(i + 1, len(file_ids)):
            fa, fb = file_data[file_ids[i]], file_data[file_ids[j]]
            set_a = set(fa["content_kw"])
            set_b = set(fb["content_kw"])
            shared = set_a & set_b
            if len(shared) >= 2:
                edge_key = tuple(sorted([file_ids[i], file_ids[j]]))
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append({
                        "from": file_ids[i],
                        "to": file_ids[j],
                        "type": "keyword",
                        "source": "content",
                        "words": sorted(shared),
                    })

    # ── Same-folder edges (weak link) ──────────────────────────────────────
    folder_groups: dict[str, list[str]] = defaultdict(list)
    for fid, data in file_data.items():
        folder_groups[data["folder"]].append(fid)
    for folder, fids in folder_groups.items():
        if len(fids) < 2:
            continue
        for i in range(len(fids)):
            for j in range(i + 1, len(fids)):
                edge_key = tuple(sorted([fids[i], fids[j]]))
                if edge_key not in edge_set:
                    edge_set.add(edge_key)
                    edges.append({
                        "from": fids[i],
                        "to": fids[j],
                        "type": "folder",
                        "folder": folder,
                    })

    # Nodes
    nodes = []
    for fid, data in file_data.items():
        node = {
            "id": fid,
            "label": data["name"],
            "folder": data["folder"],
            "tags": data["tags"],
            "size": max(8, min(40, data["size"] // 200)),
        }
        nodes.append(node)

    return {"nodes": nodes, "edges": edges}


# Cache graph for 60s
_cache: dict = {}
_cache_time: float = 0


@router.get("/api/docs/graph")
def get_graph():
    """Return the knowledge graph as {nodes, edges}."""
    import time
    global _cache, _cache_time
    now = time.time()
    if not _cache or (now - _cache_time) > 60:
        _cache = build_graph()
        _cache_time = now
    return _cache
