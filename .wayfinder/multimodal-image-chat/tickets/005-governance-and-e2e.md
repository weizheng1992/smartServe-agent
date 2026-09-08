---
id: "005"
title: 图片治理与全链路验收
map: multimodal-image-chat
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: ""
status: open
blocked-by: ["002", "003", "004"]
blocks: []
created: 2026-09-08
---

## Question

收口票:治理补齐 + 全链路验收,多模态链路从"能跑"到"敢用"。

**治理**(TS 时代零防护,考古裁决必须补):

- 引擎侧 imageUrls 归一化与校验:数量上限(如 ≤3/条)、坏 URL/不可达图不炸主链路(vision 失败=无 vision,不失败会话)。
- 上传与 vision 的双重限额对齐(网关 10MB/张 + 引擎总量)。

**验收**:

- E2E:选图上传 → 发破损图 → damage_assessment 卡片渲染(web 主链路 chromium)。
- `eval/testCases/ecommerce/multimodal-damage.json` 复核:现用例是 `[image: ...]` 文本模拟,裁决是否升级为真实图片链路用例(动基线须重钉并记录)。
- 文档回填:CHANGELOG、`docs/architecture/multimodal-and-rich-cards.md` 的 TS 残留引用、CLAUDE.md Phase 1b 回收池条目(多模态 vision 移除出池)。

**验收**:E2E 绿;契约/eval/prompt 基线不回归(或重钉有记录);ruff 干净。

## Resolution
