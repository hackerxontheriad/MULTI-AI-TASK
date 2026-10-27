"""MAD X persistent application data.

Uses DATABASE_URL when supplied (PostgreSQL recommended for hosted deployments),
otherwise a local SQLite file. No provider credentials are stored in this database.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, create_engine, select, func
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MADX_DATA_DIR", str(BASE_DIR / "data"))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
_RAW_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if _RAW_DATABASE_URL:
    if _RAW_DATABASE_URL.startswith("postgres://"):
        _RAW_DATABASE_URL = "postgresql+psycopg://" + _RAW_DATABASE_URL[len("postgres://"):]
    elif _RAW_DATABASE_URL.startswith("postgresql://") and "+" not in _RAW_DATABASE_URL.split(":", 1)[0]:
        _RAW_DATABASE_URL = "postgresql+psycopg://" + _RAW_DATABASE_URL[len("postgresql://"):]
    DATABASE_URL = _RAW_DATABASE_URL
else:
    DATABASE_URL = f"sqlite:///{(DATA_DIR / 'madx.sqlite3').as_posix()}"

URL = make_url(DATABASE_URL)
_ENGINE_OPTIONS: dict[str, Any] = {"pool_pre_ping": True}
if URL.get_backend_name() == "sqlite":
    _ENGINE_OPTIONS["connect_args"] = {"check_same_thread": False, "timeout": 20}
    if URL.database and URL.database != ":memory:":
        Path(URL.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
engine: Engine = create_engine(DATABASE_URL, **_ENGINE_OPTIONS)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    subject: Mapped[str] = mapped_column(String(180), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(180), default="")
    role: Mapped[str] = mapped_column(String(20), default="user", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_subject: Mapped[str] = mapped_column(String(220), index=True)
    title: Mapped[str] = mapped_column(String(240))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    planner_model: Mapped[str] = mapped_column(String(240), default="")
    worker_models_json: Mapped[str] = mapped_column(Text, default="[]")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    archive_path: Mapped[str] = mapped_column(Text, default="")
    archive_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    error_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TaskRecord(Base):
    __tablename__ = "project_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    owner_subject: Mapped[str] = mapped_column(String(220), index=True)
    title: Mapped[str] = mapped_column(String(240))
    assigned_role: Mapped[str] = mapped_column(String(100), default="Worker")
    provider_route: Mapped[str] = mapped_column(String(240), default="")
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    output_summary: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str] = mapped_column(String(100), default="")
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(220), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    source_ip_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


def initialize() -> None:
    Base.metadata.create_all(engine)


def upsert_user(subject: str, email: str, name: str = "") -> None:
    with SessionLocal.begin() as db:
        row = db.get(User, subject)
        if row is None:
            db.add(User(subject=subject, email=email.lower()[:320], name=name[:180], last_seen_at=utcnow()))
        else:
            row.email = email.lower()[:320]
            row.name = name[:180]
            row.last_seen_at = utcnow()
            row.active = True


def create_project(*, owner: str, title: str, prompt: str, planner_model: str,
                   worker_models: list[str]) -> str:
    project_id = str(uuid.uuid4())
    import json
    with SessionLocal.begin() as db:
        db.add(Project(id=project_id, owner_subject=owner, title=title[:240], prompt=prompt,
                       planner_model=planner_model[:240], worker_models_json=json.dumps(worker_models)))
    return project_id


def set_project(project_id: str, owner: str, **fields: Any) -> bool:
    allowed = {"status", "file_count", "archive_path", "archive_blob", "error_summary", "title"}
    with SessionLocal.begin() as db:
        row = db.get(Project, project_id)
        if row is None or row.owner_subject != owner:
            return False
        for key, value in fields.items():
            if key in allowed:
                setattr(row, key, value)
        row.updated_at = utcnow()
    return True


def get_project(project_id: str, owner: str | None = None) -> dict[str, Any] | None:
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        if row is None or (owner is not None and row.owner_subject != owner):
            return None
        return _project_dict(row)


def get_archive(project_id: str, owner: str | None = None) -> tuple[bytes, str] | None:
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        if row is None or (owner is not None and row.owner_subject != owner):
            return None
        if row.archive_blob:
            return bytes(row.archive_blob), row.title
        if row.archive_path and row.archive_path.startswith("firebase://"):
            import firebase_files
            try:
                return firebase_files.download_project_artifact(row.archive_path), row.title
            except Exception as exc:
                raise RuntimeError("Firebase project ZIP download failed; check Storage bucket and service-account permissions.") from exc
        if row.archive_path and Path(row.archive_path).is_file():
            return Path(row.archive_path).read_bytes(), row.title
        return None


def admin_recent_projects(limit: int = 30) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.scalars(select(Project).order_by(Project.created_at.desc()).limit(min(max(limit, 1), 100))).all()
        return [{"id": r.id, "owner_subject": r.owner_subject[:12] + "…", "title": r.title,
                 "status": r.status, "file_count": r.file_count,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                 "archive_available": bool(r.archive_blob or (r.archive_path and (r.archive_path.startswith("firebase://") or Path(r.archive_path).is_file())))}
                for r in rows]


def list_projects(owner: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = select(Project).order_by(Project.created_at.desc()).limit(min(max(limit, 1), 100))
        if owner is not None:
            query = query.where(Project.owner_subject == owner)
        return [_project_dict(row) for row in db.scalars(query).all()]


def _project_dict(row: Project) -> dict[str, Any]:
    return {"id": row.id, "owner_subject": row.owner_subject, "title": row.title, "prompt": row.prompt,
            "status": row.status, "planner_model": row.planner_model, "file_count": row.file_count,
            "archive_available": bool(row.archive_blob or (row.archive_path and (row.archive_path.startswith("firebase://") or Path(row.archive_path).is_file()))),
            "error_summary": row.error_summary, "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def add_task(*, project_id: str, owner: str, title: str, role: str, route: str, prompt: str) -> str:
    task_id = str(uuid.uuid4())
    with SessionLocal.begin() as db:
        db.add(TaskRecord(id=task_id, project_id=project_id, owner_subject=owner, title=title[:240],
                          assigned_role=role[:100], provider_route=route[:240], prompt=prompt))
    return task_id


def start_task(task_id: str) -> None:
    with SessionLocal.begin() as db:
        row = db.get(TaskRecord, task_id)
        if row:
            row.status = "running"
            row.finished_at = None


def finish_task(task_id: str, *, status: str, output_summary: str = "", error_code: str = "",
                elapsed_ms: int = 0) -> None:
    with SessionLocal.begin() as db:
        row = db.get(TaskRecord, task_id)
        if row:
            row.status = status[:24]
            row.output_summary = output_summary[:6000]
            row.error_code = error_code[:100]
            row.elapsed_ms = max(0, int(elapsed_ms))
            row.finished_at = utcnow()


def list_tasks(project_id: str, owner: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = select(TaskRecord).where(TaskRecord.project_id == project_id).order_by(TaskRecord.created_at.asc()).limit(limit)
        if owner is not None:
            query = query.where(TaskRecord.owner_subject == owner)
        return [{"id": r.id, "project_id": r.project_id, "title": r.title, "role": r.assigned_role,
                 "route": r.provider_route, "status": r.status, "output_summary": r.output_summary,
                 "error_code": r.error_code, "elapsed_ms": r.elapsed_ms,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "finished_at": r.finished_at.isoformat() if r.finished_at else None}
                for r in db.scalars(query).all()]


def write_audit(actor: str, action: str, detail: str = "", source_ip_hash: str = "") -> None:
    with SessionLocal.begin() as db:
        db.add(AuditEvent(actor=actor[:220], action=action[:100], detail=detail[:1000],
                          source_ip_hash=source_ip_hash[:64]))


def admin_overview() -> dict[str, Any]:
    with SessionLocal() as db:
        return {"users": db.scalar(select(func.count()).select_from(User)) or 0,
                "active_users": db.scalar(select(func.count()).select_from(User).where(User.active.is_(True))) or 0,
                "projects": db.scalar(select(func.count()).select_from(Project)) or 0,
                "running_projects": db.scalar(select(func.count()).select_from(Project).where(Project.status == "running")) or 0,
                "tasks": db.scalar(select(func.count()).select_from(TaskRecord)) or 0,
                "failed_tasks": db.scalar(select(func.count()).select_from(TaskRecord).where(TaskRecord.status == "failed")) or 0,
                "audit_events": db.scalar(select(func.count()).select_from(AuditEvent)) or 0,
                "database_backend": URL.get_backend_name()}


def admin_recent_events(limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(max(limit, 1), 100))).all()
        return [{"actor": r.actor, "action": r.action, "detail": r.detail,
                 "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


initialize()
