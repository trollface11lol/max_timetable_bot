from sqlalchemy import Column, BigInteger, Text, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class MaxSubscribe(Base):
    __tablename__ = "max_subscribes"

    chat_id = Column(BigInteger, primary_key=True)
    teacher_ids = Column(Text, nullable=True)
    group_ids = Column(Text, nullable=True)
    auditorium_ids = Column(Text, nullable=True)
    everyday_nots = Column(Boolean, nullable=False, default=False, server_default="false")


class SnapshotInfo(Base):
    __tablename__ = "snapshot_info"

    snapshot_id = Column(BigInteger, primary_key=True)
