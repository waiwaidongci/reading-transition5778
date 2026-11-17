from sqlalchemy import Column,Integer,String,Text,ForeignKey,UniqueConstraint
from ..config.database import Base
from ..config.settings import CONFIG
class BackfillJob(Base):
    __tablename__=CONFIG['backfill_table']
    id=Column(Integer,primary_key=True)
    source_id=Column(Integer,ForeignKey(CONFIG['source_table']+'.id'),nullable=False)
    dict_version_id=Column(Integer,ForeignKey(CONFIG['dict_table']+'.id'),nullable=False)
    state=Column(String(20),default='queued')
    total_sessions=Column(Integer,default=0)
    processed_sessions=Column(Integer,default=0)
    last_record_id=Column(Integer,default=0)
    attempts=Column(Integer,default=0)
    error=Column(Text,default='')
    created_at=Column(String(40),nullable=False)
    updated_at=Column(String(40),nullable=False)
