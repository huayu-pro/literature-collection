#!/usr/bin/env python3
# 建议用 /usr/bin/python3 运行
"""生成交付校验的 7 个夹具目录（base / bit1 / bit2 / bit4 / bit8 / citations / nofulltext）。

用法：
    /usr/bin/python3 evals/make_delivery_fixture.py /tmp/lit_delivery_test
然后用 verify_delivery.py 逐个校验，期望退出码 0/1/2/4/8/4/1。
"""
import csv
import json
import shutil
import sys
from pathlib import Path

MIN_CHARS = 4000


def write_md(path, rid, chars=6000, status="ok", access="HTML"):
    path.write_text(
        f"""---
rid: {rid}
title: 测试文献{rid}
authors: 张三
source: 测试期刊
year: "2021"
cited: 12
downloads: 100
access: {access}
quality_tags: CSSCI
chars: {chars}
status: {status}
---

# 测试文献{rid}

> **作者**：张三

## 一

正文内容。
""", encoding="utf-8")


def make(name, root):
    d = root / name
    (d / "正文").mkdir(parents=True, exist_ok=True)
    write_md(d / "正文" / "C0001_甲.md", "C0001")
    write_md(d / "正文" / "C0002_乙.md", "C0002")
    rows = [
        dict(rid="C0001", platform="cnki", title="测试文献C0001", authors="张三", source="测试期刊",
             year="2021", cited="12", downloads="100", quality_tags="CSSCI", access="HTML",
             rel_path_md="正文/C0001_甲.md", rel_path_pdf="", chars="6000", status="ok", note="",
             score="0.75", citedness_2yr=""),
        dict(rid="C0002", platform="cnki", title="测试文献C0002", authors="李四", source="测试期刊",
             year="2021", cited="8", downloads="80", quality_tags="CSSCI", access="HTML",
             rel_path_md="正文/C0002_乙.md", rel_path_pdf="", chars="6000", status="ok", note="",
             score="0.0", citedness_2yr=""),
    ]
    with open(d / "index.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    stats = {"total": 2, "with_md": 2, "with_pdf": 0, "missing_file": 0, "unregistered": 0, "thin": 0}
    (d / "index_stats.json").write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
    (d / "检索报告.md").write_text(
        "# 检索报告\n\n<!-- STATS " + json.dumps(stats, ensure_ascii=False) + " -->\n", encoding="utf-8")
    write_records_and_citations(d, extra=False)
    return d


def sample_records(extra=False):
    recs = [
        {"rid": "C0001", "platform": "cnki", "title": "测试文献C0001", "authors": "张三",
         "source": "测试期刊", "year": "2021", "issue": "3", "volume": "", "pages": "12-20",
         "keywords": "测试;夹具", "abstract": "夹具摘要。", "issn": "1000-0000", "cn": "11-0000/Z",
         "cited": 12, "downloads": 100, "url": "https://kns.cnki.net/kcms2/article/abstract?v=f1",
         "doi": "", "type": "期刊"},
        {"rid": "C0002", "platform": "cnki", "title": "测试文献C0002", "authors": "李四",
         "source": "测试期刊", "year": "2021", "issue": "3", "volume": "", "pages": "21-30",
         "keywords": "夹具", "abstract": "夹具摘要二。", "issn": "1000-0000", "cn": "11-0000/Z",
         "cited": 8, "downloads": 80, "url": "https://kns.cnki.net/kcms2/article/abstract?v=f2",
         "doi": "", "type": "期刊"},
    ]
    if extra:
        recs.append({"rid": "C0003", "platform": "cnki", "title": "夹具第三篇（无全文）",
                     "authors": "王五", "source": "测试期刊", "year": "2022", "cited": 0,
                     "downloads": 0, "url": "", "doi": "", "type": "期刊"})
    return recs


def write_records_and_citations(d, extra=False, short_citations=False):
    """records.json + 知网格式题录；short_citations=True 时题录故意少一条（位 4 用例）。"""
    recs = sample_records(extra)
    (d / "raw").mkdir(exist_ok=True)
    (d / "raw" / "records.json").write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    n_cite = len(recs) - 1 if short_citations else len(recs)
    lines = []
    for i, r in enumerate(recs[:n_cite], 1):
        # SR 恒为 1：知网真实导出的 13 条样例里 SR 全部是 1，不是导出序号
        # （v1.3 fixture 写成 f"SR {i}" 递增，与 references 和 smoke-cases 的口径冲突）
        lines += [f"RT Journal Article", "SR 1", f"A1 {r['authors']}", f"T1 {r['title']}",
                  f"JF {r['source']}", f"YR {r['year']}", ""]
    (d / "文献题录.txt").write_text("\r\n".join(lines), encoding="utf-8")


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/lit_delivery_test")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    base = make("base", root)

    shutil.copytree(base, root / "bit1")
    rows = read_rows(root / "bit1" / "index.csv")
    rows[1]["rel_path_md"] = "正文/C0002_缺失.md"
    write_rows(root / "bit1" / "index.csv", rows)

    shutil.copytree(base, root / "bit2")
    rows = read_rows(root / "bit2" / "index.csv")
    rows[1]["rel_path_md"] = "正文/C0009_乙.md"
    write_rows(root / "bit2" / "index.csv", rows)
    (root / "bit2" / "正文" / "C0002_乙.md").rename(root / "bit2" / "正文" / "C0009_乙.md")

    shutil.copytree(base, root / "bit4")
    stats = json.loads((root / "bit4" / "index_stats.json").read_text(encoding="utf-8"))
    stats["total"] = 3
    (root / "bit4" / "检索报告.md").write_text(
        "# 检索报告\n\n<!-- STATS " + json.dumps(stats, ensure_ascii=False) + " -->\n", encoding="utf-8")

    shutil.copytree(base, root / "bit8")
    write_md(root / "bit8" / "正文" / "C0002_乙.md", "C0002", chars=100)

    shutil.copytree(base, root / "citations")
    # records 3 条但题录只写 2 条 → count.citations 置位 4
    write_records_and_citations(root / "citations", extra=True, short_citations=True)

    shutil.copytree(base, root / "nofulltext")
    d = root / "nofulltext"
    write_records_and_citations(d, extra=True)  # records 与题录都是 3 条，对账通过
    rows = read_rows(d / "index.csv")
    rows.append(dict(rid="C0003", platform="cnki", title="夹具第三篇（无全文）", authors="王五",
                     source="测试期刊", year="2022", cited="0", downloads="0", quality_tags="",
                     access="", rel_path_md="", rel_path_pdf="", chars="", status="missing_file",
                     note="文件缺失，待核对", score="0.0", citedness_2yr=""))
    write_rows(d / "index.csv", rows)
    stats = json.loads((d / "index_stats.json").read_text(encoding="utf-8"))
    stats.update({"total": 3, "missing_file": 1, "no_fulltext": 1})
    (d / "index_stats.json").write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
    (d / "检索报告.md").write_text(
        "# 检索报告\n\n## 五、缺口与待核对\n\n"
        "- C0003 夹具第三篇（无全文）：付费墙，机构未订阅\n\n<!-- STATS "
        + json.dumps(stats, ensure_ascii=False) + " -->\n", encoding="utf-8")
    # 故意不生成 未获取全文.md → 位 1

    print(f"✓ 夹具已生成：{root}（base/bit1/bit2/bit4/bit8/citations/nofulltext）")


if __name__ == "__main__":
    main()
