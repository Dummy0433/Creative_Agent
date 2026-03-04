#!/usr/bin/env python3
"""Phase 1 表格初始化脚本：创建字段并插入测试数据到 TABLE0/1/2。"""

import json

import requests

from feishu import get_token, _headers
from settings import get_settings

# ── 表格地址配置 ─────────────────────────────────────────────

TABLES = {
    "TABLE0": {"app_token": "OeumbrA5OaLEYpsurLBlVRDegde", "table_id": "tbl3hLBeyvNUe91s"},
    "TABLE1": {"app_token": "ZVpIbYAzXavJwPsIo7YlXBI2gJe", "table_id": "tblmBqweQeyO8Eis"},
    "TABLE2": {"app_token": "Weqqb5u5vaqVb6sX7lXlTJjxgdK", "table_id": "tblyjwU9kHwQ8Yjk"},
}

# ── 字段定义 ─────────────────────────────────────────────────

# TABLE0 路由表字段
TABLE0_FIELDS = ["archetype_app_token", "archetype_table_id", "instance_app_token", "instance_table_id"]
# TABLE1 区域原型表字段
TABLE1_FIELDS = ["设计风格", "特色物件", "特色图案", "配色原则", "主材质", "禁忌"]
# TABLE2 档位规则表字段
TABLE2_FIELDS = ["region", "tier", "价格区间", "允许物象", "禁止物象", "场景要求", "视觉质感", "容器备选"]

# ── 测试数据 ─────────────────────────────────────────────────

# TABLE0 路由数据：MENA 区域指向 TABLE1 和 TABLE3
TABLE0_DATA = {
    "文本": "MENA",
    "archetype_app_token": "ZVpIbYAzXavJwPsIo7YlXBI2gJe",
    "archetype_table_id": "tblmBqweQeyO8Eis",
    "instance_app_token": "A4vIbpBaha7xr0soriylME5Lgke",
    "instance_table_id": "tblxocvuizuA2W3Y",
}

# TABLE1 区域原型数据：MENA 区域的设计规范
TABLE1_DATA = {
    "文本": "MENA",
    "设计风格": "写实为主，Pixar/Disney风格渲染，高度细节感、温润质感与叙事感",
    "特色物件": "骆驼/猎鹰/Dallah咖啡壶/阿拉伯咖啡/土耳其红茶/玻璃茶杯/椰枣/库纳法/果仁蜜饼/阿拉伯长袍/头巾/香薰炉Mabkhara/项链/Darbuka鼓/邪恶之眼/法蒂玛之手/棕榈树/沙漠玫瑰",
    "特色图案": "阿拉伯书法纹样(库法体/誊抄体)/几何马赛克(星形/菱形)/植物缠枝纹(棕榈叶/无花果枝)",
    "配色原则": "以其他颜色为主，金色仅作点缀，比例约3:7；注意价效规范，低价档克制用金",
    "主材质": "丝绸质感为主基调",
    "禁忌": "清真寺不可直接出现(可虚拟化抽象化)/女性角色着装不可暴露/六芒星/显眼十字架/人物正面画像(宗教反偶像崇拜)/动物雕像可接受",
}

# TABLE2 档位规则数据：MENA 区域 T0-T4 各档位的设计约束
TABLE2_ROWS = [
    {
        "文本": "MENA_T0", "region": "MENA", "tier": "T0", "价格区间": "1-99",
        "允许物象": "文化手势/祈祷手势/邪恶之眼/法蒂玛之手/阿拉伯书法文字/美食(椰枣/鹰嘴豆泥/库纳法/咖啡豆)/器具(Dallah/玻璃茶杯)/足球/阿拉伯长袍/头巾/香薰炉/项链/配饰",
        "禁止物象": "动物整体/植物/自然地貌/大型场景/人物全身",
        "场景要求": "纯色背景居中，主体单独呈现，其他元素仅少量点缀",
        "视觉质感": "常规材质，弱质感，造型简单饱满不失细节",
        "容器备选": "贴纸/徽章/胸针/明信片/冰箱贴/珐琅别针/装饰补丁",
    },
    {
        "文本": "MENA_T1", "region": "MENA", "tier": "T1", "价格区间": "99-999",
        "允许物象": "T0全部/+乐器(Darbuka鼓)/+Shisha水烟壶/+Brass Tray",
        "禁止物象": "动物整体/植物/自然地貌",
        "场景要求": "物象单独出现或搭配简单场景(纯色背景/餐桌/盒子)",
        "视觉质感": "常规材质，遵循布料/玻璃等现实微质感，细节适度深入",
        "容器备选": "贴纸/徽章/胸针/明信片/冰箱贴/珐琅别针",
    },
    {
        "文本": "MENA_T2", "region": "MENA", "tier": "T2", "价格区间": "1000-2999",
        "允许物象": "T1全部/+植物(棕榈树/橄榄树/石榴树/沙漠玫瑰)",
        "禁止物象": "动物整体/自然地貌",
        "场景要求": "必须搭配简单场景(餐桌/盒子/室内陈设)",
        "视觉质感": "质感偏写实，材质种类适当增加，细节刻画深入",
        "容器备选": "装饰摆件/礼盒/装饰品",
    },
    {
        "文本": "MENA_T3", "region": "MENA", "tier": "T3", "价格区间": "3000-8999",
        "允许物象": "T2全部/+动物(骆驼/猎鹰)/+自然地貌(沙漠落日/绿洲)",
        "禁止物象": "无特殊限制",
        "场景要求": "必须搭配简单场景或复杂自然场景",
        "视觉质感": "质感写实，可增加贵金属/宝石/发光材质，细节刻画深入",
        "容器备选": "无需容器",
    },
    {
        "文本": "MENA_T4", "region": "MENA", "tier": "T4", "价格区间": "9000-29999",
        "允许物象": "T3全部/华丽场景/宫殿建筑/大型自然景观",
        "禁止物象": "无",
        "场景要求": "必须搭配华丽场景(宫殿/宏大自然)",
        "视觉质感": "质感高度写实，多材质结合，贵金属/宝石为主要表达",
        "容器备选": "无需容器",
    },
]


