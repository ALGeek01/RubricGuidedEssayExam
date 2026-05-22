"""Unit tests for AI / manual / compare analysis view payloads."""

from __future__ import annotations

import pandas as pd

from app.question_analysis import (
    build_analysis_views_payload,
    build_compare_view_payload,
    build_manual_view_payload,
    enrich_analysis_df_manual,
)
from app.question_analysis_support import (
    QuestionAnalysisFilterState,
    build_analysis_share_snapshot,
)


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "session_id": 1,
                "question_id": 10,
                "question_index": 0,
                "education_level": "undergraduate",
                "llm_mode": "mock",
                "relevance_score": 7.0,
                "quality_score": 6.0,
                "humor_score": 4.0,
                "quality_code": 2,
                "grade_appropriateness_code": 3,
            },
            {
                "session_id": 1,
                "question_id": 11,
                "question_index": 1,
                "education_level": "undergraduate",
                "llm_mode": "mock",
                "relevance_score": 8.0,
                "quality_score": 7.0,
                "humor_score": 5.0,
                "quality_code": 3,
                "grade_appropriateness_code": 3,
            },
        ]
    )


def test_enrich_analysis_df_manual():
    df = _sample_df()
    manual = {10: {"quality": 4, "grade": 2}, 11: {"quality": 3, "grade": None}}
    out = enrich_analysis_df_manual(df, manual)
    assert out.loc[out.question_id == 10, "manual_quality_code"].iloc[0] == 4
    assert out.loc[out.question_id == 11, "manual_grade_code"].isna().iloc[0]


def test_manual_view_payload_counts_and_freq():
    df = enrich_analysis_df_manual(_sample_df(), {10: {"quality": 4, "grade": 2}, 11: {"quality": 3, "grade": 3}})
    payload = build_manual_view_payload(df)
    assert payload["manual_qly_set"] == 2
    assert payload["manual_lvl_set"] == 2
    assert sum(payload["quality_freq"]) == 2
    assert payload["overall"]["mean_quality"] == 3.5


def test_compare_view_agreement_and_delta():
    df = enrich_analysis_df_manual(_sample_df(), {10: {"quality": 2, "grade": 3}, 11: {"quality": 3, "grade": 4}})
    payload = build_compare_view_payload(df)
    assert payload["qly"]["paired"] == 2
    assert payload["qly"]["agree"] == 2
    assert payload["qly"]["agree_pct"] == 100.0
    assert len(payload["delta_qly_freq"]) == 7


def test_build_analysis_share_snapshot_includes_questions_and_metrics():
    df = _sample_df()
    manual = {10: {"quality": 4, "grade": 2}}
    views = build_analysis_views_payload(df, manual, compare_by="education_level")
    chart_payload = {"empty": False, "total": 2, "views": views}
    state = QuestionAnalysisFilterState(
        session_id=None,
        education_level="",
        llm_mode="all",
        compare_by="education_level",
        sample_limit=200,
        run_analysis=True,
    )

    class Row:
        session_id = 1
        exam_code = "ABC12"
        question_id = 10
        question_index = 0
        education_level = "undergraduate"
        use_mock_llm = True
        essay_question = "Explain widgets."
        quality_code = 2
        grade_appropriateness_code = 3
        relevance_score = 7.0
        quality_score = 6.0
        humor_score = 4.0

    snap = build_analysis_share_snapshot(
        state=state,
        chart_payload=chart_payload,
        methodology_note="Mock embeddings.",
        analysis_rows=[Row()],
        manual_rank_by_question=manual,
        feedback_by_question={10: "Solid prompt."},
        compare_by_label="Education level",
        compare_options={"education_level": "Education level"},
        uses_remote_agent=False,
        manual_rank_count_quality=1,
        manual_rank_count_grade=1,
        url_analysis_scored="/professor/question-analysis?run=1",
    )
    assert snap is not None
    assert snap["format"] == "rgee-analysis-share-v1"
    assert len(snap["questions"]) == 1
    assert snap["questions"][0]["manual_quality_code"] == 4
    assert "views" in snap["metrics"]


def test_build_analysis_views_payload_has_three_views():
    df = _sample_df()
    manual = {10: {"quality": 4, "grade": 2}}
    views = build_analysis_views_payload(df, manual, compare_by="education_level")
    assert "ai" in views and "manual" in views and "compare" in views
    assert views["ai"]["total"] == 2
    assert "category_tables" in views
    assert len(views["category_tables"]["ai"]) >= 1
