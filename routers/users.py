from fastapi import APIRouter
from pydantic import BaseModel
import random
from data import members

router = APIRouter()

class UserReq(BaseModel):
    username: str

@router.post("/register")
def register(req: UserReq):
    if req.username in members:
        return {"status": "fail", "message": "用戶已存在"}

    members[req.username] = {"weight": 0, "wins": 0}

    return {"status": "ok", "weight": 0, "wins": 0}

@router.post("/login")
def login(req: UserReq):
    if req.username not in members:
        return {"status": "fail", "message": "用戶不存在! 請先點擊註冊"}

    return {"status": "ok", "weight": members[req.username]["weight"]}
