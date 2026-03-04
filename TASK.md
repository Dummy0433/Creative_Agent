# Gift Service — Claude Code 实现任务书

## 目标
输入 `{"region": "MENA", "subject": "雄狮", "price": 1}` → 输出生成图，发到 Wells 飞书。

## 凭证
所有凭证从此文件读取：`/home/wells9076/.openclaw/secrets/agents/intelligence.yaml`

```python
import yaml
with open("/home/wells9076/.openclaw/secrets/agents/intelligence.yaml") as f:
    secrets = yaml.safe_load(f)

FEISHU_APP_ID     = secrets["feishu"]["app_id"]
FEISHU_APP_SECRET = secrets["feishu"]["app_secret"]
FEISHU_RECEIVE_ID = secrets["feishu"]["receive_id"]   # Wells 的 open_id
GEMINI_API_KEY    = secrets["gemini"]["api_key"]
```

---

## 项目结构

```
/home/wells9076/projects/gift-service/
├── TASK.md              ← 本文件
├── setup_tables.py      ← Phase 1：建字段 + 填 mock 数据
├── main.py              ← Phase 2：FastAPI 服务
├── requirements.txt
└── .env.example
```

---

## Bitable 表信息

| 表 | app_token | table_id | 状态 |
|----|-----------|----------|------|
| TABLE0 路由 | OeumbrA5OaLEYpsurLBlVRDegde | tbl3hLBeyvNUe91s | 空表，需建字段+填数据 |
| TABLE1 区域通用 | ZVpIbYAzXavJwPsIo7YlXBI2gJe | tblmBqweQeyO8Eis | 空表，需建字段+填数据 |
| TABLE2 区域档位 | Weqqb5u5vaqVb6sX7lXlTJjxgdK | tblyjwU9kHwQ8Yjk | 空表，需建字段+填数据 |
| TABLE3 实例层 | A4vIbpBaha7xr0soriylME5Lgke | tblxocvuizuA2W3Y | 已有14条，只读 |

---

## Phase 1：setup_tables.py

### 功能
1. 获取 Feishu tenant_access_token
2. 为 TABLE0/1/2 创建字段
3. 写入 MENA mock 数据

### TABLE0 字段设计

主字段（已存在，重命名）：`文本` → 用作 `region`
新增字段（全部 type=1 Text）：
- `archetype_app_token`
- `archetype_table_id`
- `instance_app_token`
- `instance_table_id`

### TABLE0 MENA 数据

```python
{
    "文本": "MENA",
    "archetype_app_token": "ZVpIbYAzXavJwPsIo7YlXBI2gJe",
    "archetype_table_id": "tblmBqweQeyO8Eis",
    "instance_app_token": "A4vIbpBaha7xr0soriylME5Lgke",
    "instance_table_id": "tblxocvuizuA2W3Y"
}
```

### TABLE1 字段设计

主字段（已存在）：`文本` → 用作 `region`
新增字段（全部 type=1 Text）：
- `设计风格`
- `特色物件`
- `特色图案`
- `配色原则`
- `主材质`
- `禁忌`

### TABLE1 MENA 数据

```python
{
    "文本": "MENA",
    "设计风格": "写实为主，Pixar/Disney风格渲染，高度细节感、温润质感与叙事感",
    "特色物件": "骆驼/猎鹰/Dallah咖啡壶/阿拉伯咖啡/土耳其红茶/玻璃茶杯/椰枣/库纳法/果仁蜜饼/阿拉伯长袍/头巾/香薰炉Mabkhara/项链/Darbuka鼓/邪恶之眼/法蒂玛之手/棕榈树/沙漠玫瑰",
    "特色图案": "阿拉伯书法纹样(库法体/誊抄体)/几何马赛克(星形/菱形)/植物缠枝纹(棕榈叶/无花果枝)",
    "配色原则": "以其他颜色为主，金色仅作点缀，比例约3:7；注意价效规范，低价档克制用金",
    "主材质": "丝绸质感为主基调",
    "禁忌": "清真寺不可直接出现(可虚拟化抽象化)/女性角色着装不可暴露/六芒星/显眼十字架/人物正面画像(宗教反偶像崇拜)/动物雕像可接受"
}
```

