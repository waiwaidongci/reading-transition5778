from sqlalchemy import Column,Integer,String,Text,ForeignKey
from ..config.database import Base
from ..config.settings import CONFIG
class Source(Base):
    __tablename__=CONFIG['source_table']
    id=Column(Integer,primary_key=True)
    key=Column(String(120),unique=True,nullable=False)
    name=Column(String(160),nullable=False)
    filename=Column(String(160),nullable=False)
    description=Column(Text,default='')
    active_version_id=Column(Integer,ForeignKey(CONFIG['dict_table']+'.id',use_alter=True),nullable=True)
