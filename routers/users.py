from fastapi import APIRouter
from pydantic import BaseModel
import sqlalchemy
from database import database, members_table

router = APIRouter()

class UserReq(BaseModel):
    username: str

@router.post("/register")
async def register(req: UserReq):
    # 1. 檢查用戶是否已存在 (SELECT)
    query = sqlalchemy.select(members_table).where(members_table.c.user_id == req.username)
    existing_user = await database.fetch_one(query)

    if existing_user:
        return {"status": "fail", "message": "用戶已存在"}

    # 2. 寫入新用戶 (INSERT)
    # 預設 weight=0, wins=0
    insert_query = members_table.insert().values(
        user_id=req.username,
        weight=0,
        wins=0
    )
    await database.execute(insert_query)

    return {"status": "ok", "weight": 0, "wins": 0}

@router.post("/login")
async def login(req: UserReq):
    # 1. 查詢用戶資料 (SELECT)
    query = sqlalchemy.select(members_table).where(members_table.c.user_id == req.username)
    user = await database.fetch_one(query)

    if not user:
        return {"status": "fail", "message": "用戶不存在! 請先點擊註冊"}

    # 2. 回傳資料庫中的真實 weight
    # user 是一個 Record 物件，可以像字典一樣取值
    return {"status": "ok", "weight": user["weight"]}
