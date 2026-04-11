from flask import Flask, render_template, request, jsonify, Response
import threading
import logging
from datetime import datetime
import time
import os
import json
import sys
import subprocess
from collections import deque

from seckill import SeckillWorker, TimeManager

# 设置项目根目录
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DRIVERS_DIR = os.path.join(PROJECT_DIR, 'drivers')

app = Flask(__name__)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 全局状态管理
class TaskManager:
    def __init__(self):
        self.tasks = {}
        self.task_counter = 0
        self.lock = threading.Lock()

    def create_task(self, platform, target_time=None, time_source='system'):
        with self.lock:
            self.task_counter += 1
            task_id = f"task_{self.task_counter}"
            self.tasks[task_id] = {
                'id': task_id,
                'platform': platform,
                'status': 'pending',
                'logs': deque(maxlen=300),
                'driver': None,
                'running': False,
                'thread': None,
                'target_time': target_time,
                'time_source': time_source,
                'time_locked': False
            }
        return task_id

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def add_log(self, task_id, message):
        if task_id in self.tasks:
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.tasks[task_id]['logs'].append({
                'time': timestamp,
                'message': message
            })

    def stop_task(self, task_id):
        if task_id in self.tasks:
            self.tasks[task_id]['running'] = False
            self.tasks[task_id]['status'] = 'stopped'

    def remove_task(self, task_id):
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if task['driver']:
                try:
                    task['driver'].quit()
                except:
                    pass
            del self.tasks[task_id]

task_manager = TaskManager()


# 统一抢购逻辑
def run_seckill_task(task_id, platform, target_time=None, time_source='system', login_wait=15):
    """
    统一抢购任务
    :param task_id: 任务ID
    :param platform: 平台名称 (jd/tb/bb)
    :param target_time: 目标时间
    :param time_source: 时间源（system/syiban_taobao）
    :param login_wait: 登录等待时间
    """
    task = task_manager.get_task(task_id)
    if not task:
        return

    task['status'] = 'running'
    task['running'] = True
    task['worker'] = None

    def log_callback(message):
        task_manager.add_log(task_id, message)

    worker = None
    try:
        worker = SeckillWorker(platform, log_callback=log_callback)
        task['worker'] = worker
        # 启用登录和购物车确认
        success = worker.start_seckill(
            target_time=target_time,
            time_source=time_source,
            login_wait=login_wait,
            wait_for_login_confirm=True,
            wait_for_cart_confirm=True
        )
        task['status'] = 'success' if success else 'failed'
    except Exception as e:
        task_manager.add_log(task_id, f"错误：{str(e)}")
        task['status'] = 'error'
    finally:
        task['running'] = False


# 路由定义
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/help')
def help_page():
    return render_template('help.html')


@app.route('/api/time/status', methods=['GET'])
def time_status():
    source = (request.args.get('source') or 'system').lower()
    platform = (request.args.get('platform') or 'tb').lower()
    if source not in ['system', 'syiban_taobao']:
        source = 'system'

    system_ms = TimeManager.get_system_time()
    selected_ms = TimeManager.now_ms(source=source, platform=platform)

    system_dt = datetime.fromtimestamp(system_ms / 1000)
    selected_dt = datetime.fromtimestamp(selected_ms / 1000)

    tz_name = os.environ.get('TZ') or (time.tzname[0] if time.tzname else 'UTC')
    return jsonify({
        'source': source,
        'platform': platform,
        'timezone': tz_name,
        'system_timestamp_ms': system_ms,
        'system_time_iso': system_dt.isoformat(timespec='milliseconds'),
        'selected_timestamp_ms': selected_ms,
        'selected_time_iso': selected_dt.isoformat(timespec='milliseconds')
    })


