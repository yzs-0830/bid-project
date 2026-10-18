from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 引入資料庫
from database import database 

# 引入您的路由模組
from routers import bidding, admin, users 

# 應用程式生命週期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 啟動區 (Startup) ---
    print("🚀 系統啟動中...")
    print("🔗 正在嘗試連接資料庫 (PostgreSQL)...")
    try:
        await database.connect()
        print("✅ 資料庫連接成功！ (Database connected)")
    except Exception as e:
        print(f"❌ 資料庫連接失敗: {e}")
    
    # --- 應用程式運作中 ---
    yield 

    # --- 關閉區 (Shutdown) ---
    print("🛑 系統關閉中...")
    print("🔌 正在斷開資料庫連接...")
    await database.disconnect()
    print("👋 資料庫連接已斷開！")


# 🌟 建立 FastAPI 實例，並載入生命週期
app = FastAPI(
    title="Bid System API",
    description="高併發競標系統後端",
    version="1.0.0",
    lifespan=lifespan
)

# 設定 CORS (允許跨域請求，這對前端很重要)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(bidding.router, prefix="/api", tags=["Bidding"])
app.include_router(admin.router,  prefix="/admin", tags=["Admin"])
app.include_router(users.router,  prefix="/user", tags=["User"])

# 測試用：根路徑
@app.get("/")
async def root():
    return {"message": "Hello! Bid System is running correctly! 🚀"}
