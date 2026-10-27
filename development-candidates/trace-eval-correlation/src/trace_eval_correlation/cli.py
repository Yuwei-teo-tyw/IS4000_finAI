"""Offline index generation and reproduction check.

build  : read the manifest's sources and write a deterministic index + .sha256 sidecar.
verify : rebuild in memory and require byte equality with a previously written index.
schema : write the JSON Schema of the index contract.

No network, provider or cloud client is imported. Output may never be written inside
a bound evidence root, so historical evidence cannot be modified by this tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from trace_eval_correlation.correlate import build_index
from trace_eval_correlation.schema import Manifest, TraceEvalIndex
from trace_eval_correlation.sources import (
    Resolver,
    UnjoinableReference,
    file_sha256,
    sha256_bytes,
)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_INCOMPLETE = 2
EXIT_USAGE = 64


class UsageError(ValueError):
    pass


def render(index: TraceEvalIndex) -> str:
    body = json.dumps(index.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
    return body + "\n"


def load_manifest(path: Path) -> tuple[Manifest, str]:
    try:
        raw = path.read_bytes()
        return Manifest.model_validate_json(raw), sha256_bytes(raw)
    except OSError as exc:
        raise UsageError("manifest unreadable") from exc
    except ValidationError as exc:
        # Report field locations only; input values are hidden.
        locs = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise UsageError(f"manifest invalid at: {', '.join(locs)}") from exc


def bind_roots(manifest: Manifest, manifest_path: Path, overrides: list[str]) -> Resolver:
    roots: dict[str, str | None] = dict(manifest.roots)
    for item in overrides:
        name, sep, bound_to = item.partition("=")
        if not sep or not name:
            raise UsageError("--root expects NAME=PATH")
        roots[name] = bound_to
    bound: dict[str, Path] = {}
    for name, value in roots.items():
        if value is None:
            raise UsageError(f"root {name!r} is unbound; pass --root {name}=PATH")
        path = Path(value)
        bound[name] = path if path.is_absolute() else (manifest_path.parent / path)
    return Resolver(bound)


def generate(manifest_path: Path, overrides: list[str]) -> tuple[TraceEvalIndex, Resolver]:
    manifest, digest = load_manifest(manifest_path)
    resolver = bind_roots(manifest, manifest_path, overrides)
    return build_index(manifest, resolver, digest), resolver


def pin_manifest(manifest_path: Path, overrides: list[str]) -> dict[str, object]:
    """Record the current sha256 of every consumed file as that source's pins."""
    manifest, _ = load_manifest(manifest_path)
    resolver = bind_roots(manifest, manifest_path, overrides)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    for spec, out in zip(manifest.sources, raw["sources"], strict=True):
        consumed = [v for k, v in spec.files.items() if k != "requests_dir"]
        consumed += [spec.evidence_manifest] if spec.evidence_manifest else []
        consumed += spec.prompt_candidates
        pins: dict[str, str] = {}
        for relative in sorted(set(consumed)):
            try:
                digest = file_sha256(resolver.resolve(spec.root, f"{spec.path}/{relative}"))
            except UnjoinableReference as exc:
                raise UsageError(f"cannot pin {spec.source_id}:{relative}: {exc}") from exc
            if digest is None:
                raise UsageError(f"cannot pin missing file {spec.source_id}:{relative}")
            pins[relative] = digest
        out["pins"] = pins
    return dict(raw)


def _refuse_inside_roots(out: Path, resolver: Resolver) -> None:
    target = out.resolve()
    for root in resolver.roots.values():
        if target == root or root in target.parents:
            raise UsageError("refusing to write inside a bound evidence root")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trace_eval_correlation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", type=Path, required=True)
        p.add_argument("--index", type=Path, required=True)
        p.add_argument("--root", action="append", default=[], metavar="NAME=PATH")
    p = sub.add_parser("pin")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--root", action="append", default=[], metavar="NAME=PATH")
    p = sub.add_parser("schema")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "pin":
            pinned = pin_manifest(args.manifest, args.root)
            manifest, _ = load_manifest(args.manifest)
            _refuse_inside_roots(args.out, bind_roots(manifest, args.manifest, args.root))
            args.out.write_text(
                json.dumps(pinned, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            return EXIT_OK
        if args.command == "schema":
            schema = json.dumps(TraceEvalIndex.model_json_schema(), indent=2, sort_keys=True)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(schema + "\n", encoding="utf-8", newline="\n")
            return EXIT_OK
        index, resolver = generate(args.manifest, args.root)
        text = render(index)
        digest = sha256_bytes(text.encode("utf-8"))
        if args.command == "build":
            _refuse_inside_roots(args.index, resolver)
            args.index.parent.mkdir(parents=True, exist_ok=True)
            args.index.write_text(text, encoding="utf-8", newline="\n")
            sidecar = args.index.with_name(args.index.name + ".sha256")
            sidecar.write_text(f"{digest}  {args.index.name}\n", encoding="utf-8", newline="\n")
            print(
                f"{index.index_status} records={len(index.records)} "
                f"findings={len(index.findings)} sha256={digest}"
            )
            return EXIT_OK if index.index_status == "COMPLETE" else EXIT_INCOMPLETE
        try:
            existing = args.index.read_bytes()
        except OSError as exc:
            raise UsageError("index unreadable") from exc
        sidecar = args.index.with_name(args.index.name + ".sha256")
        parts = sidecar.read_text(encoding="utf-8").split() if sidecar.exists() else []
        recorded = parts[0] if parts else None
        same = existing == text.encode("utf-8") and recorded == digest
        print(
            f"{'REPRODUCED' if same else 'NOT_REPRODUCED'} sha256={digest} "
            f"recorded={recorded or 'UNAVAILABLE'}"
        )
        return EXIT_OK if same else EXIT_MISMATCH
    except UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE
