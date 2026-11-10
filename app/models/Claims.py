from pydantic import BaseModel
from datetime import datetime

class Claims(BaseModel):
    sub:str
    type:str
    version:int
    exp:datetime
    jti:str | None=None
    pwf: str |None=None