### TABLE2 字段设计

主字段（已存在）：`文本` → 用作 `region_tier`（如 "MENA_T0"）
新增字段（全部 type=1 Text）：
- `region`
- `tier`
- `价格区间`
- `允许物象`
- `禁止物象`
- `场景要求`
- `视觉质感`
- `容器备选`

### TABLE2 MENA 数据（5行，T0~T4）

```python
rows = [
    {
        "文本": "MENA_T0",
        "region": "MENA",
        "tier": "T0",
        "价格区间": "1-99",
        "允许物象": "文化手势/祈祷手势/邪恶之眼/法蒂玛之手/阿拉伯书法文字/美食(椰枣/鹰嘴豆泥/库纳法/咖啡豆)/器具(Dallah/玻璃茶杯)/足球/阿拉伯长袍/头巾/香薰炉/项链/配饰",
        "禁止物象": "动物整体/植物/自然地貌/大型场景/人物全身",
        "场景要求": "纯色背景居中，主体单独呈现，其他元素仅少量点缀",
        "视觉质感": "常规材质，弱质感，造型简单饱满不失细节",
        "容器备选": "贴纸/徽章/胸针/明信片/冰箱贴/珐琅别针/装饰补丁"
    },
    {
        "文本": "MENA_T1",
        "region": "MENA",
        "tier": "T1",
        "价格区间": "99-999",
        "允许物象": "T0全部/+乐器(Darbuka鼓)/+Shisha水烟壶/+Brass Tray",
        "禁止物象": "动物整体/植物/自然地貌",
        "场景要求": "物象单独出现或搭配简单场景(纯色背景/餐桌/盒子)",
        "视觉质感": "常规材质，遵循布料/玻璃等现实微质感，细节适度深入",
        "容器备选": "贴纸/徽章/胸针/明信片/冰箱贴/珐琅别针"
    },
    {
        "文本": "MENA_T2",
        "region": "MENA",
        "tier": "T2",
        "价格区间": "1000-2999",
        "允许物象": "T1全部/+植物(棕榈树/橄榄树/石榴树/沙漠玫瑰)",
        "禁止物象": "动物整体/自然地貌",
        "场景要求": "必须搭配简单场景(餐桌/盒子/室内陈设)",
        "视觉质感": "质感偏写实，材质种类适当增加，细节刻画深入",
        "容器备选": "装饰摆件/礼盒/装饰品"
    },
    {
        "文本": "MENA_T3",
        "region": "MENA",
        "tier": "T3",
        "价格区间": "3000-8999",
        "允许物象": "T2全部/+动物(骆驼/猎鹰)/+自然地貌(沙漠落日/绿洲)",
        "禁止物象": "无特殊限制",
        "场景要求": "必须搭配简单场景或复杂自然场景",
        "视觉质感": "质感写实，可增加贵金属/宝石/发光材质，细节刻画深入",
        "容器备选": "无需容器"
    },
    {
        "文本": "MENA_T4",
        "region": "MENA",
        "tier": "T4",
        "价格区间": "9000-29999",
        "允许物象": "T3全部/华丽场景/宫殿建筑/大型自然景观",
        "禁止物象": "无",
        "场景要求": "必须搭配华丽场景(宫殿/宏大自然)",
        "视觉质感": "质感高度写实，多材质结合，贵金属/宝石为主要表达",
        "容器备选": "无需容器"
    }
]
```

### setup_tables.py 执行逻辑

```python
# 伪代码
1. get_token()
2. for each table (TABLE0/1/2):
   a. create_fields() — POST /bitable/v1/apps/{app_token}/tables/{table_id}/fields
   b. create_record() — POST /bitable/v1/apps/{app_token}/tables/{table_id}/records
3. print("Setup complete")
```

注意：字段创建 API 需要 `base:field:create` 权限。如果 400 报错，说明权限不足，请跳过字段创建，直接用现有的"文本"主字段，将所有数据 JSON 序列化后存入"文本"字段（兼容模式）。

