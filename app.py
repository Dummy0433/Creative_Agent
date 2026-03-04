"""FastAPI 接口 + CLI 入口：礼物生成服务。"""

import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from models import GenerateRequest, GenerateResponse
from pipeline import generate
from settings import get_settings

app = FastAPI(title="Gift Service")


@app.post("/generate", response_model=GenerateResponse)
def generate_endpoint(req: GenerateRequest):
    """生成接口：接收 region / subject / price，返回生成结果。"""
    result = generate(req.region, req.subject, req.price)
    return result


@app.post("/bot/callback")
async def bot_callback(request: Request):
    """飞书机器人事件回调（challenge 验证 + 消息处理预留）。"""
    body = await request.json()
    # challenge 验证（飞书首次配置回调时会发送）
    if "challenge" in body:
        return JSONResponse({"challenge": body["challenge"]})
    # TODO: 解析事件，提取消息内容，调用 generate()
    return JSONResponse({"code": 0})


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        # 启动 FastAPI 服务: python app.py serve
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        # CLI 模式：使用默认参数直接运行 Pipeline
        s = get_settings()
        generate(s.default_region, s.default_subject, s.default_price)
