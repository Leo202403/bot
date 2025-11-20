"""
内存监控系统 - 精确追踪OOM位置
V8.5.2.4.89.2

功能：
1. 实时监控内存使用（RSS/VMS）
2. 记录每个关键步骤的内存变化
3. OOM预警（接近限制时警告）
4. 生成详细的内存分析报告
5. 支持装饰器和上下文管理器两种用法
"""

import os
import gc
import time
import psutil
import traceback
import threading
from datetime import datetime
from functools import wraps
from contextlib import contextmanager
from typing import Optional, List, Dict, Any


class MemoryMonitor:
    """内存监控器"""
    
    def __init__(
        self,
        name: str = "default",
        log_file: str = "memory_monitor.log",
        warning_threshold_mb: int = 800,  # 警告阈值（MB）
        critical_threshold_mb: int = 950,  # 危险阈值（MB）
        check_interval: float = 5.0,  # 后台检查间隔（秒）
        enable_background_monitor: bool = True
    ):
        self.name = name
        self.log_file = log_file
        self.warning_threshold = warning_threshold_mb * 1024 * 1024  # 转为字节
        self.critical_threshold = critical_threshold_mb * 1024 * 1024
        self.check_interval = check_interval
        self.enable_background = enable_background_monitor
        
        # 内存记录
        self.records: List[Dict[str, Any]] = []
        self.checkpoints: Dict[str, Dict[str, Any]] = {}
        
        # 进程信息
        self.process = psutil.Process(os.getpid())
        self.baseline_memory = self._get_memory_info()
        
        # 后台监控线程
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_running = False
        
        # 初始化日志文件
        self._init_log_file()
        
        if self.enable_background:
            self.start_background_monitor()
    
    def _get_memory_info(self) -> Dict[str, int]:
        """获取当前内存信息"""
        mem_info = self.process.memory_info()
        return {
            'rss': mem_info.rss,  # 实际物理内存
            'vms': mem_info.vms,  # 虚拟内存
            'timestamp': time.time()
        }
    
    def _format_size(self, bytes_size: int) -> str:
        """格式化字节大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.2f}{unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.2f}TB"
    
    def _init_log_file(self):
        """初始化日志文件"""
        with open(self.log_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"内存监控日志 - {self.name}\n")
            f.write(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"PID: {os.getpid()}\n")
            f.write(f"基线内存: RSS={self._format_size(self.baseline_memory['rss'])}, "
                   f"VMS={self._format_size(self.baseline_memory['vms'])}\n")
            f.write(f"警告阈值: {self._format_size(self.warning_threshold)}\n")
            f.write(f"危险阈值: {self._format_size(self.critical_threshold)}\n")
            f.write("=" * 80 + "\n\n")
    
    def _log(self, message: str, level: str = "INFO"):
        """写入日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] [{level}] {message}\n"
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_line)
        
        # 同时打印到控制台（警告和错误）
        if level in ['WARNING', 'ERROR', 'CRITICAL']:
            print(f"[MemoryMonitor] {log_line.strip()}")
    
    def checkpoint(self, name: str, details: str = ""):
        """设置检查点"""
        mem_info = self._get_memory_info()
        
        # 计算与基线的差异
        rss_delta = mem_info['rss'] - self.baseline_memory['rss']
        vms_delta = mem_info['vms'] - self.baseline_memory['vms']
        
        # 计算与上一个检查点的差异
        if self.records:
            last_record = self.records[-1]
            rss_increase = mem_info['rss'] - last_record['rss']
            vms_increase = mem_info['vms'] - last_record['vms']
        else:
            rss_increase = 0
            vms_increase = 0
        
        # 保存检查点
        record = {
            'name': name,
            'details': details,
            'rss': mem_info['rss'],
            'vms': mem_info['vms'],
            'rss_delta': rss_delta,
            'vms_delta': vms_delta,
            'rss_increase': rss_increase,
            'vms_increase': vms_increase,
            'timestamp': mem_info['timestamp']
        }
        
        self.records.append(record)
        self.checkpoints[name] = record
        
        # 检查是否超过阈值
        level = "INFO"
        if mem_info['rss'] >= self.critical_threshold:
            level = "CRITICAL"
        elif mem_info['rss'] >= self.warning_threshold:
            level = "WARNING"
        
        # 记录日志
        log_msg = (
            f"[{name}] RSS={self._format_size(mem_info['rss'])} "
            f"(Δ{self._format_size(rss_delta)}, +{self._format_size(rss_increase)})"
        )
        if details:
            log_msg += f" | {details}"
        
        self._log(log_msg, level)
        
        # 如果达到危险阈值，触发GC并警告
        if mem_info['rss'] >= self.critical_threshold:
            self._log(
                f"⚠️ 内存接近危险阈值！当前RSS={self._format_size(mem_info['rss'])} "
                f"(阈值={self._format_size(self.critical_threshold)})",
                "CRITICAL"
            )
            self._log("正在触发垃圾回收...", "INFO")
            gc.collect()
            
            # GC后重新检查
            new_mem_info = self._get_memory_info()
            freed = mem_info['rss'] - new_mem_info['rss']
            self._log(
                f"GC完成，释放{self._format_size(freed)}，"
                f"当前RSS={self._format_size(new_mem_info['rss'])}",
                "INFO"
            )
    
    def _background_monitor(self):
        """后台监控线程"""
        while self.monitor_running:
            try:
                mem_info = self._get_memory_info()
                
                # 只在超过警告阈值时记录
                if mem_info['rss'] >= self.warning_threshold:
                    rss_delta = mem_info['rss'] - self.baseline_memory['rss']
                    self._log(
                        f"[后台监控] RSS={self._format_size(mem_info['rss'])} "
                        f"(Δ{self._format_size(rss_delta)})",
                        "WARNING" if mem_info['rss'] < self.critical_threshold else "CRITICAL"
                    )
                    
                    # 如果达到危险阈值，尝试获取堆栈信息
                    if mem_info['rss'] >= self.critical_threshold:
                        stack_info = "\n".join(traceback.format_stack())
                        self._log(
                            f"⚠️ 当前调用栈:\n{stack_info}",
                            "CRITICAL"
                        )
                
                time.sleep(self.check_interval)
            except Exception as e:
                self._log(f"后台监控异常: {e}", "ERROR")
                break
    
    def start_background_monitor(self):
        """启动后台监控"""
        if not self.monitor_running:
            self.monitor_running = True
            self.monitor_thread = threading.Thread(
                target=self._background_monitor,
                daemon=True
            )
            self.monitor_thread.start()
            self._log("后台监控已启动", "INFO")
    
    def stop_background_monitor(self):
        """停止后台监控"""
        if self.monitor_running:
            self.monitor_running = False
            if self.monitor_thread:
                self.monitor_thread.join(timeout=5)
            self._log("后台监控已停止", "INFO")
    
    def get_top_memory_increases(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """获取内存增长最大的检查点"""
        sorted_records = sorted(
            self.records,
            key=lambda x: x['rss_increase'],
            reverse=True
        )
        return sorted_records[:top_n]
    
    def generate_report(self) -> str:
        """生成内存分析报告"""
        lines = []
        lines.append("=" * 80)
        lines.append(f"内存监控报告 - {self.name}")
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 80)
        lines.append("")
        
        # 当前内存状态
        current_mem = self._get_memory_info()
        lines.append("📊 当前内存状态:")
        lines.append(f"  RSS: {self._format_size(current_mem['rss'])}")
        lines.append(f"  VMS: {self._format_size(current_mem['vms'])}")
        lines.append(f"  基线RSS: {self._format_size(self.baseline_memory['rss'])}")
        lines.append(f"  总增长: {self._format_size(current_mem['rss'] - self.baseline_memory['rss'])}")
        lines.append("")
        
        # Top 10内存增长点
        lines.append("🔥 Top 10内存增长点:")
        top_increases = self.get_top_memory_increases(10)
        for i, record in enumerate(top_increases, 1):
            lines.append(
                f"  #{i} [{record['name']}] "
                f"+{self._format_size(record['rss_increase'])} "
                f"(总RSS={self._format_size(record['rss'])})"
            )
            if record['details']:
                lines.append(f"      详情: {record['details']}")
        lines.append("")
        
        # 所有检查点
        lines.append("📍 所有检查点:")
        for i, record in enumerate(self.records, 1):
            lines.append(
                f"  {i:3d}. [{record['name']}] "
                f"RSS={self._format_size(record['rss'])} "
                f"(Δ{self._format_size(record['rss_delta'])}, "
                f"+{self._format_size(record['rss_increase'])})"
            )
        
        lines.append("")
        lines.append("=" * 80)
        
        report = "\n".join(lines)
        
        # 保存到日志
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write("\n" + report + "\n")
        
        return report
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.stop_background_monitor()
        report = self.generate_report()
        print(report)


