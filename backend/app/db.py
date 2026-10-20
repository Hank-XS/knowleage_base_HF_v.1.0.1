"""关系库（PostgreSQL / SQLite 内嵌回退），表结构对应设计文档 4.4 节。"""
import datetime as dt
import uuid

from sqlalchemy import (JSON, DateTime, Integer, String, Text, UniqueConstraint, create_engine)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, sessionmaker)

from .config import DATA_DIR, settings


def _engine():
    if settings.kb_pg_dsn:
        return create_engine(settings.kb_pg_dsn, pool_pre_ping=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{DATA_DIR / 'kb.sqlite3'}", connect_args={"check_same_thread": False})


engine = _engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "t_user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    pwd_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # dev/biz/arch/gov/admin
    display_name: Mapped[str] = mapped_column(String(64), default="")


class VerifiedAnswer(Base):
    """已验证答案库（长时记忆），fingerprint+scene 唯一。"""
    __tablename__ = "t_verified_answer"
    answer_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    question_norm: Mapped[str] = mapped_column(Text)
    scene_code: Mapped[str] = mapped_column(String(32), index=True)
    answer_json: Mapped[str] = mapped_column(JSON)
    sources_json: Mapped[str] = mapped_column(JSON)
    hit_type: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="verified")  # verified/pending/stale
    verified_by: Mapped[str] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kb_version: Mapped[str] = mapped_column(String(32), default="v0")
    question_emb: Mapped[str] = mapped_column(Text, default="")  # JSON 数组，相似判定用
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GovernTask(Base):
    __tablename__ = "t_govern_task"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_type: Mapped[str] = mapped_column(String(24))  # tagging / mapping_review
    title: Mapped[str] = mapped_column(String(200))
    items_json: Mapped[JSON] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/done
    operator: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class KbVersion(Base):
    __tablename__ = "t_kb_version"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_no: Mapped[str] = mapped_column(String(32), unique=True)
    change_note: Mapped[str] = mapped_column(Text, default="")
    changed_objs: Mapped[int] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class IngestJob(Base):
    __tablename__ = "t_ingest_job"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(String(32))
    object_keys: Mapped[JSON] = mapped_column(JSON, default=list)
    options_json: Mapped[JSON] = mapped_column(JSON, default=dict)
    steps: Mapped[JSON] = mapped_column(JSON, default=list)  # [{step,status,detail}]
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class QaSession(Base):
    __tablename__ = "t_qa_session"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scene_code: Mapped[str] = mapped_column(String(32), default="ATM")
    user: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class QaMessage(Base):
    __tablename__ = "t_qa_message"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(32), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer_id: Mapped[str] = mapped_column(String(32), index=True)
    hit_type: Mapped[str] = mapped_column(String(8), default="miss")
    payload_json: Mapped[JSON] = mapped_column(JSON, default=dict)  # 完整答案+溯源+trace
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "t_audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    object: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[JSON] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str] = mapped_column(String(64), default="-")


class ToolSpec(Base):
    __tablename__ = "t_tool_spec"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec_json: Mapped[JSON] = mapped_column(JSON, default=dict)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LabelVocab(Base):
    """受控标签词表：approved 可被 LLM 选用；candidate 需治理员审批。"""
    __tablename__ = "t_label_vocab"
    __table_args__ = (UniqueConstraint("category", "value", name="uk_vocab_cat_val"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), index=True)   # 功能域/业务对象/治理/技术属性/交易属性
    value: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="approved")  # approved/candidate/rejected
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PromptTemplate(Base):
    """式样书提示词配置（按 type 唯一）。"""
    __tablename__ = "t_prompt_template"
    type: Mapped[str] = mapped_column(String(32), primary_key=True)  # program/interface/batch/copybook
    title: Mapped[str] = mapped_column(String(128), default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CodeWorkResult(Base):
    """代码树：注释 / 式样书结果（本地 SQLite / PG）。"""
    __tablename__ = "t_code_work_result"
    __table_args__ = (UniqueConstraint("path", "symbol", name="uk_code_work_path_sym"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    path: Mapped[str] = mapped_column(String(512), index=True)
    symbol: Mapped[str] = mapped_column(String(128), default="")
    language: Mapped[str] = mapped_column(String(32), default="cobol")
    hint: Mapped[str] = mapped_column(String(256), default="")
    source_code: Mapped[str] = mapped_column(Text, default="")
    annotated_code: Mapped[str] = mapped_column(Text, default="")
    annotate_json: Mapped[JSON] = mapped_column(JSON, default=dict)
    prompt_type: Mapped[str] = mapped_column(String(32), default="")
    spec_markdown: Mapped[str] = mapped_column(Text, default="")
    spec_json: Mapped[JSON] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KbLibrary(Base):
    """知识库（文件夹）节点。"""
    __tablename__ = "t_kb_library"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    parent_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KbDocument(Base):
    """知识库文档主表。"""
    __tablename__ = "t_kb_document"
    __table_args__ = (UniqueConstraint("library_key", "path", name="uk_kb_doc_lib_path"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    library_key: Mapped[str] = mapped_column(String(128), index=True)
    path: Mapped[str] = mapped_column(String(512), default="")
    name: Mapped[str] = mapped_column(String(256), index=True)
    doc_type: Mapped[str] = mapped_column(String(32), default="txt")
    version: Mapped[str] = mapped_column(String(32), default="v1.0")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/review/published
    vectorized: Mapped[int] = mapped_column(Integer, default=0)
    official: Mapped[int] = mapped_column(Integer, default=1)
    security: Mapped[str] = mapped_column(String(16), default="public")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    object_key: Mapped[str] = mapped_column(String(512), default="")
    source_path: Mapped[str] = mapped_column(String(512), default="")  # hf_data 相对路径
    author: Mapped[str] = mapped_column(String(64), default="")
    tags_json: Mapped[JSON] = mapped_column(JSON, default=list)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class KbDocVersion(Base):
    """文档版本正文。"""
    __tablename__ = "t_kb_doc_version"
    __table_args__ = (UniqueConstraint("doc_id", "version", name="uk_kb_doc_ver"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    doc_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KbDocChunk(Base):
    """文档切片。"""
    __tablename__ = "t_kb_doc_chunk"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    doc_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[str] = mapped_column(String(32), default="v1.0")
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(256), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    start_offset: Mapped[int] = mapped_column(Integer, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, default=0)


def init_db() -> None:
    Base.metadata.create_all(engine)
