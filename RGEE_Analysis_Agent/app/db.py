"""SQLite persistence for analysis runs (quality tracking DB — separate from main RGEE)."""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


class AnalysisRun(Base):
    """One instructor-triggered scoring job."""

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    source: Mapped[str] = mapped_column(String(128), default="rgee-main")
    methodology_note: Mapped[str] = mapped_column(Text, default="")
    question_count: Mapped[int] = mapped_column(Integer, default=0)


class AnalysisRowRecord(Base):
    """Per-question snapshot for dashboards and longitudinal quality views."""

    __tablename__ = "analysis_row_records"
    __table_args__ = (Index("ix_row_session_q", "session_id", "question_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        index=True,
    )
    session_id: Mapped[int] = mapped_column(Integer, index=True)
    question_id: Mapped[int] = mapped_column(Integer, index=True)
    row_json: Mapped[str] = mapped_column(Text)


def _engine():
    url = get_settings().agent_database_url
    connect_args = (
        {"check_same_thread": False, "timeout": 20} if url.startswith("sqlite") else {}
    )
    eng = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=20000")
            cur.close()

    return eng


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def persist_analysis_run(
    db: Session,
    *,
    source: str,
    methodology_note: str,
    rows: list[dict[str, Any]],
) -> int:
    run = AnalysisRun(
        source=source[:128],
        methodology_note=methodology_note or "",
        question_count=len(rows),
    )
    db.add(run)
    db.flush()
    rid = int(run.id)
    for r in rows:
        sid = int(r["session_id"])
        qid = int(r["question_id"])
        db.add(
            AnalysisRowRecord(
                run_id=rid,
                session_id=sid,
                question_id=qid,
                row_json=json.dumps(r, ensure_ascii=False),
            )
        )
    db.commit()
    return rid


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
