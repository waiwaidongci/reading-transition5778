from sqlalchemy import Column,Integer,String,JSON,Text,ForeignKey,UniqueConstraint
from ..config.database import Base
from ..config.settings import CONFIG
class DictVersion(Base):
    __tablename__=CONFIG['dict_table']
    __table_args__=(UniqueConstraint('source_id','version',name='uq_dict_version'),)
    id=Column(Integer,primary_key=True)
    source_id=Column(Integer,ForeignKey(CONFIG['source_table']+'.id'),nullable=False)
    version=Column(Integer,nullable=False)
    state=Column(String(20),default='building')
    aliases=Column(JSON,nullable=False)
    alias_chains=Column(JSON,nullable=False)
    signature=Column(String(64),nullable=False)
    created_by=Column(String(120),nullable=False)
    created_at=Column(String(40),nullable=False)
    published_at=Column(String(40),default='')
    error=Column(Text,default='')
