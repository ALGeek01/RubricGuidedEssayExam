"""
Semantic exam-question scoring for RGEE_Analysis_Agent (parallel service).

Same embedding-based 4-point coding as the main RGEE app, isolated so PyTorch work
does not run inside the student-facing Uvicorn process.

Set RGEE_MOCK_QUESTION_ANALYSIS=1 in tests to skip model download/load.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.education_levels import guidance_for_level, label_for_level

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Coding scheme #1 — Essay question quality (4 points; verbatim rubric shape from course brief).
QUALITY_CODE_ANCHORS: tuple[str, ...] = (
    "1 point: Poorly phrased, confusing, ambiguous, or inappropriate essay exam question.",
    "2 points: Somewhat clear but lacks depth or focus; does not encourage critical thinking enough.",
    "3 points: Clear and well-structured essay question; could be improved for greater depth or challenge.",
    (
        "4 points: Exceptionally well-phrased, thought-provoking essay question with clear instructions "
        "for high-quality student responses."
    ),
)

# Coding scheme #2 — Grade level appropriateness (4 points).
GRADE_APPROPRIATENESS_ANCHORS: tuple[str, ...] = (
    "1 point: Complexity is significantly below or above the target grade level.",
    "2 points: Complexity is somewhat inappropriate for the target grade level.",
    "3 points: Complexity is mostly appropriate for the target grade level.",
    "4 points: Complexity is perfectly suited for the target grade level expectations.",
)

ANCHOR_QUALITY = (
    "A clear, specific, academically rigorous essay exam question with measurable "
    "criteria and unambiguous expectations for the student."
)
ANCHOR_HUMOR = (
    "Playful, witty, humorous, joke-like, amusing, or comedic tone meant to entertain."
)
ANCHOR_NEUTRAL_TONE = (
    "Formal neutral academic assessment language without jokes or casual banter."
)


def _mock_mode() -> bool:
    return os.environ.get("RGEE_MOCK_QUESTION_ANALYSIS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _sim_to_score(sim: float) -> float:
    """Map cosine similarity (typically [-1, 1]) to 0–10 with two decimals."""
    s = float(np.clip((float(sim) + 1.0) * 5.0, 0.0, 10.0))
    return round(s, 2)


def _classify_4pt_max_cosine(
    vec: np.ndarray, anchor_matrix: np.ndarray, anchor_texts: tuple[str, ...]
) -> tuple[int, str]:
    """vec and rows of anchor_matrix are L2-normalized; return code 1–4 and rationale."""
    sims = anchor_matrix @ vec
    k = int(np.argmax(sims))
    code = k + 1
    win_txt = anchor_texts[k]
    sim_f = float(sims[k])
    rationale = (
        f"Code {code}/4 — max cosine {sim_f:.2f} vs rubric tier: {win_txt}"
    )
    return code, rationale


def _hash_proxy_rows(
    meta: list[dict[str, Any]], texts: list[str], bundles: list[str]
) -> list[QuestionAnalysisRow]:
    out_rows: list[QuestionAnalysisRow] = []
    for r, qb, qt in zip(meta, bundles, texts, strict=True):
        rel, qual, hum = _mock_scores(qt, qb)
        h = hashlib.sha256((qt + "\n" + qb).encode("utf-8")).digest()
        q_code = 1 + (h[3] % 4)
        g_code = 1 + (h[4] % 4)
        out_rows.append(
            QuestionAnalysisRow(
                session_id=int(r["session_id"]),
                exam_code=r.get("exam_code"),
                question_id=int(r["question_id"]),
                question_index=int(r["question_index"]),
                education_level=str(r.get("education_level") or ""),
                use_mock_llm=bool(r.get("use_mock_llm")),
                essay_question=qt,
                professor_domain=str(r.get("professor_domain") or ""),
                background_information=str(r.get("background_information") or ""),
                relevance_score=rel,
                quality_score=qual,
                humor_score=hum,
                quality_code=int(q_code),
                quality_code_rationale=(
                    f"[Mock] Coding scheme #1 — essay question quality tier {q_code}/4 (hash-based stand-in)."
                ),
                grade_appropriateness_code=int(g_code),
                grade_appropriateness_rationale=(
                    f"[Mock] Coding scheme #2 — grade appropriateness tier {g_code}/4 (hash-based stand-in)."
                ),
                relevance_notes=_label_from_score(rel, "alignment with domain/context"),
                quality_notes=_label_from_score(qual, "embedding vs single quality prototype"),
                humor_notes=_humor_notes(hum),
            )
        )
    return out_rows


def _mock_scores(question_text: str, domain_bundle: str) -> tuple[float, float, float]:
    h = hashlib.sha256((question_text + "\n" + domain_bundle).encode("utf-8")).digest()
    # Deterministic spreads in ~2–9 range so charts look sane in fixtures.
    r = 2.0 + (h[0] % 71) / 10.0
    q = 2.5 + (h[1] % 65) / 10.0
    hu = 1.8 + (h[2] % 58) / 10.0
    return round(r, 2), round(q, 2), round(hu, 2)


def _load_model(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(
            "sentence-transformers is not installed. Run "
            "`pip install -r requirements-analysis.txt` on a Python version with "
            "PyTorch wheels to enable live embeddings."
        ) from e
    return SentenceTransformer(model_name)


@dataclass(frozen=True)
class QuestionAnalysisRow:
    session_id: int
    exam_code: str | None
    question_id: int
    question_index: int
    education_level: str
    use_mock_llm: bool
    essay_question: str
    professor_domain: str
    background_information: str
    relevance_score: float
    quality_score: float
    humor_score: float
    quality_code: int
    quality_code_rationale: str
    grade_appropriateness_code: int
    grade_appropriateness_rationale: str
    relevance_notes: str
    quality_notes: str
    humor_notes: str


def analyze_questions_semantic(
    rows: list[dict[str, Any]],
    *,
    model_name: str = DEFAULT_MODEL,
    sample_limit: int | None = None,
) -> tuple[list[QuestionAnalysisRow], str]:
    """
    rows: dicts must include keys session_id, exam_code, question_id, question_index,
    education_level, use_mock_llm, essay_question, professor_domain, background_information

    Uses sentence-transformers when installed; otherwise deterministic hash proxies with a notice.
    """
    if not rows:
        return [], "No questions matched the filters."

    df_in = pd.DataFrame(rows)
    if sample_limit is not None and sample_limit > 0 and len(df_in) > sample_limit:
        df_in = df_in.sample(n=int(sample_limit), random_state=42).sort_values(
            by=["session_id", "question_index"]
        )

    texts: list[str] = []
    bundles: list[str] = []
    meta: list[dict[str, Any]] = df_in.to_dict("records")

    for r in meta:
        qtext = str(r.get("essay_question") or "")
        domain = str(r.get("professor_domain") or "")
        bg = str(r.get("background_information") or "")
        texts.append(qtext)
        bundles.append("\n".join(p for p in [domain.strip(), bg.strip()[:1200]] if p.strip()))

    if _mock_mode():
        out_rows = _hash_proxy_rows(meta, texts, bundles)
        return (
            out_rows,
            f"Mock analysis (deterministic hashing; sample n={len(out_rows)}). "
            "Includes 4-point coding stand-ins for schemes #1 and #2.",
        )

    if importlib.util.find_spec("sentence_transformers") is None:
        out_rows = _hash_proxy_rows(meta, texts, bundles)
        return (
            out_rows,
            "sentence-transformers / PyTorch not installed (see requirements-analysis.txt). "
            f"Showing deterministic hash-based scores and coding stand-ins (n={len(out_rows)}).",
        )

    model = _load_model(model_name)
    qual_mat = model.encode(
        list(QUALITY_CODE_ANCHORS),
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    grade_mat = model.encode(
        list(GRADE_APPROPRIATENESS_ANCHORS),
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    anchor_emb = model.encode(
        [ANCHOR_QUALITY, ANCHOR_HUMOR, ANCHOR_NEUTRAL_TONE],
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    comp_texts = []
    for r, qt in zip(meta, texts, strict=True):
        lid = str(r.get("education_level") or "")
        lvl_label = label_for_level(lid)
        guide = guidance_for_level(lid)
        comp_texts.append(
            f"Target learner level: {lvl_label}. Level expectations: {guide}\n\nEssay exam question:\n{qt}"
        )

    q_emb = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    bundle_emb = model.encode(bundles, normalize_embeddings=True, show_progress_bar=False)
    comp_emb = model.encode(comp_texts, normalize_embeddings=True, show_progress_bar=False)

    aq, ah, an = anchor_emb

    result: list[QuestionAnalysisRow] = []
    for i, r in enumerate(meta):
        qc, qr = _classify_4pt_max_cosine(q_emb[i], qual_mat, QUALITY_CODE_ANCHORS)
        gc, gr = _classify_4pt_max_cosine(comp_emb[i], grade_mat, GRADE_APPROPRIATENESS_ANCHORS)

        rel_sim = float(np.dot(q_emb[i], bundle_emb[i]))
        qual_sim = float(np.dot(q_emb[i], aq))
        humor_sim_raw = float(np.dot(q_emb[i], ah))
        neutral_sim = float(np.dot(q_emb[i], an))
        levity = humor_sim_raw - neutral_sim

        relevance = _sim_to_score(rel_sim)
        quality = _sim_to_score(qual_sim)
        levity_clamped = float(np.clip(levity, -1.0, 1.0))
        humor = _sim_to_score(levity_clamped)

        qt = texts[i]
        result.append(
            QuestionAnalysisRow(
                session_id=int(r["session_id"]),
                exam_code=r.get("exam_code"),
                question_id=int(r["question_id"]),
                question_index=int(r["question_index"]),
                education_level=str(r.get("education_level") or ""),
                use_mock_llm=bool(r.get("use_mock_llm")),
                essay_question=qt,
                professor_domain=str(r.get("professor_domain") or ""),
                background_information=str(r.get("background_information") or ""),
                relevance_score=relevance,
                quality_score=quality,
                humor_score=humor,
                quality_code=qc,
                quality_code_rationale=(
                    f"Coding scheme #1 — essay question quality. {qr}"
                ),
                grade_appropriateness_code=gc,
                grade_appropriateness_rationale=(
                    f"Coding scheme #2 — grade appropriateness ({label_for_level(str(r.get('education_level') or ''))}). "
                    f"{gr}"
                ),
                relevance_notes=_label_from_score(relevance, "embedding alignment with domain + background"),
                quality_notes=_label_from_score(
                    quality, "continuous signal vs single high-quality prompt prototype (supplementary)"
                ),
                humor_notes=_humor_notes(humor),
            )
        )

    note = (
        f"Model {model_name} · Four-point codes = nearest rubric tier under cosine similarity · "
        f"n={len(result)} · Continuous 0–10 metrics are supplementary embeddings."
    )
    return result, note


def _label_from_score(score: float, axis: str) -> str:
    if score >= 7.5:
        return f"Strong ({axis}); score {score:.1f}/10"
    if score >= 5.0:
        return f"Moderate ({axis}); score {score:.1f}/10"
    return f"Weak ({axis}); score {score:.1f}/10 — consider rewriting or tightening scope"


def _humor_notes(score: float) -> str:
    if score >= 6.5:
        return f"Elevated playful/witty leaning vs neutral exam tone ({score:.1f}/10)."
    if score >= 4.0:
        return f"Mixed tone — some lightness possible ({score:.1f}/10)."
    return f"Mostly formal/neutral tone for an exam ({score:.1f}/10)."

