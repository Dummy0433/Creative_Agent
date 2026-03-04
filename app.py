"""FastAPI endpoint + CLI entry point for the gift generation service."""

import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from models import GenerateRequest, GenerateResponse
from pipeline import generate
from settings import get_settings

app = FastAPI(title="Gift Service")


@app.post("/generate", response_model=GenerateResponse)
def generate_endpoint(req: GenerateRequest):
    result = generate(req.region, req.subject, req.price)
    return result


@app.post("/bot/callback")
async def bot_callback(request: Request):
    """Feishu bot event callback (challenge verification + message stub)."""
    body = await request.json()
    # Challenge verification
    if "challenge" in body:
        return JSONResponse({"challenge": body["challenge"]})
    # TODO: parse event, extract message, call generate()
    return JSONResponse({"code": 0})


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import uvicorn

        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        s = get_settings()
        generate(s.default_region, s.default_subject, s.default_price)
