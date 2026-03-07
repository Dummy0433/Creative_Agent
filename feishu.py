"""飞书 (Lark) API 封装：认证、多维表格查询、消息发送。

提供 async 版本（供 pipeline 使用）和 sync 便捷函数（供 bot_ws 等同步调用方使用）。
"""

import json
import logging
import threading
import time

import httpx

from settings import get_settings

logger = logging.getLogger(__name__)

# ── Token 缓存（进程内单例）──────────────────────────────────
_token_cache: dict[str, tuple[str, float]] = {}  # {cache_key: (token, expire_time)}
_token_lock = threading.Lock()
_TOKEN_TTL = 5400  # 缓存 90 分钟（飞书 token 有效期 2 小时，留 30 分钟缓冲）

# 所有 HTTP 请求的默认超时（秒）
_DEFAULT_TIMEOUT = 30


def _new_async_client(**kwargs) -> httpx.AsyncClient:
    """创建 async HTTP 客户端（每次调用新建，避免 event loop 关闭问题）。"""
    timeout = kwargs.pop("timeout", _DEFAULT_TIMEOUT)
    return httpx.AsyncClient(timeout=timeout, **kwargs)


# ── Async API ────────────────────────────────────────────────


async def get_token(app_id=None, app_secret=None):
    """获取飞书租户访问令牌 (tenant_access_token)，带缓存。"""
    s = get_settings()
    app_id = app_id or s.feishu_app_id
    app_secret = app_secret or s.feishu_app_secret
    cache_key = f"{app_id}:{app_secret}"

    with _token_lock:
        cached = _token_cache.get(cache_key)
        if cached:
            token, expire_at = cached
            if time.time() < expire_at:
                return token

    async with _new_async_client() as client:
        resp = await client.post(
            f"{s.feishu_base_url}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
    resp.raise_for_status()
    token = resp.json()["tenant_access_token"]

    with _token_lock:
        _token_cache[cache_key] = (token, time.time() + _TOKEN_TTL)
    logger.debug("[飞书] 获取新 token 成功")
    return token


def _headers(token):
    """构造带认证信息的请求头。"""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def query_bitable(token, app_token, table_id, filter_expr=None, view_id=None):
    """查询多维表格记录。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    params = {"page_size": 100}
    if filter_expr:
        params["filter"] = filter_expr
    if view_id:
        params["view_id"] = view_id
    async with _new_async_client() as client:
        resp = await client.get(url, headers=_headers(token), params=params)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("items", [])


def extract_text(fields, key="文本"):
    """从字段中提取文本值（纯内存操作，保持同步）。"""
    val = fields.get(key, "")
    if isinstance(val, list):
        return "".join(item.get("text", "") for item in val) if val else ""
    return str(val) if val else ""


def _is_attachment(val):
    """判断字段值是否为飞书附件数组。"""
    return (isinstance(val, list)
            and len(val) > 0
            and isinstance(val[0], dict)
            and "file_token" in val[0])


def parse_record(record):
    """解析多维表格记录（纯内存操作，保持同步）。"""
    raw = record.get("fields", {})
    text = extract_text(raw, "文本")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    result = {}
    for k in raw:
        val = raw[k]
        if _is_attachment(val):
            result[k] = val
        else:
            result[k] = extract_text(raw, k)
    return result


async def download_media(token, url):
    """使用认证头下载飞书媒体资源，返回字节数据。"""
    async with _new_async_client(timeout=60) as client:
        resp = await client.get(
            url, headers={"Authorization": f"Bearer {token}"},
        )
    if not resp.is_success:
        ct = resp.headers.get("content-type", "")
        body = resp.json() if "json" in ct else {}
        code = body.get("code", "")
        msg = body.get("msg", resp.text[:200])
        raise RuntimeError(f"下载媒体失败 (HTTP {resp.status_code}, code={code}): {msg}")
    return resp.content


async def upload_image(token, image_bytes):
    """上传图片到飞书，返回 image_key。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/images"
    is_png = image_bytes[:4] == b'\x89PNG'
    logger.info("[上传图片] 准备上传: %d bytes, PNG=%s", len(image_bytes), is_png)
    async with _new_async_client() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": ("gift.png", image_bytes, "image/png")},
        )
    resp.raise_for_status()
    resp_json = resp.json()
    logger.info("[上传图片] 飞书响应: %s", resp_json)
    data = resp_json.get("data", {})
    image_key = data.get("image_key")
    if not image_key:
        raise RuntimeError(f"飞书上传图片响应中缺少 image_key: {resp.text[:300]}")
    return image_key


async def send_image(token, receive_id, image_key):
    """发送图片消息，返回 message_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "image",
        "content": json.dumps({"image_key": image_key}),
    }
    async with _new_async_client() as client:
        resp = await client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("message_id", "")


async def send_text(token, receive_id, text):
    """发送文本消息。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    async with _new_async_client() as client:
        resp = await client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()