def _spawn_detached_restart():
    """启动一个脱离当前进程的重启器，避免在请求线程里 execv 导致卡死。"""
    argv = [sys.executable] + sys.argv

    if os.name == 'nt':
        # Windows：用辅助脚本在新的可见控制台窗口中重启，避免“后台活着但没窗口”
        import tempfile
        helper_code = r'''
import os
import sys
import time
import subprocess

project_dir = sys.argv[1]
argv = sys.argv[2:]

time.sleep(2)

# 避免使用 cmd start 字符串拼接导致路径被错误解析（例如 "\AutoBuy\"）
# 直接以新控制台启动 Python 进程更稳。
if len(argv) >= 2 and not os.path.isabs(argv[1]):
    argv[1] = os.path.join(project_dir, argv[1])

subprocess.Popen(
    argv,
    cwd=project_dir,
    creationflags=subprocess.CREATE_NEW_CONSOLE,
)
'''
        fd, helper_path = tempfile.mkstemp(prefix='autobuy_restart_', suffix='.py')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(helper_code)
        subprocess.Popen(
            [sys.executable, helper_path, PROJECT_DIR, *argv],
            cwd=PROJECT_DIR,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        # Linux / macOS：sleep 后后台拉起
        import shlex
        cmdline = ' '.join(shlex.quote(x) for x in argv)
        subprocess.Popen(
            ['sh', '-c', f'sleep 2; cd {shlex.quote(PROJECT_DIR)}; nohup {cmdline} >/dev/null 2>&1 &'],
            cwd=PROJECT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _background_self_update():
    """后台自更新并重启当前进程。"""
    try:
        logger.info('开始执行应用自更新...')
        subprocess.run(['git', 'pull', '--rebase', '--autostash', 'origin', 'main'], cwd=PROJECT_DIR, check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', os.path.join(PROJECT_DIR, 'requirements.txt')], cwd=PROJECT_DIR, check=True)
        logger.info('自更新完成，准备重启应用...')
        _spawn_detached_restart()
        time.sleep(0.5)
        os._exit(0)
    except Exception as e:
        logger.error(f'自更新失败: {e}')


# API 路由
@app.route('/api/app/update', methods=['POST'])
def update_app():
    thread = threading.Thread(target=_background_self_update, daemon=True)
    thread.start()
    return jsonify({'status': 'updating', 'message': '开始拉取更新并准备重启，请稍后刷新页面'})


# API 路由
@app.route('/api/driver/download', methods=['POST'])
def download_driver():
    """下载驱动"""
    try:
        from webdriver_manager.chrome import ChromeDriverManager

        logger.info("开始检查 Chrome 浏览器版本...")
        driver_manager = ChromeDriverManager()
        logger.info("正在下载匹配的 ChromeDriver...")
        driver_path = driver_manager.install()

        logger.info(f"ChromeDriver 准备完成，路径: {driver_path}")

        # 返回详细的消息
        return jsonify({
            'success': True,
            'message': '驱动准备完成',
            'path': driver_path
        })
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"下载驱动失败: {e}\n{error_detail}")
        return jsonify({
            'success': False,
            'message': f'下载失败: {str(e)}'
        }), 500


# API 路由
@app.route('/api/jd/start', methods=['POST'])
def start_jd():
    data = request.json or {}
    target_time = data.get('target_time')
    time_source = (data.get('time_source') or 'system').lower()

    if not target_time:
        return jsonify({'error': '请设置抢购时间'}), 400

    if time_source not in ['system', 'syiban_taobao']:
        return jsonify({'error': '不支持的时间源'}), 400

    task_id = task_manager.create_task('jd', target_time, time_source=time_source)
    thread = threading.Thread(target=run_seckill_task, args=(task_id, 'jd', target_time, time_source, 25))
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id, 'status': 'started'})


@app.route('/api/tb/start', methods=['POST'])
def start_tb():
    data = request.json or {}
    target_time = data.get('target_time')
    time_source = (data.get('time_source') or 'system').lower()

    if not target_time:
        return jsonify({'error': '请设置抢购时间'}), 400

    if time_source not in ['system', 'syiban_taobao']:
        return jsonify({'error': '不支持的时间源'}), 400

    task_id = task_manager.create_task('tb', target_time, time_source=time_source)
    thread = threading.Thread(target=run_seckill_task, args=(task_id, 'tb', target_time, time_source, 15))
    thread.daemon = True
    thread.start()

    return jsonify({'task_id': task_id, 'status': 'started'})


