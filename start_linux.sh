#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "========================================"
echo "    AutoBuy Linux 启动脚本"
echo "========================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "[错误] 未检测到 python3，请先安装 Python 3.8+"
  exit 1
fi

echo "[1/5] 检测到 Python 环境"
python3 --version

if [ -f ".venv/bin/activate" ]; then
  echo "[2/5] 激活 .venv 虚拟环境..."
  # shellcheck disable=SC1091
  source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  echo "[2/5] 激活 venv 虚拟环境..."
  # shellcheck disable=SC1091
  source venv/bin/activate
else
  echo "[2/5] 未检测到虚拟环境，使用系统 Python"
fi

if command -v google-chrome >/dev/null 2>&1; then
  BROWSER_NAME="google-chrome"
elif command -v chromium >/dev/null 2>&1; then
  BROWSER_NAME="chromium"
elif command -v chromium-browser >/dev/null 2>&1; then
  BROWSER_NAME="chromium-browser"
else
  echo "[警告] 未检测到 Chrome/Chromium，Selenium 可能无法正常拉起浏览器窗口"
  BROWSER_NAME=""
fi

if [ -n "$BROWSER_NAME" ]; then
  echo "[3/5] 检测到浏览器：$BROWSER_NAME"
else
  echo "[3/5] 未检测到可用浏览器"
fi

echo "[4/5] 检查依赖..."
if ! python3 -c "import flask" >/dev/null 2>&1; then
  echo "    依赖未安装，正在安装..."
  pip install -r requirements.txt
else
  echo "    依赖已安装"
fi

read -r -p "请输入启动端口（直接回车自动从 5000 开始寻找空闲端口）: " PORT
PORT="${PORT:-5000}"
ORIGINAL_PORT="$PORT"

is_port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -lnt | grep -q ":${port} "
  else
    netstat -lnt 2>/dev/null | grep -q ":${port} "
  fi
}

while is_port_in_use "$PORT"; do
  echo "[提示] 端口 $PORT 已被占用，尝试下一个端口..."
  PORT=$((PORT + 1))
done

if [ "$ORIGINAL_PORT" != "$PORT" ]; then
  echo "[提示] 已自动切换到空闲端口：$PORT"
fi

echo "[5/5] 启动 Web 应用..."
echo "========================================"
echo

echo "应用启动成功！即将自动打开浏览器访问："
echo "http://localhost:$PORT"
echo

echo "提示:"
echo "  - Linux 下若要看到 Selenium 拉起的 Chrome 窗口，必须在有图形桌面的会话里运行"
echo "  - 如果通过 SSH 纯终端运行，Chrome 可能无法显示窗口"
echo "  - 可使用 Ctrl+C 停止服务"
echo

echo "========================================"
echo

if command -v xdg-open >/dev/null 2>&1; then
  (sleep 2; xdg-open "http://localhost:$PORT" >/dev/null 2>&1 || true) &
fi

python3 app.py --port "$PORT"