---

## Phase 2：main.py（FastAPI 服务）

### 依赖

```
fastapi
uvicorn
google-generativeai
pyyaml
requests
pillow
```

### 核心流程

```python
POST /generate
body: {"region": str, "subject": str, "price": int}

def generate(region, subject, price):

    # ── STEP 0: 加载凭证 ──────────────────────────
    secrets = load_yaml("/home/wells9076/.openclaw/secrets/agents/intelligence.yaml")
    feishu_token = get_feishu_token(secrets)
    gemini_key = secrets["gemini"]["api_key"]

    # ── STEP 1: 判断档位 ──────────────────────────
    tier = detect_tier(price)
    # T0: 1-99, T1: 99-999, T2: 1000-2999, T3: 3000-8999, T4: 9000-29999

    # ── STEP 2: 查路由表 (TABLE0) ─────────────────
    route = query_table0(feishu_token, region)
    # → archetype_app_token, archetype_table_id
    # → instance_app_token, instance_table_id

    # ── STEP 3: 查区域通用信息 (TABLE1) ───────────
    region_info = query_bitable(
        feishu_token,
        route["archetype_app_token"],
        route["archetype_table_id"],
        filter=f'CurrentValue.[文本] = "{region}"'
    )
    # → 设计风格/特色物件/配色原则/主材质/禁忌

    # ── STEP 4: 查档位规则 (TABLE2) ───────────────
    tier_rules = query_table2(feishu_token, region, tier)
    # → 允许物象/禁止物象/场景要求/视觉质感/容器备选

    # ── STEP 5: 主体合规判断 (纯 Python) ──────────
    subject_final = validate_subject(subject, tier_rules, region_info)
    # 逻辑：
    # - 如果 subject 属于动物/植物/地貌 而当前 tier 禁止
    # - 则 subject_final = f"{subject}{random_container}"
    # - 容器从 tier_rules["容器备选"] 中随机选一个

    # ── STEP 6: 查实例 (TABLE3，few-shot) ─────────
    instances = query_instances(
        feishu_token,
        route["instance_app_token"],
        route["instance_table_id"],
        region=region, tier=tier, limit=3
    )
    # → [{name, price, 物象I, 物象II, 风格, 材质, 设计理念}, ...]

    # ── STEP 7: Gemini 需求拆解 ───────────────────
    structured = gemini_analyze(
        api_key=gemini_key,
        model="gemini-2.0-flash",
        system=build_system_prompt(tier_rules),
        context=build_context(region_info, tier_rules),
        examples=format_instances(instances),
        user_input=f"region: {region}, subject: {subject_final}, price: {price} coins"
    )
    # 输出结构化 JSON：
    # {
    #   "subject_final": "雄狮贴纸",
    #   "color_palette": "深金色为主，配以暖棕与米白",
    #   "material": "金属质感徽章",
    #   "background": "纯黑色背景",
    #   "region_style": "细腻轻盈的MENA文化元素",
    #   "pattern": "none"
    # }

    # ── STEP 8: Gemini Prompt 生成 ────────────────
    prompts = gemini_prompt_gen(
        api_key=gemini_key,
        model="gemini-2.0-flash",
        structured_json=structured
    )
    # 输出：
    # {
    #   "prompt": "中文prompt...",
    #   "english_prompt": "English prompt..."
    # }

    # ── STEP 9: Gemini 图片生成 ───────────────────
    image_bytes = gemini_generate_image(
        api_key=gemini_key,
        model="gemini-2.0-flash-exp-image-generation",
        prompt=prompts["english_prompt"]
    )
    # 返回 PNG bytes

    # ── STEP 10: 发送到 Wells 飞书 ────────────────
    send_to_feishu(
        feishu_token=feishu_token,
        receive_id=secrets["feishu"]["receive_id"],
        image_bytes=image_bytes,
        caption=f"[礼物生成] {region} | {subject_final} | {price} coins\n\nPrompt: {prompts['prompt']}"
    )

    return {
        "subject_final": subject_final,
        "tier": tier,
        "prompt": prompts["prompt"],
        "english_prompt": prompts["english_prompt"],
        "status": "sent_to_feishu"
    }
```

