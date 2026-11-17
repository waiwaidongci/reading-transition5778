from sqlalchemy import Column,Integer,String,ForeignKey,UniqueConstraint
from ..config.database import Base
from ..config.settings import CONFIG
class NormalizedSession(Base):
    __tablename__=CONFIG['normalized_table']
    __table_args__=(UniqueConstraint('dict_version_id','record_id',name='uq_normalized_record'),)
    id=Column(Integer,primary_key=True)
    dict_version_id=Column(Integer,ForeignKey(CONFIG['dict_table']+'.id'),nullable=False)
    record_id=Column(Integer,ForeignKey(CONFIG['record_table']+'.id'),nullable=False)
    canonical_path=Column(String(2000),nullable=False)
