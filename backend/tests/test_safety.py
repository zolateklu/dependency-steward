import io
import json
import stat
import zipfile
from copy import deepcopy

import pytest

from steward.domain import parse_lock, publication_gate, severity, source_path, text_hash, validate_repair
from steward.providers import decode_artifact
from steward.store import Conflict


@pytest.mark.parametrize(
    "path",
    [
        "../src/a.ts",
        "/src/a.ts",
        "src/a.test.ts",
        "src/__tests__/a.ts",
        "src/config.ts",
        ".github/workflows/run.yml",
        "package.json",
        "src/../../a.ts",
        "src\\a.ts",
    ],
)
def test_repair_path_denied(path):
    with pytest.raises(ValueError):
        source_path(path)


def test_repair_requires_current_hash_and_known_evidence():
    files = {"src/a.ts": "old"}
    raw = {
        "diagnosis": "API changed",
        "evidence_ids": ["diagnostic"],
        "uncertainty": "",
        "edits": [{"path": "src/a.ts", "before_sha256": text_hash("old"), "new_content": "new"}],
    }
    assert validate_repair(raw, files, list(files), {"diagnostic"}).edits[0].new_content == "new"
    with pytest.raises(ValueError, match="Unknown evidence"):
        validate_repair(raw, files, list(files), set())
    raw["edits"][0]["before_sha256"] = "bad"
    with pytest.raises(ValueError, match="Stale source"):
        validate_repair(raw, files, list(files), {"diagnostic"})


def test_repair_size_limit():
    raw = {
        "diagnosis": "API changed",
        "evidence_ids": ["d"],
        "uncertainty": "",
        "edits": [{"path": "src/a.ts", "before_sha256": text_hash("old"), "new_content": "x" * 25000}],
    }
    with pytest.raises(ValueError, match="budget"):
        validate_repair(raw, {"src/a.ts": "old"}, ["src/a.ts"], {"d"})


def test_lockfile_rejects_workspaces_and_unsupported_versions(plan):
    lock = json.loads(plan["lock"])
    assert parse_lock(lock)[0]["direct"]
    lock["packages"][""]["workspaces"] = ["apps/*"]
    with pytest.raises(ValueError, match="Monorepos"):
        parse_lock(lock)
    with pytest.raises(ValueError):
        parse_lock({"lockfileVersion": 1})


def test_hoisted_dependency_paths_preserve_production_exposure():
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"app-lib": "1.0.0"}, "devDependencies": {"tool": "1.0.0"}},
            "node_modules/app-lib": {"version": "1.0.0", "dependencies": {"shared": "1.0.0"}},
            "node_modules/tool": {"version": "1.0.0", "dependencies": {"shared": "1.0.0"}, "dev": True},
            "node_modules/shared": {"version": "1.0.0"},
        },
    }
    shared = next(p for p in parse_lock(lock) if p["name"] == "shared")
    assert shared["direct"] is False
    assert shared["dev"] is False
    assert set(shared["dependency_paths"]) == {"app-lib → shared", "tool → shared"}


def test_cvss_vector_is_parsed_and_missing_severity_is_unknown():
    points, _ = severity({"severity": [{"score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]})
    assert points == 39
    assert severity({}) == (15, "unknown")


def test_publication_passes_only_exact_tested_artifact(plan, result):
    publication_gate({"state": "publishing", "plan": plan}, result, plan["base_sha"])
    for mutation in (
        "missing_command",
        "decreased_tests",
        "modified_tests",
        "tampered_hash",
        "new_advisory",
        "incomplete_osv",
        "failed_check",
        "wrong_target",
    ):
        bad = deepcopy(result)
        if mutation == "missing_command":
            bad["candidate"]["commands"].pop("build")
        elif mutation == "decreased_tests":
            bad["candidate"]["test_count"] = 3
        elif mutation == "modified_tests":
            bad["changes"]["src/schema.test.ts"] = "skip all"
        elif mutation == "tampered_hash":
            bad["changes"]["package.json"] += " "
        elif mutation == "new_advisory":
            bad["new_advisories"] = ["GHSA-new"]
        elif mutation == "incomplete_osv":
            bad["osv_complete"] = False
        elif mutation == "failed_check":
            bad["candidate"]["commands"]["build"]["exit_code"] = 1
        elif mutation == "wrong_target":
            manifest = json.loads(bad["changes"]["package.json"])
            manifest["dependencies"]["zod"] = "4.0.0"
            bad["changes"]["package.json"] = json.dumps(manifest)
            bad["hashes"]["package.json"] = text_hash(bad["changes"]["package.json"])
        with pytest.raises(ValueError):
            publication_gate({"state": "publishing", "plan": plan}, bad, plan["base_sha"])
    with pytest.raises(ValueError, match="moved"):
        publication_gate({"state": "publishing", "plan": plan}, result, "c" * 40)
    with pytest.raises(ValueError, match="not authorized"):
        publication_gate({"state": "cancelled", "plan": plan}, result, plan["base_sha"])


@pytest.mark.parametrize("kind", ["traversal", "symlink", "duplicate", "unexpected"])
def test_unsafe_archive_is_rejected(kind):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        if kind == "traversal":
            archive.writestr("../evidence.json", "{}")
        elif kind == "symlink":
            item = zipfile.ZipInfo("evidence.json")
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(item, "/etc/passwd")
        elif kind == "duplicate":
            archive.writestr("evidence.json", "{}")
            with pytest.warns(UserWarning):
                archive.writestr("evidence.json", "{}")
        else:
            archive.writestr("surprise.txt", "data")
    with pytest.raises(ValueError):
        decode_artifact(out.getvalue())


def test_store_cas_prevents_lost_updates(service):
    rev = service.store.put("test", 0, {"value": 1})
    service.store.put("test", rev, {"value": 2})
    with pytest.raises(Conflict):
        service.store.put("test", rev, {"value": 3})
    assert service.store.get("test")[1]["value"] == 2