### System Prompt（需求拆解用）

```
你是专业的TikTok礼物设计 Prompt 工程师。
根据用户输入和设计规范，输出结构化 JSON。

## 通用禁忌（所有区域）
- 严禁：政治/宗教娱乐化/丧葬/色情/血腥暴力/歧视
- 严禁：未经授权的IP与品牌
- 禁止：王冠/奖杯/龙/私人飞机等"尊贵"锚点
- 禁止：低幼元素（婴儿/校车/棒棒糖）
- 不得遮挡主播面部

## 输出格式（严格JSON）
{
  "subject_final": "最终主体描述",
  "color_palette": "配色自然语言描述",
  "material": "材质描述",
  "background": "背景描述",
  "region_style": "区域风格描述",
  "pattern": "yes/none"
}
```

### Prompt 生成 System Prompt

```
你是专业图片提示词生成师。
将结构化JSON转换为适合图片生成模型的单行提示词。

固定开头：保证高质量 C4D OCTANE 卡通渲染的风格，视觉重心指向右方，
整体呈三分之二正面视角（约30°-40°俯视），主体占比整体画面的95%，
主体居中且呈现完整造型非局部造型，画面背景为纯黑色的纯色块背景便于抠图。

输出严格JSON：
{
  "prompt": "完整中文提示词",
  "english_prompt": "Complete English prompt"
}
```

### Gemini 图片生成调用方式

```python
import google.generativeai as genai
from PIL import Image
import io

genai.configure(api_key=gemini_key)
model = genai.GenerativeModel("gemini-2.0-flash-exp-image-generation")
response = model.generate_content(
    prompt,
    generation_config={"response_modalities": ["image"]}
)
# 从 response 中提取图片 bytes
for part in response.candidates[0].content.parts:
    if hasattr(part, "inline_data"):
        image_bytes = part.inline_data.data
        break
```

### 飞书发图

```python
# Step 1: 上传图片获取 image_key
upload_url = "https://open.feishu.cn/open-apis/im/v1/images"
resp = requests.post(upload_url,
    headers={"Authorization": f"Bearer {feishu_token}"},
    data={"image_type": "message"},
    files={"image": ("gift.png", image_bytes, "image/png")}
)
image_key = resp.json()["data"]["image_key"]

# Step 2: 发送消息
send_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
requests.post(send_url,
    headers={"Authorization": f"Bearer {feishu_token}", "Content-Type": "application/json"},
    json={
        "receive_id": receive_id,
        "msg_type": "image",
        "content": json.dumps({"image_key": image_key})
    }
)
```

---

## 执行顺序

```bash
cd /home/wells9076/projects/gift-service

# 1. 安装依赖
pip install fastapi uvicorn google-generativeai pyyaml requests pillow

# 2. 建表 + 填数据
python setup_tables.py

# 3. 直接测试（不启动服务器，直接跑主流程）
python main.py
# 在 main.py 底部加：
# if __name__ == "__main__":
#     result = generate("MENA", "雄狮", 1)
#     print(result)
```

---

## 验收标准

- [ ] `python setup_tables.py` 运行无报错，TABLE0/1/2 有数据
- [ ] `python main.py` 运行后：
  - 雄狮（动物）在 T0 被判定超规 → 转换为容器形式（如"雄狮徽章"）
  - 输出结构化 JSON
  - 输出中英文 Prompt
  - 生成图片
  - 图片发送到 Wells 飞书
- [ ] 控制台打印完整执行日志（每步骤状态）

---

## 注意事项

1. **Bitable 查询 filter 语法**：`CurrentValue.[字段名] = "值"`
2. **字段创建失败**：如果 `base:field:create` 权限报 400，切换到兼容模式（JSON 序列化存入"文本"字段），服务代码相应处理 JSON 解析
3. **Gemini 图片生成**：如果 `gemini-2.0-flash-exp-image-generation` 不可用，fallback 到 `imagen-3.0-generate-001`
4. **所有步骤打印日志**，方便排查
