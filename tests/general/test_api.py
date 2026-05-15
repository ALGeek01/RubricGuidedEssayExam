"""HTTP tests for all routes (MOCK_LLM, isolated SQLite)."""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_home(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Start exam" in r.text
    assert "Resume exam" in r.text


def test_start_page_loads(client: TestClient):
    r = client.get("/start")
    assert r.status_code == 200
    assert b"/start/generated" in r.content
    assert b"/start/nominated" in r.content
    r2 = client.get("/start/generated")
    assert r2.status_code == 200
    assert b"education_level" in r2.content or b"Education level" in r2.content


def test_resume_page_loads(client: TestClient):
    r = client.get("/resume")
    assert r.status_code == 200
    assert "Resume your in-progress exam" in r.text


def test_resume_redirects_to_in_progress_exam(client: TestClient):
    from app.database import ExamSession, SessionLocal

    r0 = client.post(
        "/exam/start",
        data={"student_id": "resume-me", "professor_domain": "Resume test domain.", "num_questions": "2"},
        follow_redirects=False,
    )
    assert r0.status_code == 303
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])
    db = SessionLocal()
    try:
        sess = db.get(ExamSession, session_id)
        assert sess is not None and sess.exam_code
        exam_id = sess.exam_code
    finally:
        db.close()
    r = client.post(
        "/resume",
        data={"student_id": "resume-me", "exam_id": exam_id},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/exam/{session_id}/question"


def test_resume_requires_both_student_and_exam_id(client: TestClient):
    r = client.post("/resume", data={"student_id": "abc", "exam_id": ""}, follow_redirects=False)
    assert r.status_code == 400
    assert "Please enter your exam ID." in r.text

    r2 = client.post("/resume", data={"student_id": "", "exam_id": "A1B2C"}, follow_redirects=False)
    assert r2.status_code == 400
    assert "Please enter your student ID." in r2.text


def test_same_student_id_reuses_one_student_row_for_two_exams(client: TestClient):
    """Distinct exam sessions share one students row (unique external_student_id)."""
    from app.database import ExamSession, SessionLocal, Student

    r1 = client.post(
        "/exam/start",
        data={"student_id": "shared-student", "professor_domain": "Topic A", "num_questions": "1"},
        follow_redirects=False,
    )
    r2 = client.post(
        "/exam/start",
        data={"student_id": "shared-student", "professor_domain": "Topic B", "num_questions": "1"},
        follow_redirects=False,
    )
    assert r1.status_code == 303 and r2.status_code == 303
    id1 = int(r1.headers["location"].split("/exam/")[1].split("/")[0])
    id2 = int(r2.headers["location"].split("/exam/")[1].split("/")[0])
    assert id1 != id2
    db = SessionLocal()
    try:
        assert db.query(Student).filter(Student.external_student_id == "shared-student").count() == 1
        s1 = db.get(ExamSession, id1)
        s2 = db.get(ExamSession, id2)
        assert s1 is not None and s2 is not None
        assert s1.student_ref_id == s2.student_ref_id
        assert s1.exam_code and len(s1.exam_code) == 5 and s1.exam_code.isalnum()
        assert s2.exam_code and len(s2.exam_code) == 5 and s2.exam_code.isalnum()
        assert s1.exam_code != s2.exam_code
    finally:
        db.close()


def test_static_css(client: TestClient):
    r = client.get("/static/style.css")
    assert r.status_code == 200


def test_exam_start_redirects_and_creates_session(client: TestClient):
    r = client.post(
        "/exam/start",
        data={
            "student_id": "test-student-1",
            "professor_domain": "Fair grading in CS courses.",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/exam/")
    assert "/question" in r.headers["location"]


def test_exam_start_rejects_invalid_education_level(client: TestClient):
    r = client.post(
        "/exam/start",
        data={
            "student_id": "x",
            "professor_domain": "y",
            "education_level": "not_a_real_level",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "text/html" in r.headers.get("content-type", "")
    assert "problem with that request" in r.text.lower()


def test_exam_start_rejects_invalid_grading_strictness(client: TestClient):
    r = client.post(
        "/exam/start",
        data={
            "student_id": "x",
            "professor_domain": "y",
            "grading_strictness": "not_a_mode",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "text/html" in r.headers.get("content-type", "")
    assert "problem with that request" in r.text.lower()


def test_insane_grading_strictness_mock_final_percent(client: TestClient):
    r0 = client.post(
        "/exam/start",
        data={
            "student_id": "insane-tester",
            "professor_domain": "Domain for insane strictness.",
            "grading_strictness": "insane",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])
    client.post(
        f"/exam/{session_id}/answer",
        data={"answer": "Answer text.", "seconds_on_question": ""},
        follow_redirects=True,
    )
    res = client.get(f"/exam/{session_id}/results")
    assert res.status_code == 200
    assert "68.0%" in res.text


def test_ai_helper_chat_blocked_when_hints_exhausted(client: TestClient):
    r0 = client.post(
        "/exam/start",
        data={
            "student_id": "no-chat-hints",
            "professor_domain": "Middle school science basics.",
            "num_questions": "1",
            "grading_strictness": "insane",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])
    r = client.post(
        f"/exam/{session_id}/hint-json",
        data={"mode": "chat", "hint_query": "tell me how to approach this question"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("hint_exhausted") is True
    assert payload.get("hint") == "Sorry you ran out of hints cannot chat with AI helper"


def test_ai_helper_chat_consumes_hint_budget(client: TestClient):
    r0 = client.post(
        "/exam/start",
        data={
            "student_id": "chat-budget-user",
            "professor_domain": "Basic geometry with triangles.",
            "num_questions": "1",
            "grading_strictness": "strict",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])

    r1 = client.post(
        f"/exam/{session_id}/hint-json",
        data={"mode": "chat", "hint_query": "tell me how to approach this question"},
    )
    assert r1.status_code == 200
    p1 = r1.json()
    assert p1.get("hint_used") == 1
    assert p1.get("hint_exhausted") is True

    r2 = client.post(
        f"/exam/{session_id}/hint-json",
        data={"mode": "chat", "hint_query": "one more question"},
    )
    assert r2.status_code == 200
    p2 = r2.json()
    assert p2.get("hint_exhausted") is True
    assert p2.get("hint") == "Sorry you ran out of hints cannot chat with AI helper"


def test_ai_helper_offtopic_message_does_not_consume_hints(client: TestClient):
    r0 = client.post(
        "/exam/start",
        data={
            "student_id": "chat-offtopic-free",
            "professor_domain": "Basic geometry with triangles.",
            "num_questions": "1",
            "grading_strictness": "balanced",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])

    r = client.post(
        f"/exam/{session_id}/hint-json",
        data={"mode": "chat", "hint_query": "what is the weather in tokyo this weekend"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("hint") == (
        "I want to help with your exam progress. Please share what part of this question "
        "you want to work on, and I will guide you without giving the final answer."
    )
    assert payload.get("hint_used") == 0
    assert payload.get("hint_remaining") == 3
    assert payload.get("hint_exhausted") is False


def test_full_exam_single_question_flow(client: TestClient):
    r0 = client.post(
        "/exam/start",
        data={
            "student_id": "s1",
            "professor_domain": "Domain text for testing.",
            "education_level": "high_school",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303
    loc = r0.headers["location"]
    session_id = int(loc.split("/exam/")[1].split("/")[0])

    q = client.get(f"/exam/{session_id}/question")
    assert q.status_code == 200
    assert b"MOCK" in q.content or b"essay" in q.content.lower()
    assert "High school" in q.text

    r1 = client.post(
        f"/exam/{session_id}/answer",
        data={"answer": "A complete answer for testing.", "seconds_on_question": "120"},
        follow_redirects=False,
    )
    assert r1.status_code == 303
    assert r1.headers["location"] == f"/exam/{session_id}/results"

    res = client.get(f"/exam/{session_id}/results")
    assert res.status_code == 200
    assert b"84" in res.content or b"grade" in res.content.lower()
    assert "Rubric breakdown" in res.text
    assert "Reference answer guidance" in res.text
    assert "Strengths" in res.text
    assert "Areas for improvement" in res.text
    assert "Suggestions" in res.text
    assert "Overall final summary" in res.text
    assert "Points" in res.text


def test_two_question_flow(client: TestClient):
    r0 = client.post(
        "/exam/start",
        data={
            "student_id": "s2",
            "professor_domain": "Multi-q domain.",
            "num_questions": "2",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303
    loc = r0.headers["location"]
    session_id = int(loc.split("/exam/")[1].split("/")[0])

    r1 = client.post(
        f"/exam/{session_id}/answer",
        data={"answer": "Answer one.", "seconds_on_question": ""},
        follow_redirects=False,
    )
    assert r1.status_code == 303
    assert "/question" in r1.headers["location"]

    r2 = client.post(
        f"/exam/{session_id}/answer",
        data={"answer": "Answer two.", "seconds_on_question": "60"},
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert r2.headers["location"] == f"/exam/{session_id}/results"

    res = client.get(f"/exam/{session_id}/results")
    assert res.status_code == 200


def test_completed_session_question_redirects_to_results(client: TestClient):
    r0 = client.post(
        "/exam/start",
        data={"student_id": "s4", "professor_domain": "x", "num_questions": "1"},
        follow_redirects=False,
    )
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])
    client.post(
        f"/exam/{session_id}/answer",
        data={"answer": "done", "seconds_on_question": ""},
        follow_redirects=True,
    )
    r = client.get(f"/exam/{session_id}/question", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/exam/{session_id}/results"


def test_exam_not_found(client: TestClient):
    q = client.get("/exam/99999/question")
    r = client.get("/exam/99999/results")
    assert q.status_code == 404
    assert r.status_code == 404
    assert "text/html" in q.headers.get("content-type", "")
    assert "we could not find that page" in q.text.lower()


def test_professor_dashboard_and_detail(logged_in_instructor: TestClient):
    client = logged_in_instructor
    r0 = client.post(
        "/exam/start",
        data={"student_id": "prof-test", "professor_domain": "y", "num_questions": "1"},
        follow_redirects=False,
    )
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])
    client.post(
        f"/exam/{session_id}/answer",
        data={"answer": "final", "seconds_on_question": ""},
        follow_redirects=True,
    )

    dash = client.get("/professor")
    assert dash.status_code == 200
    assert b"prof-test" in dash.content or b"prof" in dash.content.lower()

    det = client.get(f"/professor/exam/{session_id}")
    assert det.status_code == 200
    assert "Reference answer guidance" in det.text
    assert "Rubric breakdown" in det.text
    assert "Strengths" in det.text
    assert "Areas for improvement" in det.text
    assert "Suggestions" in det.text
    assert "Overall final summary" in det.text
    assert "Points" in det.text

    assert client.get("/professor/exam/99999").status_code == 404


def test_professor_requires_login(client: TestClient):
    r = client.get("/professor", follow_redirects=False)
    assert r.status_code == 303
    assert "/professor/login" in (r.headers.get("location") or "")

    r2 = client.get("/professor/exam/1", follow_redirects=False)
    assert r2.status_code == 303
    assert "/professor/login" in (r2.headers.get("location") or "")

    assert client.get("/professor/tools", follow_redirects=False).status_code == 303
    assert client.get("/professor/question-analysis", follow_redirects=False).status_code == 303
    assert client.get("/professor/question-analysis/nomination", follow_redirects=False).status_code == 303
    assert client.get("/professor/question-analysis/manual-feedback", follow_redirects=False).status_code == 303
    rlog = client.get("/performance-log", follow_redirects=False)
    assert rlog.status_code == 303
    assert "/professor/login" in (rlog.headers.get("location") or "")


def test_professor_logout_clears_session(logged_in_instructor: TestClient):
    r = logged_in_instructor.post("/professor/logout", follow_redirects=False)
    assert r.status_code == 303
    assert logged_in_instructor.get("/professor", follow_redirects=False).status_code == 303


def test_professor_login_wrong_password_returns_403_with_message(client: TestClient):
    r = client.post(
        "/professor/login",
        data={"username": "elliott", "password": "definitely-wrong", "next": "/professor"},
        follow_redirects=False,
    )
    assert r.status_code == 403
    assert "Invalid username or password" in r.text
    assert "We hit a temporary issue" not in r.text


def test_performance_log_page_requires_instructor_sign_in(client: TestClient):
    r = client.get("/performance-log", follow_redirects=False)
    assert r.status_code == 303
    assert "/professor/login" in (r.headers.get("location") or "")


def test_performance_log_visible_when_instructor_signed_in(logged_in_instructor: TestClient):
    r = logged_in_instructor.get("/performance-log")
    assert r.status_code == 200
    assert "Performance log" in r.text


def test_question_analysis_dashboard(logged_in_instructor: TestClient):
    dash = logged_in_instructor.get("/professor/question-analysis?run=1")
    assert dash.status_code == 200
    assert "Exam question analysis" in dash.text
    assert "Mock analysis" in dash.text or "No questions matched" in dash.text


def test_http_log_links_exam_start_to_session(logged_in_instructor: TestClient):
    r0 = logged_in_instructor.post(
        "/exam/start",
        data={
            "student_id": "assoc-test",
            "professor_domain": "Association test domain.",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])

    log_page = logged_in_instructor.get("/performance-log")
    assert log_page.status_code == 200
    assert f'href="/professor/exam/{session_id}"' in log_page.text
    assert "assoc-test" in log_page.text


def test_question_analysis_lists_generated_prompt(logged_in_instructor: TestClient):
    r0 = logged_in_instructor.post(
        "/exam/start",
        data={
            "student_id": "analysis-student",
            "professor_domain": "Widget engineering for qualitative analysis fixture.",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303

    qa = logged_in_instructor.get("/professor/question-analysis?run=1")
    assert qa.status_code == 200
    assert "Question-level detail" in qa.text
    assert "Widget engineering for qualitative analysis fixture" in qa.text or "analysis-student" in qa.text


def test_client_timing_records_and_returns_204(logged_in_instructor: TestClient):
    r0 = logged_in_instructor.post(
        "/exam/start",
        data={
            "student_id": "timing-student",
            "professor_domain": "Topic for timing test.",
            "num_questions": "1",
        },
        follow_redirects=False,
    )
    assert r0.status_code == 303
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])

    r = logged_in_instructor.post(
        f"/exam/{session_id}/client-timing",
        data={"client_ms_wall": "1234.5"},
    )
    assert r.status_code == 204

    log_page = logged_in_instructor.get("/performance-log")
    assert log_page.status_code == 200
    assert "generate_click_to_first_question_visible" in log_page.text
    assert "1234.5" in log_page.text or "1234" in log_page.text
    assert "timing-student" in log_page.text


def test_client_timing_unknown_session_404(client: TestClient):
    r = client.post(
        "/exam/99999/client-timing",
        data={"client_ms_wall": "100"},
    )
    assert r.status_code == 404


def test_answer_invalid_session(client: TestClient):
    r0 = client.post(
        "/exam/start",
        data={"student_id": "s5", "professor_domain": "z", "num_questions": "1"},
        follow_redirects=False,
    )
    session_id = int(r0.headers["location"].split("/exam/")[1].split("/")[0])
    client.post(
        f"/exam/{session_id}/answer",
        data={"answer": "x", "seconds_on_question": ""},
        follow_redirects=True,
    )
    r = client.post(
        f"/exam/{session_id}/answer",
        data={"answer": "again", "seconds_on_question": ""},
        follow_redirects=False,
    )
    # Idempotent: duplicate submit after exam completed → redirect to results (not 400).
    assert r.status_code == 303
    assert r.headers["location"] == f"/exam/{session_id}/results"


def test_nominated_exam_publish_and_student_start(client: TestClient, logged_in_instructor: TestClient):
    from app.database import ExamQuestion, SessionLocal

    r0 = client.post(
        "/exam/start",
        data={
            "student_id": "tpl-source",
            "professor_domain": "Nominated template domain.",
            "num_questions": "2",
        },
        follow_redirects=False,
    )
    sid_src = int(r0.headers["location"].split("/exam/")[1].split("/")[0])
    client.post(
        f"/exam/{sid_src}/answer",
        data={"answer": "first answer for nominee test."},
        follow_redirects=True,
    )
    db = SessionLocal()
    try:
        qrows = (
            db.query(ExamQuestion)
            .filter(ExamQuestion.session_id == sid_src)
            .order_by(ExamQuestion.question_index.asc())
            .all()
        )
        assert len(qrows) == 2
        qids = [qrows[0].id, qrows[1].id]
    finally:
        db.close()

    from urllib.parse import urlencode

    body = urlencode(
        [
            ("title", "Fixture nominated"),
            ("next", "/professor/question-analysis/nomination?run=1"),
            ("question_id", str(qids[0])),
            ("question_id", str(qids[1])),
        ]
    )
    r_pub = logged_in_instructor.post(
        "/professor/question-analysis/create-nominated-exam",
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r_pub.status_code == 303
    loc = r_pub.headers["location"]
    assert "nominated_created=" in loc
    code = loc.split("nominated_created=")[-1].split("&")[0]
    assert len(code) == 8

    r_bad = client.post(
        "/exam/start-nominated",
        data={"student_id": "stu-nom", "exam_id": "BAD1"},
    )
    assert r_bad.status_code == 400

    r_start = client.post(
        "/exam/start-nominated",
        data={"student_id": "stu-nom", "exam_id": code},
        follow_redirects=False,
    )
    assert r_start.status_code == 303
    new_sid = int(r_start.headers["location"].split("/exam/")[1].split("/")[0])
    assert client.get(f"/exam/{new_sid}/question").status_code == 200
    client.post(
        f"/exam/{new_sid}/answer",
        data={"answer": "answer one"},
        follow_redirects=True,
    )
    assert client.get(f"/exam/{new_sid}/question").status_code == 200
    client.post(
        f"/exam/{new_sid}/answer",
        data={"answer": "answer two"},
        follow_redirects=True,
    )
    assert client.get(f"/exam/{new_sid}/results").status_code == 200
