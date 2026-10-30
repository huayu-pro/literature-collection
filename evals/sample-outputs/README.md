# 交付物样例（脱敏）

全部由 `evals/make_delivery_fixture.py` 的虚构夹具数据（张三/李四/测试文献）经真实脚本生成，
不含任何真实检索数据；字段齐全度覆盖「全字段」与「卷期缺失降级」两种形态。
核对真实交付的格式时，对照本目录同名文件即可。

| 样例 | 生成命令 |
|---|---|
| 文献题录.txt | `export_citations.py <目录>`（auto：知网/WoS 双格式） |
| 参考文献.md | `export_citations.py <目录> --format gbt7714` |
| 参考文献-apa.md | `export_citations.py <目录> --format apa` |
| 参考文献-mla.md | `export_citations.py <目录> --format mla` |
| 未获取全文.md | `build_index.py <目录>`（存在缺失文献时自动生成） |
| 检索报告.md | `render_report.py <目录> --title "<题目>"`（v1.4 新增 renderer，数字全部取自 index_stats.json，不手写） |

题录样例里 `SR` 恒为 `1`（知网真实导出 13 条记录全是 1，不是导出序号）——
v1.3 的样例与 fixture 曾写成递增序号，与 references 和 smoke-cases 的口径冲突，已对齐。
