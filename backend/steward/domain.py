import difflib
import hashlib
import json
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import COMMANDS


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    payload = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    )
    return hashlib.sha256(payload).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def safe_path(path):
    parts = PurePosixPath(path).parts
    if (
        not parts
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(p in ("..", ".") for p in parts)
    ):
        raise ValueError("Unsafe file path")
    if str(PurePosixPath(path)) != path:
        raise ValueError("Non-canonical file path")
    return path


def source_path(path):
    safe_path(path)
    p = PurePosixPath(path)
    if (
        not path.startswith("src/")
        or p.suffix not in (".ts", ".tsx", ".js", ".jsx")
        or re.search(r"(^|[./_-])(test|tests|spec|__tests__|config)([./_-]|$)", path, re.I)
    ):
        raise ValueError("Only reviewed source files may be repaired")
    return path


def parse_lock(lock):
    if lock.get("lockfileVersion") not in (2, 3) or "" not in lock.get("packages", {}):
        raise ValueError("Only a single npm package-lock v2/v3 is supported")
    root = lock["packages"][""]
    if root.get("workspaces"):
        raise ValueError("Monorepos are outside the prototype scope")
    direct = {**root.get("dependencies", {}), **root.get("devDependencies", {})}
    installed = lock["packages"]

    def resolve(parent, name):
        current = parent
        while True:
            candidate = f"{current}/node_modules/{name}" if current else f"node_modules/{name}"
            if candidate in installed:
                return candidate
            if not current:
                return None
            current = current.rsplit("/node_modules/", 1)[0] if "/node_modules/" in current else ""

    paths = {}
    queue = deque((resolve("", name), [name], name in root.get("devDependencies", {})) for name in direct)
    visited = set()
    while queue:
        path, chain, dev_path = queue.popleft()
        if path is None or (path, chain[0]) in visited or len(chain) > 12:
            continue
        visited.add((path, chain[0]))
        paths.setdefault(path, []).append({"chain": chain, "dev": dev_path})
        pkg = installed[path]
        for name in {**pkg.get("dependencies", {}), **pkg.get("optionalDependencies", {})}:
            queue.append((resolve(path, name), [*chain, name], dev_path))
    result = []
    for path, pkg in lock["packages"].items():
        if not path:
            continue
        if pkg.get("link") or not path.startswith("node_modules/"):
            raise ValueError("Workspace and linked dependencies are unsupported")
        name = path.rsplit("node_modules/", 1)[-1]
        version = pkg.get("version", "")
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", version):
            raise ValueError(f"Unsupported package version: {name}")
        is_direct = name in direct and path == f"node_modules/{name}"
        parent = path.rsplit("/node_modules/", 1)[0] if "/node_modules/" in path else "root (hoisted)"
        result.append(
            {
                "name": name,
                "version": version,
                "path": path,
                "direct": is_direct,
                "dev": all(p["dev"] for p in paths[path]) if paths.get(path) else pkg.get("dev", False),
                "parent": parent,
                "dependency_paths": [" → ".join(p["chain"]) for p in paths.get(path, [])[:4]],
            }
        )
    return result


def severity(advisory):
    scores = []
    for entry in advisory.get("severity", []):
        raw = entry.get("score", "")
        try:
            if raw.startswith("CVSS:4"):
                from cvss import CVSS4

                score = CVSS4(raw).scores()[0]
            elif raw.startswith("CVSS:3"):
                from cvss import CVSS3

                score = CVSS3(raw).scores()[0]
            elif raw.startswith("CVSS:2") or raw.startswith("AV:"):
                from cvss import CVSS2

                score = CVSS2(raw.removeprefix("CVSS:2.0/")).scores()[0]
            else:
                score = float(raw)
            if 0 <= float(score) <= 10:
                scores.append(float(score))
        except Exception:
            # Malformed provider vectors are uncertainty, never a fabricated numeric score.
            continue
    if scores:
        return round(max(scores) * 4), f"CVSS {max(scores):g}"
    label = str(advisory.get("database_specific", {}).get("severity", "unknown")).lower()
    return {"critical": 40, "high": 30, "moderate": 20, "medium": 20, "low": 10}.get(label, 15), label


