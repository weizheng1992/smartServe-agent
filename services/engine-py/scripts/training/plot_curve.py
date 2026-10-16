"""训练曲线 SVG 生成器(读 run 目录 metrics.json → curve.html)。

手写自包含 SVG,零新依赖;风格对齐 2026-09-18 手产 curve.html:
双 y 带(上 = 训练损失、下 = heldout 准确率)+ 末端值标注 + epoch 刻度,
虚线为各带终值的收敛参考线。train.py 收尾自动调用;也支持独立重跑
(`--run-dir`),重训/旧 run 补曲线都不必再手画。

兼容性:老 metrics.json(无 meta 键)与无 heldout 评估的 curve 均可渲染;
单点曲线以圆点标记保证可见。
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 画布与版式(与现存手产 curve.html 逐字对齐)
_W, _H = 760, 300
_X0, _X1 = 60.0, 660.0
_LOSS_TOP, _LOSS_BOTTOM = 44.0, 150.0
_ACC_TOP, _ACC_BOTTOM = 160.0, 216.0
_TICK_Y, _AXIS_Y = 278, 296
_MAX_TICKS = 5


def load_metrics(run_dir: str | Path) -> dict:
    path = Path(run_dir) / "metrics.json"
    if not path.exists():
        raise SystemExit(f"[Plot] {path} 不存在;先跑 train.py 产出 metrics.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _band(values: list[float], y_top: float, y_bottom: float) -> list[float]:
    """值 → 像素 y(值越大越靠上;单点/等值退化为带中线,除零保护)。"""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        mid = (y_top + y_bottom) / 2
        return [mid] * len(values)
    scale = (y_bottom - y_top) / (hi - lo)
    return [y_top + (hi - v) * scale for v in values]


def _path_d(xs: list[float], ys: list[float]) -> str:
    points = [f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True)]
    return "M" + " L".join(points)


def _xticks(n: int) -> list[tuple[float, str]]:
    """epoch 刻度(≤5 个,均布;含首尾;n=1 时单刻度)。"""
    if n == 1:
        return [(_X0, "1")]
    indices = sorted({round(i * (n - 1) / (_MAX_TICKS - 1)) for i in range(_MAX_TICKS)})
    return [(_X0 + i * (_X1 - _X0) / (n - 1), str(i + 1)) for i in indices]


def build_svg(curve: list[dict], *, title: str, subtitle: str) -> str:
    """纯函数:loss_curve → 自包含 SVG 页面文本。"""
    has_heldout = any("heldout_acc" in e for e in curve)
    if not has_heldout:
        subtitle += " · 无 heldout 评估"
    n = len(curve)
    xs = [_X0] if n == 1 else [_X0 + i * (_X1 - _X0) / (n - 1) for i in range(n)]

    losses = [float(e["train_loss"]) for e in curve]
    loss_ys = _band(losses, _LOSS_TOP, _LOSS_BOTTOM)
    loss_end, loss_first = losses[-1], losses[0]

    parts = [
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
        '<body style="font-family:sans-serif;background:#fff;margin:24px">',
        f'<h2 style="margin:0 0 4px">{_esc(title)}</h2>',
        f'<p style="color:#888;font-size:13px;margin:4px 0 16px">{_esc(subtitle)}</p>',
        f'<svg width="{_W}" height="{_H}" viewBox="0 0 {_W} {_H}">',
        '<text x="8" y="22" font-size="12" fill="#18181b" font-weight="bold">训练损失 train_loss</text>',
        f'<line x1="{_X0}" y1="{loss_ys[-1]:.1f}" x2="{_X1}" y2="{loss_ys[-1]:.1f}" stroke="#f43f5e" stroke-dasharray="4 3"/>',
    ]
    if n == 1:
        parts.append(f'<circle cx="{xs[0]:.1f}" cy="{loss_ys[0]:.1f}" r="3" fill="#18181b"/>')
    else:
        parts.append(f'<path d="{_path_d(xs, loss_ys)}" fill="none" stroke="#18181b" stroke-width="2"/>')
        if loss_first != loss_end:
            parts.append(f'<text x="728" y="{loss_ys[0] + 4:.1f}" font-size="11" fill="#a1a1aa">{loss_first:.2f}</text>')
    parts += [
        f'<text x="728" y="{loss_ys[-1] + 4:.1f}" font-size="11" fill="#18181b">{loss_end:.2f}</text>',
        '<text x="8" y="166" font-size="12" fill="#18181b" font-weight="bold">heldout 准确率</text>',
    ]
    if has_heldout:
        accs = [float(e["heldout_acc"]) for e in curve]
        acc_ys = _band(accs, _ACC_TOP, _ACC_BOTTOM)
        acc_end = accs[-1]
        parts.append(
            f'<line x1="{_X0}" y1="{acc_ys[-1]:.1f}" x2="{_X1}" y2="{acc_ys[-1]:.1f}" stroke="#10b981" stroke-dasharray="4 3"/>'
        )
        if n == 1:
            parts.append(f'<circle cx="{xs[0]:.1f}" cy="{acc_ys[0]:.1f}" r="3" fill="#10b981"/>')
        else:
            parts.append(f'<path d="{_path_d(xs, acc_ys)}" fill="none" stroke="#10b981" stroke-width="2"/>')
        parts.append(f'<text x="728" y="{acc_ys[-1] + 4:.1f}" font-size="11" fill="#10b981">{acc_end * 100:.1f}%</text>')
    parts.append(
        "".join(
            f'<text x="{x:.0f}" y="{_TICK_Y}" font-size="10" fill="#a1a1aa" text-anchor="middle">{_esc(label)}</text>'
            for x, label in _xticks(n)
        )
    )
    parts += [
        f'<text x="{(_X0 + _X1) / 2:.0f}" y="{_AXIS_Y}" font-size="10" fill="#a1a1aa" text-anchor="middle">epoch</text>',
        "</svg>",
        "</body></html>",
    ]
    return "".join(parts)


def write_curve_html(run_dir: str | Path) -> Path:
    """读 run 目录 metrics.json,写 curve.html,返回产物路径。"""
    run_dir = Path(run_dir)
    metrics = load_metrics(run_dir)
    meta = metrics.get("meta") or {}
    train_block = metrics.get("train") or {}
    n_classes = len(train_block.get("per_class") or {})
    encoder = meta.get("encoder") or "未知 encoder"
    samples = meta.get("train_samples")
    scale = f"{samples} 句" if isinstance(samples, int) else "样本数未知"
    title = f"指标映射分类头 · 训练曲线（{encoder}，{scale} × {n_classes} 类）"
    started = meta.get("started_at")
    when = f"{started} 训练" if started else "训练时间未知"
    subtitle = f"数据源:{run_dir / 'metrics.json'} · loss_curve({when},逐 epoch 记录)"
    out = run_dir / "curve.html"
    out.write_text(build_svg(metrics.get("loss_curve") or [], title=title, subtitle=subtitle), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 run 目录 metrics.json 生成训练曲线 curve.html")
    parser.add_argument("--run-dir", required=True, help="训练 run 目录(含 metrics.json)")
    args = parser.parse_args(argv)
    out = write_curve_html(args.run_dir)
    print(f"[Plot] 曲线已生成 → {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
