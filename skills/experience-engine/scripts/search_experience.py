"""
检索经验脚本
用法: python search_experience.py <query> [scene_id] [--product-name <product_name>]

必填参数:
  query           检索关键词（空格分隔的关键词/短语）

可选参数:
  scene_id        场景ID
  --product-name  产品名称（从场景 reference 中读取，默认不限制产品）

调用人工号通过 getpass.getuser() 自动获取，默认检索同场景下各用户的经验。
"""

import argparse
import getpass
import sys
import json
import urllib.request
import urllib.error

BASE_URL = "https://fuyao.rnd.huawei.com"
DEFAULT_SCENE_ID = ""
SEARCH_FIELD = "rag_search_text"
TOP_K = 5
SCORE_THRESHOLD = 0.3


def search_experience(query: str, scene_id: str = "", user_id: str = "", *,
                      product_name: str = "") -> dict:
    scene_id = (scene_id or DEFAULT_SCENE_ID).strip()
    product_name = (product_name or "").strip()
    user_id = user_id.strip()

    if not scene_id:
        return {"code": 400, "msg": "scene_id 未提供，请在对应场景的 reference 中配置 scene_id", "data": None}

    try:
        caller_id = getpass.getuser().strip()
    except Exception as e:
        return {"code": 400, "msg": f"无法自动获取调用人工号: {e}", "data": None}
    if not caller_id:
        return {"code": 400, "msg": "自动获取的调用人工号为空，请检查系统用户名", "data": None}

    payload = {
        "scene_id": scene_id,
        "caller_id": caller_id,
        "query": query,
        "search_field": SEARCH_FIELD,
        "top_k": TOP_K,
        "score_threshold": SCORE_THRESHOLD,
    }
    if product_name:
        payload["product"] = {"product_name": product_name}
    if user_id:
        payload["user_id"] = user_id

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/memory/experience/doc/search",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"code": e.code, "msg": f"HTTP {e.code}: {body}", "data": None}
    except Exception as e:
        return {"code": 500, "msg": str(e), "data": None}


def print_search_input(query: str, scene_id: str, product_name: str):
    """打印检索输入"""
    print("=" * 60)
    print("【经验检索输入】")
    print(f"query: {query}")
    print(f"scene_id: {scene_id}")
    print(f"product_name: {product_name or '不限制产品'}")
    print(f"score_threshold: {SCORE_THRESHOLD}")
    print(f"top_k: {TOP_K}")
    print("=" * 60)


def print_search_result(result: dict):
    """打印检索返回"""
    print("【经验检索返回】")

    if result.get("code") != 200:
        print(f"检索失败: code={result.get('code')}, msg={result.get('msg')}")
        print("=" * 60)
        return

    data = result.get("data") or {}
    items = data.get("items") or []
    total_candidates = data.get("total_candidates", 0)
    total_ranked = data.get("total_ranked", 0)

    print(f"召回候选数: {total_candidates}")
    print(f"通过阈值数: {total_ranked}")
    print(f"返回条数: {len(items)}")

    if not items:
        if total_candidates > 0 and total_ranked == 0:
            print(f"⚠️  有 {total_candidates} 条候选被阈值 {SCORE_THRESHOLD} 过滤，可考虑降低阈值")
        else:
            print("未命中任何经验")
        print("=" * 60)
        return

    for i, item in enumerate(items, 1):
        print(f"\n--- 第 {i} 条 ---")
        print(f"title: {item.get('title', '')}")
        print(f"summary: {item.get('summary', '')}")
        print(f"score: {item.get('score', '')}")
        experience = item.get("experience", "")
        if experience:
            print(f"experience:\n{experience}")
        rag_text = item.get("rag_search_text", "")
        if rag_text:
            print(f"rag_search_text: {rag_text}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="按场景检索历史经验，产品名称过滤可选，调用人工号自动获取")
    parser.add_argument("query", help="检索关键词，空格分隔的关键词/短语")
    parser.add_argument("scene_id", nargs="?", default="", help="场景ID，从场景 reference 中读取")
    parser.add_argument("--product-name", default="", help="产品名称，从场景 reference 中读取，默认不限制产品")
    args = parser.parse_args()

    query = args.query
    effective_scene_id = (args.scene_id or DEFAULT_SCENE_ID).strip()
    product_name = args.product_name.strip()

    # 打印检索输入
    print_search_input(query, effective_scene_id, product_name)

    # 执行检索
    result = search_experience(query, effective_scene_id, product_name=product_name)

    # 打印检索返回
    print_search_result(result)

    # 输出原始 JSON
    print("\n【原始返回 JSON】")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("code") == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
