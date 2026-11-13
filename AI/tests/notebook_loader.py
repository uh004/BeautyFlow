"""실행 테스트 셀을 건드리지 않고 정의 이름으로 노트북 코드를 읽는다."""
import ast
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def definition_cells():
    path = ROOT / 'AI/notebooks/MVP.ipynb'
    notebook = json.loads(path.read_text(encoding='utf-8'))
    cells = {}
    for index, cell in enumerate(notebook['cells']):
        if cell['cell_type'] != 'code':
            continue
        source = ''.join(cell['source'])
        for statement in ast.parse(source).body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if statement.name in cells:
                    raise ValueError(f'노트북 정의가 중복됐습니다: {statement.name}')
                cells[statement.name] = (index, source)
    return cells


def load_definitions(namespace, *names):
    loaded = set()
    for name in names:
        index, source = definition_cells()[name]
        if index not in loaded:
            exec(compile(source, f'MVP.ipynb:cell-{index}', 'exec'), namespace)
            loaded.add(index)
