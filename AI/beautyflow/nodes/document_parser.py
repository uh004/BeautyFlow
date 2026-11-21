"""① 문서 분석 노드 (DocumentParser).

로컬 합성 PPTX에서 텍스트·이미지·좌표를 추출하고 슬라이드별 JSON으로 저장한다.
외부 URL이나 이미지가 없는 문서는 즉시 차단한다.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pandas as pd
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from AI.beautyflow.config import PROJECT_ROOT
from AI.beautyflow.state import VideoAgentState

# Windows DLL 차단 대응용 경량 토크나이저 주입 (unstructured import 전 설정)
if "unstructured.nlp.tokenize" not in sys.modules:
    _mock_tokenize = types.ModuleType("unstructured.nlp.tokenize")
    _mock_tokenize.sent_tokenize = lambda text: [s.strip() for s in text.split(".") if s.strip()]
    _mock_tokenize.word_tokenize = lambda text: text.split()
    _mock_tokenize.pos_tag = lambda text: [(w, "NN") for w in text.split()]
    sys.modules["unstructured.nlp.tokenize"] = _mock_tokenize

from unstructured.partition.pptx import partition_pptx


def document_parser(state: VideoAgentState) -> dict:
    """PPTX에서 텍스트·이미지·좌표를 추출해 raw_slides와 JSON을 생성한다."""
    try:
        # 1) 입력 경로 검증 (외부 URL·비지원 확장자 차단)
        file_path = str(state.get("file_path", "")).strip()
        if not file_path or "://" in file_path:
            raise ValueError("로컬 합성 PPTX 파일 경로를 지정하세요.")
        pptx_path = (PROJECT_ROOT / file_path).resolve()
        if not pptx_path.is_file():
            raise FileNotFoundError(f"파일이 없습니다: {pptx_path}")
        if pptx_path.suffix.lower() != ".pptx":
            raise ValueError("현재는 PPTX만 지원합니다. PDF는 아직 미구현입니다.")

        output_dir = (PROJECT_ROOT / (state.get("output_dir") or "output")).resolve()
        image_dir = output_dir / "images" / pptx_path.stem
        prs = Presentation(str(pptx_path))

        # 2) Unstructured 기반 텍스트 요소 분류
        elements = partition_pptx(filename=str(pptx_path))
        parsed_records = [
            {
                "element_type": type(el).__name__,
                "page_number": el.metadata.to_dict().get("page_number", 1),
                "text": el.text.strip(),
            }
            for el in elements
        ]
        if not parsed_records:
            raise ValueError("추출된 텍스트가 없습니다.")
        df_elements = pd.DataFrame(parsed_records)

        # 3) 슬라이드별 이미지 추출 및 원문·EMU 좌표 수집
        if not any(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for slide in prs.slides for shape in slide.shapes):
            raise ValueError("추출할 이미지가 없습니다. 대체 소재가 필요합니다.")

        image_dir.mkdir(parents=True, exist_ok=True)
        raw_slides = []
        for slide_no, slide in enumerate(prs.slides, 1):
            image_paths, image_positions, text_blocks = [], [], []
            for shape in slide.shapes:
                bbox = [shape.left, shape.top, shape.width, shape.height]
                if shape.has_text_frame and shape.text.strip():
                    text_blocks.append({"text": shape.text, "bbox": bbox})
                if shape.has_table:
                    table_text = "\n".join(" | ".join(cell.text for cell in row.cells) for row in shape.table.rows)
                    text_blocks.append({"text": table_text, "bbox": bbox})
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    save_path = image_dir / f"slide_{slide_no}_img_{len(image_paths) + 1}.{shape.image.ext}"
                    save_path.write_bytes(shape.image.blob)
                    image_paths.append(str(save_path))
                    image_positions.append({"path": str(save_path), "bbox": bbox})

            group = df_elements[df_elements["page_number"] == slide_no]
            titles = group[group["element_type"] == "Title"]["text"].tolist()
            body = group[group["element_type"].isin(["Text", "NarrativeText", "ListItem", "Table"])]["text"].tolist()
            raw_slides.append(
                {
                    "slide_no": slide_no,
                    "title": titles[0] if titles else "(제목 없음)",
                    "texts": [block["text"] for block in text_blocks],
                    "image_paths": image_paths,
                    "all_titles": titles,
                    "body_paragraphs": body,
                    "elements": group.to_dict("records"),
                    "text_blocks": text_blocks,
                    "image_positions": image_positions,
                }
            )

        # 4) 추출 결과 JSON 저장
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{pptx_path.stem}_unstructured.json"
        json_path.write_text(json.dumps(raw_slides, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "raw_slides": raw_slides,
            "parsed_json_path": str(json_path),
            "status": "running",
            "error_message": None,
        }
    except Exception as error:
        return {
            "raw_slides": [],
            "parsed_json_path": None,
            "status": "failed",
            "error_message": f"DocumentParser: {error}",
        }
