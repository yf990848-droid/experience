"""通过同目录 coreinsight-cli.exe 检索经验（Python 3.9+，仅标准库）。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

CLI_PATH = Path(__file__).resolve().with_name("coreinsight-cli.exe")
SEARCH_FIELD = "rag_search_text"
PAGE_SIZE = 5
REQUEST_TIMEOUT = 120


def search_experience(query: str, scene: str = "", user_id: str = "", *,
                      product_name: str = ""):
    """返回 (CLI 退出码, 原始 stdout)；本地调用异常由 main 展示。"""
    scene = (scene or "").strip()
    if not scene:
        raise ValueError("场景名称未提供，请从对应场景的 reference 读取")
    if not query or not query.strip():
        raise ValueError("检索关键词不能为空")
    if not CLI_PATH.is_file():
        raise FileNotFoundError(f"安装包不完整，缺少 CLI：{CLI_PATH}")
    command = [str(CLI_PATH), "--timeout", str(REQUEST_TIMEOUT),
               "experience", "search", "--query", query, "--scene", scene,
               "--search_field", SEARCH_FIELD, "--page", "1",
               "--page_size", str(PAGE_SIZE)]
    product_name = (product_name or "").strip()
    if product_name:
        command.extend(["--products", product_name])
    if user_id and user_id.strip():
        command.extend(["--user_id", user_id.strip()])
    completed = subprocess.run(command, capture_output=True, encoding="utf-8",
                               timeout=REQUEST_TIMEOUT + 10, shell=False)
    return completed.returncode, completed.stdout


def print_search_input(query, scene, product_name):
    print("=" * 60)
    print("【经验检索输入】")
    print(f"query: {query}")
    print(f"scene: {scene}")
    print(f"product_name: {product_name or '不限制产品'}")
    print(f"search_field: {SEARCH_FIELD}")
    print(f"page: 1, page_size: {PAGE_SIZE}")
    print("=" * 60)


def print_search_result(returncode, raw):
    """展示业务结果并返回退出码，不修改 CLI 原始响应。"""
    try:
        response = json.loads(raw)
    except (ValueError, TypeError):
        print(f"检索失败：CLI 未返回有效 JSON（退出码 {returncode}）")
        return 1
    if not isinstance(response, dict):
        print("检索失败：CLI 返回结构不是 JSON 对象")
        return 1
    error = response.get("error")
    if returncode == 3 or (isinstance(error, dict) and error.get("code") == -32002):
        print("未登录或会话已失效，请在终端登录后重试。")
        print(f'CMD："{CLI_PATH}" auth login --username <工号>')
        print(f'PowerShell：& "{CLI_PATH}" auth login --username <工号>')
        return 3
    result = response.get("result")
    if returncode != 0 or error is not None or not isinstance(result, dict):
        print(f"检索失败：CLI 退出码 {returncode}；详情见原始返回 JSON")
        return 1
    if result.get("code") != 200:
        print(f"检索失败：code={result.get('code')}, msg={result.get('msg')}")
        return 1
    data = result.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        print("检索失败：返回数据缺少 data.items 数组")
        return 1
    items = data["items"]
    if any(not isinstance(item, dict) for item in items):
        print("检索失败：data.items 中存在非对象条目")
        return 1
    print(f"召回候选数: {data.get('total_candidates', '未返回')}")
    print(f"排序结果总数: {data.get('total_ranked', '未返回')}")
    print(f"返回条数: {len(items)}")
    if not items:
        print("未命中任何经验")
    for i, item in enumerate(items, 1):
        print(f"\n--- 第 {i} 条 ---")
        for key in ("title", "summary", "score", "experience", "rag_search_text"):
            print(f"{key}: {item.get(key, '')}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="使用 CLI 按场景名称检索经验，产品名称可选")
    parser.add_argument("query", help="检索关键词")
    parser.add_argument("scene", nargs="?", default="", help="场景名称，从 reference 读取")
    parser.add_argument("--product-name", default="", help="产品名称，默认不限制产品")
    args = parser.parse_args()
    scene, product_name = args.scene.strip(), args.product_name.strip()
    print_search_input(args.query, scene, product_name)
    print("【经验检索返回】")
    raw = None
    try:
        returncode, raw = search_experience(args.query, scene, product_name=product_name)
        status = print_search_result(returncode, raw)
    except subprocess.TimeoutExpired:
        print("检索失败：CLI 调用超时，请检查网络或稍后重试")
        status = 1
    except (OSError, ValueError) as exc:
        print(f"检索失败：{exc}")
        status = 1
    print("=" * 60)
    print("\n【原始返回 JSON】")
    if raw is None:
        print("未取得 CLI 返回 JSON。")
    else:
        # 保留 CLI stdout 原文；即使不是有效 JSON，也不伪造或裁剪响应。
        print(raw, end="" if raw.endswith("\n") else "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
