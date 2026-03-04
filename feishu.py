"""飞书 (Lark) API 封装：认证、多维表格查询、消息发送。"""

import json

import requests

from settings import get_settings


def get_token(app_id=None, app_secret=None):
    """获取飞书租户访问令牌 (tenant_access_token)。

    参数可选，默认从 settings 中读取。
    """
    s = get_settings()
    app_id = app_id or s.feishu_app_id
    app_secret = app_secret or s.feishu_app_secret
    resp = requests.post(
        f"{s.feishu_base_url}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    resp.raise_for_status()
    return resp.json()["tenant_access_token"]


def _headers(token):
    """构造带认证信息的请求头。"""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def query_bitable(token, app_token, table_id, filter_expr=None):
    """查询多维表格记录。

    Args:
        token: 飞书访问令牌
        app_token: 多维表格应用 token
        table_id: 表格 ID
        filter_expr: 可选的过滤表达式

    Returns:
        记录列表 (list[dict])
    """
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    params = {"page_size": 100}
    if filter_expr:
        params["filter"] = filter_expr
    resp = requests.get(url, headers=_headers(token), params=params)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("items", [])


def extract_text(fields, key="文本"):
    """从字段中提取文本值。

    飞书多维表格的文本字段可能是字符串或富文本数组，此函数统一处理。
    """
    val = fields.get(key, "")
    if isinstance(val, list):
        # 富文本格式：[{"text": "..."}, ...]
        return "".join(item.get("text", "") for item in val) if val else ""
    return str(val) if val else ""


def _is_attachment(val):
    """判断字段值是否为飞书附件数组。

    附件字段格式为 [{"file_token": "...", "name": "...", ...}, ...]
    """
    return (isinstance(val, list)
            and len(val) > 0
            and isinstance(val[0], dict)
            and "file_token" in val[0])


def parse_record(record):
    """解析多维表格记录。

    优先尝试将「文本」字段作为 JSON 解析（兼容 fallback 模式），
    失败则逐字段提取：附件数组保留原始结构，其余走 extract_text。
    """
    raw = record.get("fields", {})
    text = extract_text(raw, "文本")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    # 逐字段提取，附件字段保留原始结构
    result = {}
    for k in raw:
        val = raw[k]
        if _is_attachment(val):
            result[k] = val
        else:
            result[k] = extract_text(raw, k)
    return result


def download_media(token, url):
    """使用认证头下载飞书媒体资源，返回字节数据。

    直接使用附件元数据中返回的 url 字段（已包含 extra 鉴权参数）。
    """
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    if not resp.ok:
        ct = resp.headers.get("content-type", "")
        body = resp.json() if "json" in ct else {}
        code = body.get("code", "")
        msg = body.get("msg", resp.text[:200])
        raise RuntimeError(f"下载媒体失败 (HTTP {resp.status_code}, code={code}): {msg}")
    return resp.content


def upload_image(token, image_bytes):
    """上传图片到飞书，返回 image_key。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/images"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        data={"image_type": "message"},
        files={"image": ("gift.png", image_bytes, "image/png")},
    )
    resp.raise_for_status()
    return resp.json()["data"]["image_key"]


def send_image(token, receive_id, image_key):
    """发送图片消息，返回 message_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "image",
        "content": json.dumps({"image_key": image_key}),
    }
    resp = requests.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("message_id", "")


def send_text(token, receive_id, text):
    """发送文本消息。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    resp = requests.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()


def send_card(token, receive_id, card_content: dict):
    """发送交互卡片消息，返回 message_id。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content),
    }
    resp = requests.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("message_id", "")
