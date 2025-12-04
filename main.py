from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import database, members_table, products_table 

from routers import bidding, admin, users 


# 🌟 處理應用程式生命週期 (替代已棄用的 @app.on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動時連接資料庫
    print("Database connecting...")
    try:
        await database.connect()
        print("Database connected successfully!")
    except Exception as e:
        print(f"Database connection failed: {e}")
    
    # yield 之後應用程式開始處理請求
    yield 

    # 關閉時斷開連接
    print("Database disconnecting...")
    await database.disconnect()
    print("Database disconnected!")


# 🌟 將 lifespan 傳給 FastAPI 實例
app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bidding.router, prefix="/api")
app.include_router(admin.router,  prefix="/admin")
app.include_router(users.router,  prefix="/user")
