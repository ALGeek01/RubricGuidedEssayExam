import json
import secrets
import string
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.config import get_settings
from app.education_levels import DEFAULT_EDUCATION_LEVEL_ID
from app.grading_strictness import DEFAULT_GRADING_STRICTNESS


class Base(DeclarativeBase):
    pass


class Student(Base):
    """One row per distinct student identifier; exam sessions link here (many exams per student)."""

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_student_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    sessions: Mapped[list["ExamSession"]] = relationship(back_populates="student")


class ExamSession(Base):
    __tablename__ = "exam_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_ref_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("students.id", ondelete="RESTRICT"),
        index=True,
    )
    professor_domain: Mapped[str] = mapped_column(Text)
    education_level: Mapped[str] = mapped_column(String(64), default=DEFAULT_EDUCATION_LEVEL_ID)
    use_mock_llm: Mapped[bool] = mapped_column(Boolean, default=True)
    num_questions_planned: Mapped[int] = mapped_column(Integer, default=1)
    current_question_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), default="in_progress")  # in_progress | completed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    final_grade_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    exam_code: Mapped[str] = mapped_column(String(5), unique=True, index=True)
    # easy | balanced | strict | insane — controls LLM grading prompt (see app.grading_strictness).
    grading_strictness: Mapped[str] = mapped_column(String(32), default=DEFAULT_GRADING_STRICTNESS)
    # Integer key into nominated_exams.id when this session was spawned from a curated template (no FK: avoids create_all cycles on SQLite).
    nominated_exam_template_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    student: Mapped["Student"] = relationship(back_populates="sessions", lazy="joined")
    questions: Mapped[list["ExamQuestion"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    final_grade_row: Mapped["FinalGrade | None"] = relationship(back_populates="session", uselist=False)


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("exam_sessions.id", ondelete="CASCADE"), index=True)
    question_index: Mapped[int] = mapped_column(Integer)
    background_information: Mapped[str] = mapped_column(Text)
    essay_question: Mapped[str] = mapped_column(Text)
    grading_rubric: Mapped[str] = mapped_column(Text)  # JSON list or text
    domain_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    seconds_on_question: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graded_state_p_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # state P from spec
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    latest_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    hint_history_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_ai_helper_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_helper_history_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["ExamSession"] = relationship(back_populates="questions")


class FinalGrade(Base):
    __tablename__ = "final_grades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("exam_sessions.id", ondelete="CASCADE"), unique=True)
    total_grade_percent: Mapped[float] = mapped_column()
    explanation: Mapped[str] = mapped_column(Text)
    summary_json: Mapped[str] = mapped_column(Text)  # full LLM payload

    session: Mapped["ExamSession"] = relationship(back_populates="final_grade_row")


class QuestionAnalysisFeedback(Base):
    """Instructor free-text notes per analyzed question (main RGEE DB; shown beside AI scores)."""

    __tablename__ = "question_analysis_feedback"
    __table_args__ = (
        UniqueConstraint("session_id", "question_id", name="uq_question_analysis_feedback_session_question"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("exam_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("exam_questions.id", ondelete="CASCADE"),
        index=True,
    )
    instructor_note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class NominatedExamSession(Base):
    """Legacy: previously used for instructor flags; retained for older databases."""

    __tablename__ = "nominated_exam_sessions"

    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("exam_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class NominatedExam(Base):
    """Instructor-published fixed exam template students can start with student ID + nominated exam ID."""

    __tablename__ = "nominated_exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    access_code: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    source_session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("exam_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    professor_domain: Mapped[str] = mapped_column(Text)
    education_level: Mapped[str] = mapped_column(String(64), default=DEFAULT_EDUCATION_LEVEL_ID)
    use_mock_llm: Mapped[bool] = mapped_column(Boolean, default=True)
    grading_strictness: Mapped[str] = mapped_column(String(32), default=DEFAULT_GRADING_STRICTNESS)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    snapshot_questions: Mapped[list["NominatedExamSnapshotQuestion"]] = relationship(
        back_populates="nominated_exam",
        cascade="all, delete-orphan",
    )


class NominatedExamSnapshotQuestion(Base):
    """Frozen question rows copied at publish time (including optional instructor manual notes)."""

    __tablename__ = "nominated_exam_snapshot_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nominated_exam_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("nominated_exams.id", ondelete="CASCADE"),
        index=True,
    )
    source_question_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("exam_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    question_index: Mapped[int] = mapped_column(Integer)
    background_information: Mapped[str] = mapped_column(Text)
    essay_question: Mapped[str] = mapped_column(Text)
    grading_rubric: Mapped[str] = mapped_column(Text)
    domain_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructor_note: Mapped[str] = mapped_column(Text, default="")

    nominated_exam: Mapped["NominatedExam"] = relationship(back_populates="snapshot_questions")


class PerformanceLog(Base):
    """Diagnostics: HTTP request duration, LLM call duration, client-reported UX timing."""

    __tablename__ = "performance_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    category: Mapped[str] = mapped_column(String(32), index=True)  # http | llm | client
    event_name: Mapped[str] = mapped_column(String(512))
    duration_ms: Mapped[float] = mapped_column(Float)
    exam_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    student_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)


def _engine():
    url = get_settings().database_url
    connect_args = (
        {
            "check_same_thread": False,
            "timeout": 20,
        }
        if url.startswith("sqlite")
        else {}
    )
    eng = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cur = dbapi_connection.cursor()
            # WAL + busy timeout reduces "database is locked" during rapid writes.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=20000")
            cur.close()
    return eng


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

EXAM_CODE_LENGTH = 5
EXAM_CODE_ALPHABET = string.ascii_uppercase + string.digits

NOMINATED_ACCESS_CODE_LENGTH = 8
NOMINATED_ACCESS_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _is_valid_exam_code(code: str) -> bool:
    return len(code) == EXAM_CODE_LENGTH and all(ch in EXAM_CODE_ALPHABET for ch in code)


def _is_valid_nominated_access_code(code: str) -> bool:
    c = (code or "").strip().upper()
    return len(c) == NOMINATED_ACCESS_CODE_LENGTH and all(ch in NOMINATED_ACCESS_CODE_ALPHABET for ch in c)


def generate_unique_exam_code(
    db: Session, *, reserved: set[str] | None = None, max_attempts: int = 128
) -> str:
    reserved_codes = reserved or set()
    for _ in range(max_attempts):
        code = "".join(secrets.choice(EXAM_CODE_ALPHABET) for _ in range(EXAM_CODE_LENGTH))
        if code in reserved_codes:
            continue
        exists = db.query(ExamSession.id).filter(ExamSession.exam_code == code).first()
        if not exists:
            return code
    raise RuntimeError("Unable to generate unique exam code")


def generate_unique_nominated_access_code(
    db: Session, *, reserved: set[str] | None = None, max_attempts: int = 256
) -> str:
    reserved_codes = reserved or set()
    for _ in range(max_attempts):
        code = "".join(
            secrets.choice(NOMINATED_ACCESS_CODE_ALPHABET) for _ in range(NOMINATED_ACCESS_CODE_LENGTH)
        )
        if code in reserved_codes:
            continue
        exists = db.query(NominatedExam.id).filter(NominatedExam.access_code == code).first()
        if not exists:
            return code
    raise RuntimeError("Unable to generate unique nominated exam access code")


def get_or_create_student(db: Session, external_student_id: str) -> Student:
    ext = external_student_id.strip()
    if not ext:
        raise ValueError("external_student_id required")
    existing = db.query(Student).filter(Student.external_student_id == ext).one_or_none()
    if existing:
        return existing
    s = Student(external_student_id=ext)
    db.add(s)
    try:
        db.flush()
        return s
    except IntegrityError:
        db.rollback()
        return db.query(Student).filter(Student.external_student_id == ext).one()


def _migrate_students_and_exam_session_fk() -> None:
    """Legacy DBs stored student_id string on exam_sessions; normalize to students + student_ref_id."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "students" not in tables:
        Student.__table__.create(bind=engine, checkfirst=True)
    if "exam_sessions" not in tables:
        return
    col_names = {c["name"] for c in insp.get_columns("exam_sessions")}
    if "student_ref_id" in col_names:
        if "student_id" in col_names:
            _backfill_student_ref_ids_from_legacy_string_column()
            _try_drop_legacy_exam_session_student_string_column()
        if "students" not in set(inspect(engine).get_table_names()):
            Student.__table__.create(bind=engine, checkfirst=True)
        return
    if "student_id" not in col_names:
        return
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            try:
                conn.execute(
                    text(
                        "ALTER TABLE exam_sessions ADD COLUMN student_ref_id INTEGER "
                        "REFERENCES students(id)"
                    )
                )
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" not in msg and "already exists" not in msg:
                    raise
        elif dialect == "postgresql":
            conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS student_ref_id INTEGER"))
        else:
            try:
                conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN student_ref_id INTEGER"))
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" not in msg and "already exists" not in msg:
                    raise
    _backfill_student_ref_ids_from_legacy_string_column()
    if dialect == "postgresql":
        _ensure_postgresql_student_fk_constraint()
    _try_drop_legacy_exam_session_student_string_column()


def _ensure_postgresql_student_fk_constraint() -> None:
    if engine.dialect.name != "postgresql":
        return
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE exam_sessions ADD CONSTRAINT exam_sessions_student_ref_id_fkey "
                    "FOREIGN KEY (student_ref_id) REFERENCES students(id)"
                )
            )
    except Exception as e:
        msg = str(e).lower()
        if "already exists" in msg or "duplicate" in msg:
            return
        raise


def _backfill_student_ref_ids_from_legacy_string_column() -> None:
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT id, student_id FROM exam_sessions WHERE student_ref_id IS NULL")
        ).fetchall()
        for rid, ext in rows:
            if ext is None or str(ext).strip() == "":
                continue
            stu = get_or_create_student(db, str(ext).strip())
            db.execute(
                text("UPDATE exam_sessions SET student_ref_id = :srid WHERE id = :id"),
                {"srid": stu.id, "id": rid},
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _try_drop_legacy_exam_session_student_string_column() -> None:
    insp = inspect(engine)
    cols = insp.get_columns("exam_sessions")
    col_names = {c["name"] for c in cols}
    if "student_id" not in col_names:
        return
    info = next(c for c in cols if c["name"] == "student_id")
    tstr = str(info.get("type", "")).upper()
    if "INT" in tstr:
        return
    dialect = engine.dialect.name
    with engine.begin() as conn:
        try:
            if dialect == "postgresql":
                conn.execute(text("ALTER TABLE exam_sessions DROP COLUMN IF EXISTS student_id"))
            else:
                conn.execute(text("ALTER TABLE exam_sessions DROP COLUMN student_id"))
        except Exception as e:
            msg = str(e).lower()
            if "no such column" in msg or "does not exist" in msg:
                return
            if dialect == "sqlite" and ("unsupported" in msg or "cannot drop" in msg):
                return
            raise


def _migrate_sqlite_schema() -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        try:
            conn.execute(
                text(
                    "ALTER TABLE exam_sessions ADD COLUMN education_level VARCHAR(64) NOT NULL DEFAULT '"
                    + DEFAULT_EDUCATION_LEVEL_ID
                    + "'"
                )
            )
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                raise
        try:
            conn.execute(
                text("ALTER TABLE exam_sessions ADD COLUMN use_mock_llm INTEGER NOT NULL DEFAULT 1")
            )
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                raise
        try:
            conn.execute(
                text(
                    "ALTER TABLE exam_sessions ADD COLUMN grading_strictness VARCHAR(32) NOT NULL DEFAULT '"
                    + DEFAULT_GRADING_STRICTNESS
                    + "'"
                )
            )
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                raise
        try:
            conn.execute(text("ALTER TABLE performance_logs ADD COLUMN student_id VARCHAR(256)"))
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                if "no such table" in msg:
                    pass
                else:
                    raise
        try:
            conn.execute(text("ALTER TABLE exam_questions ADD COLUMN hints_used INTEGER NOT NULL DEFAULT 0"))
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                if "no such table" in msg:
                    pass
                else:
                    raise
        try:
            conn.execute(text("ALTER TABLE exam_questions ADD COLUMN latest_hint TEXT"))
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                if "no such table" in msg:
                    pass
                else:
                    raise
        try:
            conn.execute(text("ALTER TABLE exam_questions ADD COLUMN hint_history_json TEXT"))
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                if "no such table" in msg:
                    pass
                else:
                    raise
        try:
            conn.execute(text("ALTER TABLE exam_questions ADD COLUMN latest_ai_helper_reply TEXT"))
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                if "no such table" in msg:
                    pass
                else:
                    raise
        try:
            conn.execute(text("ALTER TABLE exam_questions ADD COLUMN ai_helper_history_json TEXT"))
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                if "no such table" in msg:
                    pass
                else:
                    raise
        try:
            conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN exam_code VARCHAR(5)"))
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                raise
    _relax_legacy_student_id_not_null_sqlite()


def _relax_legacy_student_id_not_null_sqlite() -> None:
    """Some legacy SQLite DBs still enforce exam_sessions.student_id NOT NULL."""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info(exam_sessions)")).fetchall()
        if not cols:
            return
        by_name = {str(c[1]): c for c in cols}
        student_col = by_name.get("student_id")
        if not student_col:
            return
        # PRAGMA columns: (cid, name, type, notnull, dflt_value, pk)
        if int(student_col[3] or 0) == 0:
            return

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS exam_sessions_new ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "student_id VARCHAR(256), "
                "professor_domain TEXT NOT NULL, "
                "education_level VARCHAR(64) NOT NULL DEFAULT '"
                + DEFAULT_EDUCATION_LEVEL_ID
                + "', "
                "use_mock_llm BOOLEAN NOT NULL DEFAULT 1, "
                "num_questions_planned INTEGER NOT NULL DEFAULT 1, "
                "current_question_index INTEGER NOT NULL DEFAULT 0, "
                "status VARCHAR(64) NOT NULL DEFAULT 'in_progress', "
                "created_at DATETIME NOT NULL, "
                "final_grade_json TEXT, "
                "grading_strictness VARCHAR(32) NOT NULL DEFAULT '"
                + DEFAULT_GRADING_STRICTNESS
                + "', "
                "student_ref_id INTEGER REFERENCES students(id) ON DELETE RESTRICT, "
                "exam_code VARCHAR(5)"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO exam_sessions_new ("
                "id, student_id, professor_domain, education_level, use_mock_llm, "
                "num_questions_planned, current_question_index, status, created_at, "
                "final_grade_json, grading_strictness, student_ref_id, exam_code"
                ") "
                "SELECT id, student_id, professor_domain, education_level, use_mock_llm, "
                "num_questions_planned, current_question_index, status, created_at, "
                "final_grade_json, grading_strictness, student_ref_id, exam_code "
                "FROM exam_sessions"
            )
        )
        conn.execute(text("DROP TABLE exam_sessions"))
        conn.execute(text("ALTER TABLE exam_sessions_new RENAME TO exam_sessions"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_exam_sessions_student_ref_id ON exam_sessions(student_ref_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_exam_sessions_exam_code ON exam_sessions(exam_code)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_exam_sessions_student_id ON exam_sessions(student_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def _backfill_exam_codes_and_enforce_unique_index() -> None:
    db = SessionLocal()
    try:
        sessions = db.query(ExamSession).order_by(ExamSession.id.asc()).all()
        seen: set[str] = set()
        changed = False
        for sess in sessions:
            code = (sess.exam_code or "").strip().upper()
            if not _is_valid_exam_code(code) or code in seen:
                sess.exam_code = generate_unique_exam_code(db, reserved=seen)
                code = sess.exam_code
                changed = True
            seen.add(code)
        if changed:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    dialect = engine.dialect.name
    with engine.begin() as conn:
        try:
            if dialect in ("sqlite", "postgresql"):
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS "
                        "ix_exam_sessions_exam_code_unique ON exam_sessions (exam_code)"
                    )
                )
            else:
                conn.execute(
                    text("CREATE UNIQUE INDEX ix_exam_sessions_exam_code_unique ON exam_sessions (exam_code)")
                )
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "duplicate" in msg:
                return
            raise


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Always ensure `students` exists. Legacy/partial DBs can have `exam_sessions.student_ref_id`
    # while migration returns early and never created `students`, which causes
    # "no such table: students" on any join to Student.
    Student.__table__.create(bind=engine, checkfirst=True)
    _migrate_sqlite_schema()
    _migrate_students_and_exam_session_fk()
    _migrate_add_nominated_exam_template_id_column()
    _backfill_exam_codes_and_enforce_unique_index()


def _migrate_add_nominated_exam_template_id_column() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "exam_sessions" not in tables:
        return
    col_names = {c["name"] for c in insp.get_columns("exam_sessions")}
    if "nominated_exam_template_id" in col_names:
        return
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            try:
                conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN nominated_exam_template_id INTEGER"))
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" not in msg and "already exists" not in msg:
                    raise
        elif dialect == "postgresql":
            conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN IF NOT EXISTS nominated_exam_template_id INTEGER"))
        else:
            try:
                conn.execute(text("ALTER TABLE exam_sessions ADD COLUMN nominated_exam_template_id INTEGER"))
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" not in msg and "already exists" not in msg:
                    raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def dumps_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
