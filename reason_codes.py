#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""全仓唯一的「未获取全文原因」枚举与映射表（v1.4.0 起统一）。

背景：此前存在两套互不相认的词汇表——
  - references/cnki/cnki-playbook.md §12 的 7 值人工枚举（写进 _quarantine/reasons.csv）
  - pdf_fetch.py 四重校验自造的 8 值流式 reason（写进 manifest.csv）
同一篇文献在两条链路上会得到两个互不映射的原因，未获取全文.md 的原因链无法归类。
本模块是唯一真源：两边都必须从这里取值 / 映射，禁止再自造新值。

用法：
    from reason_codes import REASONS, canonical, is_valid
    canonical("doi_mismatch")            → "mismatch"
    canonical("unreadable:bad header")   → "invalid_pdf"
    is_valid("paywall")                  → True
"""
import re

# 规范枚举（10 值）。新增值必须同时改本文件的 REASON_TEXT 与
# references/cnki/cnki-playbook.md §12、references/shared/failure-reasons.md
REASONS = (
    "no_html",      # 两次确认都没有 HTML 入口
    "no_pdf",       # 有「原版阅读」但下载捕获失败 / 无 OA 直链可下
    "paywall",      # 机构未订阅或需个人付费
    "captcha",      # 滑块 / hCaptcha 反复失败
    "scan_only",    # PDF 无文本层（扫描件）
    "thin_text",    # 正文 < --min-chars（默认 4000 字）
    "mismatch",     # DOI 或篇名与记录不符（含无匹配记录）
    "invalid_pdf",  # 下载物不是有效 PDF（太小 / 无魔数 / 0 页 / 不可读）
    "no_oa",        # OpenAlex 查不到 OA 直链
    "network",      # 下载或接口失败（超时、无文件落盘）
)

REASON_TEXT = {
    "no_html": "两次确认都没有 HTML 入口",
    "no_pdf": "有「原版阅读」但下载捕获失败",
    "paywall": "机构未订阅 / 需要个人付费",
    "captcha": "滑块或 hCaptcha 反复失败",
    "scan_only": "PDF 无文本层（无可提取文字）",
    "thin_text": "正文 < 4000 字",
    "mismatch": "DOI/篇名与记录不符",
    "invalid_pdf": "下载物不是有效 PDF（过小 / 无魔数 / 0 页 / 不可读）",
    "no_oa": "OpenAlex 无 OA 直链",
    "network": "下载或接口失败（超时 / 无文件落盘）",
}

# pdf_fetch.py 四重校验的原始 reason → 规范值。
# 键带前缀匹配的用 REASON_PREFIX_MAP（unreadable:<detail> 这类带细节尾巴的）。
REASON_MAP = {
    "ok": "",
    "no_file": "network",
    "no_record": "mismatch",
    "too_small": "invalid_pdf",
    "not_pdf": "invalid_pdf",
    "no_pages": "invalid_pdf",
    "doi_mismatch": "mismatch",
    "title_mismatch": "mismatch",
}

REASON_PREFIX_MAP = (
    ("unreadable", "invalid_pdf"),
)

_UNKNOWN = "network"


def is_valid(value):
    return (value or "").strip() in REASONS


def canonical(value, default=_UNKNOWN):
    """把任意来源的 reason 归一到规范枚举；已在枚举内则原样返回。

    未登记的新写法一律落到 default（network）而不是原样透传——宁可让原因笼统，
    也不让第二套词汇表悄悄复活（v1.3 的病根）。
    """
    v = (value or "").strip()
    if not v:
        return ""
    if v in REASONS:
        return v
    if v in REASON_MAP:
        return REASON_MAP[v]
    for prefix, target in REASON_PREFIX_MAP:
        if v.startswith(prefix):
            return target
    return default


def describe(value):
    return REASON_TEXT.get(canonical(value), "")


def all_rows():
    """给文档生成 / lint 用：[(值, 中文说明), ...]"""
    return [(r, REASON_TEXT[r]) for r in REASONS]


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="失败原因枚举自检")
    ap.add_argument("value", nargs="?", help="待归一的 reason，不给则打印全表")
    args = ap.parse_args()
    if args.value:
        print(f"{args.value} → {canonical(args.value)}（{describe(args.value)}）")
        raise SystemExit(0 if is_valid(canonical(args.value)) else 1)
    for k, v in all_rows():
        print(f"{k:<12} {v}")
