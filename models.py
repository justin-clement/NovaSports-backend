from pydantic import BaseModel

class NovaUser:
    nickname: str
    password: str

class NewUser:
    first_name: str
    last_name: str
    gender: str
    email: str
    phone_number: str
    nickname: str
    password: str

class Recommendation:
    league: str
    home: str
    away: str
    recommendation: str

class ID_check:
    id: str

class Subscriber: 
    nickname: str
    amount_paid: int