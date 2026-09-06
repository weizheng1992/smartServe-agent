# .wayfinder/ — 本地 markdown tracker

本仓库的 wayfinder tracker。一张地图一个目录,目录名即地图 slug。

## 结构

```text
.wayfinder/
├── README.md                          ← 本文件(tracker 约定)
└── <map-slug>/
    ├── map.md                         ← 地图(type: map, label wayfinder:map)
    └── tickets/
        └── NNN-<short-slug>.md        ← 子 ticket(type: ticket)
```

## Frontmatter 约定

地图(`map.md`):

```yaml
---
id: <map-slug>
title: <地图名>
type: map
labels: [wayfinder:map]
status: open          # open | closed
created: YYYY-MM-DD
---
```

Ticket(`tickets/NNN-*.md`):

```yaml
---
id: "NNN"                     # 三位编号,同地图内唯一
title: <ticket 名>
map: <map-slug>
type: ticket
labels: [wayfinder:<research|prototype|grilling|task>]
mode: AFK                     # AFK | HITL
assignee: ""                  # 领取即填,这就是 claim
status: open                  # open | closed
blocked-by: []                # 阻塞本票的 ticket id 列表
blocks: []                    # 本票阻塞的 ticket id 列表
created: YYYY-MM-DD
---
## Question
<这张票要解决的任务/决策>
```

## 操作约定

- **Frontier** = `status: open` 且 `blocked-by` 中所有票已 `closed` 且 `assignee` 为空的 ticket。工作模式默认取编号最小的 frontier 票。
- **Claim**:动手前先把 `assignee` 填上自己(git 用户名);并发 session 跳过已 claim 的票。
- **Resolve**:在票文件末尾追加 `## Resolution` 段记录做了什么/关键事实,`status` 改 `closed`,并在地图 `map.md` 的 **Decisions so far** 追加一行 `- [title](tickets/NNN-*.md): <一行要点>`。
- **票内新发现的票**:创建-后连线(先建文件拿到 id,再回填两边的 blocked-by/blocks),并视情况把地图 **Not yet specified** 里的雾毕业成票。
- **划出范围**:把票 `status: closed`(不等阻塞),在地图 **Out of scope** 留一行理由加链接;不进 Decisions so far。
- 解析 frontier 时直接 grep 各票 frontmatter,不要信目录里的陈旧列表。
