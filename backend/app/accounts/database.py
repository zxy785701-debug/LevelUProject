from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, String, Integer, Double, DateTime, JSON, ForeignKey, UniqueConstraint, LargeBinary
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from ..errors import AppError


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity: Mapped[str] = mapped_column(String(64), unique=True)
    appid: Mapped[str] = mapped_column(String(64, collation='utf8mb4_bin'))
    openid: Mapped[str] = mapped_column(String(128, collation='utf8mb4_bin'))
    unionid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nickname: Mapped[str] = mapped_column(String(32), default='好奇心同学')
    xp: Mapped[int] = mapped_column(Integer, default=0)
    coins: Mapped[int] = mapped_column(Integer, default=0)
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    avatar_version: Mapped[int] = mapped_column(Integer, default=0)
    agreement_version: Mapped[str] = mapped_column(String(32))
    consent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint('appid', 'openid', name='uq_wechat_identity'),)


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class QuizRow(Base):
    __tablename__ = 'quizzes'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    content: Mapped[dict] = mapped_column(JSON)


class Attempt(Base):
    __tablename__ = 'learning_attempts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    quiz_id: Mapped[str | None] = mapped_column(ForeignKey('quizzes.id', ondelete='CASCADE'), nullable=True)
    quiz: Mapped[dict] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(12))
    answers: Mapped[list] = mapped_column(JSON, default=list)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    review_keys: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report_attempts: Mapped[int] = mapped_column(Integer, default=0)


class Reward(Base):
    __tablename__ = 'reward_ledger'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    quiz_id: Mapped[str] = mapped_column(ForeignKey('quizzes.id', ondelete='CASCADE'))
    question_id: Mapped[str] = mapped_column(String(128))
    xp: Mapped[int] = mapped_column(Integer)
    coins: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint('user_id', 'quiz_id', 'question_id', name='uq_question_reward'),)


class WrongRow(Base):
    __tablename__ = 'wrong_questions'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    key: Mapped[str] = mapped_column(String(180), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey('learning_attempts.id', ondelete='CASCADE'))
    question_id: Mapped[str] = mapped_column(String(128))
    mastered: Mapped[int] = mapped_column(Integer, default=0)
    reviews: Mapped[list] = mapped_column(JSON, default=list)


class Quota(Base):
    __tablename__ = 'ai_quotas'
    identity: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[str] = mapped_column(String(10))
    quiz_count: Mapped[int] = mapped_column(Integer, default=0)
    calls: Mapped[list] = mapped_column(JSON, default=list)
    busy_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    busy_until: Mapped[float] = mapped_column(Double, default=0)
    retire_after: Mapped[float | None] = mapped_column(Double, nullable=True, index=True)


class Operation(Base):
    __tablename__ = 'ai_operations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    key: Mapped[str] = mapped_column(String(128, collation='utf8mb4_bin'))
    digest: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(12))
    attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default='running')
    charged: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint('user_id', 'key', name='uq_user_operation'),)


class Database:
    def __init__(self, settings):
        self.settings = settings
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            if not self.settings.mysql_user:
                raise AppError('MYSQL_NOT_CONFIGURED', '请先配置 MySQL 数据库', 503)
            name = self.settings.mysql_test_database if self.settings.database_testing else self.settings.mysql_database
            url = URL.create('mysql+pymysql', username=self.settings.mysql_user, password=self.settings.mysql_password.get_secret_value(), host=self.settings.mysql_host, port=self.settings.mysql_port, database=name, query={'charset': 'utf8mb4'})
            self._engine = create_engine(url, pool_pre_ping=True, isolation_level='READ COMMITTED', connect_args={'connect_timeout': 5}, hide_parameters=True)
        return self._engine

    def session(self):
        return sessionmaker(self.engine, expire_on_commit=False).begin()

    def migrate(self):
        from alembic.config import Config
        from alembic import command
        config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
        with self.engine.begin() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
