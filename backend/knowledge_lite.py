"""Hermes knowledge index — standalone lite version (no hermes_cli dependency).

Copied from hermes_cli/knowledge.py with get_hermes_home replaced.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal envs
    yaml = None


def get_hermes_home() -> Path:
    """Standalone replacement for hermes_constants.get_hermes_home."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()


import os  # noqa: E402 — needed by get_hermes_home


INDEX_VERSION = 1
DEFAULT_INDEX_PATH = Path("knowledge_index.jsonl")
MAX_CONTENT_CHARS = 12000

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([^'\"\s]+)"),
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
]


@dataclass
class KnowledgeItem:
    id: str
    type: str
    title: str
    summary: str
    source_path: str
    entrypoint: str
    project: str | None
    tags: list[str]
    sensitivity: str
    status: str
    updated_at: str
    stale_after: str | None = None


# ── Phase 4: Decision publishing ────────────────────────────────

SHARED_DIR_NAME = "knowledge"  # under hermes_home


def _shared_dir(hermes_home: Path | None = None) -> Path:
    home = (hermes_home or get_hermes_home()).resolve()
    d = home / SHARED_DIR_NAME / "shared"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _decisions_dir(hermes_home: Path | None = None) -> Path:
    d = _shared_dir(hermes_home) / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class Decision:
    id: str
    project: str
    title: str
    author: str
    body: str
    rationale: str
    alternatives: str
    tags: list[str]
    created_at: str
    superseded_by: str | None = None

    def to_frontmatter_md(self) -> str:
        lines = ["---"]
        lines.append(f"id: {self.id}")
        lines.append(f"project: {self.project}")
        lines.append(f"title: {json.dumps(self.title, ensure_ascii=False)}")
        lines.append(f"author: {self.author}")
        lines.append(f"created_at: {self.created_at}")
        tag_str = ", ".join(json.dumps(t, ensure_ascii=False) for t in self.tags)
        lines.append(f"tags: [{tag_str}]")
        if self.superseded_by:
            lines.append(f"superseded_by: {self.superseded_by}")
        lines.append("---")
        lines.append("")
        if self.rationale:
            lines.append("## Rationale")
            lines.append("")
            lines.append(self.rationale)
            lines.append("")
        if self.alternatives:
            lines.append("## Alternatives Considered")
            lines.append("")
            lines.append(self.alternatives)
            lines.append("")
        lines.append("## Decision")
        lines.append("")
        lines.append(self.body)
        lines.append("")
        return "\n".join(lines)


def publish_decision(
    project: str,
    title: str,
    author: str,
    body: str,
    rationale: str = "",
    alternatives: str = "",
    tags: list[str] | None = None,
    hermes_home: Path | None = None,
) -> Path:
    """Write a decision file (append-only, no overwrite)."""
    now = datetime.now(timezone.utc)
    slug = _slug(title)[:60]
    date_prefix = now.strftime("%Y-%m-%d")
    filename = f"{date_prefix}-{slug}.md"

    decisions_dir = _decisions_dir(hermes_home)
    filepath = decisions_dir / filename

    # Collision guard: append numeric suffix if file exists
    counter = 1
    while filepath.exists():
        filepath = decisions_dir / f"{date_prefix}-{slug}-{counter}.md"
        counter += 1

    decision = Decision(
        id=f"decision-{slug}",
        project=project,
        title=title,
        author=author,
        body=body,
        rationale=rationale,
        alternatives=alternatives,
        tags=tags or [],
        created_at=now.replace(microsecond=0).isoformat(),
    )
    filepath.write_text(decision.to_frontmatter_md(), encoding="utf-8")
    return filepath


def load_decisions(
    project: str | None = None,
    author: str | None = None,
    since: str | None = None,
    hermes_home: Path | None = None,
) -> list[Decision]:
    """Load all decisions, optionally filtered."""
    decisions_dir = _decisions_dir(hermes_home)
    if not decisions_dir.exists():
        return []

    results: list[Decision] = []
    for path in sorted(decisions_dir.glob("*.md")):
        dec = _parse_decision_file(path)
        if dec is None:
            continue
        if project and dec.project != project:
            continue
        if author and dec.author != author:
            continue
        if since and dec.created_at < since:
            continue
        results.append(dec)
    return results


def _parse_decision_file(path: Path) -> Decision | None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta, body = _parse_frontmatter(raw)
    if not meta.get("id"):
        return None

    # Split body into rationale / alternatives / decision sections
    rationale, alternatives, decision_body = _split_decision_sections(body)

    return Decision(
        id=str(meta["id"]),
        project=str(meta.get("project", "")),
        title=str(meta.get("title", path.stem)),
        author=str(meta.get("author", "unknown")),
        body=decision_body.strip(),
        rationale=rationale.strip(),
        alternatives=alternatives.strip(),
        tags=_as_list(meta.get("tags")),
        created_at=str(meta.get("created_at", _mtime_iso(path))),
        superseded_by=meta.get("superseded_by"),
    )


def _split_decision_sections(body: str) -> tuple[str, str, str]:
    """Split markdown body into (rationale, alternatives, decision)."""
    rationale_parts: list[str] = []
    alternatives_parts: list[str] = []
    decision_parts: list[str] = []
    current = "decision"

    for line in body.splitlines():
        stripped = line.strip().lower()
        if stripped == "## rationale":
            current = "rationale"
            continue
        elif stripped == "## alternatives considered":
            current = "alternatives"
            continue
        elif stripped == "## decision":
            current = "decision"
            continue

        if current == "rationale":
            rationale_parts.append(line)
        elif current == "alternatives":
            alternatives_parts.append(line)
        else:
            decision_parts.append(line)

    return (
        "\n".join(rationale_parts),
        "\n".join(alternatives_parts),
        "\n".join(decision_parts),
    )


# ── Phase 5: Multi-expert collaboration ─────────────────────────

EXPERT_STALE_SECONDS = 300  # 5 minutes without heartbeat = stale


@dataclass
class Expert:
    id: str
    role: str
    project: str
    capabilities: list[str]
    registered_at: str
    last_heartbeat: str
    status: str  # active | idle | stale | offline


def _experts_dir(hermes_home: Path | None = None) -> Path:
    d = _shared_dir(hermes_home) / "experts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _blackboard_dir(hermes_home: Path | None = None) -> Path:
    d = _shared_dir(hermes_home) / "blackboard"
    d.mkdir(parents=True, exist_ok=True)
    return d


def register_expert(
    expert_id: str,
    role: str,
    project: str,
    capabilities: list[str] | None = None,
    hermes_home: Path | None = None,
) -> Path:
    """Register or re-register an expert instance."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    expert = Expert(
        id=expert_id,
        role=role,
        project=project,
        capabilities=capabilities or [],
        registered_at=now,
        last_heartbeat=now,
        status="active",
    )
    filepath = _experts_dir(hermes_home) / f"{expert_id}.json"
    filepath.write_text(json.dumps(asdict(expert), ensure_ascii=False, indent=2), encoding="utf-8")
    return filepath


def heartbeat_expert(expert_id: str, hermes_home: Path | None = None) -> bool:
    """Update an expert's heartbeat timestamp."""
    filepath = _experts_dir(hermes_home) / f"{expert_id}.json"
    if not filepath.exists():
        return False
    data = json.loads(filepath.read_text(encoding="utf-8"))
    data["last_heartbeat"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data["status"] = "active"
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def deregister_expert(expert_id: str, hermes_home: Path | None = None) -> bool:
    """Mark an expert as offline."""
    filepath = _experts_dir(hermes_home) / f"{expert_id}.json"
    if not filepath.exists():
        return False
    data = json.loads(filepath.read_text(encoding="utf-8"))
    data["status"] = "offline"
    data["last_heartbeat"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def load_experts(
    project: str | None = None,
    role: str | None = None,
    status: str | None = None,
    hermes_home: Path | None = None,
) -> list[Expert]:
    """Load registered experts, optionally filtered."""
    experts_dir = _experts_dir(hermes_home)
    if not experts_dir.exists():
        return []

    # Auto-mark stale experts
    now = datetime.now(timezone.utc)
    results: list[Expert] = []
    for path in sorted(experts_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        expert = Expert(**data)

        # Check staleness
        if expert.status == "active":
            try:
                last_hb = datetime.fromisoformat(expert.last_heartbeat)
                if (now - last_hb).total_seconds() > EXPERT_STALE_SECONDS:
                    expert.status = "stale"
            except (ValueError, TypeError):
                pass

        if project and expert.project != project:
            continue
        if role and expert.role != role:
            continue
        if status and expert.status != status:
            continue
        results.append(expert)
    return results


def post_to_blackboard(
    expert_id: str,
    project: str,
    category: str,  # "progress" | "conflict" | "note"
    title: str,
    body: str,
    hermes_home: Path | None = None,
) -> Path:
    """Post a message to the shared blackboard (append-only)."""
    now = datetime.now(timezone.utc)
    slug = _slug(title)[:60]
    date_prefix = now.strftime("%Y-%m-%d")
    filename = f"{date_prefix}-{category}-{slug}.md"

    bb_dir = _blackboard_dir(hermes_home)
    filepath = bb_dir / filename

    counter = 1
    while filepath.exists():
        filepath = bb_dir / f"{date_prefix}-{category}-{slug}-{counter}.md"
        counter += 1

    lines = [
        "---",
        f"author: {expert_id}",
        f"project: {project}",
        f"category: {category}",
        f"created_at: {now.replace(microsecond=0).isoformat()}",
        "---",
        "",
        f"# {title}",
        "",
        body,
        "",
    ]
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


def load_blackboard(
    project: str | None = None,
    category: str | None = None,
    author: str | None = None,
    since: str | None = None,
    hermes_home: Path | None = None,
) -> list[dict]:
    """Load blackboard entries."""
    bb_dir = _blackboard_dir(hermes_home)
    if not bb_dir.exists():
        return []

    results: list[dict] = []
    for path in sorted(bb_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8", errors="replace")
        meta, body = _parse_frontmatter(raw)
        if not meta:
            continue

        entry = {
            "path": str(path),
            "filename": path.name,
            "author": meta.get("author", "unknown"),
            "project": meta.get("project", ""),
            "category": meta.get("category", ""),
            "created_at": meta.get("created_at", ""),
            "title": body.strip().split("\n", 1)[0].lstrip("# ").strip() if body.strip() else path.stem,
            "body": body.strip(),
        }

        if project and entry["project"] != project:
            continue
        if category and entry["category"] != category:
            continue
        if author and entry["author"] != author:
            continue
        if since and entry["created_at"] < since:
            continue
        results.append(entry)
    return results


def generate_context_report(
    project: str,
    role: str | None = None,
    include_private: bool = False,
    limit: int = 20,
    hermes_home: Path | None = None,
) -> str:
    """Generate a single-text context report for an expert to consume on startup."""
    home = (hermes_home or get_hermes_home()).resolve()
    parts: list[str] = []

    # 1. Active experts
    experts = load_experts(project=project, hermes_home=home)
    if experts:
        active = [e for e in experts if e.status in ("active", "idle")]
        if active:
            parts.append("## Active Experts")
            parts.append("")
            for e in active:
                caps = f" [{', '.join(e.capabilities)}]" if e.capabilities else ""
                parts.append(f"- **{e.id}** ({e.role}){caps} — last seen {e.last_heartbeat}")
            parts.append("")

    # 2. Recent decisions
    decisions = load_decisions(project=project, hermes_home=home)
    if decisions:
        parts.append("## Decisions")
        parts.append("")
        for d in decisions[-5:]:  # Last 5 decisions
            parts.append(f"### {d.title}")
            parts.append(f"by {d.author} at {d.created_at}")
            parts.append("")
            parts.append(d.body[:500])
            if d.superseded_by:
                parts.append(f"*Superseded by: {d.superseded_by}*")
            parts.append("")

    # 3. Knowledge index (compressed)
    repo_root = Path.cwd()
    items = build_index(repo_root, home)
    project_items = search_items(
        items, "", project=project, include_private=include_private, limit=limit,
    )
    if project_items:
        parts.append("## Knowledge Assets")
        parts.append("")
        for item in project_items[:10]:
            parts.append(f"- **{item.title}** ({item.type}/{item.sensitivity})")
            parts.append(f"  {item.summary}")
        parts.append("")

    # 4. Recent blackboard
    bb_entries = load_blackboard(project=project, hermes_home=home)
    if bb_entries:
        parts.append("## Blackboard")
        parts.append("")
        for entry in bb_entries[-5:]:
            parts.append(f"### {entry['title']}")
            parts.append(f"by {entry['author']} [{entry['category']}]")
            parts.append("")
            parts.append(entry["body"][:300])
            parts.append("")

    return "\n".join(parts) if parts else "No context available for this project."


def redact_secrets(text: str) -> str:
    """Redact common inline secret formats from text."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.pattern.startswith("(?i)(api"):
            redacted = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
        elif pattern.pattern.startswith("(?i)(bearer"):
            redacted = pattern.sub(lambda m: f"{m.group(1)}[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def build_index(
    repo_root: Path | None = None,
    hermes_home: Path | None = None,
) -> list[KnowledgeItem]:
    """Build an in-memory read-only index of known Hermes assets."""
    root = (repo_root or Path.cwd()).resolve()
    home = (hermes_home or get_hermes_home()).resolve()
    items: list[KnowledgeItem] = []
    seen: set[str] = set()

    for base, source_type in (
        (root / "skills", "skill"),
        (root / "optional-skills", "optional_skill"),
        (home / "skills", "user_skill"),
    ):
        for skill_path in sorted(base.glob("**/SKILL.md")):
            item = _skill_item(skill_path, root, home, source_type)
            if item.id not in seen:
                items.append(item)
                seen.add(item.id)

    memories_dir = home / "memories"
    registry = memories_dir / "MEMORY.md"
    if registry.exists():
        item = _text_item(
            registry,
            root,
            home,
            item_id="memory-registry",
            item_type="memory",
            title="Hermes Memory Registry",
            sensitivity="private",
            project=None,
            tags=["memory", "registry"],
            summary="Searchable registry of Hermes memory topics. Content is private by default.",
        )
        items.append(item)

    for note_path in sorted((memories_dir / "rollout_summaries").glob("*.md")):
        item = _rollout_item(note_path, root, home)
        if item.id not in seen:
            items.append(item)
            seen.add(item.id)

    return items


def write_index(items: Iterable[KnowledgeItem], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for item in items:
            row = asdict(item)
            row["index_version"] = INDEX_VERSION
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_index(index_path: Path) -> list[KnowledgeItem]:
    items: list[KnowledgeItem] = []
    with index_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            data = json.loads(line)
            data.pop("index_version", None)
            items.append(KnowledgeItem(**data))
    return items


def search_items(
    items: Iterable[KnowledgeItem],
    query: str,
    scope: str | None = None,
    project: str | None = None,
    include_private: bool = False,
    limit: int = 10,
) -> list[KnowledgeItem]:
    terms = [t.lower() for t in query.split() if t.strip()]
    scored: list[tuple[int, KnowledgeItem]] = []
    for item in items:
        if not _visible(item, include_private):
            continue
        if scope and item.type != scope:
            continue
        if project and (item.project or "").lower() != project.lower():
            continue
        haystack = " ".join(
            [
                item.id,
                item.type,
                item.title,
                item.summary,
                item.project or "",
                " ".join(item.tags),
            ]
        ).lower()
        score = sum(1 for term in terms if term in haystack)
        if terms and score == 0:
            continue
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return [item for _, item in scored[:limit]]


def get_item(
    items: Iterable[KnowledgeItem],
    item_id: str,
    include_private: bool = False,
) -> KnowledgeItem | None:
    for item in items:
        if item.id == item_id and _visible(item, include_private):
            return item
    return None


def read_item_content(item: KnowledgeItem, include_private: bool = False) -> str:
    if not _visible(item, include_private):
        raise PermissionError(f"{item.id} is {item.sensitivity}")
    if item.sensitivity == "secret":
        raise PermissionError(f"{item.id} is secret")
    path = Path(item.source_path)
    content = path.read_text(encoding="utf-8", errors="replace")
    return redact_secrets(content[:MAX_CONTENT_CHARS])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes_knowledge")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--hermes-home", type=Path, default=get_hermes_home())
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build", help="Build a read-only knowledge index")
    build_p.add_argument("--output", type=Path)

    search_p = sub.add_parser("search", help="Search the knowledge index")
    search_p.add_argument("query")
    search_p.add_argument("--scope")
    search_p.add_argument("--project")
    search_p.add_argument("--include-private", action="store_true")
    search_p.add_argument("--limit", type=int, default=10)
    search_p.add_argument("--json", action="store_true")

    get_p = sub.add_parser("get", help="Get one knowledge item")
    get_p.add_argument("id")
    get_p.add_argument("--include-private", action="store_true")
    get_p.add_argument("--content", action="store_true")
    get_p.add_argument("--json", action="store_true")

    context_p = sub.add_parser("context", help="Get project-scoped context")
    context_p.add_argument("--project", required=True)
    context_p.add_argument("--include-private", action="store_true")
    context_p.add_argument("--limit", type=int, default=20)
    context_p.add_argument("--json", action="store_true")

    # Phase 4: publish
    pub_p = sub.add_parser("publish", help="Publish a decision for other experts")
    pub_p.add_argument("--project", required=True)
    pub_p.add_argument("--title", required=True)
    pub_p.add_argument("--author", required=True)
    pub_p.add_argument("--body", required=True)
    pub_p.add_argument("--rationale", default="")
    pub_p.add_argument("--alternatives", default="")
    pub_p.add_argument("--tags", nargs="*", default=[])

    # Phase 4: decisions
    dec_p = sub.add_parser("decisions", help="List published decisions")
    dec_p.add_argument("--project", default=None)
    dec_p.add_argument("--author", default=None)
    dec_p.add_argument("--since", default=None, help="ISO datetime filter")
    dec_p.add_argument("--json", action="store_true")

    # Phase 5: expert management
    reg_p = sub.add_parser("register", help="Register an expert instance")
    reg_p.add_argument("--expert-id", required=True)
    reg_p.add_argument("--role", required=True)
    reg_p.add_argument("--project", required=True)
    reg_p.add_argument("--capabilities", nargs="*", default=[])

    hb_p = sub.add_parser("heartbeat", help="Send expert heartbeat")
    hb_p.add_argument("--expert-id", required=True)

    dereq_p = sub.add_parser("deregister", help="Mark expert as offline")
    dereq_p.add_argument("--expert-id", required=True)

    stat_p = sub.add_parser("status", help="Show expert status")
    stat_p.add_argument("--project", default=None)
    stat_p.add_argument("--role", default=None)
    stat_p.add_argument("--json", action="store_true")

    # Phase 5: blackboard
    bb_p = sub.add_parser("blackboard", help="Post to or read the shared blackboard")
    bb_sub = bb_p.add_subparsers(dest="bb_action")
    bb_post = bb_sub.add_parser("post", help="Post a message")
    bb_post.add_argument("--expert-id", required=True)
    bb_post.add_argument("--project", required=True)
    bb_post.add_argument("--category", required=True, choices=["progress", "conflict", "note"])
    bb_post.add_argument("--title", required=True)
    bb_post.add_argument("--body", required=True)
    bb_read = bb_sub.add_parser("read", help="Read blackboard entries")
    bb_read.add_argument("--project", default=None)
    bb_read.add_argument("--category", default=None)
    bb_read.add_argument("--author", default=None)
    bb_read.add_argument("--limit", type=int, default=10)

    # Phase 5: context report (enhanced)
    report_p = sub.add_parser("report", help="Generate full context report for expert startup")
    report_p.add_argument("--project", required=True)
    report_p.add_argument("--role", default=None)
    report_p.add_argument("--include-private", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "build":
        output = args.output or args.index
        items = build_index(args.repo_root, args.hermes_home)
        write_index(items, output)
        print(f"Wrote {len(items)} items to {output}")
        return 0

    items = _load_or_build(args.index, args.repo_root, args.hermes_home)
    if args.command == "search":
        results = search_items(
            items,
            args.query,
            scope=args.scope,
            project=args.project,
            include_private=args.include_private,
            limit=args.limit,
        )
        _print_items(results, as_json=args.json)
        return 0

    if args.command == "get":
        item = get_item(items, args.id, include_private=args.include_private)
        if item is None:
            print(f"Not found or not visible: {args.id}")
            return 1
        if args.content:
            print(read_item_content(item, include_private=args.include_private))
        elif args.json:
            print(json.dumps(asdict(item), ensure_ascii=False, sort_keys=True))
        else:
            _print_items([item], as_json=False)
        return 0

    if args.command == "context":
        results = search_items(
            items,
            "",
            project=args.project,
            include_private=args.include_private,
            limit=args.limit,
        )
        _print_items(results, as_json=args.json)
        return 0

    # Phase 4: publish
    if args.command == "publish":
        filepath = publish_decision(
            project=args.project,
            title=args.title,
            author=args.author,
            body=args.body,
            rationale=args.rationale,
            alternatives=args.alternatives,
            tags=args.tags,
            hermes_home=args.hermes_home,
        )
        print(f"Published: {filepath.name}")
        return 0

    # Phase 4: decisions
    if args.command == "decisions":
        decisions = load_decisions(
            project=args.project,
            author=args.author,
            since=args.since,
            hermes_home=args.hermes_home,
        )
        if args.json:
            for d in decisions:
                print(json.dumps(asdict(d), ensure_ascii=False, sort_keys=True))
        else:
            if not decisions:
                print("No decisions found.")
            for d in decisions:
                superseded = f" (superseded by {d.superseded_by})" if d.superseded_by else ""
                print(f"[{d.created_at}] {d.id} by {d.author}{superseded}")
                print(f"  {d.title}")
                if d.tags:
                    print(f"  tags: {', '.join(d.tags)}")
                print()
        return 0

    # Phase 5: register
    if args.command == "register":
        filepath = register_expert(
            expert_id=args.expert_id,
            role=args.role,
            project=args.project,
            capabilities=args.capabilities,
            hermes_home=args.hermes_home,
        )
        print(f"Registered: {args.expert_id} as {args.role}")
        return 0

    # Phase 5: heartbeat
    if args.command == "heartbeat":
        if heartbeat_expert(args.expert_id, hermes_home=args.hermes_home):
            print(f"Heartbeat: {args.expert_id}")
            return 0
        print(f"Expert not found: {args.expert_id}")
        return 1

    # Phase 5: deregister
    if args.command == "deregister":
        if deregister_expert(args.expert_id, hermes_home=args.hermes_home):
            print(f"Offline: {args.expert_id}")
            return 0
        print(f"Expert not found: {args.expert_id}")
        return 1

    # Phase 5: status
    if args.command == "status":
        experts = load_experts(
            project=args.project,
            role=args.role,
            hermes_home=args.hermes_home,
        )
        if args.json:
            for e in experts:
                print(json.dumps(asdict(e), ensure_ascii=False, sort_keys=True))
        else:
            if not experts:
                print("No experts registered.")
            for e in experts:
                caps = f" [{', '.join(e.capabilities)}]" if e.capabilities else ""
                print(f"{e.id}  role={e.role}  status={e.status}  project={e.project}{caps}")
                print(f"  registered: {e.registered_at}  last heartbeat: {e.last_heartbeat}")
        return 0

    # Phase 5: blackboard
    if args.command == "blackboard":
        if args.bb_action == "post":
            filepath = post_to_blackboard(
                expert_id=args.expert_id,
                project=args.project,
                category=args.category,
                title=args.title,
                body=args.body,
                hermes_home=args.hermes_home,
            )
            print(f"Posted: {filepath.name}")
            return 0
        elif args.bb_action == "read":
            entries = load_blackboard(
                project=args.project,
                category=args.category,
                author=args.author,
                hermes_home=args.hermes_home,
            )
            entries = entries[-args.limit:]
            if not entries:
                print("No blackboard entries found.")
            for entry in entries:
                print(f"[{entry['created_at']}] {entry['title']}")
                print(f"  by {entry['author']} [{entry['category']}]")
                print()
            return 0
        else:
            print("Usage: blackboard post|read ...")
            return 1

    # Phase 5: report
    if args.command == "report":
        report = generate_context_report(
            project=args.project,
            role=args.role,
            include_private=args.include_private,
            hermes_home=args.hermes_home,
        )
        print(report)
        return 0

    return 1


def _load_or_build(index_path: Path, repo_root: Path, hermes_home: Path) -> list[KnowledgeItem]:
    if index_path.exists():
        return load_index(index_path)
    return build_index(repo_root, hermes_home)


def _print_items(items: Iterable[KnowledgeItem], as_json: bool) -> None:
    if as_json:
        for item in items:
            print(json.dumps(asdict(item), ensure_ascii=False, sort_keys=True))
        return
    for item in items:
        project = f" project={item.project}" if item.project else ""
        print(f"{item.id} [{item.type}/{item.sensitivity}{project}]")
        print(f"  {item.title}")
        print(f"  {item.summary}")


def _visible(item: KnowledgeItem, include_private: bool) -> bool:
    if item.sensitivity == "secret":
        return False
    if item.sensitivity == "private" and not include_private:
        return False
    return True


def _skill_item(path: Path, repo_root: Path, hermes_home: Path, source_type: str) -> KnowledgeItem:
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta, body = _parse_frontmatter(raw)
    hermes_meta = (meta.get("metadata") or {}).get("hermes") or {}
    name = str(meta.get("name") or path.parent.name)
    title = _title_from_name(name)
    summary = str(meta.get("description") or _first_sentence(body) or f"Hermes skill: {title}")
    tags = _as_list(hermes_meta.get("tags"))
    if not tags:
        tags = _path_tags(path, repo_root, hermes_home)
    project = _infer_project(path, repo_root, hermes_home, tags)
    sensitivity = str(hermes_meta.get("sensitivity") or "internal")
    updated_at = _mtime_iso(path)
    return KnowledgeItem(
        id=_stable_id(source_type, path, repo_root, hermes_home),
        type=source_type,
        title=title,
        summary=summary,
        source_path=str(path.resolve()),
        entrypoint=str(path.name),
        project=project,
        tags=tags,
        sensitivity=sensitivity,
        status=str(meta.get("status") or "active"),
        updated_at=updated_at,
    )


def _rollout_item(path: Path, repo_root: Path, hermes_home: Path) -> KnowledgeItem:
    stem = path.stem
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-", "", stem)
    tags = [part for part in re.split(r"[-_]+", slug.lower()) if len(part) > 2][:12]
    return _text_item(
        path,
        repo_root,
        hermes_home,
        item_id=f"rollout-{_slug(slug)[:80]}",
        item_type="rollout_summary",
        title=_title_from_name(slug),
        sensitivity="private",
        project=_project_from_tags(tags),
        tags=["rollout"] + tags,
        summary=_summary_from_file(path),
    )


def _text_item(
    path: Path,
    repo_root: Path,
    hermes_home: Path,
    item_id: str,
    item_type: str,
    title: str,
    sensitivity: str,
    project: str | None,
    tags: list[str],
    summary: str,
) -> KnowledgeItem:
    return KnowledgeItem(
        id=item_id,
        type=item_type,
        title=title,
        summary=summary,
        source_path=str(path.resolve()),
        entrypoint=path.name,
        project=project,
        tags=tags,
        sensitivity=sensitivity,
        status="active",
        updated_at=_mtime_iso(path),
    )


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    frontmatter = text[4:end]
    body = text[end + 4 :]
    if yaml is None:
        return _parse_simple_frontmatter(frontmatter), body
    parsed = yaml.safe_load(frontmatter) or {}
    return parsed if isinstance(parsed, dict) else {}, body


def _parse_simple_frontmatter(frontmatter: str) -> dict:
    parsed: dict[str, object] = {}
    for line in frontmatter.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "-")):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip("\"'")
        if value.startswith("[") and value.endswith("]"):
            parsed[key.strip()] = [
                part.strip().strip("\"'")
                for part in value[1:-1].split(",")
                if part.strip()
            ]
        else:
            parsed[key.strip()] = value
    return parsed


def _summary_from_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = redact_secrets(raw)
    for line in raw.splitlines():
        stripped = line.strip(" #\t")
        if stripped:
            return stripped[:240]
    return f"Knowledge note from {path.name}"


def _first_sentence(text: str) -> str:
    cleaned = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if not cleaned:
        return ""
    return re.split(r"(?<=[.!?。！？])\s+", cleaned, maxsplit=1)[0][:240]


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _stable_id(source_type: str, path: Path, repo_root: Path, hermes_home: Path) -> str:
    rel = _relative_id_path(path.parent, repo_root, hermes_home)
    return _slug(f"{source_type}-{rel}")


def _relative_id_path(path: Path, repo_root: Path, hermes_home: Path) -> str:
    for base in (repo_root, hermes_home):
        try:
            return str(path.resolve().relative_to(base.resolve()))
        except ValueError:
            continue
    return path.name


def _path_tags(path: Path, repo_root: Path, hermes_home: Path) -> list[str]:
    rel = _relative_id_path(path.parent, repo_root, hermes_home)
    return [part.lower() for part in Path(rel).parts if part not in (".", "skills")]


def _infer_project(
    path: Path,
    repo_root: Path,
    hermes_home: Path,
    tags: list[str],
) -> str | None:
    rel = _relative_id_path(path, repo_root, hermes_home)
    parts = Path(rel).parts
    if parts and parts[0] in {"skills", "optional-skills"} and len(parts) > 1:
        return parts[1]
    return _project_from_tags(tags)


def _project_from_tags(tags: list[str]) -> str | None:
    known = {
        "hermes",
        "gateway",
        "article-worker",
        "trendradar",
        "discipline",
        "kimi",
        "codex",
    }
    for tag in tags:
        if tag.lower() in known:
            return tag.lower()
    return None


def _title_from_name(name: str) -> str:
    return re.sub(r"[-_]+", " ", name).strip().title()


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower())
    return re.sub(r"-+", "-", slug).strip("-") or "item"


def _mtime_iso(path: Path) -> str:
    dt = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return dt.replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