# ── 工具函数 ─────────────────────────────────────────────────

def create_field(token, app_token, table_id, field_name):
    """在多维表格中创建文本类型字段。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    resp = requests.post(url, headers=_headers(token), json={"field_name": field_name, "type": 1})
    if resp.status_code == 200:
        print(f"    + 字段已创建: {field_name}")
        return True
    else:
        detail = resp.json().get("msg", resp.text[:120])
        print(f"    x 字段创建失败 ({resp.status_code}): {field_name} - {detail}")
        return False


def create_record(token, app_token, table_id, fields):
    """插入一条记录（各字段独立写入）。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    resp = requests.post(url, headers=_headers(token), json={"fields": fields})
    if resp.status_code == 200:
        return True
    else:
        detail = resp.json().get("msg", resp.text[:120])
        print(f"    x 记录插入失败 ({resp.status_code}): {detail}")
        return False


def create_record_fallback(token, app_token, table_id, fields):
    """回退模式：将所有数据序列化为 JSON 存入「文本」字段。"""
    base = get_settings().feishu_base_url
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    json_str = json.dumps(fields, ensure_ascii=False)
    resp = requests.post(url, headers=_headers(token), json={"fields": {"文本": json_str}})
    if resp.status_code == 200:
        return True
    else:
        detail = resp.json().get("msg", resp.text[:120])
        print(f"    x 回退插入失败 ({resp.status_code}): {detail}")
        return False


def setup_table(token, name, app_token, table_id, field_names, records):
    """初始化单张表格：创建字段 + 插入记录。"""
    print(f"\n{'='*50}")
    print(f"[正在初始化 {name}]")
    print(f"  app_token={app_token}, table_id={table_id}")

    # 创建字段
    fields_ok = True
    print(f"  正在创建 {len(field_names)} 个字段...")
    for fname in field_names:
        if not create_field(token, app_token, table_id, fname):
            fields_ok = False

    if not fields_ok:
        print("  警告: 部分字段创建失败 -> 使用回退模式（JSON 存入文本字段）")

    # 插入记录
    print(f"  正在插入 {len(records)} 条记录...")
    for i, rec in enumerate(records):
        if fields_ok:
            # 正常模式
            ok = create_record(token, app_token, table_id, rec)
            if ok:
                print(f"    + 记录 {i+1}/{len(records)} 完成")
            else:
                # 正常模式失败，尝试回退
                print(f"    尝试回退模式: 记录 {i+1}...")
                if create_record_fallback(token, app_token, table_id, rec):
                    print(f"    + 记录 {i+1}/{len(records)} 完成（回退模式）")
        else:
            # 字段创建失败，直接用回退模式
            if create_record_fallback(token, app_token, table_id, rec):
                print(f"    + 记录 {i+1}/{len(records)} 完成（回退模式）")

    print(f"  完成: {name}")


# ── 主入口 ───────────────────────────────────────────────────

def main():
    """认证后依次初始化 TABLE0、TABLE1、TABLE2。"""
    token = get_token()

    setup_table(token, "TABLE0 (路由表)",
                TABLES["TABLE0"]["app_token"], TABLES["TABLE0"]["table_id"],
                TABLE0_FIELDS, [TABLE0_DATA])
    setup_table(token, "TABLE1 (区域原型)",
                TABLES["TABLE1"]["app_token"], TABLES["TABLE1"]["table_id"],
                TABLE1_FIELDS, [TABLE1_DATA])
    setup_table(token, "TABLE2 (档位规则)",
                TABLES["TABLE2"]["app_token"], TABLES["TABLE2"]["table_id"],
                TABLE2_FIELDS, TABLE2_ROWS)

    print(f"\n{'='*50}")
    print("初始化完成! 所有表格已配置。")


if __name__ == "__main__":
    main()
