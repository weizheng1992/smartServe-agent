# answerQuality judge 校准流程(05 号票)

背景(审计 CONFIRMED):judge 与被测引擎同族同模型(glm 判 glm)、一致率从未被
度量、无 Unknown 弃权档。MT-Bench 律:judge-人一致 ≥80% 才可用。

## 步骤

1. **构建复判包**(judge 治下用例约 9 例/轮,默认 4 轮 ≈ 36 判次,约 15 分钟):
   ```bash
   PROMPTFOO_PYTHON=$PWD/services/.venv/bin/python \
     python3 eval/judge_calibration/build_package.py   # 默认 4 轮
   ```
2. **人工复判**:填 `calibration_sheet.md` 每例「人工」列(`同意` / `不同意:理由`)。
3. **统计**:`python3 eval/judge_calibration/tabulate.py` → 一致率与不同意清单。
4. **裁决**:≥80% 留档为 judge 基线数字;<80% 收紧 rubric(三维评分标准细化)
   后重建包重测。首测数字无论高低都写入本 README 留档(judge 的「评测的评测」基线)。

## 首测留档(2026-10-26)

- **v1(三维 rubric):一致率 78%(21/27)—— <80% 不可用,按流程收紧**
- 三盲区:指代准确性/多模态证据透明/相关性与范围;衍生引擎缺陷 1 个(20 号票:指代消解)
- v2(2026-10-26):六维 + 双段式(先推理后结论)+ Unknown 弃权档(score=-1,[弃权] 前缀台账识别);judge 仍同族自评(glm 判 glm)—— 多档可用时换异族 judge
- v2 复测:build_package 重新生成表 → 人工再判 → 目标 ≥80% 留档为基线数字

## 后续升级(首测后)

- judge prompt 双段式(先推理后结论)+ 显式 Unknown 弃权档
- 大模型多档可用时换异族 judge,并在 eval/baselines/README 声明同族自评局限
- 每月固定抽评复测一致率
