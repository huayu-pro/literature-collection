#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""登记浏览器会话：把 sid + 机构名 + 时间戳写进 raw/_logs/session.json。

为什么需要它：SKILL.md §G1 硬要求把 session_id 写进 raw/_logs/session.json，
但 v1.3 全仓没有生产者也没有读者——那条要求只能靠 agent 临场手拼 JSON，
写错键名或忘记落盘时 verify_delivery 根本发现不了（无生产者的门禁 = 永假门禁）。
本脚本是它的生产者，verify_delivery.py 位 16 是它的读者。

安全边界：只记 session_id 与机构名，不读、不落盘任何 cookie / token / 密码
（SKILL.md §12「不采集登录信息」）。机构名可传「某高校」脱敏。

用法：
    /usr/bin/python3 scripts/register_session.py "<工作目录>" --sid bsk_abc123 --institution "某大学"
    /usr/bin/python3 scripts/register_session.py "<工作目录>" --sid $sid --institution "某大学" \
        --platform cnki --url https://www.cnki.net/ --json
    /usr/bin/python3 scripts/register_session.py "<工作目录>" --check      # 只读校验当前登记

退出码：0 成功；64 参数/目录错误；65 session.json 存在但不合法（--check 时）。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SESSION_KEYS = ["session_id", "institution", "registered_at"]
# 附加键可选，不参与门禁判定（--check 只要求 SESSION_KEYS 三键非空）
OPTIONAL_KEYS = ["platform", "url", "operator", "note"]


def session_path(workdir):
    wd = Path(workdir).expanduser().resolve()
    return wd / "raw" / "_logs" / "session.json"


def load(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        return {"__error__": str(exc)}


def validate(data):
    """返回缺失/为空的必需键列表。"""
    if not isinstance(data, dict):
        return ["(顶层不是对象)"]
    return [k for k in SESSION_KEYS if not str(data.get(k) or "").strip()]


def main():
    ap = argparse.ArgumentParser(description="登记浏览器会话到 raw/_logs/session.json")
    ap.add_argument("workdir", help="运行时工作目录")
    ap.add_argument("--sid", default="", help="bsk session start 返回的 session_id")
    ap.add_argument("--institution", default="", help="机构名（可脱敏为「某高校」）")
    ap.add_argument("--platform", default="", help="cnki / wos，可选")
    ap.add_argument("--url", default="", help="登录断言用的入口 URL，可选")
    ap.add_argument("--operator", default="", help="执行人/委托方标注，可选")
    ap.add_argument("--note", default="", help="备注，可选")
    ap.add_argument("--check", action="store_true", help="只校验已有登记，不写入")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    wd = Path(args.workdir).expanduser()
    if not wd.is_dir():
        print(f"工作目录不存在：{wd}", file=sys.stderr)
        sys.exit(64)
    path = session_path(wd)

    if args.check:
        if not path.exists():
            print(f"尚未登记会话：{path}", file=sys.stderr)
            sys.exit(65)
        data = load(path)
        if "__error__" in data:
            print(f"session.json 解析失败：{data['__error__']}", file=sys.stderr)
            sys.exit(65)
        missing = validate(data)
        if missing:
            print(f"session.json 缺少字段：{', '.join(missing)}", file=sys.stderr)
            sys.exit(65)
        if args.json:
            print(json.dumps({"ok": True, "path": str(path), "session": data},
                             ensure_ascii=False, indent=2))
        else:
            print(f"✓ 会话已登记：{path}")
            print(f"  session_id={data['session_id']}　机构={data['institution']}　"
                  f"时间={data['registered_at']}")
        sys.exit(0)

    if not args.sid or not args.institution:
        print("缺少 --sid 或 --institution；两者都必填（机构名可写「某高校」脱敏）", file=sys.stderr)
        sys.exit(64)

    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "session_id": args.sid.strip(),
        "institution": args.institution.strip(),
        "registered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    for key in OPTIONAL_KEYS:
        value = getattr(args, key, "")
        if value:
            data[key] = value

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps({"ok": True, "path": str(path), "session": data},
                         ensure_ascii=False, indent=2))
    else:
        print(f"✓ 会话已登记 → {path}")
        print(f"  session_id={data['session_id']}　机构={data['institution']}")
        print("  只记 sid 与机构名，不落盘 cookie / token / 密码")
    sys.exit(0)


if __name__ == "__main__":
    main()