def priority(advisories, dev, target, novel, complete):
    points, label = max((severity(a) for a in advisories), default=(0, "no known advisory"))
    parts = {
        "severity": points,
        "exposure": 5 if dev else 20,
        "published_target": 20 if target else 0,
        "novelty": 10 if novel else 0,
        "evidence": 10 if complete else 0,
    }
    return min(100, sum(parts.values())), parts, label


class Edit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    before_sha256: str
    new_content: str


class Repair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnosis: str = Field(max_length=4000)
    evidence_ids: list[str] = Field(max_length=30)
    edits: list[Edit] = Field(max_length=5)
    uncertainty: str = Field(max_length=2000)


def validate_repair(raw, files, allowed, evidence_ids):
    repair = Repair.model_validate(raw)
    if not set(repair.evidence_ids).issubset(evidence_ids):
        raise ValueError("Unknown evidence citation")
    if repair.edits and not repair.evidence_ids:
        raise ValueError("A source repair requires evidence citations")
    seen, changed, total = set(), 0, 0
    for edit in repair.edits:
        source_path(edit.path)
        if edit.path not in allowed or edit.path not in files or edit.path in seen:
            raise ValueError("Unapproved or repeated edit path")
        seen.add(edit.path)
        if text_hash(files[edit.path]) != edit.before_sha256:
            raise ValueError("Stale source hash")
        total += len(edit.new_content.encode())
        delta = difflib.ndiff(files[edit.path].splitlines(), edit.new_content.splitlines())
        changed += sum(line.startswith(("+ ", "- ")) for line in delta)
    if changed > 200 or total > 24 * 1024:
        raise ValueError("Repair exceeds the authorized edit budget")
    return repair


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package: str = Field(min_length=1, max_length=200, pattern=r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$")
    target: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


class StartRequest(BaseModel):
    plan_id: str
    plan_hash: str
    publish_draft: Literal[True]


def publication_gate(job, result, current_sha):
    if job["state"] != "publishing":
        raise ValueError("Job is not authorized to publish")
    plan = job["plan"]
    if current_sha != plan["base_sha"]:
        raise ValueError("Default branch moved; authorize a new plan")
    if not result.get("baseline", {}).get("passed") or not result.get("candidate", {}).get("passed"):
        raise ValueError("Baseline and candidate must both pass")
    for stage in ("baseline", "candidate"):
        report = result[stage]
        if set(report.get("commands", {})) != set(COMMANDS):
            raise ValueError("Missing required command evidence")
        if not report.get("installed") or not report.get("test_count", 0):
            raise ValueError("Missing installation or test evidence")
        if any(c.get("exit_code") != 0 for c in report["commands"].values()):
            raise ValueError("A required check failed")
    if result["candidate"]["test_count"] < result["baseline"]["test_count"]:
        raise ValueError("Test count decreased")
    if not result.get("osv_complete") or result.get("new_advisories"):
        raise ValueError("Advisory comparison is incomplete or introduces an advisory")
    changes = result.get("changes", {})
    if not changes or len(changes) > 7:
        raise ValueError("Missing or excessive file changes")
    for path, text in changes.items():
        safe_path(path)
        if path not in ("package.json", "package-lock.json") and path not in plan["allowed_paths"]:
            raise ValueError("Artifact contains an unauthorized file")
        if text_hash(text) != result.get("hashes", {}).get(path):
            raise ValueError("Tested artifact hash mismatch")
    before = json.loads(plan["manifest"])
    after = json.loads(changes.get("package.json", plan["manifest"]))
    expected = json.loads(plan["manifest"])
    expected[plan["dependency_section"]][plan["package"]] = plan["target"]
    if after != expected or before == after:
        raise ValueError("Manifest change differs from the authorized plan")
    lock = json.loads(changes.get("package-lock.json", "{}"))
    parse_lock(lock)
    installed = lock["packages"].get(f"node_modules/{plan['package']}", {}).get("version")
    if (
        installed != plan["target"]
        or lock["packages"][""][plan["dependency_section"]][plan["package"]] != plan["target"]
    ):
        raise ValueError("Lockfile target does not match the plan")
