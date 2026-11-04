"""Reviewed runner helper; stdlib only. This file executes only on an owned GitHub-hosted VM."""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

COMMANDS = ["test:ci", "typecheck", "build"]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def run(args, cwd, timeout=180):
    started = time.monotonic()
    env = {**os.environ, "npm_config_ignore_scripts": "true", "CI": "true"}
    # Scripts never receive the runner's API token or workflow input payloads.
    for key in list(env):
        if any(word in key.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "PLAN_B64", "REPAIR_B64")):
            env.pop(key, None)
    try:
        process = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=timeout)
        code, output = process.returncode, process.stdout + process.stderr
    except subprocess.TimeoutExpired as exc:
        code, output = 124, (exc.stdout or b"") + (exc.stderr or b"") + b"\nCommand timed out."
    return {"exit_code": code, "duration": round(time.monotonic() - started, 3),
            "log": output[-160000:].decode(errors="replace")}


def checks(root):
    manifest = json.loads((root / "package.json").read_text())
    report = {"installed": False, "passed": False, "test_count": 0, "commands": {}}
    if not set(COMMANDS).issubset(manifest.get("scripts", {})):
        report["error"] = "Required scripts are missing"
        return report
    report["install"] = run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], root)
    if report["install"]["exit_code"]:
        return report
    report["installed"] = True
    test_report = root / "steward-tests.json"
    test_report.unlink(missing_ok=True)
    for command in COMMANDS:
        report["commands"][command] = run(["npm", "run", "--ignore-scripts", command], root)
    if test_report.is_file() and not test_report.is_symlink() and test_report.stat().st_size < 1_000_000:
        data = json.loads(test_report.read_text())
        report["test_count"] = data.get("numTotalTests", 0)
        report["failed_tests"] = [
            item.get("fullName", "unknown") for suite in data.get("testResults", [])
            for item in suite.get("assertionResults", []) if item.get("status") == "failed"]
        report["test_report_hash"] = sha(test_report.read_text())
    report["passed"] = (report["test_count"] > 0 and len(report["commands"]) == 3
                        and all(r["exit_code"] == 0 for r in report["commands"].values()))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["baseline", "upgrade", "repair"])
    parser.add_argument("--root", default="work")
    parser.add_argument("--input", default="input/evidence.json")
    parser.add_argument("--output", default="output/evidence.json")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    plan = json.loads(base64.b64decode(os.environ["PLAN_B64"]))
    job_id = os.environ["JOB_ID"]
    if not re.fullmatch(r"[a-f0-9]{24}", job_id) or not re.fullmatch(r"[a-f0-9]{40}", plan["base_sha"]):
        raise ValueError("Invalid job or commit")
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if actual != plan["base_sha"] or plan["commands"] != COMMANDS:
        raise ValueError("Checkout or command profile differs from authorization")
    if subprocess.check_output(["node", "--version"], text=True).strip() != f"v{plan['node']}":
        raise ValueError("Node version differs from authorization")
    if subprocess.check_output(["npm", "--version"], text=True).strip() != plan["npm"]:
        raise ValueError("npm version differs from authorization")
    result = {"job_id": job_id, "plan_hash": plan["hash"], "base_sha": plan["base_sha"],
              "attempt": int(os.environ["ATTEMPT"]), "changes": {}, "hashes": {}, "sources": {}}
    for path in plan["allowed_paths"]:
        candidate = root / path
        if (not path.startswith("src/") or candidate.is_symlink() or not candidate.resolve().is_relative_to(root)
                or not candidate.is_file()):
            raise ValueError("Source path is not an owned regular file")
        text = candidate.read_text()
        if sha(text) != plan["source_hashes"][path]:
            raise ValueError("Source differs from the approved base")
    if args.stage == "baseline":
        result["baseline"] = checks(root)
        result["candidate"] = {}
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as output:
                output.write(f"passed={str(result['baseline']['passed']).lower()}\n")
    else:
        original = json.loads(Path(args.input).read_text())
        if (original["job_id"] != job_id or original["plan_hash"] != plan["hash"]
                or original["base_sha"] != plan["base_sha"] or not original["baseline"]["passed"]):
            raise ValueError("Baseline/candidate artifact correlation failed")
        result["baseline"] = original["baseline"]
        if args.stage == "upgrade":
            manifest_path = root / "package.json"
            manifest = json.loads(manifest_path.read_text())
            manifest[plan["dependency_section"]][plan["package"]] = plan["target"]
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            generated = run(["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], root)
            if generated["exit_code"]:
                result["candidate"] = {"passed": False, "installed": False, "test_count": 0,
                                       "commands": {}, "lock_generation": generated}
            else:
                result["candidate"] = checks(root)
        else:
            payload = json.loads(base64.b64decode(os.environ["REPAIR_B64"]))
            if digest(original) != payload["input_hash"]:
                raise ValueError("Repair input is not the exact first candidate")
            result["input_hash"] = payload["input_hash"]
            for path, text in original["changes"].items():
                if path not in ["package.json", "package-lock.json", *plan["allowed_paths"]]:
                    raise ValueError("Candidate artifact has an unauthorized file")
                if sha(text) != original["hashes"][path]:
                    raise ValueError("Candidate hash mismatch")
                (root / path).write_text(text)
            for edit in payload["repair"]["edits"]:
                if edit["path"] not in plan["allowed_paths"]:
                    raise ValueError("Source edit is not allowed")
                target = root / edit["path"]
                if sha(target.read_text()) != edit["before_sha256"]:
                    raise ValueError("Repair source hash mismatch")
                target.write_text(edit["new_content"])
            result["candidate"] = checks(root)
        changes = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=root, text=True).splitlines()
        for path in changes:
            if path not in ["package.json", "package-lock.json", *plan["allowed_paths"]]:
                raise ValueError("Execution changed a test, workflow or unauthorized file")
            file = root / path
            if file.is_symlink() or not file.is_file():
                raise ValueError("Changed files must be regular files")
            text = file.read_text()
            result["changes"][path], result["hashes"][path] = text, sha(text)
        for path in plan["allowed_paths"]:
            result["sources"][path] = (root / path).read_text()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(result, indent=2)
    if len(raw.encode()) > 900000:
        raise ValueError("Evidence exceeds its storage limit")
    output.write_text(raw)


if __name__ == "__main__":
    main()
