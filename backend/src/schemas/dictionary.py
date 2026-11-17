from pydantic import BaseModel,Field
class AliasPair(BaseModel):
    old:str=Field(min_length=1,max_length=120)
    new:str=Field(min_length=1,max_length=120)
class DictVersionInput(BaseModel):
    aliases:list[AliasPair]=Field(default=list,max_length=2000)
class AliasPreviewInput(BaseModel):
    aliases:list[AliasPair]=Field(default=list,max_length=2000)
