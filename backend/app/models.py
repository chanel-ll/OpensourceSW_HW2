"""SQLite schema. Note bodies live as markdown files under notes/ (Obsidian-compatible); the DB only maps them."""
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
                        UniqueConstraint, create_engine, event, inspect, text)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from .settings import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _fk_on(conn, _):
    conn.execute("PRAGMA foreign_keys=ON")

Session = sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    name_source = Column(String, default="draft")      # draft | auto (heuristic) | llm | user ; llm/user never regenerated
    kind = Column(String, default="author_group")      # author_group | institution_filter (P3) | page_parse (P3)
    org_type = Column(String, default="university")    # university | company | individual
    homepage_url = Column(String, default="")
    page_title = Column(String, default="")
    status = Column(String, default="draft")           # draft | collecting | ready | error
    status_message = Column(Text, default="")
    keywords = Column(JSON, default=list)
    include_in_world = Column(Boolean, default=False)  # P2
    created_at = Column(DateTime, default=now)
    last_updated = Column(DateTime)
    authors = relationship("Author", back_populates="source", cascade="all, delete-orphan")


class Author(Base):
    __tablename__ = "authors"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"))
    name = Column(String, nullable=False)
    affiliation = Column(String, default="")
    openalex_id = Column(String)
    s2_id = Column(String)
    dblp_pid = Column(String)       # auto-matched only when publication titles overlap
    source = relationship("Source", back_populates="authors")


class Paper(Base):
    __tablename__ = "papers"
    id = Column(Integer, primary_key=True)
    norm_title = Column(String, index=True, unique=True)
    title = Column(Text, nullable=False)
    abstract = Column(Text, default="")
    year = Column(Integer)
    pub_date = Column(String)        # YYYY-MM-DD when known
    venue = Column(String, default="")
    is_preprint = Column(Boolean, default=False)
    authors = Column(JSON, default=list)   # [{name, openalex_id, s2_id}]
    doi = Column(String)
    arxiv_id = Column(String)
    s2_id = Column(String)
    openalex_id = Column(String)
    links = Column(JSON, default=dict)     # {arxiv, pdf, doi, code, project}
    categories = Column(JSON, default=list)  # arXiv categories
    keywords = Column(JSON, default=list)    # KeyBERT
    summary = Column(JSON)                    # {one_line, contributions[], keywords[], model, created_at}
    starred = Column(Boolean, default=False)
    starred_at = Column(DateTime)              # Library sort order
    hidden = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now)
    references = Column(JSON, default=list)    # OpenAlex ids this paper cites (citation edges inside the app)
    embedding = Column(LargeBinary)            # float32 MiniLM vector of title+abstract
    subfield_id = Column(Integer, ForeignKey("subfields.id", ondelete="SET NULL"))
    subfield_pinned = Column(Boolean, default=False)  # user moved it -> reclassification keeps it
    note_file = Column(String)                 # notes/papers/<file>.md once a memo exists


class Field(Base):
    __tablename__ = "fields"
    id = Column(Integer, primary_key=True)
    name = Column(String, default="")
    name_locked = Column(Boolean, default=False)  # user renamed -> kept across reclassification


class Subfield(Base):
    __tablename__ = "subfields"
    id = Column(Integer, primary_key=True)
    field_id = Column(Integer, ForeignKey("fields.id", ondelete="SET NULL"))
    name = Column(String, default="")
    name_locked = Column(Boolean, default=False)
    field_pinned = Column(Boolean, default=False)  # user moved/merged it into a field


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    status = Column(String, default="아이디어")  # 아이디어 | 진행 중 | 투고 준비 | 완료
    folder = Column(String, nullable=False)     # notes/projects/<folder>/
    created_at = Column(DateTime, default=now)
    updated_at = Column(DateTime, default=now)


class AppMeta(Base):
    """Small key/value store, e.g. which model produced the stored keywords/embeddings."""
    __tablename__ = "app_meta"
    key = Column(String, primary_key=True)
    value = Column(Text)


class LibraryGroup(Base):
    """User-made groups for starred papers; a paper may sit in several groups."""
    __tablename__ = "library_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=now)


class LibraryItem(Base):
    __tablename__ = "library_items"
    group_id = Column(Integer, ForeignKey("library_groups.id", ondelete="CASCADE"), primary_key=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(DateTime, default=now)


class ProjectReference(Base):
    __tablename__ = "project_references"
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String, default="관련 연구")  # 베이스라인 | 관련 연구 | 방법론 참고 | 데이터셋
    memo = Column(Text, default="")
    added_at = Column(DateTime, default=now)


class PaperSource(Base):
    __tablename__ = "paper_sources"
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)


class UpdateRun(Base):
    __tablename__ = "update_runs"
    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=now)
    finished_at = Column(DateTime)
    status = Column(String, default="running")  # running | ok | partial | error
    trigger = Column(String, default="manual")  # manual | auto
    errors = Column(JSON, default=list)


class PaperChange(Base):
    __tablename__ = "paper_changes"
    __table_args__ = (UniqueConstraint("run_id", "paper_id", "kind"),)
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("update_runs.id", ondelete="CASCADE"), index=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"))
    source_id = Column(Integer, ForeignKey("sources.id", ondelete="SET NULL"))
    kind = Column(String)            # NEW | ACCEPTED | UPDATED
    detail = Column(Text, default="")
    read = Column(Boolean, default=False)


Base.metadata.create_all(engine)


def _add_missing_columns():
    """create_all never alters existing tables; add new nullable columns so older DBs keep working."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(engine.dialect)
                    default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                    extra = f" DEFAULT {int(default) if isinstance(default, bool) else repr(default)}" if default is not None and not isinstance(default, (list, dict)) else ""
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}{extra}'))


_add_missing_columns()