@app.route('/api/tasks/<task_id>/confirm', methods=['POST'])
def confirm_stage(task_id):
    """用户确认当前阶段，进入下一步"""
    data = request.json
    stage = data.get('stage')  # 'login' 或 'cart'
    task = task_manager.get_task(task_id)

    if not task:
        return jsonify({'error': '任务不存在'}), 404

    if not task.get('worker'):
        return jsonify({'error': 'Worker未初始化'}), 400

    worker = task['worker']
    # 使用字典来设置确认状态
    if hasattr(worker, '_confirm_states'):
        worker._confirm_states[stage] = True
        logger.info(f"设置 {stage}_confirmed = True for task {task_id}")
        logger.info(f"当前确认状态: {worker._confirm_states}")
    else:
        logger.error(f"Worker 没有 _confirm_states 属性")

    if stage == 'login':
        task['time_locked'] = True

    task_manager.add_log(task_id, f"用户已确认{stage}阶段，继续下一步...")

    return jsonify({'status': 'ok', 'time_locked': task.get('time_locked', False)})


@app.route('/api/tasks/<task_id>/status')
def get_task_status(task_id):
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    return jsonify({
        'id': task['id'],
        'platform': task['platform'],
        'status': task['status'],
        'running': task['running'],
        'target_time': task.get('target_time'),
        'time_source': task.get('time_source', 'system'),
        'time_locked': task.get('time_locked', False),
        'logs': list(task['logs'])
    })


@app.route('/api/tasks/<task_id>/target-time', methods=['POST'])
def update_target_time(task_id):
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    if task.get('time_locked'):
        return jsonify({'error': '购物车已确认，抢购时间已锁定'}), 400

    data = request.json or {}
    target_time = data.get('target_time')
    if not target_time:
        return jsonify({'error': '请提供新的抢购时间'}), 400

    time_source = data.get('time_source')
    if time_source is not None:
        time_source = (time_source or 'system').lower()
        if time_source not in ['system', 'syiban_taobao']:
            return jsonify({'error': '不支持的时间源'}), 400
        task['time_source'] = time_source

    task['target_time'] = target_time
    worker = task.get('worker')
    if worker:
        try:
            worker.target_time = target_time
            if time_source is not None:
                worker.time_source = task.get('time_source', 'system')
        except Exception:
            pass

    source_text = '系统时间' if task.get('time_source', 'system') == 'system' else 'syiban淘宝时间'
    task_manager.add_log(task_id, f'抢购时间已更新为：{target_time}（时间源：{source_text}）')
    return jsonify({
        'status': 'ok',
        'target_time': target_time,
        'time_source': task.get('time_source', 'system'),
        'time_locked': task.get('time_locked', False)
    })


@app.route('/api/tasks/<task_id>/stop', methods=['POST'])
def stop_task(task_id):
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    task_manager.stop_task(task_id)
    task_manager.add_log(task_id, "用户请求停止任务")

    return jsonify({'status': 'stopped'})


@app.route('/api/tasks/<task_id>/close-browser', methods=['POST'])
def close_browser(task_id):
    """关闭浏览器"""
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    worker = task.get('worker')
    if worker and hasattr(worker, 'driver') and worker.driver:
        try:
            worker.stop()
            task_manager.add_log(task_id, "浏览器已关闭")
            return jsonify({'status': 'ok'})
        except Exception as e:
            task_manager.add_log(task_id, f"关闭浏览器失败：{str(e)}")
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify({'error': '浏览器未打开或已关闭'}), 400


@app.route('/api/tasks/<task_id>/logs')
def stream_logs(task_id):
    def generate():
        last_log_count = 0
        while True:
            task = task_manager.get_task(task_id)
            if not task:
                yield f"data: {json.dumps({'error': '任务不存在'})}\n\n"
                break

            logs = list(task['logs'])
            if len(logs) > last_log_count:
                for log in logs[last_log_count:]:
                    yield f"data: {json.dumps(log)}\n\n"
                last_log_count = len(logs)

            if not task['running'] and task['status'] in ['success', 'failed', 'error', 'stopped']:
                break

            time.sleep(0.5)

    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='AutoBuy Web UI')
    parser.add_argument('--host', default=os.getenv('HOST', '0.0.0.0'), help='监听地址，默认 0.0.0.0')
    parser.add_argument('--port', type=int, default=int(os.getenv('PORT', '5000')), help='监听端口，默认 5000，可多实例分别指定')
    parser.add_argument('--debug', action='store_true', default=os.getenv('DEBUG', 'false').lower() == 'true', help='是否开启 Flask debug')
    args = parser.parse_args()

    logger.info(f"启动 AutoBuy Web UI: http://{args.host}:{args.port} (debug={args.debug})")
    app.run(debug=args.debug, host=args.host, port=args.port)
