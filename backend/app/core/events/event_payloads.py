from pydantic import BaseModel


class UserRegisteredPayload(BaseModel):
    user_id: int
    email: str
    role: str
