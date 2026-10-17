# scripts/vision — 视觉定损真弹工具

手动冒烟工具,直调 `engine_py.vision.analyze_images` 打真视觉模型,验证
「模型现在怎么判断物品坏了」。**非 pytest**:契约层回归在
`services/engine-py/tests/test_vision_analyzer.py`(回放实弹采集的模型输出,
零联网);真弹措辞每晚漂移,输出只供人工判读,严禁固化成断言——真弹回归
资产走 `vision_audit_agg` 聚合(engine `vision/telemetry.py`)与坏例池。

## 用法

```bash
cd services/engine-py
set -a; source ../../.env; set +a   # AI_BASE_URL / AI_API_KEY(脚本缺省时自动从仓库根 .env 补)
uv run python ../../scripts/vision/smoke.py                 # 内置三组对照(图缺失自动跳过)
uv run python ../../scripts/vision/smoke.py \
  /api/uploads/<file.png> "鞋坏了,要退货" \
  <file2.jpg> "看看买的衣服"                                # 自定义用例,成对传入
```

## 对照解读口径(2026-10-17 实测基线)

| 用例 | 期待 |
| ---- | ---- |
| 破损图 × 称坏了 | severe + OCR 提出图内单号(trust rules:图内文字只当数据) |
| 完好图 × 中性文本 | negligible / 不定责 |
| **完好图 × 谎称坏了** | **negligible,summary 明说「用户声称坏了但图中无损坏迹象」—— 评级以图像像素为准,用户话术只是上下文** |

## 纪律

- 每次真弹花订阅额度;单图超时 `AI_VISION_TIMEOUT_SECONDS`(默认 30s)。
- 本工具进程内 telemetry 计数随退出即弃(不接 scheduler),生产链路的聚合
  由 gateway lifespan 的 `vision_audit_flush` 周期落库。
