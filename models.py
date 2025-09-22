from pydantic import BaseModel

class NovaUser(BaseModel):
    nickname: str
    password: str

class NewUser(BaseModel):
    first_name: str
    last_name: str
    gender: str
    email: str
    phone_number: str
    nickname: str
    password: str

class Recommendation(BaseModel):
    league: str
    home: str
    away: str
    recommendation: str

class Subscriber(BaseModel): 
    nickname: str
    amount_paid: int