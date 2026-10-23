"""部署面 nginx 配置契约 —— socket.io 反代块(2026-10-23 线上认领失效收口)。

背景:坐席台(apps/merchant-admin,3006)以 path=/socket.io + transports=
['websocket'] 连同源 socket.io;dev 由 Vite proxy 代转,生产 nginx 此前只有
/api/ 反代块,顶层 /socket.io/ 落进 `location / { try_files /index.html }`
SPA 回退——WebSocket 握手收到 HTML,坐席永远不在线、人工接管无法认领
(实弹:3006 /socket.io polling 返回 index.html,直连 gateway:4000 握手正常)。
本册把「3006 server 块必须带 /socket.io/ 反代(升级头 + 长连接调优)」钉死为
静态配置契约;线上行为由部署后探针(轮询握手 JSON + WS 101)验收。
"""

from __future__ import annotations

import re
from pathlib import Path

_NGINX_CONF = Path(__file__).resolve().parents[3] / "deploy" / "nginx.conf"


def _server_block(listen_port: int) -> str:
    """按 listen 端口切出 server 块文本。"""
    text = _NGINX_CONF.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^server \{)", text, flags=re.MULTILINE)
    for block in blocks:
        if re.search(rf"^    listen {listen_port};$", block, flags=re.MULTILINE):
            return block
    raise AssertionError(f"deploy/nginx.conf 缺少 listen {listen_port} 的 server 块")


class TestSocketIoProxy:
    def test_merchant_admin_block_proxies_socket_io(self):
        """/socket.io/ 必须反代 gateway 且带 WS 升级头 —— 缺块即复现线上认领失效。"""
        block = _server_block(3006)
        m = re.search(r"location /socket\.io/ \{.*?\n    \}", block, flags=re.DOTALL)
        assert m is not None, (
            "3006 server 块缺 location /socket.io/ —— socket.io 握手会落进 "
            "SPA 回退(index.html),坐席台永不上线(2026-10-23 线上实弹)"
        )
        loc = m.group(0)
        assert "gateway:4000" in loc, "socket.io 反代必须指向 gateway upstream"
        assert "proxy_set_header Upgrade $http_upgrade;" in loc
        assert "proxy_set_header Connection $connection_upgrade;" in loc, (
            "缺 Connection 升级头,WS 握手到不了 Upgrade 语义"
        )

    def test_socket_io_long_connection_tuning(self):
        """长连接调优与 /api/ 同款:关缓冲 + 1h 读超时(socket.io 心跳 25s,短超时会腰斩长连)。"""
        block = _server_block(3006)
        m = re.search(r"location /socket\.io/ \{.*?\n    \}", block, flags=re.DOTALL)
        assert m is not None
        loc = m.group(0)
        assert "proxy_buffering off;" in loc
        assert "proxy_read_timeout 3600s;" in loc
