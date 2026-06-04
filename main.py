import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, Any
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()

from middleware.x402_middleware import X402Middleware
from agents.orchestrator import run_pipeline

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(title="DataForge API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET","POST"], allow_headers=["*"])
app.add_middleware(X402Middleware,
    pay_to=os.getenv("WALLET_ADDRESS","0xYourWallet"),
    amount_usdc=os.getenv("PRICE_USDC","0.001"),
    network=os.getenv("NETWORK","base-sepolia"),
    protected_paths=["/format","/batch"],
    facilitator_url=os.getenv("X402_FACILITATOR","https://x402.org/facilitator"),
)

class FormatRequest(BaseModel):
    data: Any
    target_schema: Optional[dict] = None
    output_format: Optional[str] = "json"

class BatchRequest(BaseModel):
    records: list[Any] = Field(..., max_length=5)
    target_schema: Optional[dict] = None
    output_format: Optional[str] = "json"

@app.get("/health")
async def health():
    return {"status":"ok","version":"1.0.0"}

@app.get("/price")
async def price_info():
    return {"price_usdc":os.getenv("PRICE_USDC","0.001"),
            "network":os.getenv("NETWORK","base-sepolia"),
            "pay_to":os.getenv("WALLET_ADDRESS","0xYourWallet")}

@app.post("/format")
async def format_data(body: FormatRequest):
    return await run_pipeline(body.data, body.target_schema, body.output_format)

@app.post("/batch")
async def batch_format(body: BatchRequest):
    results = [await run_pipeline(r, body.target_schema, body.output_format) for r in body.records]
    return {"count":len(results),"results":results}

@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error":str(exc)})
