"""Feishu (Lark) API: authentication, Bitable queries, messaging."""

import json

import requests

from settings import get_settings


def get_token(app_id=None, app_secret=None):
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
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def query_bitable(token, app_token, table_id, filter_expr=None):
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    params = {"page_size": 100}
    if filter_expr:
        params["filter"] = filter_expr
    resp = requests.get(url, headers=_headers(token), params=params)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("items", [])


def extract_text(fields, key="文本"):
    val = fields.get(key, "")
    if isinstance(val, list):
        return "".join(item.get("text", "") for item in val) if val else ""
    return str(val) if val else ""


def parse_record(record):
    """Try to parse record as JSON-in-text-field (fallback mode)."""
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
        result[k] = extract_text(raw, k)
    return result


def upload_image(token, image_bytes):
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
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/im/v1/messages?receive_id_type=open_id"
    body = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    resp = requests.post(url, headers=_headers(token), json=body)
    resp.raise_for_status()
