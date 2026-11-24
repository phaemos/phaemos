from sqlalchemy import Column, DateTime, Integer, func

from app.db import Base


class ModelSigningRecord(Base):
    """
    One row, written when a signed anomaly model has been saved on this deployment (migration 030).

    The model file is signed and an unsigned old-format bundle is accepted only while no signed one has ever been saved.
    The markers beside the file cannot show that to someone who can write the whole model folder, so the fact is also kept
    here, in the database, which that person cannot reach by writing files.
    """

    __tablename__ = "model_signing"

    # always 1: the table holds a single row
    id        = Column(Integer, primary_key=True, default=1)
    first_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
