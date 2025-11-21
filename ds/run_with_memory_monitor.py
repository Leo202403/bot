#!/usr/bin/env python3
"""
【V8.5.2.4.89.2】带内存监控的回测运行器
"""
import tracemalloc
import sys
import time
import threading

# 启动内存跟踪
tracemalloc.start()

def background_monitor():
    """后台内存监控线程"""
    log_file = open("memory_monitor_simple.log", "w")
    log_file.write("时间,当前内存(MB),峰值内存(MB)\n")
    log_file.flush()
    
    while True:
        try:
            current, peak = tracemalloc.get_traced_memory()
            current_mb = current / 1024 / 1024
            peak_mb = peak / 1024 / 1024
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log_line = f"{timestamp},{current_mb:.2f},{peak_mb:.2f}\n"
            log_file.write(log_line)
            log_file.flush()
            
            # 内存警告
            if current_mb > 800:
                print(f"⚠️ [内存警告] 当前: {current_mb:.2f}MB, 峰值: {peak_mb:.2f}MB", flush=True)
            
            time.sleep(5)
        except Exception as e:
            print(f"⚠️ 内存监控错误: {e}", flush=True)
            time.sleep(5)

# 启动后台监控线程
monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

print("✓ 内存监控已启动（日志：memory_monitor_simple.log)", flush=True)

# 设置Python路径
sys.path.insert(0, '/root/10-23-bot/ds')

# 导入并运行主程序
try:
    # 使用runpy而不是importlib，更可靠
    import runpy
    runpy.run_path('deepseek_多币种智能版.py', run_name='__main__')
except Exception as e:
    print(f"❌ 运行失败: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)

