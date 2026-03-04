"""TABLE0-3 Bitable queries."""

import feishu
from settings import get_settings


def query_table0(token: str, region: str) -> dict:
    s = get_settings()
    print(f"\n[STEP 2] Querying TABLE0 (routing) for region={region}...")
    records = feishu.query_bitable(token, s.table0_app_token, s.table0_table_id)
    for rec in records:
        data = feishu.parse_record(rec)
        region_val = data.get("文本", "")
        if region_val == region or data.get("region") == region:
            print(f"  Found route for {region}")
            return data
    raise RuntimeError(f"Region '{region}' not found in TABLE0")


def query_region_info(token: str, app_token: str, table_id: str, region: str) -> dict:
    print(f"\n[STEP 3] Querying TABLE1 (region info) for region={region}...")
    records = feishu.query_bitable(token, app_token, table_id)
    for rec in records:
        data = feishu.parse_record(rec)
        region_val = data.get("文本", "")
        if region_val == region or data.get("region") == region:
            print(f"  Found region info for {region}")
            return data
    raise RuntimeError(f"Region '{region}' not found in TABLE1")


def query_tier_rules(token: str, region: str, tier: str) -> dict:
    s = get_settings()
    region_tier = f"{region}_{tier}"
    print(f"\n[STEP 4] Querying TABLE2 (tier rules) for {region_tier}...")
    records = feishu.query_bitable(token, s.table2_app_token, s.table2_table_id)
    for rec in records:
        data = feishu.parse_record(rec)
        text_val = data.get("文本", "")
        if text_val == region_tier:
            print(f"  Found tier rules for {region_tier}")
            return data
    raise RuntimeError(f"Tier rules for '{region_tier}' not found in TABLE2")


def query_instances(token: str, app_token: str, table_id: str, region: str, tier: str, limit: int = 3) -> list[dict]:
    print(f"\n[STEP 6] Querying TABLE3 (instances) for few-shot examples...")
    records = feishu.query_bitable(token, app_token, table_id)
    instances = []
    for rec in records:
        data = feishu.parse_record(rec)
        instances.append(data)
        if len(instances) >= limit:
            break
    print(f"  Found {len(instances)} instance(s)")
    return instances
