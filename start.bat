@echo off
chcp 65001 >nul
title 某行核心系统迁移知识库 Demo

echo ============================================
echo  某行核心系统迁移知识库 - 一键启动
echo  前端: http://localhost:5666
echo  后端: http://127.0.0.1:8000/docs
echo ============================================
echo.

REM ---- 启动后端 ----
cd /d "%~dp0backend"
if not exist .env copy .env.example .env >nul
start "kb-backend" cmd /k "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

REM ---- 等后端就绪 ----
echo 等待后端就绪...
:waitloop
timeout /t 1 /nobreak >nul
curl -s -o nul http://127.0.0.1:8000/api/v1/health && goto frontend
goto waitloop

:frontend
echo 后端已就绪，启动前端...
cd /d "%~dp0frontend"
start "kb-frontend" cmd /k "pnpm dev:antd"

echo.
echo 两个窗口已启动（关闭对应窗口即停止对应服务）。
echo 浏览器即将打开 http://localhost:5666
timeout /t 12 /nobreak >nul
start http://localhost:5666
pause >nul
