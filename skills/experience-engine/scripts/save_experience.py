"""
存入经验脚本

所有字段均使用命名参数。experience 字段**必须**通过临时文件传入
(用 --experience-file 指定路径),以规避不同 shell(bash / PowerShell / cmd)
对特殊字符的解析差异。

用法:
    # 1. 先把 experience 的 Markdown 内容写入一个临时文件,比如 /tmp/exp.md
    # 2. 执行:
    python save_experience.py \
      --title "<title>" \
      --summary "<summary>" \
      --rag "<rag_search_text>" \
      --scene-id "<scene_id>" \
      --scene "<scene>" \
      --experience-file "/tmp/exp.md"

必填:
  --title            经验标题
  --summary          经验摘要
  --rag              检索关键词(空格分隔)
  --scene-id         场景ID
  --experience-file  experience Markdown 内容的临时文件路径

可选:
  --scene            场景名称
  --user-id          用户ID(默认取 $USERNAME 环境变量)
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error

BASE_URL = "https://fuyao.rnd.huawei.com"
DEFAULT_USER_ID = os.getenv("USERNAME", "default_user")


def save_experience(title: str, summary: str, experience: str, rag_search_text: str,
                    scene_id: str, scene: str = "", user_id: str = "") -> dict:
    user_id = user_id or DEFAULT_USER_ID

    if not scene_id:
        return {"code": 400, "msg": "scene_id 未提供", "data": None}

    payload = {
        "scene_id": scene_id,
        "user_id": user_id,
        "title": title,
        "summary": summary,
        "experience": experience,
        "rag_search_text": rag_search_text,
    }
    if scene:
        payload["scene"] = scene

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/memory/experience/doc",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"code": e.code, "msg": f"HTTP {e.code}: {body}", "data": None}
    except Exception as e:
        return {"code": 500, "msg": str(e), "data": None}


def main():
    parser = argparse.ArgumentParser(
        description="存入经验到经验中心(experience 从临时文件读取)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  # 先把 experience Markdown 写入临时文件,再执行:\n"
            "  python save_experience.py \\\n"
            "    --title \"标题\" \\\n"
            "    --summary \"摘要\" \\\n"
            "    --rag \"关键词1 关键词2\" \\\n"
            "    --scene-id 421 \\\n"
            "    --scene \"场景名称\" \\\n"
            "    --experience-file \"/tmp/experience.md\""
        ),
    )
    parser.add_argument("--title", required=True, help="经验标题")
    parser.add_argument("--summary", required=True, help="经验摘要")
    parser.add_argument("--rag", required=True, help="检索关键词(rag_search_text)")
    parser.add_argument("--scene-id", required=True, help="场景ID")
    parser.add_argument("--experience-file", required=True,
                        help="experience Markdown 内容的临时文件路径")
    parser.add_argument("--scene", default="", help="场景名称(可选)")
    parser.add_argument("--user-id", default="", help="用户ID(可选,默认取 $USERNAME)")

    args = parser.parse_args()

    # 读 experience 文件
    if not os.path.isfile(args.experience_file):
        print(f"错误:experience 文件不存在: {args.experience_file}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.experience_file, "r", encoding="utf-8") as f:
            experience = f.read()
    except Exception as e:
        print(f"错误:读取 experience 文件失败: {e}", file=sys.stderr)
        sys.exit(1)

    if not experience.strip():
        print(f"错误:experience 文件内容为空: {args.experience_file}", file=sys.stderr)
        sys.exit(1)

    result = save_experience(
        title=args.title,
        summary=args.summary,
        experience=experience,
        rag_search_text=args.rag,
        scene_id=args.scene_id,
        scene=args.scene,
        user_id=args.user_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
