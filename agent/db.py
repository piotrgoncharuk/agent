"""Схема БД (SQLite → PostgreSQL без изменений кода, только DATABASE_URL)."""
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .settings import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Stage(StrEnum):
    """Этапы CRM-воронки (М6)."""
    NEW = "new"                # собран
    QUALIFIED = "qualified"    # прошёл скоринг
    DRAFTED = "drafted"        # отклик подготовлен
    SENT = "sent"              # отправлен владельцем
    REPLIED = "replied"        # клиент ответил
    INTERVIEW = "interview"    # переговоры
    WON = "won"                # контракт
    DELIVERED = "delivered"    # сдан
    REVIEWED = "reviewed"      # получен отзыв
    LOST = "lost"
    SKIPPED = "skipped"        # отклонён скорингом или владельцем


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("platform", "external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(1024), default="")
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(4), default="en")
    budget_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_type: Mapped[str] = mapped_column(String(16), default="unknown")  # fixed | hourly | unknown
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    client_info: Mapped[dict] = mapped_column(JSON, default=dict)  # рейтинг, траты, верификация, страна
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_details: Mapped[dict] = mapped_column(JSON, default=dict)
    service_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    stage: Mapped[Stage] = mapped_column(Enum(Stage), default=Stage.NEW, index=True)
    stage_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    contract_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    proposals: Mapped[list["Proposal"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    events: Mapped[list["StageEvent"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    language: Mapped[str] = mapped_column(String(4))
    text: Mapped[str] = mapped_column(Text)
    questions: Mapped[list] = mapped_column(JSON, default=list)  # уточняющие вопросы клиенту
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_note: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    approved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="proposals")


class StageEvent(Base):
    __tablename__ = "stage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    from_stage: Mapped[Stage | None] = mapped_column(Enum(Stage), nullable=True)
    to_stage: Mapped[Stage] = mapped_column(Enum(Stage))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[Job] = relationship(back_populates="events")


def make_session_factory(url: str | None = None) -> sessionmaker:
    url = url or get_settings().database_url
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
