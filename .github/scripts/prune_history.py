#!/usr/bin/env python3
"""Recria o branch sem frames já publicados, sem baixar os blobs das imagens."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class SafetyError(RuntimeError):
    """Falha de validação que deve impedir qualquer reescrita."""


@dataclass(frozen=True)
class PrunePlan:
    total_manifest: int
    next_index: int
    current_frames: frozenset[str]
    future_frames: frozenset[str]
    removable_frames: tuple[str, ...]


def git(*args: str, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} falhou: {stderr}")
    return result.stdout.decode("utf-8", errors="surrogateescape").strip()


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyError(f"não foi possível ler JSON válido de {path}: {exc}") from exc


def manifest_files(manifest: object) -> list[str]:
    if not isinstance(manifest, list) or not manifest:
        raise SafetyError("manifesto vazio ou inválido")

    files: list[str] = []
    for position, item in enumerate(manifest):
        if not isinstance(item, dict):
            raise SafetyError(f"item {position} do manifesto não é um objeto")
        if item.get("index") != position:
            raise SafetyError(f"índice inconsistente no item {position}")
        file = item.get("file")
        if not isinstance(file, str) or not file.startswith("frames/"):
            raise SafetyError(f"caminho inválido no item {position}: {file!r}")
        path = Path(file)
        if path.is_absolute() or ".." in path.parts:
            raise SafetyError(f"caminho inseguro no item {position}: {file!r}")
        files.append(file)

    if len(files) != len(set(files)):
        raise SafetyError("o manifesto contém caminhos duplicados")
    return files


def read_next_index(state: object, label: str) -> int:
    if not isinstance(state, dict):
        raise SafetyError(f"{label} não é um objeto")
    value = state.get("next_index")
    if not isinstance(value, int) or isinstance(value, bool):
        raise SafetyError(f"next_index inválido em {label}: {value!r}")
    return value


def current_frame_paths() -> frozenset[str]:
    raw = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", "frames"],
        capture_output=True,
        check=True,
    ).stdout
    return frozenset(
        entry.decode("utf-8", errors="surrogateescape")
        for entry in raw.split(b"\0")
        if entry
    )


def build_plan(
    manifest: object,
    cutoff_state: object,
    latest_state: object,
    current_frames: frozenset[str],
) -> PrunePlan:
    files = manifest_files(manifest)
    cutoff_index = read_next_index(cutoff_state, "estado do corte")
    latest_index = read_next_index(latest_state, "estado atual")

    if not 0 <= cutoff_index <= latest_index <= len(files):
        raise SafetyError(
            "índices fora de ordem ou do manifesto: "
            f"corte={cutoff_index}, atual={latest_index}, total={len(files)}"
        )

    future = frozenset(files[cutoff_index:])
    missing_future = sorted(future - current_frames)
    if missing_future:
        preview = ", ".join(missing_future[:5])
        raise SafetyError(
            f"ABORTADO: {len(missing_future)} frames futuros estão ausentes; "
            f"primeiros: {preview}"
        )

    removable = tuple(sorted(current_frames - future))
    return PrunePlan(
        total_manifest=len(files),
        next_index=cutoff_index,
        current_frames=current_frames,
        future_frames=future,
        removable_frames=removable,
    )


def rewrite_as_root(plan: PrunePlan, cutoff: str) -> str | None:
    if not plan.removable_frames:
        return None

    expected_head = os.environ.get("EXPECTED_HEAD")
    actual_head = git("rev-parse", "HEAD")
    if not expected_head or actual_head != expected_head:
        raise SafetyError(
            f"HEAD mudou ou não foi informado: esperado={expected_head!r}, atual={actual_head}"
        )

    git("read-tree", "HEAD")
    payload = b"\0".join(
        path.encode("utf-8", errors="surrogateescape")
        for path in plan.removable_frames
    ) + b"\0"
    git("update-index", "--force-remove", "-z", "--stdin", input_bytes=payload)

    # Os blobs dos frames são promisor objects no clone parcial. --missing-ok
    # permite montar a nova árvore usando seus IDs sem baixar as imagens.
    new_tree = git("write-tree", "--missing-ok")
    old_tree = git("rev-parse", "HEAD^{tree}")
    if new_tree == old_tree:
        return None

    message = (
        f"cleanup: remove frames publicados até {cutoff}\n\n"
        f"Frames removidos: {len(plan.removable_frames)}\n"
        f"Próximo índice no corte: {plan.next_index}\n"
    )
    new_commit = git("commit-tree", new_tree, input_bytes=message.encode("utf-8"))
    if git("rev-list", "--parents", "-n", "1", new_commit).count(" ") != 0:
        raise SafetyError("o commit de limpeza deveria ser um novo commit raiz")
    return new_commit


def append_summary(plan: PrunePlan, cutoff: str, execute: bool, new_commit: str | None):
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destination:
        return
    examples = list(plan.removable_frames[:3]) + list(plan.removable_frames[-3:])
    lines = [
        "## Limpeza de frames",
        "",
        f"- Corte: `{cutoff}`",
        f"- Índice no corte: `{plan.next_index}`",
        f"- Frames atuais: `{len(plan.current_frames)}`",
        f"- Frames preservados: `{len(plan.future_frames)}`",
        f"- Frames removíveis: `{len(plan.removable_frames)}`",
        f"- Modo: `{'execute' if execute else 'dry-run'}`",
        f"- Novo commit raiz: `{new_commit or 'nenhum'}`",
        "",
        "Amostra dos caminhos removíveis:",
        "```",
        *examples,
        "```",
    ]
    with Path(destination).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def set_output(name: str, value: str):
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cutoff-state", type=Path, required=True)
    parser.add_argument("--latest-state", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan = build_plan(
            load_json(args.manifest),
            load_json(args.cutoff_state),
            load_json(args.latest_state),
            current_frame_paths(),
        )
        print(
            f"corte={args.cutoff} next_index={plan.next_index} "
            f"atuais={len(plan.current_frames)} preservar={len(plan.future_frames)} "
            f"remover={len(plan.removable_frames)} modo={'execute' if args.execute else 'dry-run'}"
        )
        new_commit = rewrite_as_root(plan, args.cutoff) if args.execute else None
        append_summary(plan, args.cutoff, args.execute, new_commit)
        set_output("new_commit", new_commit or "")
        set_output("removed_count", str(len(plan.removable_frames)))
        return 0
    except (SafetyError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERRO DE SEGURANÇA: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
