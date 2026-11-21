"""실행 테스트 셀을 건드리지 않고 정의 이름으로 노트북 또는 AI/beautyflow 모듈 코드를 읽는다."""

import ast
import json
import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# BEAUTYFLOW_USE_MODULE=1 모드에서 로드할 분리 모듈 순서 (위상 정렬)
MODULE_FILES = [
    "AI/beautyflow/config.py",
    "AI/beautyflow/state.py",
    "AI/beautyflow/nodes/document_parser.py",
    "AI/beautyflow/nodes/product_analyzer.py",
    "AI/beautyflow/nodes/script_generator.py",
    "AI/beautyflow/nodes/claim_validator.py",
    "AI/beautyflow/nodes/script_reviser.py",
    "AI/beautyflow/nodes/tts_generator.py",
    "AI/beautyflow/nodes/video_renderer.py",
    "AI/beautyflow/nodes/video_qa.py",
    "AI/beautyflow/graph.py",
]


def _prepare_module_source(source: str) -> str:
    """공유 테스트 네임스페이스 exec 시 내부 import 및 future annotations 줄만 빈 줄로 치환한다."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (
            (node.module or "").startswith("AI.beautyflow") or node.module == "__future__"
        ):
            for ln in range(node.lineno - 1, node.end_lineno):
                lines[ln] = "\n"
    return "".join(lines)


def _use_module_mode() -> bool:
    return os.environ.get("BEAUTYFLOW_USE_MODULE", "").strip().lower() in {"1", "true", "yes"}


@lru_cache(maxsize=2)
def _module_sources() -> list[tuple[str, str]]:
    return [(rel, _prepare_module_source((ROOT / rel).read_text(encoding="utf-8"))) for rel in MODULE_FILES]


@lru_cache(maxsize=2)
def definition_cells():
    if _use_module_mode():
        cells = {}
        for index, (rel, source) in enumerate(_module_sources()):
            for statement in ast.parse(source).body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    cells[statement.name] = (index, source)
        return cells

    rel_path = os.environ.get("BEAUTYFLOW_NOTEBOOK") or "AI/notebooks/MVP.ipynb"
    path = Path(rel_path)
    if not path.is_absolute():
        path = ROOT / path
    notebook = json.loads(path.read_text(encoding="utf-8"))
    cells = {}
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        for statement in ast.parse(source).body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if statement.name in cells:
                    raise ValueError(f"노트북 정의가 중복됐습니다: {statement.name}")
                cells[statement.name] = (index, source)
    return cells


def load_definitions(namespace, *names):
    loaded = set()
    if _use_module_mode():
        # 테스트가 사전에 주입한 모의 객체·경로(PROJECT_ROOT, 모의 노드 함수 등)를 보존
        requested = set(names)
        preexisting = {k: v for k, v in namespace.items() if k not in requested and not k.startswith("__")}
        sources = _module_sources()
        cells = definition_cells()
        needed_max = max((cells[name][0] for name in names), default=1)
        for idx in range(needed_max + 1):
            rel, src = sources[idx]
            if idx not in loaded:
                exec(compile(src, rel, "exec"), namespace)
                loaded.add(idx)
                namespace.update(preexisting)
        return

    rel_path = os.environ.get("BEAUTYFLOW_NOTEBOOK") or "AI/notebooks/MVP.ipynb"
    label = Path(rel_path).name
    for name in names:
        index, source = definition_cells()[name]
        if index not in loaded:
            exec(compile(source, f"{label}:cell-{index}", "exec"), namespace)
            loaded.add(index)
