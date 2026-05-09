"""
Semantic exam-question analysis for instructor dashboards.

Implements **research-style 4-point coding** (see quantitative coding brief) by matching
each prompt to the closest rubric tier in embedding space (sentence-transformers / PyTorch).

Also reports continuous 0–10 side signals: relevance (vs domain bundle), legacy quality
anchor, and humor / levity vs neutral tone.

In tests, set RGEE_MOCK_QUESTION_ANALYSIS=1 to skip model download/load.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import logging
import os
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from app.education_levels import guidance_for_level, label_for_level

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Instructor-facing copy for the question-analysis filter form (shown next to the controls).
ANALYSIS_COMPARE_BY_HELP: dict[str, str] = {
    "education_level": (
        "Charts and the category table group each question by the exam session’s education level "
        "(e.g. middle school vs high school). Use this to see whether scores differ by level."
    ),
    "llm_mode": (
        "Groups each question by whether that exam was generated with the Mock LLM (built-in, "
        "deterministic demo) or Production (live Together.ai). Use this to compare patterns when "
        "switching between demo and real model runs."
    ),
    "session_id": (
        "One row per exam attempt: each group is a single session id. Useful when you care about "
        "variation across attempts rather than a single aggregate slice."
    ),
    "quality_code": (
        "Buckets questions by the assigned 1–4 essay question quality code from embedding-based rubric "
        "matching. Use this to see how other metrics differ across quality tiers."
    ),
    "grade_appropriateness_code": (
        "Buckets questions by the assigned 1–4 grade-appropriateness code. Use this to compare "
        "relevance and other signals across appropriateness tiers."
    ),
}

ANALYSIS_LLM_FILTER_HELP: dict[str, str] = {
    "all": (
        "Include every scored question in the sample, whether the source exam used Mock or "
        "Production. Best default for an overview."
    ),
    "mock": (
        "Only sessions where the instructor ran in Mock LLM mode (no external API). Good for "
        "classroom demos and repeatable local testing."
    ),
    "production": (
        "Only sessions where the instructor used Production / Together.ai for generation. "
        "Excludes mock-only runs so you are comparing real-model behavior."
    ),
}

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


def analysis_dataframe(analysis: list[QuestionAnalysisRow]) -> pd.DataFrame:
    if not analysis:
        return pd.DataFrame()
    records = []
    for a in analysis:
        records.append(
            {
                "session_id": a.session_id,
                "exam_code": a.exam_code or "",
                "question_id": a.question_id,
                "question_index": a.question_index,
                "education_level": a.education_level,
                "llm_mode": "mock" if a.use_mock_llm else "production",
                "relevance_score": a.relevance_score,
                "quality_score": a.quality_score,
                "humor_score": a.humor_score,
                "quality_code": a.quality_code,
                "grade_appropriateness_code": a.grade_appropriateness_code,
                "essay_preview": (a.essay_question or "")[:200],
            }
        )
    return pd.DataFrame.from_records(records)


def build_analysis_chart_payload(df: pd.DataFrame, compare_by: str = "education_level") -> dict[str, Any]:
    """JSON-serializable metrics for client-side Chart.js dashboard widgets."""
    if df.empty:
        return {"empty": True}
    qc = df["quality_code"].astype(int).value_counts().reindex(range(1, 5), fill_value=0)
    gc = df["grade_appropriateness_code"].astype(int).value_counts().reindex(range(1, 5), fill_value=0)
    means = df[["relevance_score", "quality_score", "humor_score"]].mean()
    out: dict[str, Any] = {
        "empty": False,
        "total": int(len(df)),
        "sessions": int(df["session_id"].nunique()),
        "quality_freq": [int(qc[i]) for i in range(1, 5)],
        "grade_freq": [int(gc[i]) for i in range(1, 5)],
        "overall": {
            "relevance": float(round(means["relevance_score"], 2)),
            "quality": float(round(means["quality_score"], 2)),
            "humor": float(round(means["humor_score"], 2)),
        },
        "compare_by": compare_by,
        "categories": [],
        "single_exam": None,
    }
    cat_df = summarize_by_category(df, compare_by=compare_by)
    if not cat_df.empty:
        group_key = compare_by if compare_by in (
            "education_level",
            "llm_mode",
            "session_id",
            "quality_code",
            "grade_appropriateness_code",
        ) else "education_level"
        for _, row in cat_df.iterrows():
            if group_key == "llm_mode":
                label = str(row["llm_mode"])
            else:
                label = str(row[group_key])
                if "llm_mode" in cat_df.columns and group_key != "llm_mode":
                    label = f"{label} ({row['llm_mode']})"
            out["categories"].append(
                {
                    "label": label[:56],
                    "mean_quality_code": float(round(row["mean_quality_code"], 3)),
                    "mean_grade_approp_code": float(round(row["mean_grade_approp_code"], 3)),
                    "relevance_score": float(round(row["relevance_score"], 2)),
                    "quality_score": float(round(row["quality_score"], 2)),
                    "humor_score": float(round(row["humor_score"], 2)),
                }
            )
    if df["session_id"].nunique() == 1:
        d3 = df.sort_values("question_index")
        out["single_exam"] = {
            "labels": [f"Q{int(i) + 1}" for i in d3["question_index"]],
            "quality_code": [int(x) for x in d3["quality_code"]],
            "grade_code": [int(x) for x in d3["grade_appropriateness_code"]],
            "relevance": [float(round(x, 2)) for x in d3["relevance_score"]],
        }
    return out


def summarize_by_category(df: pd.DataFrame, compare_by: str = "education_level") -> pd.DataFrame:
    """Aggregate summary by selected category (+ llm_mode when useful)."""
    if df.empty:
        return df
    allowed = {"education_level", "llm_mode", "session_id", "quality_code", "grade_appropriateness_code"}
    group_key = compare_by if compare_by in allowed else "education_level"
    group_cols = [group_key] if group_key == "llm_mode" else [group_key, "llm_mode"]
    g = df.groupby(group_cols, dropna=False).agg(
        relevance_score=("relevance_score", "mean"),
        quality_score=("quality_score", "mean"),
        humor_score=("humor_score", "mean"),
        mean_quality_code=("quality_code", "mean"),
        mean_grade_approp_code=("grade_appropriateness_code", "mean"),
    )
    return g.reset_index().sort_values(group_cols)


def coding_code_frequency_chart_base64(series: pd.Series, title: str, xlabel: str) -> str | None:
    """Bar chart of code frequencies (expects index 1..4)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if series.empty:
        return None
    counts = series.astype(int).value_counts().reindex(range(1, 5), fill_value=0)

    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    x = np.arange(4)
    ax.bar(x, counts.values.astype(float), color="#38bdf8", width=0.65)
    ax.set_xticks(x)
    ax.set_xticklabels([str(i + 1) for i in range(4)])
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")
    ax.set_title(title)
    ax.set_facecolor("#121a2e")
    ax.tick_params(colors="#cbd5f5")
    for spine in ax.spines.values():
        spine.set_color("#334155")
    ax.title.set_color("#f1f5f9")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#121a2e")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def build_category_charts_base64(
    analysis: list[QuestionAnalysisRow], compare_by: str = "education_level"
) -> dict[str, str]:
    """Matplotlib PNG figures as base64 for HTML embedding."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = analysis_dataframe(analysis)
    charts: dict[str, str] = {}
    if df.empty:
        return charts

    def _png_b64(fig) -> str:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#121a2e")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("ascii")

    # 4-point code distributions (portfolio)
    fq_img = coding_code_frequency_chart_base64(
        df["quality_code"],
        "Frequency — essay question quality (codes 1–4)",
        "Quality code",
    )
    if fq_img:
        charts["freq_quality_codes"] = fq_img
    fg_img = coding_code_frequency_chart_base64(
        df["grade_appropriateness_code"],
        "Frequency — grade appropriateness (codes 1–4)",
        "Appropriateness code",
    )
    if fg_img:
        charts["freq_grade_codes"] = fg_img

    # Overall means — continuous supplementary metrics
    means = df[["relevance_score", "quality_score", "humor_score"]].mean()
    fig1, ax1 = plt.subplots(figsize=(7, 2.2))
    cols = ["relevance_score", "quality_score", "humor_score"]
    labels_c = ["Relevance", "Quality (embedding)", "Humor / levity"]
    ax1.barh(labels_c, [means[c] for c in cols], color=["#38bdf8", "#818cf8", "#34d399"])
    ax1.set_xlim(0, 10)
    ax1.set_xlabel("Mean score (0–10)")
    ax1.set_title("Supplementary continuous means (embedding signals)")
    ax1.set_facecolor("#121a2e")
    ax1.tick_params(colors="#cbd5f5")
    for spine in ax1.spines.values():
        spine.set_color("#334155")
    ax1.title.set_color("#f1f5f9")
    charts["overall_means"] = _png_b64(fig1)

    # By selected comparison category — include mean tiers + continuous
    category_col = compare_by if compare_by in df.columns else "education_level"
    if df[category_col].nunique() >= 1:
        summ = (
            df.groupby(category_col, dropna=False)
            .agg(
                relevance_score=("relevance_score", "mean"),
                quality_score=("quality_score", "mean"),
                humor_score=("humor_score", "mean"),
                mean_quality_code=("quality_code", "mean"),
                mean_grade_approp_code=("grade_appropriateness_code", "mean"),
            )
            .sort_index()
        )
        if not summ.empty:
            fig2, ax2 = plt.subplots(figsize=(max(7.0, 1.2 * len(summ.index)), 3.8))
            x = np.arange(len(summ.index))
            w = 0.2
            ax2.bar(x - 1.5 * w, summ["mean_quality_code"], width=w, label="Mean quality code", color="#38bdf8")
            ax2.bar(x - 0.5 * w, summ["mean_grade_approp_code"], width=w, label="Mean appropriateness code", color="#34d399")
            ax2.bar(x + 0.5 * w, summ["relevance_score"] / 2.5, width=w, label="Relevance ÷2.5 (0–4 scale)", color="#818cf8")
            ax2.bar(x + 1.5 * w, summ["humor_score"] / 2.5, width=w, label="Humor ÷2.5 (0–4 scale)", color="#f472b6")
            ax2.set_xticks(x)
            ax2.set_xticklabels(list(summ.index), rotation=28, ha="right", color="#cbd5f5")
            ax2.set_ylabel("Scale (mix)", color="#cbd5f5")
            ax2.set_title(f"By {category_col.replace('_', ' ')}: mean 4-point codes + scaled signals")
            ax2.legend(
                facecolor="#1e2d45",
                labelcolor="#e2e8f0",
                edgecolor="#334155",
                fontsize=8,
            )
            ax2.set_facecolor("#121a2e")
            ax2.set_ylim(0, 4.5)
            for spine in ax2.spines.values():
                spine.set_color("#334155")
            ax2.tick_params(colors="#cbd5f5")
            ax2.title.set_color("#f1f5f9")
            charts["by_category"] = _png_b64(fig2)

    # Single-exam continuous view
    if df["session_id"].nunique() == 1 and not df.empty:
        d3 = df.sort_values("question_index")
        fig3, ax3 = plt.subplots(figsize=(max(6.0, 0.45 * len(d3)), 3.8))
        xq = np.arange(len(d3))
        wq = 0.3
        ax3.bar(xq - wq, d3["quality_code"], width=wq, label="Quality code", color="#38bdf8")
        ax3.bar(xq, d3["grade_appropriateness_code"], width=wq, label="Appropriate. code", color="#34d399")
        ax3.bar(xq + wq, d3["relevance_score"] / 2.5, width=wq, label="Relevance ÷2.5", color="#818cf8")
        ax3.set_xticks(xq)
        qlabels = [f"Q{int(i) + 1}" for i in d3["question_index"]]
        ax3.set_xticklabels(qlabels, color="#cbd5f5")
        ax3.set_ylabel("Code / scaled score")
        code = d3["exam_code"].iloc[0] if "exam_code" in d3.columns else ""
        sid = int(d3["session_id"].iloc[0])
        ax3.set_title(f"Per question — session #{sid}" + (f" ({code})" if code else ""))
        ax3.legend(facecolor="#1e2d45", labelcolor="#e2e8f0", edgecolor="#334155", fontsize=8)
        ax3.set_facecolor("#121a2e")
        ax3.set_ylim(0, 4.8)
        for spine in ax3.spines.values():
            spine.set_color("#334155")
        ax3.tick_params(colors="#cbd5f5")
        ax3.title.set_color("#f1f5f9")
        charts["single_exam"] = _png_b64(fig3)

    return charts