async def upload_file(token, file_bytes, file_name="gift.png"):
    """上传文件到飞书，返回 file_key（保留原始格式，不压缩）。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/files"
    async with _new_async_client() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={"file_type": "stream", "file_name": file_name},
            files={"file": (file_name, file_bytes, "application/octet-stream")},
        )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    file_key = data.get("file_key")
    if not file_key:
        raise RuntimeError(f"飞书上传文件响应中缺少 file_key: {resp.text[:300]}")
    return file_key


async def send_file(token, receive_id, file_key):
    """发送文件消息，返回 message_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "file",
        "content": json.dumps({"file_key": file_key}),
    }
    async with _new_async_client() as client:
        resp = await client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("message_id", "")


async def send_card(token, receive_id, card_content: dict):
    """发送交互卡片消息，返回 message_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content),
    }
    async with _new_async_client() as client:
        resp = await client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("message_id", "")


async def create_bitable_record(token, app_token, table_id, fields: dict):
    """在多维表格中创建一条记录，返回 record_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    body = {"fields": fields}
    async with _new_async_client() as client:
        resp = await client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    record_id = data.get("record", {}).get("record_id", "")
    return record_id


# ── Sync 便捷函数（供 bot_ws.py 等同步调用方使用）────────────
# Lark SDK 内部有 event loop，不能用 asyncio.run() 桥接。
# 因此 sync 函数直接使用 httpx 同步客户端。


def _sync_client() -> httpx.Client:
    """获取临时同步 HTTP 客户端。"""
    return httpx.Client(timeout=_DEFAULT_TIMEOUT)


def get_token_sync(app_id=None, app_secret=None):
    s = get_settings()
    app_id = app_id or s.feishu_app_id
    app_secret = app_secret or s.feishu_app_secret
    cache_key = f"{app_id}:{app_secret}"

    with _token_lock:
        cached = _token_cache.get(cache_key)
        if cached:
            token, expire_at = cached
            if time.time() < expire_at:
                return token

    with _sync_client() as client:
        resp = client.post(
            f"{s.feishu_base_url}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
    resp.raise_for_status()
    token = resp.json()["tenant_access_token"]

    with _token_lock:
        _token_cache[cache_key] = (token, time.time() + _TOKEN_TTL)
    logger.debug("[飞书] 获取新 token 成功 (sync)")
    return token


def query_bitable_sync(token, app_token, table_id, filter_expr=None, view_id=None):
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    params = {"page_size": 100}
    if filter_expr:
        params["filter"] = filter_expr
    if view_id:
        params["view_id"] = view_id
    with _sync_client() as client:
        resp = client.get(url, headers=_headers(token), params=params)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("items", [])


def download_media_sync(token, url):
    with httpx.Client(timeout=60) as client:
        resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
    if not resp.is_success:
        ct = resp.headers.get("content-type", "")
        body = resp.json() if "json" in ct else {}
        code = body.get("code", "")
        msg = body.get("msg", resp.text[:200])
        raise RuntimeError(f"下载媒体失败 (HTTP {resp.status_code}, code={code}): {msg}")
    return resp.content


def upload_image_sync(token, image_bytes):
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/images"
    with _sync_client() as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={"image_type": "message"},
            files={"image": ("gift.png", image_bytes, "image/png")},
        )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    image_key = data.get("image_key")
    if not image_key:
        raise RuntimeError(f"飞书上传图片响应中缺少 image_key: {resp.text[:300]}")
    return image_key


def send_image_sync(token, receive_id, image_key):
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "image",
        "content": json.dumps({"image_key": image_key}),
    }
    with _sync_client() as client:
        resp = client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("message_id", "")


def send_text_sync(token, receive_id, text):
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    with _sync_client() as client:
        resp = client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()


def upload_file_sync(token, file_bytes, file_name="gift.png"):
    """上传文件到飞书（sync），返回 file_key。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/files"
    with _sync_client() as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={"file_type": "stream", "file_name": file_name},
            files={"file": (file_name, file_bytes, "application/octet-stream")},
        )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    file_key = data.get("file_key")
    if not file_key:
        raise RuntimeError(f"飞书上传文件响应中缺少 file_key: {resp.text[:300]}")
    return file_key


def send_file_sync(token, receive_id, file_key):
    """发送文件消息（sync），返回 message_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "file",
        "content": json.dumps({"file_key": file_key}),
    }
    with _sync_client() as client:
        resp = client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("message_id", "")


def send_card_sync(token, receive_id, card_content):
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content),
    }
    with _sync_client() as client:
        resp = client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("message_id", "")


def update_card_sync(token, message_id, card_content):
    """通过 PATCH 更新已发送的卡片消息内容。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages/{message_id}"
    body = {"content": json.dumps(card_content)}
    with _sync_client() as client:
        resp = client.patch(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json()


def delete_message_sync(token, message_id):
    """删除指定消息。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages/{message_id}"
    with _sync_client() as client:
        resp = client.delete(url, headers=_headers(token))
    resp.raise_for_status()
    return resp.json()


def create_bitable_record_sync(token, app_token, table_id, fields: dict):
    """在多维表格中创建一条记录（sync），返回 record_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    body = {"fields": fields}
    with _sync_client() as client:
        resp = client.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    record_id = data.get("record", {}).get("record_id", "")
    return record_id
