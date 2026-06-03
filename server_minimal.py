#!/usr/bin/env python
"""最小化服务器，用于测试基础功能"""
import sys
sys.stdout.reconfigure(line_buffering=True)
print("[Minimal] Starting...", flush=True)

from aiohttp import web
print("[Minimal] aiohttp imported", flush=True)

async def hello(request):
    return web.Response(text="Server OK!")

app = web.Application()
app.router.add_get('/', hello)
app.router.add_static('/frontend/', path='./frontend/', name='frontend')

print("[Minimal] Starting server on http://localhost:8080", flush=True)
web.run_app(app, host='0.0.0.0', port=8080)
