#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行（本机 /usr/bin/python3 有 pymupdf；PATH 上的另一个 python3 缺它）
"""环境自检：跑文献搜集前先把解释器、依赖、CLI、目录四件事钉死。

用法：
    /usr/bin/python3 scripts/env_check.py --json
    /usr/bin/python3 scripts/env_check.py --workdir /path/to/工作目录

退出码：0 全部通过（允许 warn）；1 存在 fail。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REQUIRED_BINS = ["bsk", "curl"]
# pdftotext/pdfinfo 只在「关键数字回原 PDF 人工核对」时用（SKILL.md §8 Gotcha），
# 主流程脚本零依赖，缺失不该挡住整个流程 → 降为可选
MANUAL_CHECK_BINS = ["pdftotext", "pdfinfo"]
# 真正被脚本 import 的只有 pymupdf（pdf_fetch 页数/内嵌 DOI、verify_delivery PDF 校验、
# pdf_to_md 文本层）。pypdf 与 openpyxl 全仓无 import——v1.3 把它们列成必填，
# 缺一个就 ok=false，主流程却根本用不到，属于过度门禁（挡真事、不挡真错）。
REQUIRED_MODULES = ["pymupdf"]
OPTIONAL_MODULES = [
    ("pypdf", "仅人工核对表格/公式时用（pitfall-library 的 find_tables 替代方案），无脚本 import"),
    ("openpyxl", "仅当用户要把 index.csv 另存为 .xlsx 时用，无脚本 import"),
]


def _run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        return 127, "", str(exc)


def _importable(exe, module):
    code = f"import {module}"
    rc, _, err = _run([exe, "-c", code])
    return rc == 0, err.splitlines()[-1] if err else ""


def check_python():
    checks = []
    missing = []
    for mod in REQUIRED_MODULES:
        ok, err = _importable(sys.executable, mod)
        checks.append({
            "name": f"module:{mod}",
            "status": "pass" if ok else "fail",
            "detail": "已安装" if ok else err,
            "fix": "" if ok else f"{sys.executable} -m pip install {mod}",
        })
        if not ok:
            missing.append(mod)

    checks.append({
        "name": "interpreter",
        "status": "pass" if not missing else "fail",
        "detail": f"当前解释器 {sys.executable} ({sys.version.split()[0]})",
        "fix": "" if not missing else "改用 /usr/bin/python3 运行所有脚本",
    })

    path_py = shutil.which("python3")
    if path_py and os.path.realpath(path_py) != os.path.realpath(sys.executable):
        ok, _ = _importable(path_py, "pymupdf")
        checks.append({
            "name": "path_python3",
            "status": "warn" if not ok else "pass",
            "detail": f"PATH 上的 python3 = {path_py}，{'缺' if not ok else '有'} pymupdf",
            "fix": "" if ok else "命令示例一律写 /usr/bin/python3，不要写 python3",
        })

    for mod, usage in OPTIONAL_MODULES:
        ok, _ = _importable(sys.executable, mod)
        checks.append({
            "name": f"optional:{mod}",
            "status": "pass" if ok else "warn",
            "detail": "已安装" if ok else f"未安装（{usage}）",
            "fix": "" if ok else f"需要时再装：{sys.executable} -m pip install {mod}",
        })
    return checks


def check_bins():
    checks = []
    for name in REQUIRED_BINS:
        path = shutil.which(name)
        checks.append({
            "name": f"bin:{name}",
            "status": "pass" if path else "fail",
            "detail": path or "未找到",
            "fix": "" if path else f"安装 {name} 并确保在 PATH 中",
        })
    for name in MANUAL_CHECK_BINS:
        path = shutil.which(name)
        checks.append({
            "name": f"optional-bin:{name}",
            "status": "pass" if path else "warn",
            "detail": (path or "未找到") + "（仅人工核对 PDF 数字时用，主流程不需要）",
            "fix": "" if path else f"如需人工核对：安装 {name}（poppler-utils）",
        })
    bsk = shutil.which("bsk")
    if bsk:
        rc, out, _ = _run([bsk, "--version"])
        ver = out.split()[-1] if rc == 0 and out else "unknown"
        ver = ver.lstrip("vV")  # 「bsk version v0.3.3」与「bsk 0.3.3」都是合法形态
        major_minor = ".".join(ver.split(".")[:2])
        checks.append({
            "name": "bsk:version",
            "status": "pass" if major_minor == "0.3" else "warn",
            "detail": f"bsk {ver}",
            "fix": "" if major_minor == "0.3" else "本技能的界面选择器按 0.3.x 实测；其他版本先读 references/shared/pitfall-library.md 的版本引导段",
        })
    return checks


def check_workdir(workdir):
    if not workdir:
        return []
    wd = Path(workdir).expanduser()
    try:
        wd.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=wd, prefix=".envcheck_", delete=True):
            pass
        return [{"name": "workdir", "status": "pass", "detail": str(wd), "fix": ""}]
    except Exception as exc:  # noqa: BLE001
        return [{"name": "workdir", "status": "fail", "detail": f"{wd}: {exc}", "fix": "换一个有写权限的目录"}]


def check_skill():
    p = Path.home() / ".workbuddy" / "skills" / "browser-skill" / "SKILL.md"
    return [{
        "name": "skill:browser-skill",
        "status": "pass" if p.exists() else "warn",
        "detail": str(p) if p.exists() else "未安装 browser-skill",
        "fix": "" if p.exists() else "先安装 browser-skill，再跑浏览器阶段",
    }]


def main():
    ap = argparse.ArgumentParser(description="文献搜集技能环境自检")
    ap.add_argument("--workdir", default="", help="运行时工作目录，检查是否可写")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    checks = []
    checks += check_python()
    checks += check_bins()
    checks += check_workdir(args.workdir)
    checks += check_skill()

    failed = [c for c in checks if c["status"] == "fail"]
    warned = [c for c in checks if c["status"] == "warn"]
    result = {"ok": not failed, "failed": len(failed), "warned": len(warned), "checks": checks}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            mark = {"pass": "✓", "warn": "!", "fail": "✗"}[c["status"]]
            print(f"{mark} {c['name']}: {c['detail']}")
            if c["fix"] and c["status"] != "pass":
                print(f"    → {c['fix']}")
        print(f"\n{'通过' if result['ok'] else '未通过'}：fail={len(failed)} warn={len(warned)}")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
