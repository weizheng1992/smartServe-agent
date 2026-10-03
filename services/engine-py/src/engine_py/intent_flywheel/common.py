"""意图飞轮共享 toolkit —— JSONL 读写与 CLI .env 装载的唯一实现。

- ``load_jsonl`` / ``write_jsonl``:write 的 stdout 管道语义(out 为空或 '-'
  打 stdout)来自 export_intent_data 的既有消费方式;行内键兼容(如
  calibrate 的 text|question 双键)属各 CLI 的输入契约,留在调用点。
- ``load_env_file``:与原 badcase.cli / export_intent_data 两份本地实现同
  策略 —— 查找顺序 CWD → services/engine-py → 仓库根,首个存在的 .env
  生效;setdefault 不覆盖已有环境变量(显式 env / CI 注入优先)。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# parents: [0]=intent_flywheel [1]=engine_py [2]=src [3]=engine-py [4]=services [5]=仓库根
_HERE = Path(__file__).resolve()
_ENGINE_ROOT = _HERE.parents[3]
_REPO_ROOT = _HERE.parents[5]

# 意图评测集:gen_intent_cases 写 / run_intent_eval 读 / calibrate 可选输入
EVAL_CASES_PATH = _ENGINE_ROOT / "evals" / "intent_cases.jsonl"


def load_jsonl(path: str | Path) -> list[dict]:
    """整读 JSONL 为 dict 列表(跳过空行;解析失败即响亮抛错)。"""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(records: list[dict], out: str | Path | None) -> None:
    """写 JSONL:``out`` 为空或 '-' 打到 stdout,否则写文件(父目录自动创建)。"""
    lines = [json.dumps(record, ensure_ascii=False, default=str) for record in records]
    if out and out != "-":
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    else:
        for line in lines:
            print(line)


def load_env_file() -> None:
    """轻量 .env 加载(项目无 python-dotenv 依赖,不为此引入):仅 setdefault 不覆盖已有环境变量。"""
    for env_path in (Path.cwd() / ".env", _ENGINE_ROOT / ".env", _REPO_ROOT / ".env"):
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))
            break