# =============== 装饰器和上下文管理器 ===============

# 全局监控器实例
_global_monitor: Optional[MemoryMonitor] = None


def init_global_monitor(
    name: str = "global",
    log_file: str = "memory_monitor.log",
    warning_threshold_mb: int = 800,
    critical_threshold_mb: int = 950
):
    """初始化全局监控器"""
    global _global_monitor
    _global_monitor = MemoryMonitor(
        name=name,
        log_file=log_file,
        warning_threshold_mb=warning_threshold_mb,
        critical_threshold_mb=critical_threshold_mb
    )
    return _global_monitor


def get_global_monitor() -> Optional[MemoryMonitor]:
    """获取全局监控器"""
    return _global_monitor


def memory_checkpoint(name: str, details: str = ""):
    """记录检查点（使用全局监控器）"""
    if _global_monitor:
        _global_monitor.checkpoint(name, details)


def monitor_function(name: Optional[str] = None):
    """装饰器：监控函数的内存使用"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            func_name = name or func.__name__
            
            if _global_monitor:
                _global_monitor.checkpoint(f"{func_name}_START")
            
            try:
                result = func(*args, **kwargs)
                
                if _global_monitor:
                    _global_monitor.checkpoint(f"{func_name}_END")
                
                return result
            except Exception as e:
                if _global_monitor:
                    _global_monitor.checkpoint(
                        f"{func_name}_ERROR",
                        details=f"Exception: {str(e)}"
                    )
                raise
        
        return wrapper
    return decorator


@contextmanager
def memory_context(name: str, details: str = ""):
    """上下文管理器：监控代码块的内存使用"""
    if _global_monitor:
        _global_monitor.checkpoint(f"{name}_START", details)
    
    try:
        yield
    finally:
        if _global_monitor:
            _global_monitor.checkpoint(f"{name}_END")


# =============== 使用示例 ===============

if __name__ == "__main__":
    # 示例1：使用全局监控器
    monitor = init_global_monitor(
        name="test",
        log_file="test_memory.log",
        warning_threshold_mb=100,  # 测试用，设低一点
        critical_threshold_mb=200
    )
    
    memory_checkpoint("程序启动")
    
    # 示例2：使用装饰器
    @monitor_function("test_function")
    def test_func():
        data = [0] * 10000000  # 分配一些内存
        return len(data)
    
    result = test_func()
    memory_checkpoint("test_function完成", f"结果={result}")
    
    # 示例3：使用上下文管理器
    with memory_context("数据处理"):
        big_list = [0] * 50000000
        memory_checkpoint("大列表创建完成", f"大小={len(big_list)}")
    
    # 生成报告
    report = monitor.generate_report()
    print(report)

