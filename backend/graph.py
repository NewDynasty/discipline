"""
Knowledge Graph API — standalone module.
Parses [[wiki-links]] and #tags from Obsidian vault to build a graph.
"""
import os
import re
from collections import defaultdict
from fastapi import APIRouter

router = APIRouter()

VAULT_ROOT = os.path.normpath(os.path.expanduser("~/Documents/Obsidian Vault"))

# Dirs to scan (relative to vault root)
SCAN_DIRS = ["Bookmarks", "Kanban", "Notes", "People", "Research", "TaskLog", "Workspace"]


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
                    edges.append({"from": src_id, "to": resolved})

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
                        edges.append({"from": files[i], "to": files[j], "tag": tag})

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
