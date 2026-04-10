@echo off
chcp 65001 >nul
echo ========================================
echo     自动抢购工具 - 快速启动脚本
echo ========================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8 或更高版本
    echo 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [1/5] 检测到 Python 环境
python --version

:: 检查虚拟环境是否存在
if exist ".venv\Scripts\activate.bat" (
    echo [2/5] 激活虚拟环境...
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    echo [2/5] 激活虚拟环境...
    call venv\Scripts\activate.bat
) else (
    echo [2/5] 虚拟环境不存在，使用系统 Python
    echo     提示：建议使用虚拟环境隔离依赖
)

:: 检查 Chrome 是否安装
reg query "HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon" >nul 2>&1
if errorlevel 1 (
    reg query "HKEY_LOCAL_MACHINE\Software\Google\Chrome\BLBeacon" >nul 2>&1
    if errorlevel 1 (
        echo [警告] 未检测到 Chrome 浏览器
        echo     请先安装 Chrome: https://www.google.com/chrome/
        echo.
    )
)

:: 检查依赖是否安装
echo [3/5] 检查依赖...
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo     依赖未安装，正在安装...
    echo.
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
) else (
    echo     依赖已安装
)

:: 检查 app.py 是否存在
if not exist "app.py" (
    echo [错误] 未找到 app.py 文件
    echo     请确保在项目根目录下运行此脚本
    pause
    exit /b 1
)

echo [4/5] 准备启动应用...
echo.

:: 启动应用
set PORT=%1
if "%PORT%"=="" (
    echo.
    set /p PORT=请输入启动端口（直接回车自动从 5000 开始寻找空闲端口）: 
)

if "%PORT%"=="" set PORT=5000

:: 自动探测空闲端口（仅当用户未显式指定或指定端口被占用时）
set ORIGINAL_PORT=%PORT%
:CHECK_PORT
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [提示] 端口 %PORT% 已被占用，尝试下一个端口...
    set /a PORT=%PORT%+1
    goto CHECK_PORT
)

if not "%ORIGINAL_PORT%"=="%PORT%" (
    echo [提示] 已自动切换到空闲端口：%PORT%
)

echo [5/5] 启动 Web 应用...
echo ========================================
echo.
echo 应用启动成功！即将自动打开浏览器访问:
echo.
echo     http://localhost:%PORT%
echo.
echo 提示:
echo   - 首次启动会自动下载 ChromeDriver，请耐心等待
echo   - 请勿关闭此窗口，否则服务将停止
echo   - 使用 Ctrl+C 可停止服务
echo   - 支持多开：双击后输入端口；若留空则自动从 5000 开始找可用端口
echo.
echo ========================================
echo.

start "" "http://localhost:%PORT%"
python app.py --port %PORT%

:: 如果程序异常退出
echo.
echo ========================================
echo 应用已停止
echo ========================================
pause
