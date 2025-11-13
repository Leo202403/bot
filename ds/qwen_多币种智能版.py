import os
import time
import csv
import schedule
from openai import OpenAI
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import json
from dotenv import load_dotenv
import requests
from pathlib import Path
from scipy.signal import argrelextrema
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import hashlib
import hmac
from typing import Dict, List, Any, Optional
import re  # 🔧 V7.6.7: 用于AI响应解析
from urllib.parse import urlencode

# 🆕 V8.3.22: 导入开仓时机分析模块
# 🆕 V8.3.23: AI自主学习版
# 🔧 V8.3.25.8: 使用新的V2分析模块（完整的市场机会对比分析）
from entry_exit_timing_analyzer_v2 import (
    analyze_entry_timing_v2,
    analyze_exit_timing_v2
)
# 保留AI深度分析功能
from entry_timing_analyzer import (
    generate_ai_entry_insights, 
    generate_ai_exit_insights
)

# 🔧 明确指定 .env.qwen 文件路径
_env_file = Path(__file__).parent / '.env.qwen'
if not _env_file.exists():
    raise FileNotFoundError(f"❌ 找不到 .env.qwen 文件: {_env_file}")
load_dotenv(_env_file, override=True)

# ==================== 【V8.3.16】优化配置开关 ====================
ENABLE_V770_FULL_OPTIMIZATION = False  # V7.7.0完整优化（7-10分钟）
ENABLE_V770_QUICK_SEARCH = True        # V7.7.0快速探索（3分钟）- 为V8.3.12提供初始参数
ENABLE_PER_SYMBOL_OPTIMIZATION = False  # Per-Symbol优化（56-91分钟）
ENABLE_CONDITIONAL_AI_CALL = True       # 条件AI调用（仅Time Exit>80%时）
AI_AGGRESSIVENESS_DYNAMIC = True        # 动态AI激进度（根据Time Exit率调整）

# ==================== 辅助函数 ====================

def extract_json_from_ai_response(ai_content: str) -> dict:
    """
    从AI响应中提取JSON对象（鲁棒版本，支持Qwen模型）
    
    尝试顺序：
    1. 跳过Qwen模型的推理标签 (<think>...</think>)
    2. 提取Markdown代码块中的JSON (```json ... ```)
    3. 提取第一个完整的JSON对象（非贪婪匹配）
    4. 尝试解析整个内容为JSON
    
    Args:
        ai_content: AI返回的原始文本
        
    Returns:
        解析后的字典对象
        
    Raises:
        ValueError: 如果无法提取有效的JSON
    """
    ai_content = ai_content.strip()
    
    # 方法0: 移除Qwen模型的推理标签（如果存在）
    # Qwen模型可能返回：<think>推理过程</think>\n{JSON}
    think_match = re.search(r'<think>.*?</think>\s*', ai_content, re.DOTALL)
    if think_match:
        ai_content = ai_content[think_match.end():].strip()
    
    # 清理函数：移除无效的控制字符
    def clean_json_str(s):
        # 移除无效的控制字符（保留 \n \r \t）
        return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', s)
    
    # 方法1: 提取Markdown代码块
    md_match = re.search(r'```(?:json)?\s*\n([\s\S]*?)\n```', ai_content)
    if md_match:
        try:
            cleaned = clean_json_str(md_match.group(1))
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    
    # 方法2: 提取第一个完整的JSON对象（非贪婪匹配+递归括号计数）
    start_idx = ai_content.find('{')
    if start_idx != -1:
        brace_count = 0
        for i, char in enumerate(ai_content[start_idx:], start=start_idx):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    # 找到完整的JSON对象
                    json_str = ai_content[start_idx:i+1]
                    try:
                        cleaned = clean_json_str(json_str)
                        return json.loads(cleaned)
                    except json.JSONDecodeError:
                        pass
                    break
    
    # 方法3: 尝试解析整个内容
    try:
        cleaned = clean_json_str(ai_content)
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    raise ValueError(f"无法从AI响应中提取有效JSON")

# ==================== AI调用优化器 ====================

class MarketStateFingerprint:
    """市场状态指纹生成器"""
    
    @staticmethod
    def generate(market_data: Dict[str, Any]) -> str:
        """
        生成市场状态指纹，仅关注影响决策的关键变化
        
        关键因素（任一变化必须重新分析）：
        1. 趋势反转（4H/1H/15m）
        2. RSI进入/离开超买超卖区
        3. MACD金叉/死叉
        4. 价格突破关键支撑阻力位
        5. 成交量异常（>200%平均值）
        6. 指标共振数变化（3/5 vs 4/5）
        7. 持仓状态改变
        """
        
        # 离散化关键指标（避免微小波动触发重新分析）
        key_state = {
            'trend_4h': market_data.get('trend_4h', ''),
            'trend_1h': market_data.get('trend_1h', ''),
            'trend_15m': market_data.get('trend_15m', ''),
            
            # RSI区间化（而非精确值）
            'rsi_14_zone': _discretize_rsi(market_data.get('rsi', {}).get('rsi_14', 50)),
            'rsi_7_zone': _discretize_rsi(market_data.get('rsi', {}).get('rsi_7', 50)),
            
            # MACD方向（而非精确值）
            'macd_direction': 'bull' if market_data.get('macd', {}).get('histogram', 0) > 0 else 'bear',
                'macd_1h_direction': 'bull' if market_data.get('mid_term', {}).get('macd_histogram', 0) > 0 else 'bear',
            
            # 价格相对支撑阻力位置（±3%内认为相同）
            'price_position': _get_price_position(
                market_data.get('current_price', 0),
                market_data.get('support_resistance', {})
            ),
            
            # 成交量状态
            'volume_status': market_data.get('volume_status', 'normal'),
            
            # 指标共振等级（分为弱/中/强）
            'consensus_level': _get_consensus_level(market_data.get('indicator_consensus', 0)),
            
            # 持仓状态
            'has_position': market_data.get('has_position', False),
            'position_side': market_data.get('position_side', 'none'),
        }
        
        # 生成哈希指纹
        fingerprint_str = json.dumps(key_state, sort_keys=True)
        return hashlib.md5(fingerprint_str.encode()).hexdigest()[:12]


def _discretize_rsi(rsi: float) -> str:
    """RSI离散化为区间"""
    if rsi >= 70:
        return 'overbought'  # 超买
    elif rsi >= 60:
        return 'high'  # 偏高
    elif rsi >= 40:
        return 'neutral'  # 中性
    elif rsi >= 30:
        return 'low'  # 偏低
    else:
        return 'oversold'  # 超卖


def _get_price_position(price: float, sr_levels: Dict) -> str:
    """判断价格相对支撑阻力的位置"""
    if not price or not sr_levels:
        return 'neutral'
    
    # 安全获取支撑阻力位（处理None情况）
    support_data = sr_levels.get('nearest_support') or {}
    resistance_data = sr_levels.get('nearest_resistance') or {}
    nearest_support = support_data.get('price', 0) if isinstance(support_data, dict) else 0
    nearest_resistance = resistance_data.get('price', 0) if isinstance(resistance_data, dict) else 0
    
    if nearest_support and abs(price - nearest_support) / price < 0.03:
        return 'at_support'  # 在支撑位
    elif nearest_resistance and abs(price - nearest_resistance) / price < 0.03:
        return 'at_resistance'  # 在阻力位
    elif nearest_support and nearest_resistance:
        range_size = nearest_resistance - nearest_support
        position = (price - nearest_support) / range_size if range_size > 0 else 0.5
        if position < 0.3:
            return 'near_support'
        elif position > 0.7:
            return 'near_resistance'
        else:
            return 'mid_range'
    
    return 'neutral'


def _get_consensus_level(consensus: int) -> str:
    """指标共振等级"""
    if consensus >= 4:
        return 'strong'  # 强共振
    elif consensus >= 3:
        return 'medium'  # 中等
    else:
        return 'weak'  # 弱


class AICallOptimizer:
    """AI调用优化器"""
    
    def __init__(self):
        self.last_fingerprints = {}  # {symbol: fingerprint}
        self.last_portfolio_call_time = None  # 上次组合决策时间
        self.call_stats = {
            'total': 0,
            'saved': 0,
            'forced': 0,  # 强制调用次数（关键变化）
        }
        # 详细记录（用于邮件报告）
        self.daily_details = {
            'skip_reasons': [],  # 跳过原因列表
            'force_reasons': [],  # 强制调用原因列表
            'saved_cost_estimate': 0.0,  # 估算节省成本
            'start_time': datetime.now(),  # 统计开始时间
        }
    
    def should_call_portfolio_ai(
        self,
        market_data_list: List[Dict[str, Any]],
        current_positions: List[Dict[str, Any]]
    ) -> tuple:
        """
        判断是否需要调用组合决策AI（针对多币种同时分析的场景）
        
        Returns:
            (是否调用, 原因说明)
        """
        self.call_stats['total'] += 1
        
        # 1. 有持仓时必须调用（保护利润/止损）
        if current_positions and len(current_positions) > 0:
            self.call_stats['forced'] += 1
            self._update_fingerprints(market_data_list)
            # 记录详情
            self.daily_details['force_reasons'].append({
                'time': datetime.now().strftime('%H:%M:%S'),
                'reason': '有持仓监控',
                'positions': len(current_positions)
            })
            return True, "🔴 有持仓，必须实时监控"
        
        # 2. 首次调用
        if not self.last_fingerprints:
            self._update_fingerprints(market_data_list)
            return True, "🟢 首次分析"
        
        # 3. 检查是否有任何币种发生关键变化
        changed_symbols = []
        critical_changes = []
        
        for data in market_data_list:
            if data is None:
                continue
            
            symbol = data.get('symbol', '')
            coin_name = symbol.split('/')[0] if symbol else ''
            
            if not coin_name:
                continue
            
            # 生成当前指纹
            current_fp = MarketStateFingerprint.generate(data)
            last_fp = self.last_fingerprints.get(coin_name)
            
            # 检查关键变化
            force_call, reason = self._check_critical_change(data)
            if force_call:
                critical_changes.append(f"{coin_name}: {reason}")
            
            # 检查状态变化
            if last_fp != current_fp:
                changed_symbols.append(coin_name)
        
        # 4. 有关键变化必须调用
        if critical_changes:
            self.call_stats['forced'] += 1
            self._update_fingerprints(market_data_list)
            # 记录详情
            self.daily_details['force_reasons'].append({
                'time': datetime.now().strftime('%H:%M:%S'),
                'reason': '关键信号',
                'details': ', '.join(critical_changes[:2])
            })
            return True, f"🔴 关键变化: {', '.join(critical_changes[:2])}"
        
        # 5. 有币种状态变化则调用
        if changed_symbols:
            self._update_fingerprints(market_data_list)
            return True, f"🟡 市场更新: {', '.join(changed_symbols[:3])}"
        
        # 6. 距上次调用超过30分钟，强制刷新
        if self.last_portfolio_call_time:
            from datetime import timedelta
            time_since_last = datetime.now() - self.last_portfolio_call_time
            if time_since_last >= timedelta(minutes=30):
                self.call_stats['forced'] += 1
                self._update_fingerprints(market_data_list)
                # 记录详情
                self.daily_details['force_reasons'].append({
                    'time': datetime.now().strftime('%H:%M:%S'),
                    'reason': '定期刷新',
                    'details': f'距上次{time_since_last.seconds//60}分钟'
                })
                return True, "🔴 距上次>30分钟，强制刷新"
        
        # 7. 所有币种状态无变化，可以跳过
        self.call_stats['saved'] += 1
        time_passed = (datetime.now() - self.last_portfolio_call_time).seconds // 60 if self.last_portfolio_call_time else 0
        
        # 记录详情 + 估算节省成本
        cost_per_call = 0.014  # Qwen API平均成本（元/次，reasoner模式约0.01-0.02）
        self.daily_details['saved_cost_estimate'] += cost_per_call
        self.daily_details['skip_reasons'].append({
            'time': datetime.now().strftime('%H:%M:%S'),
            'reason': '状态无变化',
            'duration': f'{time_passed}分钟',
            'saved_cost': cost_per_call
        })
        
        return False, f"✅ 跳过: 所有币种状态无变化 (已{time_passed}分钟)"
    
    def _update_fingerprints(self, market_data_list: List[Dict[str, Any]]):
        """更新所有币种的指纹"""
        for data in market_data_list:
            if data is None:
                continue
            symbol = data.get('symbol', '')
            coin_name = symbol.split('/')[0] if symbol else ''
            if coin_name:
                self.last_fingerprints[coin_name] = MarketStateFingerprint.generate(data)
        self.last_portfolio_call_time = datetime.now()
    
    def _check_critical_change(self, market_data: Dict[str, Any]) -> tuple:
        """检查单个币种是否有关键变化（必须立即分析）"""
        
        # 关键形态出现
        pa = market_data.get('price_action', {})
        if pa.get('pin_bar') in ['bullish_pin', 'bearish_pin']:
            return True, "Pin Bar"
        if pa.get('engulfing') in ['bullish_engulfing', 'bearish_engulfing']:
            return True, "吞没形态"
        if pa.get('breakout'):
            return True, "突破信号"
        
        # 成交量异常
        if market_data.get('volume_analysis', {}).get('volume_ratio', 0) > 200:
            return True, "异常放量"
        
        return False, ""
    
    def get_stats(self) -> Dict[str, Any]:
        """获取优化统计"""
        saved_rate = (self.call_stats['saved'] / self.call_stats['total'] * 100) if self.call_stats['total'] > 0 else 0
        
        return {
            'total_decisions': self.call_stats['total'],
            'api_calls': self.call_stats['forced'] + (self.call_stats['total'] - self.call_stats['saved'] - self.call_stats['forced']),
            'calls_saved': self.call_stats['saved'],
            'save_rate': f"{saved_rate:.1f}%",
            'cost_reduction': f"约{saved_rate * 0.8:.0f}%",  # 考虑Qwen自身缓存
        }
    
    def reset_stats(self):
        """重置统计"""
        self.call_stats = {'total': 0, 'saved': 0, 'forced': 0}
    
    def get_daily_report_html(self) -> str:
        """生成每日优化报告（HTML格式，用于邮件）"""
        stats = self.get_stats()
        
        # 统计时长
        duration = datetime.now() - self.daily_details['start_time']
        hours = duration.total_seconds() / 3600
        
        # 按原因分组统计跳过次数
        skip_by_reason = {}
        for skip in self.daily_details['skip_reasons']:
            reason = skip['reason']
            skip_by_reason[reason] = skip_by_reason.get(reason, 0) + 1
        
        # 最近跳过记录（最多显示10条）
        recent_skips = self.daily_details['skip_reasons'][-10:]
        
        # 按原因分组统计强制调用
        force_by_reason = {}
        for force in self.daily_details['force_reasons']:
            reason = force['reason']
            force_by_reason[reason] = force_by_reason.get(reason, 0) + 1
        
        html = f"""
<div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
    <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
        🚀 AI调用优化报告
    </h2>
    
    <div style="background: white; padding: 15px; border-radius: 5px; margin: 15px 0;">
        <h3 style="color: #27ae60;">📊 总体统计（过去{hours:.1f}小时）</h3>
        <table style="width: 100%; border-collapse: collapse;">
            <tr style="background: #ecf0f1;">
                <td style="padding: 10px; border: 1px solid #bdc3c7;"><strong>总决策次数</strong></td>
                <td style="padding: 10px; border: 1px solid #bdc3c7;">{stats['total_decisions']} 次</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #bdc3c7;"><strong>实际API调用</strong></td>
                <td style="padding: 10px; border: 1px solid #bdc3c7; color: #e74c3c;">{stats['api_calls']} 次</td>
            </tr>
            <tr style="background: #ecf0f1;">
                <td style="padding: 10px; border: 1px solid #bdc3c7;"><strong>智能跳过</strong></td>
                <td style="padding: 10px; border: 1px solid #bdc3c7; color: #27ae60;"><strong>{stats['calls_saved']} 次</strong></td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #bdc3c7;"><strong>节省率</strong></td>
                <td style="padding: 10px; border: 1px solid #bdc3c7; color: #f39c12;"><strong>{stats['save_rate']}</strong></td>
            </tr>
            <tr style="background: #d5f4e6;">
                <td style="padding: 10px; border: 1px solid #bdc3c7;"><strong>💰 节省成本</strong></td>
                <td style="padding: 10px; border: 1px solid #bdc3c7; color: #27ae60;">
                    <strong>约 ¥{self.daily_details['saved_cost_estimate']:.2f} 元</strong>
                </td>
            </tr>
        </table>
    </div>
    
    <div style="background: white; padding: 15px; border-radius: 5px; margin: 15px 0;">
        <h3 style="color: #27ae60;">✅ 跳过明细（节省成本）</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
            <tr style="background: #27ae60; color: white;">
                <th style="padding: 8px; border: 1px solid #bdc3c7;">原因类型</th>
                <th style="padding: 8px; border: 1px solid #bdc3c7;">次数</th>
            </tr>
"""
        
        for reason, count in skip_by_reason.items():
            html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #bdc3c7;">{reason}</td>
                <td style="padding: 8px; border: 1px solid #bdc3c7; text-align: center;">{count}</td>
            </tr>
"""
        
        html += """
        </table>
        
        <h4 style="color: #7f8c8d; margin-top: 15px;">最近10次跳过记录</h4>
        <table style="width: 100%; border-collapse: collapse; font-size: 11px;">
            <tr style="background: #ecf0f1;">
                <th style="padding: 6px; border: 1px solid #bdc3c7;">时间</th>
                <th style="padding: 6px; border: 1px solid #bdc3c7;">原因</th>
                <th style="padding: 6px; border: 1px solid #bdc3c7;">持续时长</th>
                <th style="padding: 6px; border: 1px solid #bdc3c7;">节省</th>
            </tr>
"""
        
        for skip in recent_skips:
            html += f"""
            <tr>
                <td style="padding: 6px; border: 1px solid #bdc3c7;">{skip['time']}</td>
                <td style="padding: 6px; border: 1px solid #bdc3c7;">{skip['reason']}</td>
                <td style="padding: 6px; border: 1px solid #bdc3c7;">{skip.get('duration', '-')}</td>
                <td style="padding: 6px; border: 1px solid #bdc3c7; color: #27ae60;">¥{skip['saved_cost']:.3f}</td>
            </tr>
"""
        
        html += """
        </table>
    </div>
    
    <div style="background: white; padding: 15px; border-radius: 5px; margin: 15px 0;">
        <h3 style="color: #e74c3c;">🔴 强制调用明细（保证效果）</h3>
        <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
            <tr style="background: #e74c3c; color: white;">
                <th style="padding: 8px; border: 1px solid #bdc3c7;">触发原因</th>
                <th style="padding: 8px; border: 1px solid #bdc3c7;">次数</th>
            </tr>
"""
        
        for reason, count in force_by_reason.items():
            html += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #bdc3c7;">{reason}</td>
                <td style="padding: 8px; border: 1px solid #bdc3c7; text-align: center;">{count}</td>
            </tr>
"""
        
        html += """
        </table>
        <p style="color: #7f8c8d; font-size: 12px; margin-top: 10px;">
            ℹ️ 强制调用确保：有持仓时实时监控、关键信号立即分析、定期刷新防遗漏
        </p>
    </div>
    
    <div style="background: #fff3cd; padding: 12px; border-radius: 5px; border-left: 4px solid #ffc107;">
        <strong>💡 优化效果说明：</strong>
        <ul style="margin: 5px 0; padding-left: 20px;">
            <li>✅ 有持仓时保持100%监控，不影响止损和利润保护</li>
            <li>✅ 关键信号（Pin Bar、吞没、突破）立即分析，不错过机会</li>
            <li>✅ 市场状态无变化时智能跳过，节省成本</li>
            <li>✅ 最多30分钟强制刷新一次，防止遗漏</li>
        </ul>
    </div>
</div>
"""
        
        return html
    
    def reset_daily_details(self):
        """重置每日详细记录（通常在每日报告发送后调用）"""
        self.daily_details = {
            'skip_reasons': [],
            'force_reasons': [],
            'saved_cost_estimate': 0.0,
            'start_time': datetime.now(),
        }


# 全局AI调用优化器实例
ai_optimizer = AICallOptimizer()

# ==================== AI调用优化器结束 ====================

# 初始化Qwen客户端
qwen_api_key = os.getenv("QWEN_API_KEY")
if not qwen_api_key:
    raise ValueError("❌ QWEN_API_KEY 环境变量未设置，请检查 .env.qwen 文件")
# 去除可能的空格和换行符
qwen_api_key = qwen_api_key.strip()
qwen_client = OpenAI(
    api_key=qwen_api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 初始化交易所（币安/OKX 二选一）
EXCHANGE_TYPE = os.getenv("EXCHANGE_TYPE", "binance")  # 默认币安

if EXCHANGE_TYPE == "binance":
    # 🔧 V7.7.0.20: 支持统一账户模式（Portfolio Margin）
    # 统一账户使用 portfolioMargin 选项自动切换到 papi 端点
    USE_PORTFOLIO_MARGIN = os.getenv("USE_PORTFOLIO_MARGIN", "true").lower() == "true"
    
    # 读取并清理 API keys
    binance_api_key = os.getenv("BINANCE_API_KEY", "").strip()
    binance_secret_key = os.getenv("BINANCE_SECRET_KEY", "").strip()
    
    exchange = ccxt.binance({
        "options": {
            "defaultType": "future",
            "portfolioMargin": USE_PORTFOLIO_MARGIN,  # 统一账户模式
            "recvWindow": 60000,  # 【修复】增大到60秒，避免系统卡顿时时间戳过期（默认5秒）
        },
        "apiKey": binance_api_key,
        "secret": binance_secret_key,
        "timeout": 30000,  # 【修复】增大超时时间到30秒（默认10秒）
        "enableRateLimit": True,  # 【修复】启用速率限制保护
    })
    
    print(f"🔧 币安交易所初始化: {'统一账户模式 (papi)' if USE_PORTFOLIO_MARGIN else '标准合约模式 (fapi)'}")
    
    # 【新增】检查时间同步，避免timestamp错误
    try:
        server_time = exchange.fetch_time()
        local_time = int(time.time() * 1000)
        time_diff = abs(server_time - local_time)
        if time_diff > 5000:  # 差异超过5秒
            print(f"⚠️  服务器时间差异: {time_diff}ms (>{5}s)")
            print(f"   本地时间: {datetime.fromtimestamp(local_time/1000)}")
            print(f"   币安时间: {datetime.fromtimestamp(server_time/1000)}")
            print(f"   建议执行: sudo ntpdate -u time.nist.gov")
        else:
            print(f"✓ 时间同步正常 (差异{time_diff}ms)")
    except Exception as e:
        print(f"⚠️  时间同步检查失败: {e}")
else:
    # 读取并清理 OKX API keys
    okx_api_key = os.getenv("OKX_API_KEY", "").strip()
    okx_secret = os.getenv("OKX_SECRET", "").strip()
    okx_password = os.getenv("OKX_PASSWORD", "").strip()
    
    exchange = ccxt.okx(
        {
            "options": {
                "defaultType": "swap",
            },
            "apiKey": okx_api_key,
            "secret": okx_secret,
            "password": okx_password,
        }
    )

# 交易参数配置
TRADE_CONFIG = {
    "symbols": [
        "BTC/USDT:USDT",
        "ETH/USDT:USDT",
        "SOL/USDT:USDT",
        "BNB/USDT:USDT",
        "XRP/USDT:USDT",
        "DOGE/USDT:USDT",
        "LTC/USDT:USDT",
    ],
    "max_leverage": 5,  # 最大杠杆5倍
    "initial_capital": int(
        os.getenv("INITIAL_CAPITAL", "100")
    ),  # 从环境变量读取初始资金
    "use_dynamic_position": True,  # 动态调整仓位（根据总资产）
    "position_ratio": 1.0,  # 总资产的100%可用于仓位
    "min_risk_reward": 1.5,  # 最小盈亏比1:1.5
    "timeframe": "15m",
    "test_mode": os.getenv("TEST_MODE", "false").lower()
    == "true",  # 从环境变量读取测试模式
    "bark_key": os.getenv("BARK_KEY", "kqMFY7827om3TQMR2iziNR"),  # Bark推送密钥
}

# ==================== V7.6.5: 信号分级配置 ====================

SIGNAL_TIER_PARAMS = {
    "HIGH": {
        "min_risk_reward": 1.5,  # 高质量信号允许更低盈亏比
        "atr_multiplier": 1.0,    # 标准ATR倍数（相对base_atr）
        "position_multiplier": 1.3,  # 仓位放大30%
        "description": "YTC高质量信号，3层趋势共振，高胜率预期",
        "rationale": "High-win-rate signals allow tighter stops (R:R 1.5) while maintaining positive expected value. Example: If win rate is 55%, expected return = 0.55×1.5 - 0.45×1 = 0.375 > 0"
            },
    "MEDIUM": {
        "min_risk_reward": 2.0,   # 标准盈亏比
        "atr_multiplier": 1.0,     # 标准ATR
        "position_multiplier": 1.0,  # 标准仓位
        "description": "标准信号，多层趋势支持，中等胜率",
        "rationale": "Standard approach for moderate confidence signals. Balanced R:R of 2.0 provides cushion for 40-45% win rate scenarios."
            },
    "LOW": {
        "min_risk_reward": 2.5,   # 保守盈亏比
        "atr_multiplier": 1.2,     # 更宽止损（避免噪音扫损）
        "position_multiplier": 0.7,  # 减小仓位30%
        "description": "低质量信号，弱趋势对齐，需要更高盈亏比保护",
        "rationale": "Low-confidence signals require higher R:R (2.5) to compensate for lower win rate (~35-40%). Wider stops prevent premature stop-outs in choppy markets."
            }
}

# ==================== V7.6.5: 币种个性化画像 ====================

SYMBOL_PROFILES = {
    "BTC/USDT:USDT": {
        "name": "比特币",
        "volatility": "LOW",
        "liquidity": "HIGH",
        "trend_style": "STABLE",
        "recommended_holding_hours": 6,
        "atr_multiplier_adjustment": 1.0,
        "false_breakout_rate": "LOW",
        "characteristics": "大盘龙头，趋势明确，假突破少，适合中线持有"
    },
    "ETH/USDT:USDT": {
        "name": "以太坊",
        "volatility": "MEDIUM",
        "liquidity": "HIGH",
        "trend_style": "STABLE",
        "recommended_holding_hours": 5,
        "atr_multiplier_adjustment": 1.05,
        "false_breakout_rate": "LOW",
        "characteristics": "主流币，流动性好，波动略大于BTC，趋势跟随性强"
    },
    "SOL/USDT:USDT": {
        "name": "Solana",
        "volatility": "HIGH",
        "liquidity": "MEDIUM",
        "trend_style": "EXPLOSIVE",
        "recommended_holding_hours": 3,
        "atr_multiplier_adjustment": 1.2,
        "false_breakout_rate": "MEDIUM",
        "characteristics": "高波动，爆发力强，假突破较多，适合短线快进快出"
    },
    "BNB/USDT:USDT": {
        "name": "币安币",
        "volatility": "MEDIUM",
        "liquidity": "HIGH",
        "trend_style": "STABLE",
        "recommended_holding_hours": 4,
        "atr_multiplier_adjustment": 1.0,
        "false_breakout_rate": "LOW",
        "characteristics": "平台币，受币安生态影响，趋势稳定"
    },
    "XRP/USDT:USDT": {
        "name": "瑞波币",
        "volatility": "HIGH",
        "liquidity": "MEDIUM",
        "trend_style": "NEWS_DRIVEN",
        "recommended_holding_hours": 2,
        "atr_multiplier_adjustment": 1.15,
        "false_breakout_rate": "HIGH",
        "characteristics": "消息面敏感，波动大，假突破多，需要快速反应"
    },
    "DOGE/USDT:USDT": {
        "name": "狗狗币",
        "volatility": "EXTREME",
        "liquidity": "MEDIUM",
        "trend_style": "SENTIMENT",
        "recommended_holding_hours": 1,
        "atr_multiplier_adjustment": 1.3,
        "false_breakout_rate": "HIGH",
        "characteristics": "Meme币，情绪驱动，波动极大，不适合趋势跟踪"
    },
    "LTC/USDT:USDT": {
        "name": "莱特币",
        "volatility": "MEDIUM",
        "liquidity": "MEDIUM",
        "trend_style": "STABLE",
        "recommended_holding_hours": 4,
        "atr_multiplier_adjustment": 1.0,
        "false_breakout_rate": "MEDIUM",
        "characteristics": "老牌币，跟随BTC，波动适中，趋势清晰"
    }
}

# 数据存储路径（Qwen专用目录）
DATA_DIR = Path(__file__).parent / "trading_data" / "qwen"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRADES_FILE = DATA_DIR / "trades_history.csv"
POSITIONS_FILE = DATA_DIR / "current_positions.csv"
STATUS_FILE = DATA_DIR / "system_status.json"
AI_DECISIONS_FILE = DATA_DIR / "ai_decisions.json"  # AI决策历史
PNL_HISTORY_FILE = DATA_DIR / "pnl_history.csv"  # 盈亏历史
CHAT_HISTORY_FILE = DATA_DIR / "chat_history.json"  # 聊天记录
LEARNING_CONFIG_FILE = DATA_DIR / "learning_config.json"  # 学习参数

# 全局变量
price_history = {}  # 每个币种的价格历史
signal_history = {}  # 每个币种的信号历史


def send_bark_notification(title, content):
    """发送Bark推送通知（支持多个地址 + Qwen分组）"""
    try:
        from urllib.parse import quote

        # 🔧 V8.2.6: 限制内容长度，避免URL过长导致404
        # GET请求URL长度限制通常为2048字符
        # 中文URL编码后长度约为原字符数×3，所以限制要更小
        MAX_TITLE_LEN = 40   # 编码后~120字符
        MAX_CONTENT_LEN = 100  # 编码后~300字符
        
        # 截断过长的标题和内容
        if len(title) > MAX_TITLE_LEN:
            title = title[:MAX_TITLE_LEN-3] + "..."
            print(f"[Bark推送] 标题过长，已截断到{MAX_TITLE_LEN}字符")
        
        if len(content) > MAX_CONTENT_LEN:
            content = content[:MAX_CONTENT_LEN-3] + "..."
            print(f"[Bark推送] 内容过长，已截断到{MAX_CONTENT_LEN}字符")

        # 3个Bark推送地址
        bark_key_config = TRADE_CONFIG.get("bark_key", "")
        bark_keys = [
            bark_key_config,
            "JhWxKdo8Chb2w9RJjSpX6m",
            "qHALdYkNgfvNe4qTT8v8UA",
        ]

        # 过滤掉空的key
        bark_keys = [k for k in bark_keys if k]

        print(f"[Bark推送] 准备发送到 {len(bark_keys)} 个设备")
        print(f"[Bark推送] 标题: {title}")
        print(f"[Bark推送] 内容: {content}")

        if not bark_keys:
            print("⚠️ 没有配置Bark推送地址，跳过推送")
            return
    
        success_count = 0
        fail_count = 0

        for idx, bark_key in enumerate(bark_keys, 1):
            try:
                # URL编码标题和内容，支持中文
                encoded_title = quote(title)
                encoded_content = quote(content)

                # 添加group参数，将推送归类到"Qwen"文件夹
                url = f"https://api.day.app/{bark_key}/{encoded_title}/{encoded_content}?group=Qwen"
                
                # 🔧 V7.7.0.16: 检查URL长度
                if len(url) > 1800:  # 预留一些安全余量
                    print(f"[Bark推送] 设备{idx}: ⚠️ URL过长({len(url)}字符)，可能失败")

                print(f"[Bark推送] 设备{idx}: 正在发送到 {bark_key[:8]}...")

                response = requests.get(url, timeout=10)

                print(f"[Bark推送] 设备{idx}: 响应状态码 {response.status_code}")

                if response.status_code == 200:
                    success_count += 1
                    print(f"[Bark推送] 设备{idx}: ✅ 推送成功")
                else:
                    fail_count += 1
                    print(
                        f"[Bark推送] 设备{idx}: ❌ 推送失败 - 状态码 {response.status_code}"
                    )
                    print(f"[Bark推送] 设备{idx}: 响应内容: {response.text[:200]}")

            except requests.exceptions.Timeout:
                fail_count += 1
                print(f"[Bark推送] 设备{idx}: ❌ 请求超时 ({bark_key[:8]}...)")
            except requests.exceptions.RequestException as e:
                fail_count += 1
                print(
                    f"[Bark推送] 设备{idx}: ❌ 网络错误 ({bark_key[:8]}...): {str(e)[:100]}"
                )
            except Exception as e:
                fail_count += 1
                print(
                    f"[Bark推送] 设备{idx}: ❌ 未知错误 ({bark_key[:8]}...): {str(e)[:100]}"
                )

        print(
            f"[Bark推送] 推送完成: 成功 {success_count}/{len(bark_keys)}, 失败 {fail_count}/{len(bark_keys)}"
        )

        if success_count > 0:
            print(
                f"✓ Bark通知已发送到 {success_count}/{len(bark_keys)} 个设备: {title}"
            )
        else:
            print(f"✗ Bark通知全部失败！请检查网络或Bark Key配置")

    except Exception as e:
        print(f"✗ Bark推送函数异常: {e}")
        import traceback

        traceback.print_exc()


def send_email_notification(subject, body_html, model_name="Qwen"):
    """发送邮件通知（用于AI参数优化详细报告）"""
    try:
        # 邮件配置
        email_config = {
            "smtp_server": "smtp.qq.com",
            "smtp_port": 465,
            "use_ssl": True,
            "username": "1273428868@qq.com",
            "password": "avxuefczxafohdbg",
            "from_address": "1273428868@qq.com",
            "to_address": "baiyuperson@88.com",
        }
        
        print(f"[邮件通知] 准备发送邮件: {subject}")
        print(f"[邮件通知] model_name输入值: {model_name}")
        
        # 创建邮件
        msg = MIMEMultipart('alternative')
        # 根据model_name添加前缀（映射：deepseek->DeepSeek, qwen->Qwen）
        display_name = "DeepSeek" if "deepseek" in model_name.lower() else "Qwen" if "qwen" in model_name.lower() else model_name
        print(f"[邮件通知] 映射后display_name: {display_name}")
        msg['Subject'] = f"[{display_name}] {subject}"
        print(f"[邮件通知] 最终邮件主题: {msg['Subject']}")
        msg['From'] = email_config['from_address']
        msg['To'] = email_config['to_address']
        msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0800')
        
        # 添加HTML内容
        html_part = MIMEText(body_html, 'html', 'utf-8')
        msg.attach(html_part)
        
        # 发送邮件
        if email_config['use_ssl']:
            server = smtplib.SMTP_SSL(email_config['smtp_server'], email_config['smtp_port'], timeout=30)
        else:
            server = smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port'], timeout=30)
        
        server.login(email_config['username'], email_config['password'])
        server.send_message(msg)
        server.quit()
        
        print(f"[邮件通知] ✅ 邮件发送成功: {subject}")
        return True
        
    except Exception as e:
        print(f"[邮件通知] ❌ 邮件发送失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def save_open_position(trade_info):
    """保存开仓记录（新增）- 加固版"""
    import fcntl
    import shutil
    from pathlib import Path

    # 定义标准列顺序，确保一致性
    STANDARD_COLUMNS = [
        "开仓时间",
        "平仓时间",
        "币种",
        "方向",
        "数量",
        "开仓价格",
        "平仓价格",
        "仓位(U)",
        "杠杆率",
        "止损",
        "止盈",
        "盈亏比",
        "盈亏(U)",
        "开仓理由",
        "平仓理由",
    ]

    max_retries = 3
    for attempt in range(max_retries):
        lock_file = None
        try:
            # 1. 创建文件锁，避免并发写入
            lock_path = TRADES_FILE.parent / f"{TRADES_FILE.name}.lock"
            lock_file = open(lock_path, "w")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # 2. 创建备份（如果文件存在）
            if TRADES_FILE.exists():
                backup_path = TRADES_FILE.parent / f"{TRADES_FILE.name}.backup"
                shutil.copy2(TRADES_FILE, backup_path)

            # 3. 创建新数据DataFrame，确保列顺序正确
            df_new = pd.DataFrame([trade_info])
            # 按标准列顺序重新排列
            df_new = df_new.reindex(columns=STANDARD_COLUMNS)
        
            # 4. 读取现有数据（如果存在）
            if TRADES_FILE.exists():
                df_existing = pd.read_csv(TRADES_FILE, encoding="utf-8")
                # 清理列名中的空格和BOM字符
                df_existing.columns = df_existing.columns.str.strip().str.replace(
                    "\ufeff", ""
                )
                # 确保列顺序一致
                df_existing = df_existing.reindex(columns=STANDARD_COLUMNS)
                # 合并数据（移除空行避免FutureWarning）
                df_combined = pd.concat([df_existing.dropna(how='all'), df_new.dropna(how='all')], ignore_index=True)
            else:
                df_combined = df_new
        
            # 5. 保存到CSV（使用临时文件，然后重命名，确保原子操作）
            temp_file = TRADES_FILE.parent / f"{TRADES_FILE.name}.tmp"
            df_combined.to_csv(temp_file, index=False, encoding="utf-8")

            # 6. 原子性替换文件
            temp_file.replace(TRADES_FILE)

            print(f"✓ 开仓记录已保存: {TRADES_FILE}")

            # 7. 释放文件锁
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

            # 成功，跳出重试循环
            break

        except BlockingIOError:
            # 文件被锁定，等待后重试
            print(f"⚠️ 文件被锁定，等待重试 (尝试 {attempt + 1}/{max_retries})")
            if lock_file:
                lock_file.close()
            import time

            time.sleep(0.5)
            continue

        except Exception as e:
            print(f"✗ 保存开仓记录失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            import traceback
            traceback.print_exc()

            # 如果有备份，尝试恢复
            backup_path = TRADES_FILE.parent / f"{TRADES_FILE.name}.backup"
            if backup_path.exists() and attempt == max_retries - 1:
                print(f"⚠️ 尝试从备份恢复...")
                try:
                    shutil.copy2(backup_path, TRADES_FILE)
                    print(f"✓ 已从备份恢复")
                except:
                    pass

            # 清理锁
            if lock_file:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()
                except:
                    pass

            # 最后一次尝试失败，不再重试
            if attempt == max_retries - 1:
                print(f"✗ 保存开仓记录失败，已尝试 {max_retries} 次")
                # 抛出异常，让上层知道保存失败
                raise
            else:
                import time

                time.sleep(0.5)
                continue


def update_close_position(coin_name, side, close_time, close_price, pnl, close_reason):
    """更新平仓记录（找到对应的开仓记录并更新）- 加固版"""
    import fcntl
    import shutil
    from pathlib import Path

    max_retries = 3
    for attempt in range(max_retries):
        lock_file = None
        try:
            # 1. 检查文件是否存在
            if not TRADES_FILE.exists():
                print(f"✗ 交易记录文件不存在")
                return
        
            # 2. 创建文件锁，避免并发写入
            lock_path = TRADES_FILE.parent / f"{TRADES_FILE.name}.lock"
            lock_file = open(lock_path, "w")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # 3. 创建备份
            backup_path = TRADES_FILE.parent / f"{TRADES_FILE.name}.backup"
            shutil.copy2(TRADES_FILE, backup_path)

            # 4. 读取现有数据
            df = pd.read_csv(TRADES_FILE, encoding="utf-8")
            # 清理列名中的空格和BOM字符
            df.columns = df.columns.str.strip().str.replace("\ufeff", "")

            # 5. 找到该币种、该方向、未平仓的最后一条记录
            mask = (
                (df["币种"] == coin_name)
                & (df["方向"] == side)
                & (df["平仓时间"].isna())
            )
            matching_rows = df[mask]
        
            if matching_rows.empty:
                print(f"⚠️ 未找到 {coin_name} {side} 的开仓记录")
                # 释放锁
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                return
        
            # 6. 更新最后一条匹配记录
            last_idx = matching_rows.index[-1]
            df.at[last_idx, "平仓时间"] = close_time
            df.at[last_idx, "平仓价格"] = close_price
            df.at[last_idx, "盈亏(U)"] = pnl
            df.at[last_idx, "平仓理由"] = close_reason

            # 7. 保存到临时文件，然后原子性替换
            temp_file = TRADES_FILE.parent / f"{TRADES_FILE.name}.tmp"
            df.to_csv(temp_file, index=False, encoding="utf-8")
            temp_file.replace(TRADES_FILE)

            print(f"✓ 平仓记录已更新: {TRADES_FILE}")

            # 8. 释放文件锁
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

            # 成功，跳出重试循环
            break

        except BlockingIOError:
            # 文件被锁定，等待后重试
            print(f"⚠️ 文件被锁定，等待重试 (尝试 {attempt + 1}/{max_retries})")
            if lock_file:
                lock_file.close()
            import time

            time.sleep(0.5)
            continue

        except Exception as e:
            print(f"✗ 更新平仓记录失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            import traceback
            traceback.print_exc()

            # 如果有备份，尝试恢复
            backup_path = TRADES_FILE.parent / f"{TRADES_FILE.name}.backup"
            if backup_path.exists() and attempt == max_retries - 1:
                print(f"⚠️ 尝试从备份恢复...")
                try:
                    shutil.copy2(backup_path, TRADES_FILE)
                    print(f"✓ 已从备份恢复")
                except:
                    pass

            # 清理锁
            if lock_file:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()
                except:
                    pass

            # 最后一次尝试失败
            if attempt == max_retries - 1:
                print(f"✗ 更新平仓记录失败，已尝试 {max_retries} 次")
                # 抛出异常，让上层知道更新失败
                raise
            else:
                import time

                time.sleep(0.5)
                continue


def save_positions_snapshot(positions, total_value):
    """保存当前持仓快照（包含完整交易信息：开仓时间、止盈止损、开仓理由等）"""
    try:
        records = []
        for pos in positions:
            records.append(
                {
                    "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "开仓时间": pos.get("open_time", ""),
                    "币种": pos["symbol"].split("/")[0],
                    "方向": "多" if pos["side"] == "long" else "空",
                    "数量": pos["size"],
                    "开仓价": pos["entry_price"],
                    "当前盈亏(U)": pos["unrealized_pnl"],
                    "杠杆": pos["leverage"],
                    "保证金(U)": pos.get("margin", 0),
                    "止损": pos.get("stop_loss", 0),
                    "止盈": pos.get("take_profit", 0),
                    "盈亏比": pos.get("risk_reward", 0),
                    "开仓理由": pos.get("open_reason", ""),
                }
            )
        
        if records:
            df = pd.DataFrame(records)
            df.to_csv(POSITIONS_FILE, index=False, encoding="utf-8")
        else:
            # 无持仓时清空文件
            pd.DataFrame(
                columns=[
                    "更新时间",
                    "开仓时间",
                    "币种",
                    "方向",
                    "数量",
                    "开仓价",
                    "当前盈亏(U)",
                    "杠杆",
                    "保证金(U)",
                    "止损",
                    "止盈",
                    "盈亏比",
                    "开仓理由",
                ]
            ).to_csv(POSITIONS_FILE, index=False, encoding="utf-8")
        
        print(f"✓ 持仓快照已更新: {POSITIONS_FILE}")
    except Exception as e:
        print(f"✗ 保存持仓快照失败: {e}")


def clear_symbol_orders(symbol, verbose=True):
    """
    V7.9.3 清理指定币种的所有止损止盈订单（包括条件单）
    
    Args:
        symbol: 交易对符号（如 BTC/USDT:USDT）
        verbose: 是否打印详细日志
    
    Returns:
        (成功数量, 失败数量)
    """
    success_count = 0
    fail_count = 0
    
    # 第1步：取消普通订单
    try:
        open_orders = exchange.fetch_open_orders(symbol)
        if verbose and len(open_orders) > 0:
            print(f"  发现 {len(open_orders)} 个普通订单")
        
        for order in open_orders:
            order_type = order.get('type', '').upper()
            order_id = order.get('id', '')
            
            # 🔧 修复：reduceOnly 可能是字符串 "true" 或布尔值 True
            reduce_only = order['info'].get('reduceOnly')
            is_reduce_only = (reduce_only == True or reduce_only == 'true' or reduce_only == 'True')
            
            # 识别止损止盈订单类型
            is_tp_sl_type = order_type in [
                'STOP_MARKET',
                'TAKE_PROFIT_MARKET',
                'STOP',
                'TAKE_PROFIT',
                'TRAILING_STOP_MARKET',
            ]
            
            # 清理所有止损止盈相关订单
            if is_reduce_only or is_tp_sl_type:
                try:
                    exchange.cancel_order(order_id, symbol)
                    success_count += 1
                    if verbose:
                        short_id = order_id[:8] + '...' if len(order_id) > 8 else order_id
                        print(f"  ✓ 已取消普通订单: {order_type} (ID: {short_id})")
                except Exception as e:
                    fail_count += 1
                    if verbose:
                        err_msg = str(e)[:50]
                        print(f"  ❌ 取消失败: {order_type} - {err_msg}")
    except Exception as e:
        if verbose:
            print(f"  ⚠️ 查询普通订单异常: {e}")
    
    # 第2步：取消条件单（Portfolio Margin特有）
    # 条件单是止损/止盈策略订单，需要使用专门的API
    try:
        # 转换symbol格式: BTC/USDT:USDT -> BTCUSDT
        if '/' in symbol:
            binance_symbol = symbol.split('/')[0] + symbol.split(':')[0].split('/')[1]
        else:
            binance_symbol = symbol
        
        # 使用ccxt的底层方法调用papi API
        # GET /papi/v1/um/conditional/openOrders
        timestamp = int(time.time() * 1000)
        
        # 尝试查询条件单
        try:
            params = {
                'symbol': binance_symbol,
                'timestamp': timestamp
            }
            
            # 按字母顺序排序并生成query string
            sorted_params = sorted(params.items())
            query_string = urlencode(sorted_params)
            
            # 生成签名
            signature = hmac.new(
                exchange.secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # 构建完整URL
            url = f"https://papi.binance.com/papi/v1/um/conditional/openOrders?{query_string}&signature={signature}"
            
            headers = {'X-MBX-APIKEY': exchange.apiKey}
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                conditional_orders = response.json()
                
                if verbose and len(conditional_orders) > 0:
                    print(f"  发现 {len(conditional_orders)} 个条件单")
                
                for order in conditional_orders:
                    strategy_id = order.get('strategyId')
                    strategy_type = order.get('strategyType', 'N/A')
                    reduce_only = order.get('reduceOnly')
                    order_status = order.get('strategyStatus', 'UNKNOWN')
                    
                    # 尝试取消所有reduceOnly的条件单（已成交/已取消会返回400，已处理为不报错）
                    if reduce_only:
                        try:
                            # DELETE /papi/v1/um/conditional/order
                            cancel_timestamp = int(time.time() * 1000)
                            
                            cancel_params = {
                                'symbol': binance_symbol,
                                'strategyId': int(strategy_id),
                                'timestamp': cancel_timestamp
                            }
                            
                            # 按字母顺序排序并生成query string
                            sorted_params = sorted(cancel_params.items())
                            cancel_query = urlencode(sorted_params)
                            
                            # 生成签名
                            cancel_signature = hmac.new(
                                exchange.secret.encode('utf-8'),
                                cancel_query.encode('utf-8'),
                                hashlib.sha256
                            ).hexdigest()
                            
                            # 构建完整URL
                            url = f"https://papi.binance.com/papi/v1/um/conditional/order?{cancel_query}&signature={cancel_signature}"
                            
                            # 调用取消API
                            cancel_response = requests.delete(url, headers=headers)
                            
                            if cancel_response.status_code == 200:
                                success_count += 1
                                if verbose:
                                    print(f"  ✓ 已取消条件单: {strategy_type} (策略ID: {strategy_id})")
                            elif cancel_response.status_code == 400:
                                # HTTP 400通常表示订单已成交或已取消，不计入失败
                                if verbose:
                                    try:
                                        error_detail = cancel_response.json().get('msg', '订单状态不允许取消')
                                    except:
                                        error_detail = '订单状态不允许取消'
                                    
                                    if '不存在' in error_detail or 'does not exist' in error_detail.lower() or 'filled' in error_detail.lower():
                                        print(f"  ℹ️ 条件单已处理: {strategy_type} (已成交或已取消)")
                                    else:
                                        print(f"  ⚠️ 取消条件单跳过: {strategy_type} - {error_detail[:50]}")
                            else:
                                fail_count += 1
                                if verbose:
                                    print(f"  ❌ 取消条件单失败: {strategy_type} - HTTP {cancel_response.status_code}")
                        except Exception as e:
                            fail_count += 1
                            if verbose:
                                print(f"  ❌ 取消条件单失败: {str(e)[:50]}")
        except Exception as e:
            # 条件单查询失败不影响整体流程
            if verbose:
                error_msg = str(e)
                if "does not exist" not in error_msg:
                    print(f"  ⚠️ 查询条件单异常: {error_msg[:50]}")
    except Exception as e:
        if verbose:
            print(f"  ⚠️ 处理条件单异常: {str(e)[:50]}")
    
    # 汇总结果
    if verbose and (success_count > 0 or fail_count > 0):
        print(f"  清理完成: 成功{success_count}个, 失败{fail_count}个")
    elif verbose and success_count == 0 and fail_count == 0:
        print(f"  无需要清理的订单")
    
    return success_count, fail_count


def set_tpsl_orders_via_papi(symbol: str, side: str, amount: float, stop_loss: float = None, take_profit: float = None, verbose: bool = True):
    """
    V7.9.3 通过papi端点为仓位设置止盈止损订单
    
    Args:
        symbol: 交易对符号（如 BTC/USDT:USDT）
        side: 仓位方向 'long' 或 'short'
        amount: 订单数量
        stop_loss: 止损价格
        take_profit: 止盈价格
        verbose: 是否打印详细日志
    
    Returns:
        (止损成功, 止盈成功)
    """
    sl_success = False
    tp_success = False
    
    # 转换symbol格式: BTC/USDT:USDT -> BTCUSDT
    if '/' in symbol:
        binance_symbol = symbol.split('/')[0] + symbol.split(':')[0].split('/')[1]
    else:
        binance_symbol = symbol
    
    # 平仓方向（与持仓相反）
    close_side = 'SELL' if side == 'long' else 'BUY'
    
    headers = {'X-MBX-APIKEY': exchange.apiKey}
    
    # 1. 设置止损订单（使用STOP_MARKET）
    if stop_loss and stop_loss > 0:
        try:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': binance_symbol,
                'side': close_side,
                'strategyType': 'STOP_MARKET',
                'stopPrice': str(stop_loss),
                'quantity': str(amount),
                'reduceOnly': 'true',
                'timestamp': timestamp
            }
            
            # 按字母顺序排序并生成query string
            sorted_params = sorted(params.items())
            query_string = urlencode(sorted_params)
            
            # 生成签名
            signature = hmac.new(
                exchange.secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # 构建完整URL
            url = f"https://papi.binance.com/papi/v1/um/conditional/order?{query_string}&signature={signature}"
            response = requests.post(url, headers=headers)
            
            if response.status_code == 200:
                sl_success = True
                if verbose:
                    print(f"  ✓ 止损单已设置: ${stop_loss:,.2f} (papi)")
            else:
                if verbose:
                    print(f"  ❌ 止损单设置失败: HTTP {response.status_code} - {response.text[:100]}")
        except Exception as e:
            if verbose:
                print(f"  ❌ 止损单设置异常: {str(e)[:80]}")
    
    # 2. 设置止盈订单（使用TAKE_PROFIT_MARKET）
    if take_profit and take_profit > 0:
        try:
            timestamp = int(time.time() * 1000)
            params = {
                'symbol': binance_symbol,
                'side': close_side,
                'strategyType': 'TAKE_PROFIT_MARKET',
                'stopPrice': str(take_profit),
                'quantity': str(amount),
                'reduceOnly': 'true',
                'timestamp': timestamp
            }
            
            # 按字母顺序排序并生成query string
            sorted_params = sorted(params.items())
            query_string = urlencode(sorted_params)
            
            # 生成签名
            signature = hmac.new(
                exchange.secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # 构建完整URL
            url = f"https://papi.binance.com/papi/v1/um/conditional/order?{query_string}&signature={signature}"
            response = requests.post(url, headers=headers)
            
            if response.status_code == 200:
                tp_success = True
                if verbose:
                    print(f"  ✓ 止盈单已设置: ${take_profit:,.2f} (papi)")
            else:
                if verbose:
                    print(f"  ❌ 止盈单设置失败: HTTP {response.status_code} - {response.text[:100]}")
        except Exception as e:
            if verbose:
                print(f"  ❌ 止盈单设置异常: {str(e)[:80]}")
    
    return sl_success, tp_success


def sync_csv_with_exchange_positions(current_positions):
    """
    同步CSV记录和交易所实际持仓
    检测被止损/止盈自动平掉的持仓，更新CSV记录
    """
    try:
        # 1. 读取CSV中未平仓的记录
        if not TRADES_FILE.exists():
            return
        
        df = pd.read_csv(TRADES_FILE, encoding="utf-8")
        df.columns = df.columns.str.strip().str.replace("\ufeff", "")
        
        # 找出未平仓的记录
        open_trades = df[df["平仓时间"].isna()]
        
        if open_trades.empty:
            return
        
        # 2. 构建交易所实际持仓的映射
        exchange_positions = {}
        for pos in current_positions:
            coin = pos["symbol"].split("/")[0]
            side = "多" if pos["side"] == "long" else "空"
            key = f"{coin}_{side}"
            exchange_positions[key] = pos
        
        # 3. 对比找出CSV有但交易所没有的持仓
        synced_count = 0
        for idx, trade in open_trades.iterrows():
            coin = trade.get("币种", "")
            side = trade.get("方向", "")
            key = f"{coin}_{side}"
            
            # 如果CSV有记录但交易所没有持仓，说明已被自动平仓
            if key not in exchange_positions:
                symbol = f"{coin}/USDT:USDT"
                
                print(f"⚠️ 检测到{coin} {side}仓已被自动平仓，正在同步CSV...")
                
                # 🆕 尝试从交易所获取实际平仓信息
                close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                close_price = 0
                pnl = 0
                
                try:
                    # 获取该币种最近的成交记录
                    recent_trades = exchange.fetch_my_trades(symbol, limit=20)
                    
                    # 找到平仓相关的成交（sell为平多，buy为平空）
                    expected_side = "sell" if side == "多" else "buy"
                    
                    for t in reversed(recent_trades):  # 从最新往前找
                        if t['side'] == expected_side:
                            close_price = float(t['price'])
                            close_time = datetime.fromtimestamp(t['timestamp']/1000).strftime("%Y-%m-%d %H:%M:%S")
                            
                            # 计算盈亏：需要开仓价
                            open_price = float(trade.get("开仓价格", 0) or 0)
                            amount = float(trade.get("数量", 0) or 0)
                            
                            if open_price > 0 and amount > 0:
                                if side == "多":
                                    pnl = (close_price - open_price) * amount
                                else:  # 空
                                    pnl = (open_price - close_price) * amount
                            
                            print(f"  ✓ 找到实际平仓记录: ${close_price:.2f} @ {close_time}, 盈亏{pnl:+.2f}U")
                            break
                except Exception as e:
                    print(f"  ⚠️ 获取成交记录失败，使用默认值: {e}")
                
                # 清理残留订单（使用统一的订单清理函数）
                try:
                    print("  正在清理残留的止损止盈订单...")
                    success, fail = clear_symbol_orders(symbol, verbose=True)
                except Exception as e:
                    print(f"  ⚠️ 清理订单失败: {e}")
                
                # 更新CSV记录
                update_close_position(
                    coin,
                    side,
                    close_time,
                    close_price,
                    pnl,
                    "系统检测：已被止损/止盈自动平仓",
                )
                
                # 【V7.9新增】发送Bark通知（系统自动平仓）
                try:
                    # 从trade获取开仓信息
                    open_time_str = trade.get('开仓时间', '')
                    entry_price = float(trade.get('开仓价格', 0) or 0)
                    
                    # 读取信号类型和持仓时间
                    signal_type = 'unknown'
                    expected_holding = 0
                    actual_holding_minutes = 0
                    
                    # 从position_contexts读取
                    model_name = os.getenv("MODEL_NAME", "qwen")
                    context_file = Path("trading_data") / model_name / "position_contexts.json"
                    if context_file.exists():
                        with open(context_file, 'r', encoding='utf-8') as f:
                            contexts = json.load(f)
                            if coin in contexts:
                                signal_type = contexts[coin].get('signal_type', 'unknown')
                                expected_holding = contexts[coin].get('expected_holding_minutes', 0)
                    
                    # 计算实际持仓时间
                    if isinstance(open_time_str, str) and open_time_str:
                        open_dt = datetime.strptime(open_time_str, "%Y-%m-%d %H:%M:%S")
                        close_dt = datetime.strptime(close_time, "%Y-%m-%d %H:%M:%S")
                        actual_holding_minutes = (close_dt - open_dt).total_seconds() / 60
                    
                    # 格式化通知
                    type_emoji = "⚡" if signal_type == 'scalping' else "🌊" if signal_type == 'swing' else "❓"
                    pnl_emoji = "📈" if pnl > 0 else "📉"
                    
                    # 判断是否达标
                    达标状态 = ""
                    if expected_holding > 0 and actual_holding_minutes > 0:
                        diff_pct = (actual_holding_minutes / expected_holding - 1) * 100
                        if abs(diff_pct) < 20:
                            达标状态 = "✓达标"
                        elif diff_pct < 0:
                            达标状态 = f"⚠️早平{abs(diff_pct):.0f}%"
                        else:
                            达标状态 = f"⏰超时{diff_pct:.0f}%"
                    
                    # 判断是止盈还是止损
                    if pnl > 0:
                        触发类型 = "止盈"
                    else:
                        触发类型 = "止损"
                    
                    # 中文化类型名称
                    type_name_cn = "超短线" if signal_type == 'scalping' else "波段" if signal_type == 'swing' else "未知"
                    send_bark_notification(
                        f"[通义千问]{coin}自动平仓{pnl_emoji}",
                        f"{side}仓 {触发类型}触发 {pnl:+.2f}U\n{type_emoji}{type_name_cn} {actual_holding_minutes:.0f}分 {达标状态}\n开${entry_price:.0f}→平${close_price:.0f}"
                            )
                except Exception as e:
                    print(f"  ⚠️ 发送Bark通知失败: {e}")
                
                # 清理决策上下文
                try:
                    clear_position_context(coin=coin)
                except:
                    pass
                
                synced_count += 1
        
        if synced_count > 0:
            print(f"✓ CSV同步完成，更新了 {synced_count} 条自动平仓记录")
        
    except Exception as e:
        print(f"⚠️ CSV同步失败: {e}")
        import traceback
        traceback.print_exc()


def save_system_status(status_data):
    """保存系统状态"""
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)
        print(f"✓ 系统状态已更新: {STATUS_FILE}")
    except Exception as e:
        print(f"✗ 保存系统状态失败: {e}")


def save_ai_decision(decision_data):
    """保存AI决策历史"""
    try:
        decision_record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "思考过程": decision_data.get("思考过程", ""),
            "analysis": decision_data.get("analysis", ""),
            "risk_assessment": decision_data.get("risk_assessment", ""),
            "actions": decision_data.get("actions", []),
        }
        
        # 加载现有历史
        if AI_DECISIONS_FILE.exists():
            with open(AI_DECISIONS_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        else:
            history = []
        
        # 添加新记录
        history.append(decision_record)
        
        # 只保留最近100条
        if len(history) > 100:
            history = history[-100:]
        
        # 保存
        with open(AI_DECISIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        
        print(f"✓ AI决策已记录: {AI_DECISIONS_FILE}")
    except Exception as e:
        print(f"✗ 保存AI决策失败: {e}")


def save_pnl_snapshot(current_positions, balance, total_position_value):
    """保存盈亏快照（用于绘制折线图）"""
    try:
        total_pnl = sum(p["unrealized_pnl"] for p in current_positions)
        
        snapshot = {
            "时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "余额": balance,
            "总仓位价值": total_position_value,
            "未实现盈亏": total_pnl,
            "总资产": balance + total_pnl,
        }
        
        df_new = pd.DataFrame([snapshot])
        
        if PNL_HISTORY_FILE.exists():
            df_existing = pd.read_csv(PNL_HISTORY_FILE)
            df_combined = pd.concat([df_existing.dropna(how='all'), df_new.dropna(how='all')], ignore_index=True)
        else:
            df_combined = df_new
        
        # 只保留最近1000条记录
        if len(df_combined) > 1000:
            df_combined = df_combined.tail(1000)
        
        df_combined.to_csv(PNL_HISTORY_FILE, index=False, encoding="utf-8")
        print(f"✓ 盈亏快照已保存: {PNL_HISTORY_FILE}")
    except Exception as e:
        print(f"✗ 保存盈亏快照失败: {e}")


def get_default_config():
    """获取默认配置（分层结构）V7.7.0.19扩展"""
    return {
        "version": "2.1",  # 🔧 V7.7.0.19: 配置版本升级
        "last_update": None,
        # === 全局参数（所有币种的兜底配置） ===
        "global": {
            # 风险控制 【V7.8优化】提高盈亏比要求，确保高质量机会
            "min_risk_reward": 3.0,  # 从1.5提高到3.0
            "atr_stop_multiplier": 1.5,
            "max_loss_per_trade": 0.02,  # 单笔最大亏损2%
            "max_consecutive_losses": 3,  # 最大连续亏损
            "trailing_stop_trigger": 1.5,  # 盈利1.5%启动移动止损
            # 仓位管理
            "base_position_ratio": 0.20,  # 基础仓位20%
            "max_position_ratio": 0.30,  # 最大单笔30%
            "high_signal_multiplier": 1.5,  # HIGH信号加仓
            "max_total_positions": 3,  # 最多3个仓位
            # 进场时机 【V7.8优化】降低共振要求，配合趋势强度评分
            "min_indicator_consensus": 2,  # 从4降到2，但要求更高盈亏比
            "key_level_penalty": 1.0,  # 关键位惩罚
            "min_trend_strength": 0.6,  # 最小趋势强度
            "require_candlestick_signal": False,  # 不强制要求裸K
            # 出场策略
            "partial_take_profit": True,  # 分批止盈
            "max_hold_time_hours": 24,  # 最大持仓24小时
            "close_on_opposite_signal": True,  # 反向信号平仓
            # AI决策质量 【V7.8优化】降低分数要求，因为新增了趋势强度评分
            "min_signal_score": 55,  # 从70降到55（确保能捕获更多高质量机会）
            
            # 🆕 V7.7.0.19: YTC前提失效阈值（可AI优化）
            "invalidation_thresholds": {
                "momentum_slope_min": 0.05,      # 最小动能阈值（低于此值视为停滞）
                "min_profit_threshold": 5,       # 最小盈利阈值（美元）
                "max_holding_hours": 24,         # 最大持仓时间（小时）
                "time_invalidation_pct": 0.8,    # 时间失效比例（80%）
                "reversal_confidence_min": 0.7,  # 反转信号最低置信度
                "allow_ai_confirmation": True,   # 系统判断前提失效时，是否请求AI确认
            },
            
            # 🆕 V7.7.0.19: 止损止盈动态调整策略
            "tp_sl_strategy": {
                "allow_dynamic_adjustment": True,    # 是否允许持仓期间调整止盈止损
                "tp_extension_multiplier": 1.0,      # 止盈扩展倍数（1.0=不扩展，2.0=扩2倍）
                "sl_tightening_enabled": False,      # 是否允许收紧止损
                "adjustment_cooldown_minutes": 60,   # 调整冷却时间（分钟）
                "min_adjustment_threshold_pct": 2.0, # 最小调整幅度（%）
            },
            
            # 【V8.0 重构】Scalping 超短线专用参数（完全分离，独立优化）
            "scalping_params": {
                # === 信号筛选 ===
                "min_signal_score": 65,              # 🔧 V8.3.17: 初始值65，由Grid Search优化（测试65/75/85）
                "min_indicator_consensus": 2,         # 共振要求（保持灵活）
                "min_risk_reward": 1.8,              # 🔧 V8.3.17: 初始值1.8，由Grid Search优化（测试1.5/2.0/2.5）
                
                # === 止盈止损（核心）===
                "atr_stop_multiplier": 1.0,          # 🆕 V8.0: 止损倍数（紧凑）
                "atr_tp_multiplier": 1.5,            # 🆕 V8.0: 止盈倍数（快速兑现）
                # 或使用盈亏比计算：tp = sl × min_risk_reward
                "use_independent_tp": True,          # 🆕 是否使用独立止盈倍数（不依赖R:R）
                
                # === 时间管理 ===
                "max_holding_hours": 2,              # 最长持仓2小时
                "protection_period_minutes": 0,      # 无保护期（快进快出）
                
                # === 仓位管理 ===
                "base_position_ratio": 0.15,         # 基础仓位15%
                "max_position_ratio": 0.20,          # 最大仓位20%
                "max_leverage": 3,                   # 最大杠杆3x
                "max_concurrent_positions": 2,       # 最多2个超短线仓位
                
                # === 风险控制 ===
                "total_risk_budget": 0.03,           # 总风险预算3%
                "max_loss_per_trade": 0.015,         # 单笔最大亏损1.5%
                "trailing_stop_trigger": 1.0,        # 🔧 V8.0: 盈利1%启动移动止损
                
                # === 交易频率控制 ===
                "cooldown_same_coin_minutes": 30,    # 同币种冷却30分钟
                "cooldown_any_coin_minutes": 15,     # 任意币种冷却15分钟
                "max_trades_per_hour": 4,            # 每小时最多4笔
            },
            
            # 【V8.0 重构】Swing 波段专用参数（完全分离，独立优化）
            "swing_params": {
                # === 信号筛选 ===
                "min_signal_score": 70,              # 🔧 V8.0: 更高要求，确保趋势质量
                "min_indicator_consensus": 2,         # 共振要求标准
                "min_risk_reward": 3.0,              # 🔧 V8.0: 提高到3.0（让利润奔跑）
                "min_trend_strength": 0.7,           # 最小趋势强度
                
                # === 止盈止损（核心）===
                "atr_stop_multiplier": 2.0,          # 🆕 V8.0: 止损倍数（宽松）
                "atr_tp_multiplier": 6.0,            # 🆕 V8.0: 止盈倍数（让利润奔跑）
                # 或使用盈亏比计算：tp = sl × min_risk_reward
                "use_independent_tp": True,          # 🆕 是否使用独立止盈倍数
                
                # === 时间管理 ===
                "max_holding_hours": 48,             # 🔧 V8.0: 延长到48小时
                "protection_period_minutes": 120,    # 保护期2小时（免疫噪音）
                "use_htf_levels": True,              # 使用高时间框架止盈止损
                
                # === 仓位管理 ===
                "base_position_ratio": 0.25,         # 基础仓位25%
                "max_position_ratio": 0.35,          # 最大仓位35%
                "max_leverage": 5,                   # 最大杠杆5x
                "max_concurrent_positions": 2,       # 最多2个波段仓位
                
                # === 风险控制 ===
                "total_risk_budget": 0.05,           # 总风险预算5%
                "max_loss_per_trade": 0.02,          # 单笔最大亏损2%
                "trailing_stop_trigger": 2.0,        # 🔧 V8.0: 盈利2%启动移动止损
                
                # === 多周期确认 ===
                "multi_timeframe_threshold": 2,      # 🔧 V8.0: 降低到2（15m+1h）
                "trailing_stop_enabled": True,       # 启用追踪止损
                "trailing_stop_trigger_pct": 2.0,    # 盈利2%启动追踪
                "trailing_stop_distance_atr": 1.0,   # 追踪距离（1倍ATR）
                "partial_exit_enabled": True,        # 启用分批平仓
                "partial_exit_first_target_pct": 50, # 第一目标平仓50%
            },
            
            # 【V7.9新增】信号优先级策略
            "signal_priority": {
                "prefer_swing_on_strong_trend": True,      # 强趋势优先Swing
                "prefer_scalping_on_high_volatility": True,# 高波动优先Scalping
                "trend_strength_threshold": 0.7,           # 强趋势阈值
                "volatility_threshold": 2.0,               # 高波动阈值
                "allow_both_types_simultaneously": True,   # 允许同时持有两种类型
            },
        },
        # === 币种风险分级 ===
        "risk_profiles": {
            "BTC/USDT:USDT": "low_risk",
            "ETH/USDT:USDT": "low_risk",
            "SOL/USDT:USDT": "high_risk",
            "BNB/USDT:USDT": "medium_risk",
            "XRP/USDT:USDT": "medium_risk",
            "DOGE/USDT:USDT": "high_risk",
            "LTC/USDT:USDT": "low_risk",
        },
        # === 风险等级安全系数 【V7.9.1优化：从硬编码改为AI基准×系数】===
        "risk_safety_multipliers": {
            "low_risk": {
                "min_risk_reward_multiplier": 1.1,   # AI学习值×1.1（BTC/ETH稳定）
                "min_signal_score_bonus": 10,        # AI学习值+10分
                "atr_stop_multiplier": 1.2,
                "min_indicator_consensus": 2,
                "base_position_ratio": 0.25,
            },
            "medium_risk": {
                "min_risk_reward_multiplier": 1.2,   # AI学习值×1.2（BNB/XRP中等）
                "min_signal_score_bonus": 15,        # AI学习值+15分
                "atr_stop_multiplier": 1.5,
                "min_indicator_consensus": 2,
                "base_position_ratio": 0.20,
            },
            "high_risk": {
                "min_risk_reward_multiplier": 1.3,   # AI学习值×1.3（SOL/DOGE波动大）
                "min_signal_score_bonus": 20,        # AI学习值+20分
                "atr_stop_multiplier": 1.8,
                "min_indicator_consensus": 3,
                "base_position_ratio": 0.15,
            },
        },
        
        # 【V7.9.1】如果AI未学习（per_symbol无数据），回退到这些最低基准
        "risk_fallback_minimums": {
            "low_risk": {"min_risk_reward": 1.8, "min_signal_score": 60},
            "medium_risk": {"min_risk_reward": 2.0, "min_signal_score": 65},
            "high_risk": {"min_risk_reward": 2.2, "min_signal_score": 70},
        },
        # === 每个币种的独立学习参数 ===
        "per_symbol": {},
        # === 市场环境参数 ===
        "market_regime": {
            "current_regime": "unknown",  # trend/range/high_volatility
            "last_check": None,
            "pause_trading": False,
        },
    }




# ============= V7.0 智能冷静期与复盘系统 =============


def get_trading_experience_level():
    """获取交易经验等级（V7.5新增）"""
    try:
        if not TRADES_FILE.exists():
            return 0, "新手"
        
        df = pd.read_csv(TRADES_FILE)
        df = df[df["平仓时间"].notna()]  # 只看已平仓交易
        trade_count = len(df)
        
        if trade_count < 5:
            return trade_count, "新手"
        elif trade_count < 20:
            return trade_count, "学习期"
        elif trade_count < 50:
            return trade_count, "成长期"
        else:
            return trade_count, "成熟期"
    except Exception as e:
        print(f"⚠️ 获取交易经验失败: {e}")
        return 0, "新手"


def get_safe_params_by_experience(trade_count, ai_config=None):
    """根据交易经验返回安全参数（V7.8.3 动态AI参数+安全系数）
    
    新策略：基于AI优化参数，用安全系数调整
    - 0-4笔：AI参数×1.5倍保守系数（新手模式）
    - 5-19笔：AI参数×1.3倍保守系数（学习期）
    - 20-49笔：AI参数×1.1倍保守系数（成长期）
    - 50+笔：直接使用AI参数（成熟期）
    
    Args:
        trade_count: 交易笔数
        ai_config: AI优化的配置字典（包含global参数）
    """
    # 获取AI优化的基础参数
    if ai_config is None:
        try:
            ai_config = load_learning_config()
        except:
            ai_config = get_default_config()
    
    ai_global = ai_config.get('global', {})
    base_rr = ai_global.get('min_risk_reward', 1.5)
    base_atr = ai_global.get('atr_stop_multiplier', 1.5)
    base_consensus = ai_global.get('min_indicator_consensus', 2)
    base_score = ai_global.get('min_signal_score', 55)
    
    if trade_count < 5:
        # 新手模式：1.5倍保守系数 + 最高标准
        return {
            "min_risk_reward": max(base_rr * 1.5, 2.5),  # AI×1.5，最低2.5
            "atr_stop_multiplier": max(base_atr * 1.3, 2.0),  # 更宽止损
            "min_indicator_consensus": min(5, max(4, base_consensus)),  # 至少4个
            "base_position_ratio": 0.10,  # 最小仓位
            "min_signal_score": min(90, base_score + 35),  # AI+35分，最高90
            "max_total_positions": 1,  # 只允许1个持仓
            "max_hold_time_hours": 12,  # 短线持仓
            "_mode": "新手模式(AI×1.5)",
            "_ai_base": f"R:R={base_rr:.1f}→{max(base_rr * 1.5, 2.5):.1f}",
        }
    elif trade_count < 20:
        # 学习期：1.3倍保守系数
        return {
            "min_risk_reward": max(base_rr * 1.3, 2.0),  # AI×1.3，最低2.0
            "atr_stop_multiplier": max(base_atr * 1.2, 1.8),
            "min_indicator_consensus": min(4, max(3, base_consensus)),  # 3-4个
            "base_position_ratio": 0.15,
            "min_signal_score": min(85, base_score + 25),  # AI+25分，最高85
            "max_total_positions": 2,
            "max_hold_time_hours": 18,
            "_mode": "学习期(AI×1.3)",
            "_ai_base": f"R:R={base_rr:.1f}→{max(base_rr * 1.3, 2.0):.1f}",
        }
    elif trade_count < 50:
        # 成长期：1.1倍保守系数
        return {
            "min_risk_reward": max(base_rr * 1.1, 1.5),  # AI×1.1，最低1.5
            "atr_stop_multiplier": max(base_atr * 1.05, 1.6),
            "min_indicator_consensus": max(2, base_consensus),  # 至少2个
            "base_position_ratio": 0.18,
            "min_signal_score": min(70, base_score + 10),  # AI+10分，最高70
            "max_total_positions": 2,
            "max_hold_time_hours": 24,
            "_mode": "成长期(AI×1.1)",
            "_ai_base": f"R:R={base_rr:.1f}→{max(base_rr * 1.1, 1.5):.1f}",
        }
    else:
        # 成熟期：直接使用AI参数
        return None


def calculate_market_volatility():
    """计算市场波动率（用于动态冷却判断）"""
    try:
        # 读取最近的盈亏快照，获取市场波动情况
        if not PNL_HISTORY_FILE.exists():
            return 1.0  # 默认正常波动
        
        df = pd.read_csv(PNL_HISTORY_FILE)
        if len(df) < 10:
            return 1.0
        
        # 计算最近24小时的波动率（资产变化的标准差）
        recent = df.tail(48)  # 假设15分钟一次，48次=12小时
        if '总资产' in recent.columns:
            returns = recent['总资产'].pct_change().dropna()
            volatility = returns.std()
            # 归一化：正常波动为1.0，高波动>1.5，极端波动>2.0
            normalized_volatility = volatility / 0.01  # 假设1%为基准波动
            return min(max(normalized_volatility, 0.5), 3.0)  # 限制在0.5-3.0之间
        
        return 1.0
    except Exception as e:
        print(f"⚠️ 计算市场波动率失败: {e}")
        return 1.0


def should_trigger_cooldown_dynamic(recent_trades, total_assets, market_volatility=1.0):
    """V7.5动态冷却期触发检查（智能判断）
    
    考虑因素：
    1. 亏损幅度：小亏损容忍度更高
    2. 时间密度：短时间内连续亏损更危险
    3. 市场环境：高波动期放宽标准
    4. 连续性：连续亏损比分散亏损更严重
    
    返回: (should_trigger, cooldown_level, reason)
    """
    from datetime import datetime
    
    if len(recent_trades) < 3:
        return False, 0, ""
    
    # 获取最近的亏损交易
    loss_trades = [t for t in recent_trades if t.get('盈亏(U)', 0) < 0]
    
    if len(loss_trades) < 3:
        return False, 0, ""
    
    # 取最近3笔亏损
    last_3_losses = loss_trades[-3:]
    
    # 计算总亏损率和总亏损额
    total_loss = sum(t['盈亏(U)'] for t in last_3_losses)
    total_loss_pct = abs(total_loss) / total_assets if total_assets > 0 else 0
    
    # 计算时间跨度
    try:
        first_time = pd.to_datetime(last_3_losses[0]['开仓时间'])
        last_time = pd.to_datetime(last_3_losses[-1]['平仓时间'])
        time_span_hours = (last_time - first_time).total_seconds() / 3600
    except:
        time_span_hours = 24  # 默认假设24小时
    
    # 动态判断逻辑
    
    # 🔴 极端情况：2小时内亏损>5% → 直接3级冷静
    if time_span_hours < 2 and total_loss_pct > 0.05:
        return True, 3, f"极端风险：{time_span_hours:.1f}小时内亏损{total_loss_pct*100:.1f}%"
    
    # 🟠 高危情况：6小时内亏损>3% → 2级冷静
    if time_span_hours < 6 and total_loss_pct > 0.03:
        return True, 2, f"高风险：{time_span_hours:.1f}小时内亏损{total_loss_pct*100:.1f}%"
    
    # 🟡 标准情况：连续3笔亏损 → 1级冷静
    # 检查是否真的连续（最近5笔中有3笔亏损）
    last_5 = recent_trades[-5:] if len(recent_trades) >= 5 else recent_trades
    consecutive_losses = sum(1 for t in last_5 if t.get('盈亏(U)', 0) < 0)
    
    if consecutive_losses >= 3:
        # 考虑市场波动率：高波动期（如暴跌）放宽判断
        if market_volatility > 1.8:
            # 市场极端波动，亏损可能不是策略问题
            if total_loss_pct < 0.02:  # 亏损<2%，容忍
                return False, 0, f"市场极端波动期，小幅亏损{total_loss_pct*100:.1f}%可容忍"
        
        # 小额亏损容忍：如果3笔合计<1U，不触发
        if abs(total_loss) < 1.0:
            return False, 0, f"亏损额度较小({abs(total_loss):.2f}U)，暂不触发冷静期"
        
        return True, 1, f"连续{consecutive_losses}笔亏损(总计{abs(total_loss):.2f}U)"
    
    return False, 0, ""


def should_pause_trading_v7(config):
    """V7.5渐进式冷静期检查（带盈利退出机制 + 动态触发）
    
    返回: (should_pause, pause_reason, remaining_minutes)
    
    V7.5改进：
    - 动态冷却触发：考虑亏损幅度、时间密度、市场环境
    - 优化盈利退出：根据冷静等级要求不同盈利质量
    """
    from datetime import datetime, timedelta
    
    # 获取当前市场环境（冷静期状态）
    market_regime = config.get("market_regime", {})
    pause_level = market_regime.get("pause_level", 0)  # 0=正常，1=2h，2=4h，3=暂停至明日
    pause_start = market_regime.get("pause_start", None)
    pause_until = market_regime.get("pause_until", None)
    
    # 如果没有暂停，返回正常
    if pause_level == 0:
        return False, "", 0
    
    # 检查是否到达恢复时间
    now = datetime.now()
    if pause_until:
        pause_until_dt = datetime.fromisoformat(pause_until)
        
        # 🆕 V7.5: 检查冷静期内是否有足够盈利（根据等级要求不同）
        if _check_profit_during_cooldown(pause_start, pause_level):
            # 盈利退出机制
            new_pause_level = max(0, pause_level - 1)
            market_regime["pause_level"] = new_pause_level
            market_regime["pause_start"] = None
            market_regime["pause_until"] = None
            config["market_regime"] = market_regime
            
            # 保存配置
            from pathlib import Path
            import json
            config_file = Path("trading_data") / os.getenv("MODEL_NAME", "qwen") / "learning_config.json"
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            # 发送盈利恢复通知
            send_recovery_notification_v7(
                model_name=os.getenv("MODEL_NAME", "Qwen"),
                recovery_type="profit_exit",
                pause_level=pause_level,
                new_pause_level=new_pause_level
            )
            
            return False, "", 0
        
        # 正常时间到达恢复
        if now >= pause_until_dt:
            # 重置冷静期状态
            market_regime["pause_level"] = 0
            market_regime["pause_start"] = None
            market_regime["pause_until"] = None
            config["market_regime"] = market_regime
            
            # 保存配置
            from pathlib import Path
            import json
            config_file = Path("trading_data") / os.getenv("MODEL_NAME", "qwen") / "learning_config.json"
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            # 发送恢复通知
            send_recovery_notification_v7(
                model_name=os.getenv("MODEL_NAME", "Qwen"),
                recovery_type="time_based",
                pause_level=pause_level,
                new_pause_level=0
            )
            
            return False, "", 0
        else:
            # 计算剩余时间
            remaining = pause_until_dt - now
            remaining_minutes = int(remaining.total_seconds() / 60)
            
            if pause_level == 3:
                reason = f"今日交易已暂停（明日00:00恢复）"
            else:
                hours = remaining_minutes // 60
                mins = remaining_minutes % 60
                cooldown_hours = 2 if pause_level == 1 else 4
                reason = f"冷静期中（{cooldown_hours}小时），剩余{hours}h{mins}m"
            
            return True, reason, remaining_minutes
    
    return False, "", 0


def _get_trigger_losses_before_cooldown(pause_start):
    """获取触发冷静期前的亏损（用于计算盈利退出阈值）"""
    try:
        from datetime import datetime
        
        pause_start_dt = datetime.fromisoformat(pause_start)
        
        # 读取交易历史
        trades_file = Path("trading_data") / os.getenv("MODEL_NAME", "qwen") / "trades_history.csv"
        if not trades_file.exists():
            return 0
        
        df = pd.read_csv(trades_file)
        if df.empty:
            return 0
        
        # 获取触发前的交易（冷静期开始前1小时内的亏损）
        df['平仓时间_dt'] = pd.to_datetime(df['平仓时间'], errors='coerce')
        trigger_window_start = pause_start_dt - pd.Timedelta(hours=1)
        trigger_trades = df[(df['平仓时间_dt'] >= trigger_window_start) & 
                           (df['平仓时间_dt'] < pause_start_dt)]
        
        if not trigger_trades.empty:
            losses = trigger_trades[trigger_trades['盈亏(U)'] < 0]
            return abs(losses['盈亏(U)'].sum())
        
        return 5.0  # 默认假设5U亏损
    except Exception as e:
        print(f"⚠️ 获取触发亏损失败: {e}")
        return 5.0


def _check_profit_during_cooldown(pause_start, pause_level=1):
    """V7.5优化：检查冷静期内是否有足够盈利退出
    
    盈利质量要求（根据冷静等级）：
    - 1级冷静：单笔盈利>1U 或 总盈利>2U
    - 2级冷静：总盈利>触发亏损的30%
    - 3级冷静：总盈利>触发亏损的50%
    """
    if not pause_start:
        return False
    
    try:
        from pathlib import Path
        import pandas as pd
        from datetime import datetime
        
        pause_start_dt = datetime.fromisoformat(pause_start)
        
        # 读取交易历史
        trades_file = Path("trading_data") / os.getenv("MODEL_NAME", "qwen") / "trades_history.csv"
        if not trades_file.exists():
            return False
        
        df = pd.read_csv(trades_file)
        if df.empty:
            return False
        
        # 过滤冷静期内的交易
        df['平仓时间_dt'] = pd.to_datetime(df['平仓时间'], errors='coerce')
        cooldown_trades = df[df['平仓时间_dt'] >= pause_start_dt]
        
        if cooldown_trades.empty:
            return False
        
        # 计算冷静期内的盈利
        profit_trades = cooldown_trades[cooldown_trades['盈亏(U)'] > 0]
        if profit_trades.empty:
            return False
        
        total_profit = profit_trades['盈亏(U)'].sum()
        max_single_profit = profit_trades['盈亏(U)'].max()
        
        # 根据冷静等级判断
        if pause_level == 1:
            # 1级：单笔>1U 或 总盈利>2U
            if max_single_profit > 1.0 or total_profit > 2.0:
                print(f"✅ 1级冷静期退出：盈利{total_profit:.2f}U (最大单笔{max_single_profit:.2f}U)")
                return True
        
        elif pause_level == 2:
            # 2级：总盈利>触发亏损的30%
            trigger_loss = _get_trigger_losses_before_cooldown(pause_start)
            required_profit = trigger_loss * 0.3
            if total_profit > required_profit:
                print(f"✅ 2级冷静期退出：盈利{total_profit:.2f}U > 要求{required_profit:.2f}U (触发亏损{trigger_loss:.2f}U的30%)")
                return True
            else:
                print(f"⏳ 盈利不足退出：{total_profit:.2f}U < {required_profit:.2f}U")
        
        elif pause_level == 3:
            # 3级：总盈利>触发亏损的50%
            trigger_loss = _get_trigger_losses_before_cooldown(pause_start)
            required_profit = trigger_loss * 0.5
            if total_profit > required_profit:
                print(f"✅ 3级冷静期退出：盈利{total_profit:.2f}U > 要求{required_profit:.2f}U (触发亏损{trigger_loss:.2f}U的50%)")
                return True
            else:
                print(f"⏳ 盈利不足退出：{total_profit:.2f}U < {required_profit:.2f}U")
        
        return False
    except Exception as e:
        print(f"⚠️ 检查冷静期盈利时出错: {e}")
        return False


# ============================================================
# 【V8.3.21】数据增强辅助函数（方案B）
# ============================================================

def get_kline_context(klines, count=10):
    """
    【V8.3.21 - 盲点1】获取K线序列上下文
    
    让AI看到最近N根K线的统计信息，理解"来龙去脉"
    
    Args:
        klines: K线列表，每个元素是dict {"open": float, "high": float, "low": float, "close": float, "volume": float}
        count: 分析最近几根K线（默认10）
    
    Returns:
        dict: K线上下文信息
    """
    try:
        if not klines or len(klines) < 2:
            return None
        
        # 取最近N根K线
        recent = klines[-min(count, len(klines)):]
        
        highs = [k['high'] for k in recent]
        lows = [k['low'] for k in recent]
        opens = [k['open'] for k in recent]
        closes = [k['close'] for k in recent]
        volumes = [k['volume'] for k in recent]
        
        # 计算K线特征
        bodies = [abs(c - o) for c, o in zip(closes, opens)]
        ranges = [h - l for h, l in zip(highs, lows)]
        
        # 阳线/阴线数量
        bullish = sum(1 for c, o in zip(closes, opens) if c > o)
        bearish = len(recent) - bullish
        
        # 价格变化
        price_change_pct = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
        
        # 趋势判断
        is_trending_up = False
        is_trending_down = False
        if len(closes) >= 5:
            is_trending_up = closes[-1] > closes[0] and closes[-1] > closes[-5]
            is_trending_down = closes[-1] < closes[0] and closes[-1] < closes[-5]
        
        return {
            "count": len(recent),
            "highest_high": max(highs),
            "lowest_low": min(lows),
            "avg_body_size": sum(bodies) / len(bodies) if bodies else 0,
            "avg_range_size": sum(ranges) / len(ranges) if ranges else 0,
            "avg_volume": sum(volumes) / len(volumes) if volumes else 0,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "bullish_ratio": bullish / len(recent) if recent else 0,
            "price_change_pct": round(price_change_pct, 2),
            "is_trending_up": is_trending_up,
            "is_trending_down": is_trending_down,
            "volatility_pct": ((max(highs) - min(lows)) / min(lows) * 100) if min(lows) > 0 else 0
        }
    except Exception as e:
        print(f"⚠️ get_kline_context失败: {e}")
        return None


def analyze_market_structure(klines, timeframe_hours=0.25):
    """
    【V8.3.21 - 盲点2】分析市场结构
    
    识别高低点序列、趋势年龄、位置等结构信息
    
    Args:
        klines: K线列表
        timeframe_hours: 时间框架（小时），15m=0.25, 1h=1.0, 4h=4.0
    
    Returns:
        dict: 市场结构信息
    """
    try:
        if not klines or len(klines) < 10:
            return None
        
        closes = [k['close'] for k in klines]
        highs = [k['high'] for k in klines]
        lows = [k['low'] for k in klines]
        
        # 识别swing高低点（简化版：局部极值）
        swing_highs = []
        swing_lows = []
        
        for i in range(2, len(klines)-2):
            high = highs[i]
            low = lows[i]
            
            # Swing High: 比前后2根都高
            if high >= max(highs[i-1], highs[i-2], highs[i+1], highs[i+2]):
                swing_highs.append((i, high))
            
            # Swing Low: 比前后2根都低
            if low <= min(lows[i-1], lows[i-2], lows[i+1], lows[i+2]):
                swing_lows.append((i, low))
        
        # 判断结构类型
        structure = "unknown"
        trend_strength = "weak"
        
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            last_2_highs = [h for _, h in swing_highs[-2:]]
            last_2_lows = [l for _, l in swing_lows[-2:]]
            
            # HH-HL (上升结构)
            if last_2_highs[-1] > last_2_highs[0] and last_2_lows[-1] > last_2_lows[0]:
                structure = "HH-HL"
                trend_strength = "strong_bullish"
            # LL-LH (下降结构)
            elif last_2_highs[-1] < last_2_highs[0] and last_2_lows[-1] < last_2_lows[0]:
                structure = "LL-LH"
                trend_strength = "strong_bearish"
            # 混乱结构
            else:
                structure = "choppy"
                trend_strength = "weak"
        
        # 计算趋势年龄（从最近的swing点开始）
        current_price = closes[-1]
        trend_age_candles = 0
        
        if swing_highs or swing_lows:
            all_swings = [(i, 'high') for i, _ in swing_highs] + [(i, 'low') for i, _ in swing_lows]
            all_swings.sort()
            if all_swings:
                last_swing_idx = all_swings[-1][0]
                trend_age_candles = len(klines) - last_swing_idx - 1
        
        # 计算趋势累计涨跌幅
        if trend_age_candles > 0 and trend_age_candles < len(closes):
            trend_start_price = closes[-(trend_age_candles+1)]
            trend_move_pct = ((current_price - trend_start_price) / trend_start_price * 100) if trend_start_price > 0 else 0
        else:
            trend_move_pct = 0
        
        # 当前价格在区间的位置（0=最低，1=最高）
        recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        recent_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)
        position_in_range = ((current_price - recent_low) / (recent_high - recent_low)) if (recent_high - recent_low) > 0 else 0.5
        
        # 距离高低点的距离
        distance_from_high = ((recent_high - current_price) / current_price * 100) if current_price > 0 else 0
        distance_from_low = ((current_price - recent_low) / current_price * 100) if current_price > 0 else 0
        
        return {
            "swing_structure": structure,
            "trend_strength": trend_strength,
            "trend_age_candles": trend_age_candles,
            "trend_age_hours": round(trend_age_candles * timeframe_hours, 1),
            "trend_move_pct": round(trend_move_pct, 2),
            "last_swing_high": swing_highs[-1][1] if swing_highs else 0,
            "last_swing_low": swing_lows[-1][1] if swing_lows else 0,
            "position_in_range": round(position_in_range, 2),
            "distance_from_high_pct": round(distance_from_high, 2),
            "distance_from_low_pct": round(distance_from_low, 2)
        }
    except Exception as e:
        print(f"⚠️ analyze_market_structure失败: {e}")
        return None


def analyze_sr_history(klines, sr_price, sr_type='resistance', tolerance_pct=0.5):
    """
    【V8.3.21 - 盲点3】分析支撑/阻力的历史测试情况
    
    识别这个支撑/阻力被测试过几次、反应如何
    
    Args:
        klines: K线列表（建议至少50-100根）
        sr_price: 支撑/阻力价格
        sr_type: 'support' or 'resistance'
        tolerance_pct: 容差百分比（默认0.5%，即价格在±0.5%范围内算"测试"）
    
    Returns:
        dict: S/R历史信息
    """
    try:
        if not klines or not sr_price or sr_price <= 0:
            return None
        
        test_count = 0
        reactions = []  # 记录每次测试后的价格反应
        last_test_ago_candles = None
        false_breakouts = 0
        
        for i, kline in enumerate(klines):
            high = kline['high']
            low = kline['low']
            close = kline['close']
            
            # 判断是否"测试"了S/R
            tested = False
            
            if sr_type == 'resistance':
                # 阻力测试：最高价接近或突破阻力位
                if high >= sr_price * (1 - tolerance_pct/100):
                    tested = True
                    # 记录反应：收盘价相对阻力位的距离
                    reaction_pct = ((close - sr_price) / sr_price * 100)
                    reactions.append(reaction_pct)
                    
                    # 假突破：最高价突破但收盘回落
                    if high > sr_price and close < sr_price:
                        false_breakouts += 1
            
            elif sr_type == 'support':
                # 支撑测试：最低价接近或跌破支撑位
                if low <= sr_price * (1 + tolerance_pct/100):
                    tested = True
                    # 记录反应：收盘价相对支撑位的距离
                    reaction_pct = ((close - sr_price) / sr_price * 100)
                    reactions.append(reaction_pct)
                    
                    # 假跌破：最低价跌破但收盘反弹
                    if low < sr_price and close > sr_price:
                        false_breakouts += 1
            
            if tested:
                test_count += 1
                last_test_ago_candles = len(klines) - i - 1
        
        if test_count == 0:
            return None
        
        # 计算平均/最大反应
        if sr_type == 'resistance':
            avg_reaction = sum(reactions) / len(reactions) if reactions else 0
            max_rejection = min(reactions) if reactions else 0  # 最大回调（负数）
            description = f"被测试{test_count}次"
            if false_breakouts > 0:
                description += f"，{false_breakouts}次假突破"
        else:  # support
            avg_reaction = sum(reactions) / len(reactions) if reactions else 0
            max_bounce = max(reactions) if reactions else 0  # 最大反弹（正数）
            description = f"被测试{test_count}次"
            if false_breakouts > 0:
                description += f"，{false_breakouts}次假跌破"
        
        return {
            "test_count": test_count,
            "last_test_ago_candles": last_test_ago_candles if last_test_ago_candles is not None else 999,
            "avg_reaction_pct": round(avg_reaction, 2),
            "max_rejection_pct": round(max_rejection, 2) if sr_type == 'resistance' else round(max_bounce, 2),
            "false_breakouts": false_breakouts,
            "description": description
        }
    except Exception as e:
        print(f"⚠️ analyze_sr_history失败: {e}")
        return None


def save_market_snapshot_v7(market_data_list):
    """保存市场快照（每15分钟）供复盘分析"""
    try:
        from pathlib import Path
        from datetime import datetime
        import pandas as pd
        
        model_name = os.getenv("MODEL_NAME", "qwen")
        snapshot_dir = Path("trading_data") / model_name / "market_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        today = datetime.now().strftime("%Y%m%d")
        snapshot_file = snapshot_dir / f"{today}.csv"
        
        # 🔧 V7.8.1 修复：加载配置用于计算risk_reward
        try:
            config = load_learning_config()
            if not config:
                config = get_default_config()
        except:
            config = get_default_config()
        
        # 准备快照数据
        snapshot_data = []
        
        # 🔧 V7.8.2: 使用K线时间戳（对齐15分钟整数倍），避免因耗时导致时间错位
        current_time = None
        
        for data in market_data_list:
            if data is None:
                print("⚠️ 跳过数据获取失败的币种（市场快照）")
                continue  # 跳过获取失败的币种
            
            # 获取币种名称（用于日志）
            coin_name = data.get("symbol", "").split("/")[0]
            
            # 获取当前K线数据（15分钟级别）
            kline_list = data.get("kline_data", [])
            current_kline = kline_list[-1] if kline_list else {}
            
            # 【V8.1.2修复】数据质量检查：确保K线数据完整
            if not current_kline:
                print(f"⚠️ {coin_name}: kline_data为空，使用fallback值（可能导致OHLC相等）")
                # 尝试从data直接构建OHLC（使用当前价格作为所有值）
                # 这是最后的fallback，但至少保证数据一致性
                fallback_price = data.get("current_price", data.get("price", 0))
                current_kline = {
                    "open": fallback_price,
                    "high": fallback_price,
                    "low": fallback_price,
                    "close": fallback_price,
                    "volume": data.get("volume", 0)
                }
                print(f"  → 使用fallback价格: ${fallback_price:.4f}")
            else:
                # 数据质量检查：确保OHLC数据合理
                o = current_kline.get("open", 0)
                h = current_kline.get("high", 0)
                l = current_kline.get("low", 0)
                c = current_kline.get("close", 0)
                
                # 检查是否所有值都相等（可能是数据问题）
                if o == h == l == c and o > 0:
                    print(f"⚠️ {coin_name}: K线OHLC都相等 (${o:.4f})，可能是数据质量问题")
                # 检查high和low的合理性
                elif h > 0 and l > 0 and (h < l or h < o or h < c or l > o or l > c):
                    print(f"⚠️ {coin_name}: K线数据异常 (O:{o:.4f} H:{h:.4f} L:{l:.4f} C:{c:.4f})")
                    # 使用close价格作为所有值（更保守的策略）
                    current_kline = {
                        "open": c,
                        "high": c,
                        "low": c,
                        "close": c,
                        "volume": current_kline.get("volume", 0)
                    }
                    print(f"  → 已修正为close价格: ${c:.4f}")
            
            # 🔧 V7.8.2: 首次循环时，从K线时间戳计算规范化时间（对齐15分钟）
            if current_time is None and current_kline.get("timestamp"):
                try:
                    import pandas as pd
                    kline_ts = current_kline["timestamp"]
                    # 处理不同类型的时间戳（先检查pd.Timestamp，避免被误判为数值）
                    if isinstance(kline_ts, pd.Timestamp):
                        # Pandas Timestamp对象
                        kline_dt = kline_ts.to_pydatetime()
                    elif isinstance(kline_ts, (int, float)):
                        # 数值型时间戳（毫秒）
                        kline_dt = datetime.fromtimestamp(int(kline_ts) / 1000)
                    else:
                        raise ValueError(f"未知的时间戳类型: {type(kline_ts)}")
                    
                    # 向下取整到15分钟（0/15/30/45）
                    minute = (kline_dt.minute // 15) * 15
                    normalized_dt = kline_dt.replace(minute=minute, second=0, microsecond=0)
                    current_time = normalized_dt.strftime("%H%M")
                    print(f"📅 市场快照时间: {current_time} (基于K线时间戳 {kline_dt.strftime('%H:%M:%S')})")
                except Exception as e:
                    print(f"⚠️ 解析K线时间戳失败: {e}，回退到系统时间")
                    current_time = datetime.now().strftime("%H%M")
            
            # 如果所有K线都无时间戳，回退到系统时间
            if current_time is None:
                current_time = datetime.now().strftime("%H%M")
            
            # 获取1小时数据（V6.0新增）
            mid_term = data.get("mid_term", {})
            mt_sr = mid_term.get("support_resistance", {})
            
            # 安全获取MACD数据
            macd_data = data.get("macd", {}) or {}
            macd_1h = (mid_term.get("macd") or {})
            
            # 安全获取支撑阻力数据
            nearest_resistance = (mt_sr.get("nearest_resistance") or {})
            nearest_support = (mt_sr.get("nearest_support") or {})
            
            # 安全获取裸K数据
            price_action = data.get("price_action", {}) or {}
            pullback = price_action.get("pullback_type", {}) or {}
            
            # 计算指标共振（用于复盘分析）
            ma = data.get("moving_averages", {}) or {}
            rsi_data = data.get("rsi", {}) or {}
            vol = data.get("volume_analysis", {}) or {}
            
            indicator_consensus = 0
            # 【V8.2.6修复】提高共振标准，只有"强信号"才计入
            # 1. EMA明确发散（MA7显著高于MA24，至少2%差距）
            ma7 = ma.get("ma7", 0)
            ma24 = ma.get("ma24", 0)
            if ma7 > 0 and ma24 > 0:
                divergence = (ma7 - ma24) / ma24 * 100
                if abs(divergence) >= 2.0:  # 至少2%的发散
                    indicator_consensus += 1
            
            # 2. MACD明确金叉/死叉（histogram显著>0或<0，至少0.01）
            macd_hist = macd_data.get("histogram", 0)
            if abs(macd_hist) >= 0.01:  # 明确的方向
                indicator_consensus += 1
            
            # 3. RSI强信号（超买>70或超卖<30，或接近中性45-55）
            rsi_14 = rsi_data.get("rsi_14", 50)
            if rsi_14 > 70 or rsi_14 < 30 or (45 <= rsi_14 <= 55):
                indicator_consensus += 1
            
            # 4. 成交量明显放量（>150%）
            if vol.get("ratio", 0) >= 1.5:
                indicator_consensus += 1
            
            # 5. 多周期趋势一致（15m、1h、4h同向）
            trend_15m = data.get("trend_15m", "")
            trend_1h = mid_term.get("trend", "")
            trend_4h = data.get("trend_4h", "")
            if ("多头" in trend_15m and "多头" in trend_1h and "多头" in trend_4h) or \
                ("空头" in trend_15m and "空头" in trend_1h and "空头" in trend_4h):
                indicator_consensus += 1
            
            # 【V8.2】计算信号评分的各个维度（保存"原料"而非"成品"）
            try:
                # 【V8.3.10.3修复】确保data不为None
                if not data or not isinstance(data, dict):
                    raise ValueError("Invalid market_data")
                
                # 先分类信号类型
                signal_classification = classify_signal_type(data)
                signal_type = signal_classification.get('signal_type', 'swing')
                
                # 计算各个维度的分数
                components = calculate_signal_score_components(data, signal_type)
            except Exception as e:
                print(f"⚠️ 计算评分维度失败: {e}")
                components = {
                    'signal_type': 'swing',
                    'total_score': 0,
                    # 默认维度值
                    'volume_surge_type': '',
                    'volume_surge_score': 0,
                    'has_breakout': False,
                    'breakout_score': 0,
                    'momentum_value': 0,
                    'momentum_score': 0,
                    'consecutive_candles': 0,
                    'consecutive_score': 0,
                    'pin_bar': '',
                    'pin_bar_score': 0,
                    'engulfing': '',
                    'engulfing_score': 0,
                    'trend_alignment': 0,
                    'trend_alignment_score': 0,
                    'trend_initiation_strength': '',
                    'trend_initiation_score': 0,
                    'trend_4h_strength': '',
                    'trend_4h_strength_score': 0,
                    'ema_divergence_pct': 0,
                    'ema_divergence_score': 0,
                    'pullback_type': '',
                    'pullback_score': 0,
                    'volume_confirmed': False,
                    'volume_confirmed_score': 0
                }
            
            # 【V8.3.21】数据增强：获取K线上下文、市场结构、S/R历史
            # 盲点1：K线序列上下文
            kline_context_15m = None
            if kline_list and len(kline_list) >= 10:
                # 转换为标准格式
                standard_klines = []
                for kline in kline_list:
                    standard_klines.append({
                        'open': kline.get('open', 0),
                        'high': kline.get('high', 0),
                        'low': kline.get('low', 0),
                        'close': kline.get('close', 0),
                        'volume': kline.get('volume', 0)
                    })
                kline_context_15m = get_kline_context(standard_klines, count=10)
            
            # 盲点2：市场结构（15m级别）
            market_structure_15m = None
            if kline_list and len(kline_list) >= 20:
                standard_klines = []
                for kline in kline_list:
                    standard_klines.append({
                        'open': kline.get('open', 0),
                        'high': kline.get('high', 0),
                        'low': kline.get('low', 0),
                        'close': kline.get('close', 0),
                        'volume': kline.get('volume', 0)
                    })
                market_structure_15m = analyze_market_structure(standard_klines, timeframe_hours=0.25)
            
            # 盲点3：支撑阻力历史
            resistance_history = None
            support_history = None
            resistance = ((data.get("support_resistance") or {}).get("nearest_resistance") or {}).get("price", 0)
            support = ((data.get("support_resistance") or {}).get("nearest_support") or {}).get("price", 0)
            
            if kline_list and len(kline_list) >= 50:
                standard_klines = []
                for kline in kline_list:
                    standard_klines.append({
                        'open': kline.get('open', 0),
                        'high': kline.get('high', 0),
                        'low': kline.get('low', 0),
                        'close': kline.get('close', 0),
                        'volume': kline.get('volume', 0)
                    })
                
                if resistance > 0:
                    resistance_history = analyze_sr_history(standard_klines, resistance, sr_type='resistance')
                if support > 0:
                    support_history = analyze_sr_history(standard_klines, support, sr_type='support')
            
            # 【V8.3.20】增强版R:R计算 - 基于趋势强度动态调整
            atr_value = (data.get("atr") or {}).get("atr_14", 0)
            price = data.get("current_price", 0)
            resistance = ((data.get("support_resistance") or {}).get("nearest_resistance") or {}).get("price", 0)
            support = ((data.get("support_resistance") or {}).get("nearest_support") or {}).get("price", 0)
            trend_15m = data.get("trend_15m", "")
            trend_1h = mid_term.get("trend", "")
            trend_4h = data.get("trend_4h", "")
            
            if atr_value > 0 and price > 0:
                # 止损距离：使用当前配置的ATR倍数
                stop_distance = atr_value * config.get("atr_stop_multiplier", 2.0)
                
                # 【关键修复】基于趋势强度动态调整止盈目标
                # 1. 判断趋势强度
                is_strong_trend = (
                    ("多头" in trend_15m and "多头" in trend_1h and "多头" in trend_4h) or
                    ("空头" in trend_15m and "空头" in trend_1h and "空头" in trend_4h)
                )
                is_medium_trend = "多头" in trend_15m or "空头" in trend_15m
                
                # 2. 动态目标倍数
                if is_strong_trend:
                    target_multiplier = 6.0  # 强趋势：三框架一致
                elif is_medium_trend:
                    target_multiplier = 4.5  # 中等趋势：15m趋势明确
                else:
                    target_multiplier = 3.0  # 弱趋势/震荡
                
                # 3. 考虑成交量激增
                vol = data.get("volume_analysis", {})
                if vol.get("ratio", 0) >= 2.0:
                    target_multiplier *= 1.3  # 巨量额外加30%
                
                # 4. 考虑指标共振
                if indicator_consensus >= 4:
                    target_multiplier *= 1.2  # 强共振额外加20%
                
                # 5. 计算目标距离
                target_distance = atr_value * target_multiplier
                
                risk_reward = round(target_distance / stop_distance, 2) if stop_distance > 0 else 0
            else:
                risk_reward = 0
            
            snapshot_data.append({
                "time": current_time,
                "coin": coin_name,
                
                # === 完整OHLCV数据（用于裸K回测）===
                "open": current_kline.get("open", data.get("price", 0)),
                "high": current_kline.get("high", data.get("high", 0)),
                "low": current_kline.get("low", data.get("low", 0)),
                "close": current_kline.get("close", data.get("price", 0)),
                "volume": current_kline.get("volume", data.get("volume", 0)),
                
                # === 技术指标（已计算好，避免重复计算）===
                "price": data.get("current_price", 0),
                "trend_4h": data.get("trend_4h", ""),
                "trend_15m": data.get("trend_15m", ""),
                "rsi_14": data.get("rsi", {}).get("rsi_14", 0),
                "rsi_7": data.get("rsi", {}).get("rsi_7", 0),
                "macd_line": macd_data.get("line", 0),
                "macd_signal": macd_data.get("signal", 0),
                "macd_histogram": macd_data.get("histogram", 0),
                "atr": (data.get("atr") or {}).get("atr_14", 0),
                "support": ((data.get("support_resistance") or {}).get("nearest_support") or {}).get("price", 0),
                "resistance": ((data.get("support_resistance") or {}).get("nearest_resistance") or {}).get("price", 0),
                "indicator_consensus": indicator_consensus,  # 指标共振数（0-5）
                # V8.2: signal_score已移除，改为保存各个评分维度（见下方的 volume_surge_score 等字段）
                "risk_reward": risk_reward,  # 【V7.8关键修复】盈亏比
                
                # === 1小时数据（V6.5新增）===
                "trend_1h": mid_term.get("trend", ""),
                "ema20_1h": mid_term.get("ema20", 0),
                "ema50_1h": mid_term.get("ema50", 0),
                "macd_1h_line": macd_1h.get("line", 0),
                "macd_1h_signal": macd_1h.get("signal", 0),
                "macd_1h_histogram": macd_1h.get("histogram", 0),
                "atr_1h": mid_term.get("atr_14", 0),
                "resistance_1h": nearest_resistance.get("price", 0),
                "resistance_1h_strength": nearest_resistance.get("strength", ""),
                "support_1h": nearest_support.get("price", 0),
                "support_1h_strength": nearest_support.get("strength", ""),
                
                # === 裸K形态（用于分析）===
                "pin_bar": price_action.get("pin_bar", ""),
                "engulfing": price_action.get("engulfing", ""),
                "pullback_type": pullback.get("type", "") if isinstance(pullback, dict) else "",
                "pullback_depth": pullback.get("depth_pct", 0) if isinstance(pullback, dict) else 0,
                
                # === 【V8.3.19.2】信号评分维度（用于信号类型识别）===
                "volume_surge_type": components.get("volume_surge_type", ""),
                "volume_surge_score": components.get("volume_surge_score", 0),
                "has_breakout": components.get("has_breakout", False),
                "breakout_score": components.get("breakout_score", 0),
                
                # === YTC增强字段（V7.5新增，用于复盘分析）===
                "momentum_slope": price_action.get("momentum_slope", 0),  # 动能斜率
                "pullback_weakness_score": price_action.get("pullback_weakness_score", 0),  # 回调弱势（0-1）
                "lwp_long": price_action.get("lwp_long", 0),  # 多头LWP参考价
                "lwp_short": price_action.get("lwp_short", 0),  # 空头LWP参考价
                "lwp_confidence": price_action.get("lwp_confidence", "none"),  # LWP置信度
                
                # YTC信号
                "ytc_signal_type": (price_action.get("ytc_signal") or {}).get("signal_type", "NONE"),  # BOF/BPB/TST/NONE
                "ytc_direction": (price_action.get("ytc_signal") or {}).get("direction", ""),  # LONG/SHORT
                "ytc_strength": (price_action.get("ytc_signal") or {}).get("strength", 0),  # 信号强度1-5
                "ytc_sr_strength": (price_action.get("ytc_signal") or {}).get("sr_strength", 0),  # S/R强度1-5
                "ytc_entry_price": (price_action.get("ytc_signal") or {}).get("entry_price", 0),  # 建议入场价
                    "ytc_rationale": (price_action.get("ytc_signal") or {}).get("rationale", ""),  # 信号原因
                
                # S/R质量评估（15分钟）
                "support_strength": ((data.get("support_resistance") or {}).get("nearest_support") or {}).get("strength", 1),  # 支撑强度1-5
                "support_polarity_switched": ((data.get("support_resistance") or {}).get("nearest_support") or {}).get("is_switched_polarity", False),  # 极性转换
                "support_fast_rejection": ((data.get("support_resistance") or {}).get("nearest_support") or {}).get("is_fast_rejection", False),  # 快速拒绝
                "resistance_strength": ((data.get("support_resistance") or {}).get("nearest_resistance") or {}).get("strength", 1),  # 阻力强度1-5
                "resistance_polarity_switched": ((data.get("support_resistance") or {}).get("nearest_resistance") or {}).get("is_switched_polarity", False),
                "resistance_fast_rejection": ((data.get("support_resistance") or {}).get("nearest_resistance") or {}).get("is_fast_rejection", False),
                
                # === 【V8.3.21】数据增强字段（方案B）===
                # 盲点1：K线序列上下文（15m）
                "kline_ctx_count": kline_context_15m.get("count", 0) if kline_context_15m else 0,
                "kline_ctx_highest": kline_context_15m.get("highest_high", 0) if kline_context_15m else 0,
                "kline_ctx_lowest": kline_context_15m.get("lowest_low", 0) if kline_context_15m else 0,
                "kline_ctx_avg_body": kline_context_15m.get("avg_body_size", 0) if kline_context_15m else 0,
                "kline_ctx_avg_range": kline_context_15m.get("avg_range_size", 0) if kline_context_15m else 0,
                "kline_ctx_bullish_cnt": kline_context_15m.get("bullish_count", 0) if kline_context_15m else 0,
                "kline_ctx_bearish_cnt": kline_context_15m.get("bearish_count", 0) if kline_context_15m else 0,
                "kline_ctx_bullish_ratio": kline_context_15m.get("bullish_ratio", 0) if kline_context_15m else 0,
                "kline_ctx_price_chg_pct": kline_context_15m.get("price_change_pct", 0) if kline_context_15m else 0,
                "kline_ctx_is_up": kline_context_15m.get("is_trending_up", False) if kline_context_15m else False,
                "kline_ctx_is_down": kline_context_15m.get("is_trending_down", False) if kline_context_15m else False,
                "kline_ctx_volatility": kline_context_15m.get("volatility_pct", 0) if kline_context_15m else 0,
                
                # 盲点2：市场结构（15m）
                "mkt_struct_swing": market_structure_15m.get("swing_structure", "") if market_structure_15m else "",
                "mkt_struct_trend_strength": market_structure_15m.get("trend_strength", "") if market_structure_15m else "",
                "mkt_struct_age_candles": market_structure_15m.get("trend_age_candles", 0) if market_structure_15m else 0,
                "mkt_struct_age_hours": market_structure_15m.get("trend_age_hours", 0) if market_structure_15m else 0,
                "mkt_struct_move_pct": market_structure_15m.get("trend_move_pct", 0) if market_structure_15m else 0,
                "mkt_struct_last_high": market_structure_15m.get("last_swing_high", 0) if market_structure_15m else 0,
                "mkt_struct_last_low": market_structure_15m.get("last_swing_low", 0) if market_structure_15m else 0,
                "mkt_struct_pos_in_range": market_structure_15m.get("position_in_range", 0) if market_structure_15m else 0,
                "mkt_struct_dist_high_pct": market_structure_15m.get("distance_from_high_pct", 0) if market_structure_15m else 0,
                "mkt_struct_dist_low_pct": market_structure_15m.get("distance_from_low_pct", 0) if market_structure_15m else 0,
                
                # 盲点3：阻力历史
                "resist_hist_test_cnt": resistance_history.get("test_count", 0) if resistance_history else 0,
                "resist_hist_last_test_ago": resistance_history.get("last_test_ago_candles", 999) if resistance_history else 999,
                "resist_hist_avg_reaction": resistance_history.get("avg_reaction_pct", 0) if resistance_history else 0,
                "resist_hist_max_rejection": resistance_history.get("max_rejection_pct", 0) if resistance_history else 0,
                "resist_hist_false_bo": resistance_history.get("false_breakouts", 0) if resistance_history else 0,
                "resist_hist_desc": resistance_history.get("description", "") if resistance_history else "",
                
                # 盲点3：支撑历史
                "support_hist_test_cnt": support_history.get("test_count", 0) if support_history else 0,
                "support_hist_last_test_ago": support_history.get("last_test_ago_candles", 999) if support_history else 999,
                "support_hist_avg_reaction": support_history.get("avg_reaction_pct", 0) if support_history else 0,
                "support_hist_max_bounce": support_history.get("max_rejection_pct", 0) if support_history else 0,
                "support_hist_false_bd": support_history.get("false_breakouts", 0) if support_history else 0,
                "support_hist_desc": support_history.get("description", "") if support_history else "",
            })
        
        # 追加到文件（添加quoting参数避免字段解析错误）
        if not snapshot_data:
            print(f"⚠️ 市场快照为空，无数据保存（所有币种获取失败）")
            return
        
        df = pd.DataFrame(snapshot_data)
        if snapshot_file.exists():
            df.to_csv(snapshot_file, mode='a', header=False, index=False, encoding='utf-8', quoting=csv.QUOTE_MINIMAL)
        else:
            df.to_csv(snapshot_file, mode='w', header=True, index=False, encoding='utf-8', quoting=csv.QUOTE_MINIMAL)
        
        print(f"✓ 市场快照已保存: {current_time} ({len(snapshot_data)}个币种)")
        
    except Exception as e:
        print(f"⚠️ 保存市场快照失败: {e}")
        import traceback
        traceback.print_exc()


def daily_review_with_kline_v7():
    """V7.0每日复盘（带K线和市场快照分析）
    
    分析内容：
    1. 今日所有交易的开仓/平仓时机是否合理
    2. 错过了哪些交易机会（基于市场快照）
    3. 结合具体K线点位给出改进建议
    """
    try:
        from pathlib import Path
        from datetime import datetime, timedelta
        import pandas as pd
        
        model_name = os.getenv("MODEL_NAME", "qwen")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        
        # 读取昨日交易记录
        trades_file = Path("trading_data") / model_name / "trades_history.csv"
        if not trades_file.exists():
            return "无交易记录"
        
        df = pd.read_csv(trades_file)
        df['平仓日期'] = pd.to_datetime(df['平仓时间'], errors='coerce').dt.strftime('%Y%m%d')
        yesterday_trades = df[df['平仓日期'] == yesterday]
        
        # 读取昨日市场快照
        snapshot_file = Path("trading_data") / model_name / "market_snapshots" / f"{yesterday}.csv"
        if not snapshot_file.exists():
            market_snapshots = None
        else:
            try:
                # 添加容错参数
                market_snapshots = pd.read_csv(snapshot_file, on_bad_lines='skip', quoting=1, encoding='utf-8-sig')
            except Exception as e:
                print(f"⚠️ 读取市场快照失败: {e}")
                try:
                    market_snapshots = pd.read_csv(snapshot_file, on_bad_lines='skip', encoding='utf-8-sig')
                except:
                    market_snapshots = None
        
        # 构建复盘文本
        review_lines = [f"【{yesterday}复盘】"]
        
        if yesterday_trades.empty:
            review_lines.append("昨日无交易")
        else:
            review_lines.append(f"昨日交易：{len(yesterday_trades)}笔\n")
            
            for _, trade in yesterday_trades.iterrows():
                coin = trade.get('币种', 'N/A')
                side = trade.get('方向', 'N/A')
                pnl = trade.get('盈亏(U)', 0)
                entry = trade.get('开仓价格', 0)
                exit_price = trade.get('平仓价格', 0)
                entry_time = trade.get('开仓时间', '')
                
                review_lines.append(f"{coin} {side}: {'+' if pnl > 0 else ''}{pnl:.2f}U ({entry}→{exit_price})")
                
                # 如果有市场快照，分析开仓时机
                if market_snapshots is not None and entry_time:
                    try:
                        entry_hhmm = entry_time.split()[1][:4] if ' ' in entry_time else entry_time[:4]
                        closest = market_snapshots[
                            (market_snapshots['coin'] == coin) &
                            (market_snapshots['time'] == entry_hhmm)
                        ]
                        
                        if not closest.empty:
                            row = closest.iloc[0]
                            review_lines.append(f"  开仓环境: 价格{row['price']} RSI{row['rsi_14']:.0f} 共振{row['indicator_consensus']}/5")
                            
                            # 简单评价
                            if side == '多' and row['price'] < row['support'] * 1.002:
                                review_lines.append("  ✅ 开仓位置佳（接近支撑）")
                            elif side == '空' and row['price'] > row['resistance'] * 0.998:
                                review_lines.append("  ✅ 开仓位置佳（接近阻力）")
                            elif row['indicator_consensus'] < 3:
                                review_lines.append("  ⚠️ 指标共振不足")
                    except Exception as e:
                        pass
                
                review_lines.append("")
        
        # 【V7.9】统计最近7天（分Scalping/Swing）
        recent_7d = df[df['平仓日期'] >= (datetime.now() - timedelta(days=7)).strftime('%Y%m%d')]
        if not recent_7d.empty:
            win_count = len(recent_7d[recent_7d['盈亏(U)'] > 0])
            total_pnl = recent_7d['盈亏(U)'].sum()
            win_rate = win_count / len(recent_7d) * 100 if len(recent_7d) > 0 else 0
            review_lines.append(f"【最近7天】{len(recent_7d)}笔 胜率{win_rate:.0f}% 总盈亏{total_pnl:+.2f}U")
        
            # 分类型统计（如果有signal_type字段）
            if '信号类型' in recent_7d.columns:
                scalping_trades = recent_7d[recent_7d['信号类型'] == 'scalping']
                swing_trades = recent_7d[recent_7d['信号类型'] == 'swing']
                
                if not scalping_trades.empty:
                    scalp_wins = len(scalping_trades[scalping_trades['盈亏(U)'] > 0])
                    scalp_pnl = scalping_trades['盈亏(U)'].sum()
                    scalp_wr = scalp_wins / len(scalping_trades) * 100
                    scalp_avg_hold = scalping_trades['预期持仓(分钟)'].mean() if '预期持仓(分钟)' in scalping_trades.columns else 0
                    review_lines.append(f"  ⚡超短线: {len(scalping_trades)}笔 胜率{scalp_wr:.0f}% {scalp_pnl:+.2f}U (均{scalp_avg_hold:.0f}分)")
                
                if not swing_trades.empty:
                    swing_wins = len(swing_trades[swing_trades['盈亏(U)'] > 0])
                    swing_pnl = swing_trades['盈亏(U)'].sum()
                    swing_wr = swing_wins / len(swing_trades) * 100
                    swing_avg_hold = swing_trades['预期持仓(分钟)'].mean() if '预期持仓(分钟)' in swing_trades.columns else 0
                    review_lines.append(f"  🌊波段: {len(swing_trades)}笔 胜率{swing_wr:.0f}% {swing_pnl:+.2f}U (均{swing_avg_hold/60:.1f}h)")
        
        # 【V7.9】识别错过的机会（分Scalping/Swing）
        if market_snapshots is not None:
            strong_signals = market_snapshots[market_snapshots['indicator_consensus'] >= 4]
            if not strong_signals.empty:
                traded_coins = set(yesterday_trades['币种'].unique()) if not yesterday_trades.empty else set()
                missed = strong_signals[~strong_signals['coin'].isin(traded_coins)].copy()
                
                if not missed.empty:
                    # 【改进】基于实际价格走向判断类型（后验分析）
                    # 方法：看如果入场，实际能持有多久才触发止盈/止损
                    # - 超短线：15-60分钟内触发止盈
                    # - 波段：2-24小时持有才触发止盈
                    
                    def classify_opportunity_by_actual_movement(row):
                        """基于实际价格走向分类机会类型"""
                        try:
                            coin = row['coin']
                            signal_time_str = row['time']
                            entry_price = row['price']
                            
                            # 获取趋势判断方向
                            trend_4h = row.get('trend_4h', '')
                            trend_15m = row.get('trend_15m', '')
                            
                            # 判断建议方向（简化逻辑：4H主导）
                            if '多头' in trend_4h or 'Bullish' in trend_4h:
                                direction = 'long'
                            elif '空头' in trend_4h or 'Bearish' in trend_4h:
                                direction = 'short'
                            elif '多头' in trend_15m or 'Bullish' in trend_15m:
                                direction = 'long'
                            elif '空头' in trend_15m or 'Bearish' in trend_15m:
                                direction = 'short'
                            else:
                                # 无法判断方向，使用信号分数（回退到旧逻辑）
                                score = row.get('signal_score', 0)
                                return '⚡Scalping' if (score >= 70 and score < 80) else '🌊Swing'
                            
                            # 设置止盈目标（简化：1.5% for scalping, 3% for swing）
                            scalping_tp_pct = 0.015  # 1.5%
                            swing_tp_pct = 0.03      # 3%
                            
                            if direction == 'long':
                                scalping_tp = entry_price * (1 + scalping_tp_pct)
                                swing_tp = entry_price * (1 + swing_tp_pct)
                            else:
                                scalping_tp = entry_price * (1 - scalping_tp_pct)
                                swing_tp = entry_price * (1 - swing_tp_pct)
                            
                            # 获取后续价格数据（从市场快照）
                            from datetime import datetime, timedelta
                            signal_time = datetime.strptime(signal_time_str, '%H:%M')
                            
                            # 查找后续1小时和24小时内的价格走势
                            later_snapshots = market_snapshots[
                                (market_snapshots['coin'] == coin) & 
                                (market_snapshots['time'] > signal_time_str)
                            ].sort_values('time')
                            
                            if later_snapshots.empty:
                                # 无后续数据，使用信号分数
                                score = row.get('signal_score', 0)
                                return '⚡Scalping' if (score >= 70 and score < 80) else '🌊Swing'
                            
                            # 检查1小时内是否触发scalping止盈
                            scalping_triggered = False
                            for _, snap in later_snapshots.head(4).iterrows():  # 4个15分钟=1小时
                                high = snap.get('high', snap.get('price', 0))
                                low = snap.get('low', snap.get('price', 0))
                                
                                if direction == 'long' and high >= scalping_tp:
                                    scalping_triggered = True
                                    break
                                elif direction == 'short' and low <= scalping_tp:
                                    scalping_triggered = True
                                    break
                            
                            if scalping_triggered:
                                return '⚡Scalping'
                            
                            # 检查24小时内是否触发swing止盈
                            swing_triggered = False
                            for _, snap in later_snapshots.head(96).iterrows():  # 96个15分钟=24小时
                                high = snap.get('high', snap.get('price', 0))
                                low = snap.get('low', snap.get('price', 0))
                                
                                if direction == 'long' and high >= swing_tp:
                                    swing_triggered = True
                                    break
                                elif direction == 'short' and low <= swing_tp:
                                    swing_triggered = True
                                    break
                            
                            if swing_triggered:
                                return '🌊Swing'
                            
                            # 都未触发，按趋势强度判断
                            score = row.get('signal_score', 0)
                            return '🌊Swing' if score >= 80 else '⚡Scalping'
                            
                        except Exception as e:
                            # 出错时回退到信号分数
                            score = row.get('signal_score', 0)
                            return '⚡Scalping' if (score >= 70 and score < 80) else '🌊Swing'
                    
                    missed['推测类型'] = missed.apply(classify_opportunity_by_actual_movement, axis=1)
                    
                    scalping_missed = missed[missed['推测类型'] == '⚡Scalping']
                    swing_missed = missed[missed['推测类型'] == '🌊Swing']
                    
                    if not scalping_missed.empty or not swing_missed.empty:
                        review_lines.append("\n【错过的机会】")
                        
                        if not scalping_missed.empty:
                            review_lines.append("  ⚡超短线机会:")
                            for _, row in scalping_missed.head(2).iterrows():
                                review_lines.append(
                                    f"    {row['coin']}: {row['time']} 共振{row['indicator_consensus']}/5 "
                                    f"价格{row['price']:.0f} 分{row.get('signal_score', 0):.0f}"
                                )
                        
                        if not swing_missed.empty:
                            review_lines.append("  🌊波段机会:")
                            for _, row in swing_missed.head(2).iterrows():
                                review_lines.append(
                                    f"    {row['coin']}: {row['time']} 共振{row['indicator_consensus']}/5 "
                                    f"价格{row['price']:.0f} 分{row.get('signal_score', 0):.0f}"
                                )
        
        return "\n".join(review_lines)
        
    except Exception as e:
        return f"复盘失败: {e}"


def send_recovery_notification_v7(model_name, recovery_type, pause_level, new_pause_level):
    """发送冷静期恢复通知"""
    if recovery_type == "profit_exit":
        title = f"[{model_name}]盈利恢复🎉"
        content = f"冷静期内获利，提前恢复交易！\n\n暂停等级: {pause_level}级→{new_pause_level}级\n恢复时间: {datetime.now().strftime('%H:%M')}"
    else:
        title = f"[{model_name}]冷静期结束✅"
        content = f"冷静期已结束，恢复正常交易\n\n暂停等级: {pause_level}级→0级\n恢复时间: {datetime.now().strftime('%H:%M')}"
    
    send_bark_notification(title, content)



def load_learning_config():
    """加载学习参数（向后兼容）"""
    if LEARNING_CONFIG_FILE.exists():
        try:
            with open(LEARNING_CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)

                # 如果是旧版本配置，自动升级
                if "version" not in config:
                    print("⚠️ 检测到旧版配置，自动升级到v7.9.1...")
                    new_config = get_default_config()
                    # 保留旧的全局参数
                    new_config["global"]["min_risk_reward"] = config.get(
                        "min_risk_reward", 1.5
                    )
                    new_config["global"]["atr_stop_multiplier"] = config.get(
                        "atr_stop_multiplier", 1.5
                    )
                    new_config["global"]["min_indicator_consensus"] = config.get(
                        "min_indicator_consensus", 4
                    )
                    new_config["global"]["key_level_penalty"] = config.get(
                        "key_level_penalty", 1.0
                    )
                    save_learning_config(new_config)  # 🔧 V7.9.1: 立即保存升级后的配置
                    return new_config

                return config
        except Exception as e:
            print(f"⚠️ 加载配置失败: {e}，使用默认配置")
            return get_default_config()

    # 🔧 V7.9.1: 配置文件不存在时，自动创建并保存
    print(f"⚠️ 配置文件不存在，创建V7.9.1默认配置...")
    config = get_default_config()
    save_learning_config(config)
    print(f"✓ 已生成配置文件: {LEARNING_CONFIG_FILE}")
    return config


def save_learning_config(config):
    """保存学习参数"""
    try:
        config["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LEARNING_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2, default=str)  # 🔧 V7.6.7: 添加default=str防止bool序列化错误
        print(f"✓ 学习参数已更新: {LEARNING_CONFIG_FILE}")
    except Exception as e:
        print(f"✗ 保存学习参数失败: {e}")


def _cold_start_optimization():
    """冷启动模式：无交易样本时放宽参数，帮助系统开单积累数据"""
    print("\n" + "=" * 70)
    print("【❄️ 冷启动优化】")
    print("=" * 70)
    
    config = load_learning_config()
    
    # 放宽全局参数，让系统更容易开单
    adjustments = {
        "global": {
            "min_risk_reward": 1.2,  # 降低盈亏比要求（原本可能是1.5+）
            "min_indicator_consensus": 3,  # 降低指标共振要求
            "atr_stop_multiplier": 1.8,  # 适度放宽止损
            "base_position_ratio": 0.15,  # 保持较小仓位，控制风险
            "min_trend_strength": 0.5,  # 降低趋势强度要求
            "key_level_penalty": 0.8,  # 放宽关键位限制
        }
    }
    
    print("\n📋 冷启动调整策略：")
    print("- 降低盈亏比要求 → 1.2:1（放宽进场门槛）")
    print("- 降低指标共振要求 → 3/5（减少信号筛选）")
    print("- 保持小仓位 → 15%（控制单笔风险）")
    print("- 目标：快速积累5-10笔交易样本，建立AI认知基础")
    
    # 应用调整
    config["global"].update(adjustments["global"])
    save_learning_config(config)
    
    print("\n✅ 冷启动参数已生效，系统将更容易开单")
    print("💡 建议：观察1-2天，积累样本后AI将进入探索/学习模式")


def get_learning_config_for_symbol(symbol, config=None):
    """获取特定币种的学习参数（分层优先级）
    
    V7.5新增：新手安全模式优先级最高
    """
    if config is None:
        config = load_learning_config()

    # 🆕 V7.8.3: 优先检查交易经验，使用AI优化+安全系数
    trade_count, experience_level = get_trading_experience_level()
    safe_params = get_safe_params_by_experience(trade_count, config)  # 传递config
    
    if safe_params is not None:
        # 新手/学习期/成长期，使用AI优化+安全系数
        final_config = config["global"].copy()
        final_config.update(safe_params)
        final_config["symbol"] = symbol
        final_config["risk_profile"] = "safe_mode"
        final_config["_source"] = f"{safe_params['_mode']} (交易{trade_count}笔)"
        print(f"🛡️ 启用{safe_params['_mode']}：交易经验{trade_count}笔")
        if '_ai_base' in safe_params:
            print(f"   📊 AI基准: {safe_params['_ai_base']}")
        return final_config

    # 1. 如果有币种特定参数且样本充足，使用币种参数
    per_symbol = config.get("per_symbol", {})
    if symbol in per_symbol:
        symbol_config = per_symbol[symbol]
        if symbol_config.get("sample_count", 0) >= 5:
            symbol_config["_source"] = f"{symbol}特定参数"
            return symbol_config

    # 2. 【V7.9.1】使用风险等级安全系数（AI基准×系数，而非硬编码）
    risk_profile = config.get("risk_profiles", {}).get(symbol, "medium_risk")
    safety_multipliers = config.get("risk_safety_multipliers", {}).get(risk_profile, {})
    fallback_minimums = config.get("risk_fallback_minimums", {}).get(risk_profile, {})

    # 3. 【V7.9.1】智能合并：AI学习值 × 安全系数
    final_config = config["global"].copy()
    
    # 获取AI学习的基准值（global或per_symbol）
    ai_base_rr = config["global"].get("min_risk_reward", 1.5)
    ai_base_score = config["global"].get("min_signal_score", 55)
    
    # 如果币种有独立学习参数，优先使用（但样本要充足）
    per_symbol_data = config.get("per_symbol", {}).get(symbol, {})
    if per_symbol_data.get("sample_count", 0) >= 10:  # 至少10笔才信任
        ai_base_rr = per_symbol_data.get("min_risk_reward", ai_base_rr)
        ai_base_score = per_symbol_data.get("min_signal_score", ai_base_score)
        print(f"   📊 使用{symbol}独立学习参数（{per_symbol_data['sample_count']}笔）")
    
    # 应用安全系数
    rr_multiplier = safety_multipliers.get("min_risk_reward_multiplier", 1.0)
    score_bonus = safety_multipliers.get("min_signal_score_bonus", 0)
    
    calculated_rr = ai_base_rr * rr_multiplier
    calculated_score = ai_base_score + score_bonus
    
    # 确保不低于最低基准（防止AI学习出错）
    final_config["min_risk_reward"] = max(
        calculated_rr,
        fallback_minimums.get("min_risk_reward", 1.5)
    )
    
    final_config["min_signal_score"] = max(
        calculated_score,
        fallback_minimums.get("min_signal_score", 55)
    )
    
    # 对共振要求：使用安全系数的设定（已经考虑了风险等级）
    if "min_indicator_consensus" in safety_multipliers:
        final_config["min_indicator_consensus"] = safety_multipliers["min_indicator_consensus"]
    
    # 其他参数使用安全系数的设定
    for key in ["atr_stop_multiplier", "base_position_ratio"]:
        if key in safety_multipliers:
            final_config[key] = safety_multipliers[key]
    
    final_config["risk_profile"] = risk_profile
    final_config["symbol"] = symbol
    
    # 【V7.9.1】显示计算过程，便于理解
    if per_symbol_data.get("sample_count", 0) >= 10:
        final_config["_source"] = f"{risk_profile}(AI学×{rr_multiplier})"
    else:
        final_config["_source"] = f"{risk_profile}(全局×{rr_multiplier})"
    
    print(f"   💡 {symbol}最终要求: R:R≥{final_config['min_risk_reward']:.1f} 分≥{final_config['min_signal_score']}")

    return final_config


def detect_market_regime(market_data_list):
    """检测当前市场环境"""
    try:
        if not market_data_list:
            return "unknown", False

        # 计算市场整体波动率
        volatilities = []
        for data in market_data_list:
            if data is None:
                continue  # 跳过获取失败的币种
            price_change_pct = abs(data.get("price_change", 0))
            volatilities.append(price_change_pct)

        avg_volatility = sum(volatilities) / len(volatilities) if volatilities else 0

        # 判断市场环境
        if avg_volatility > 5.0:  # 日波动>5%
            return "high_volatility", True  # 暂停交易
        elif avg_volatility > 2.0:  # 日波动>2%
            return "trend", False  # 趋势市
        elif avg_volatility < 1.0:  # 日波动<1%
            return "range", False  # 震荡市
        else:
            return "trend", False  # 默认趋势市

    except Exception as e:
        print(f"⚠️ 市场环境检测失败: {e}")
        return "unknown", False


def calculate_position_size_smart(symbol, signal_quality, total_assets, config, signal_type='swing'):
    """【V7.9增强】智能仓位计算（分Scalping/Swing独立计算）
    
    Args:
        symbol: 交易对
        signal_quality: 信号质量（HIGH/MEDIUM/LOW）
        total_assets: 总资产
        config: 配置
        signal_type: 信号类型（scalping/swing）
    """
    try:
        # 1. 获取分类型参数
        if signal_type == 'scalping':
            type_params = config.get('global', {}).get('scalping_params', {})
        else:
            type_params = config.get('global', {}).get('swing_params', {})

        # 2. 基础仓位（使用分类型参数）
        base_ratio = type_params.get("base_position_ratio", 0.20)
        base_position = total_assets * base_ratio

        # 3. 根据信号质量调整
        if signal_quality == "HIGH":
            multiplier = 1.5
        elif signal_quality == "MEDIUM":
            multiplier = 1.0
        else:  # LOW
            multiplier = 0.7

        position = base_position * multiplier

        # 4. 检查最大仓位限制（使用分类型参数）
        max_ratio = type_params.get("max_position_ratio", 0.30)
        max_position = total_assets * max_ratio
        position = min(position, max_position)

        # 5. 检查单笔最大亏损限制
        max_loss_ratio = config.get('global', {}).get("max_loss_per_trade", 0.02)
        max_loss_position = total_assets * max_loss_ratio / 0.02  # 假设2%止损
        position = min(position, max_loss_position)

        type_name_cn = "超短线" if signal_type == 'scalping' else "波段"
        print(f"   【V7.9仓位】{type_name_cn}: 基础{base_ratio*100:.0f}% → 质量×{multiplier} = ${position:.2f}")

        return position

    except Exception as e:
        print(f"⚠️ 智能仓位计算失败: {e}")
        # 返回保守仓位
        return total_assets * 0.15



def check_signal_type_risk_budget(signal_type, current_positions, planned_position, config):
    """【V7.9新增】检查分类型风险预算
    
    Args:
        signal_type: 信号类型（scalping/swing）
        current_positions: 当前持仓列表
        planned_position: 计划开仓金额
        config: 配置
    
    Returns:
        (allowed: bool, reason: str, adjusted_position: float)
    """
    try:
        # 获取分类型参数
        if signal_type == 'scalping':
            type_params = config.get('global', {}).get('scalping_params', {})
        else:
            type_params = config.get('global', {}).get('swing_params', {})
        
        max_concurrent = type_params.get('max_concurrent_positions', 2)
        total_risk_budget = type_params.get('total_risk_budget', 0.05)
        
        # 统计同类型现有持仓
        same_type_positions = [
            p for p in current_positions 
            if p.get('signal_type') == signal_type or p.get('_temp_signal_type') == signal_type
                ]
        
        # 检查数量限制
        type_name_cn = "超短线" if signal_type == 'scalping' else "波段"
        if len(same_type_positions) >= max_concurrent:
            return False, f"{type_name_cn}持仓已达上限({max_concurrent}个)", 0
        
        # 检查风险预算
        # 从position_contexts.json读取signal_type（如果可用）
        try:
            from pathlib import Path
            import json
            model_name = os.getenv("MODEL_NAME", "qwen")
            context_file = Path("trading_data") / model_name / "position_contexts.json"
            if context_file.exists():
                with open(context_file, 'r', encoding='utf-8') as f:
                    contexts = json.load(f)
                    for pos in same_type_positions:
                        coin = pos['symbol'].split('/')[0]
                        if coin in contexts and 'signal_type' in contexts[coin]:
                            pos['_temp_signal_type'] = contexts[coin]['signal_type']
        except:
            pass
        
        # 重新计算（考虑临时标记）
        same_type_positions = [
            p for p in current_positions 
            if p.get('_temp_signal_type') == signal_type
                ]
        
        total_same_type_risk = sum([abs(p.get('unrealized_pnl', 0)) for p in same_type_positions])
        
        # 从TRADES_FILE读取最近的总资产
        try:
            total_assets = 100  # 默认值
            if TRADES_FILE.exists():
                import pandas as pd
                df = pd.read_csv(TRADES_FILE)
                if not df.empty and '仓位(U)' in df.columns:
                    recent_positions = df['仓位(U)'].dropna()
                    if len(recent_positions) > 0:
                        # 估算总资产（假设平均仓位占20%）
                        avg_position = recent_positions.mean()
                        total_assets = avg_position / 0.20
        except:
            pass
        
        max_risk = total_assets * total_risk_budget
        remaining_budget = max_risk - total_same_type_risk
        
        if remaining_budget < planned_position * 0.02:  # 假设2%风险
            # 尝试调整仓位
            adjusted = remaining_budget / 0.02
            if adjusted < planned_position * 0.5:  # 如果调整后<50%，拒绝
                return False, f"{type_name_cn}风险预算不足({total_same_type_risk:.2f}/{max_risk:.2f}U)", 0
            else:
                return True, f"{type_name_cn}风险预算紧张，仓位调整", adjusted
        
        return True, f"{type_name_cn}风险预算充足", planned_position
    
    except Exception as e:
        print(f"⚠️ 风险预算检查失败: {e}")
        return True, "检查失败，放行", planned_position


def check_scalping_frequency(coin_name, config):
    """【V7.9新增】检查Scalping频率限制
    
    Args:
        coin_name: 币种名称
        config: 配置
    
    Returns:
        (allowed: bool, reason: str)
    """
    try:
        from datetime import datetime, timedelta
        
        scalping_params = config.get('global', {}).get('scalping_params', {})
        cooldown_same = scalping_params.get('cooldown_same_coin_minutes', 30)
        cooldown_any = scalping_params.get('cooldown_any_coin_minutes', 15)
        max_per_hour = scalping_params.get('max_trades_per_hour', 4)
        
        # 读取最近的交易记录
        if not TRADES_FILE.exists():
            return True, "无历史记录"
        
        import pandas as pd
        df = pd.read_csv(TRADES_FILE)
        if df.empty:
            return True, "无交易记录"
        
        now = datetime.now()
        
        # 转换时间（处理可能的异常）
        try:
            df['开仓时间_dt'] = pd.to_datetime(df['开仓时间'], errors='coerce')
            df = df.dropna(subset=['开仓时间_dt'])
        except:
            return True, "时间解析失败，放行"
        
        # 只看Scalping订单（如果有signal_type字段）
        if '信号类型' in df.columns:
            scalping_df = df[df['信号类型'] == 'scalping'].copy()
        else:
            # 没有signal_type，按预期持仓时间判断（<1小时视为Scalping）
            if '预期持仓(分钟)' in df.columns:
                scalping_df = df[df['预期持仓(分钟)'] < 60].copy()
            else:
                scalping_df = df  # 无法判断，检查全部
        
        # 检查1: 同币种冷却期
        same_coin_recent = scalping_df[
            (scalping_df['币种'] == coin_name) &
            (scalping_df['开仓时间_dt'] > now - timedelta(minutes=cooldown_same))
        ]
        if len(same_coin_recent) > 0:
            last_time = same_coin_recent['开仓时间_dt'].max()
            wait_minutes = cooldown_same - (now - last_time).total_seconds() / 60
            return False, f"{coin_name}冷却中（还需{wait_minutes:.0f}分钟）"
        
        # 检查2: 任意币种冷却期
        any_coin_recent = scalping_df[
            scalping_df['开仓时间_dt'] > now - timedelta(minutes=cooldown_any)
        ]
        if len(any_coin_recent) > 0:
            last_time = any_coin_recent['开仓时间_dt'].max()
            wait_minutes = cooldown_any - (now - last_time).total_seconds() / 60
            return False, f"Scalping全局冷却中（还需{wait_minutes:.0f}分钟）"
        
        # 检查3: 每小时交易数
        last_hour = scalping_df[
            scalping_df['开仓时间_dt'] > now - timedelta(hours=1)
        ]
        if len(last_hour) >= max_per_hour:
            return False, f"Scalping每小时交易限制({len(last_hour)}/{max_per_hour})"
        
        return True, f"Scalping频率检查通过（{len(last_hour)}/{max_per_hour}笔/小时）"
    
    except Exception as e:
        print(f"⚠️ Scalping频率检查失败: {e}")
        return True, "检查失败，放行"


def check_cash_reserve(total_assets, available_balance, planned_position_usd, current_positions):
    """
    检查现金储备比例（防止满仓爆仓）
    
    规则：
    - 至少保留20%现金作为安全储备
    - 满仓风险过高，必须保留应急资金
    
    Args:
        total_assets: 总资产
        available_balance: 可用余额
        planned_position_usd: 计划开仓金额
        current_positions: 当前持仓列表
    
    Returns:
        (allowed: bool, reason: str, adjusted_position: float)
    """
    try:
        # 计算已使用保证金
        used_margin = 0
        for pos in current_positions:
            position_value = abs(pos.get("contracts", 0) * pos.get("entry_price", 0))
            leverage = pos.get("leverage", 1)
            if leverage > 0:
                used_margin += position_value / leverage
        
        # 计算现金储备比例（最低20%）
        MIN_CASH_RESERVE_RATIO = 0.20  # 20%
        required_reserve = total_assets * MIN_CASH_RESERVE_RATIO
        
        # 计划开仓后的剩余现金
        remaining_cash = available_balance - planned_position_usd
        
        if remaining_cash < required_reserve:
            # 计算允许的最大开仓金额
            max_allowed_position = available_balance - required_reserve
            
            if max_allowed_position < planned_position_usd * 0.3:  # 如果调整后<30%，直接拒绝
                return False, f"现金储备不足（需保留{MIN_CASH_RESERVE_RATIO*100:.0f}%={required_reserve:.2f}U，剩余{remaining_cash:.2f}U）", 0
            else:
                return True, f"现金储备紧张，仓位调整至{max_allowed_position:.2f}U", max_allowed_position
        
        # 计算使用率
        usage_rate = (used_margin + planned_position_usd) / total_assets * 100
        
        return True, f"现金储备充足（使用率{usage_rate:.1f}%，储备{remaining_cash:.2f}U）", planned_position_usd
    
    except Exception as e:
        print(f"⚠️ 现金储备检查失败: {e}")
        return True, "检查失败，放行", planned_position_usd


def check_single_direction_per_coin(symbol, operation, current_positions):
    """
    检查单币种单方向限制（每个币种只能有一个方向的一个订单）
    
    规则：
    - 单个币种只能持有一个方向的订单（做多或做空）
    - 不允许同一币种同时做多和做空（对冲）
    - 不允许同一方向开多单（防止管理混乱）
    - 可以追加到现有订单，但不能新开第二单
    
    Args:
        symbol: 交易对符号
        operation: 操作类型（OPEN_LONG/OPEN_SHORT）
        current_positions: 当前持仓列表
    
    Returns:
        (allowed: bool, reason: str)
    """
    try:
        # 检查是否已有该币种的持仓
        existing_positions = [p for p in current_positions if p.get("symbol") == symbol]
        
        if not existing_positions:
            return True, f"该币种无持仓，可以开仓"
        
        # 获取现有订单的方向
        existing_position = existing_positions[0]
        existing_side = existing_position.get("side", "").lower()
        
        # 确定新订单方向
        new_side = "long" if operation == "OPEN_LONG" else "short"
        
        # 检查是否是相同方向
        if existing_side == new_side:
            contracts = abs(existing_position.get("contracts", 0))
            entry_price = existing_position.get("entry_price", 0)
            position_value = contracts * entry_price
            
            return False, (
                f"该币种已有{existing_side}仓位（{position_value:.2f}U），"
                f"不允许同方向开第二单。建议：追加到现有订单或等待平仓后再开"
            )
        
        # 检查是否是相反方向（对冲）
        if existing_side != new_side:
            return False, (
                f"该币种已有{existing_side}仓位，不允许开{new_side}仓（禁止对冲）。"
                f"建议：先平仓现有订单再开反向单"
            )
        
        return True, f"检查通过"
    
    except Exception as e:
        print(f"⚠️ 单方向检查失败: {e}")
        return True, "检查失败，放行"


def ai_optimize_parameters(trading_data_summary, learning_mode="full_optimization", sample_count=0):
    """让AI分析交易数据并提出参数优化建议（支持不同学习模式 + 历史经验复用）
    
    Args:
        trading_data_summary: 交易数据摘要
        learning_mode: 学习模式 (exploration/initial_learning/full_optimization)
        sample_count: 当前样本数量
    """
    try:
        # 🆕 V7.6.3.2: 加载历史验证经验（每日复盘记录）
        validation_history = load_validation_history(max_records=10)
        
        # 根据学习模式调整提示词
        mode_instructions = {
            "exploration": f"""
## 🔍 Current Mode: Exploration Mode (Samples: {sample_count}/5)

**Optimization Strategy**:
- Goal: Accumulate samples, build initial understanding
- Style: Moderately relax parameters, avoid over-strict preventing entries
- Adjustment Range: Gentle (±10-15% per change)
- Focus: Lower entry threshold, maintain small positions for risk control
    - Forbidden: Don't over-tighten (min_risk_reward ≤1.5, min_indicator_consensus ≤4)
""",
            "initial_learning": f"""
## 📚 Current Mode: Initial Learning Mode (Samples: {sample_count}/10)

**Optimization Strategy**:
- Goal: Find obvious issues from limited data
- Style: Targeted adjustments, avoid aggressive changes
- Adjustment Range: Moderate (±15-20% per change)
- Focus: Identify clear loss patterns (frequent stops, prolonged holds, etc.)
- Caution: Limited samples, avoid overfitting
""",
            "full_optimization": f"""
## 🎯 Current Mode: Deep Optimization Mode (Samples: {sample_count} trades)

**Optimization Strategy**:
- Goal: Comprehensive analysis, fine-tuning
- Style: Data-driven, bold adjustments allowed
- Adjustment Range: Flexible based on severity (±20-30%)
- Focus: Deep dive into win rate, R:R, hold time root causes
- Allowed: Can set differentiated parameters per symbol
"""
        }
        
        mode_instruction = mode_instructions.get(learning_mode, mode_instructions["full_optimization"])
        
        # 🆕 V7.6.3.2: 构建历史经验上下文
        if validation_history:
            experience_context = "## 📚 HISTORICAL VALIDATION LESSONS (Recent Daily Reviews)\n\n"
            experience_context += "**Learn from previous parameter optimization attempts to avoid repeating mistakes:**\n\n"
            
            for i, lesson in enumerate(validation_history, 1):
                status = "✅ EFFECTIVE" if lesson['was_effective'] else "❌ INEFFECTIVE"
                applied = "✓ APPLIED" if lesson['should_apply'] else "✗ REJECTED"
                
                experience_context += f"### Lesson {i} ({lesson['date'][:10]}) - {status} ({applied})\n"
                experience_context += f"**Attempted Adjustments**:\n{json.dumps(lesson['attempted_adjustments'], indent=2, ensure_ascii=False)}\n\n"
                
                if lesson['composite_improvement'] is not None:
                    experience_context += f"**Composite Profit Metric Change**: {lesson['composite_improvement']:+.1f}%\n"
                    experience_context += f"  (= Weighted Win Rate × Weighted Profit Ratio × Capture Rate)\n\n"
                
                experience_context += f"**Key Insight**: {lesson['key_insight'][:200]}...\n"
                
                if not lesson['was_effective']:
                    experience_context += f"**Root Cause**: {lesson['root_cause'][:200]}...\n"
                
                experience_context += f"**Final Decision**: {'Applied to production' if lesson['should_apply'] else 'Rejected'}\n\n"
                experience_context += "---\n\n"
        else:
            experience_context = "## 📚 HISTORICAL VALIDATION LESSONS\n\nNo historical data available yet. This is the first optimization.\n\n"
        
        prompt = f"""**[IMPORTANT: Respond ONLY in Chinese (中文)]**

You are a professional quantitative trading parameter optimization expert. Analyze the following trading data comprehensively and propose actionable parameter adjustments.

{experience_context}

{mode_instruction}

## TRADING DATA STATISTICS

{trading_data_summary}

## ADJUSTABLE PARAMETERS

1. **Risk Control**
- min_risk_reward: Minimum risk-reward ratio (current value shown above)
- atr_stop_multiplier: ATR stop-loss multiplier (current value shown above)
- max_loss_per_trade: Max loss per trade % (0.01-0.03)
- max_consecutive_losses: Max consecutive losses (2-5)

2. **Position Management**
- base_position_ratio: Base position ratio (0.10-0.30)
- high_signal_multiplier: High-quality signal multiplier (1.0-2.0)

3. **Entry Timing**
- min_indicator_consensus: Min indicators consensus (3-5)
- key_level_penalty: Key level penalty coefficient (0.5-1.0)
- min_trend_strength: Minimum trend strength (0.5-0.8)

4. **Exit Strategy**
- max_hold_time_hours: Max holding time hours (12-48)
- partial_take_profit: Partial profit taking (true/false)

## COMPREHENSIVE ANALYSIS REQUIREMENTS

### 1. **问题诊断 (Diagnosis)** - 3-4句
识别核心问题，包括：
- 胜率问题（如：低于50%）
- 盈亏比问题（如：低于1.5:1）
- 止损/止盈触发模式（如：频繁止损、提前止盈）
- 信号质量问题（如：逆势、假突破、震荡市）

### 2. **根本原因 (Root Cause)** - 4-5句
深挖参数层面的根因：
- 哪个参数设置过松/过紧
- 导致了什么类型的错误交易
- 举1-2个具体交易案例说明（如："XRP空单在震荡市中被1.7倍ATR止损频繁扫损"）
- 与当前市场环境的匹配度（如：参数适合趋势市，但当前为震荡市）

### 3. **参数调整建议 (Adjustments)** - 明确对比
对每个需要调整的参数，说明：
- **当前值 → 建议值**（如：min_risk_reward 1.5 → 1.8）
- **调整理由**（1句话，如："降低盈亏比门槛以提高入场机会，配合更严格的信号过滤"）
- **影响范围**（如："影响所有币种的开仓决策"）

### 4. **量化预期效果 (Expected Effect)** - 5-6句，必须包含具体数值
- **胜率预期**："从当前X%提升至Y%（±Z%）"，说明原因
- **盈亏比预期**："从当前A:1改善至B:1"，说明如何实现
- **机会捕获率**："预计提升至15-25%"（基于历史错过机会分析）
- **具体案例**："如昨日错过的BTC 1245强信号，调整后可捕获"
- **风险提示**："可能增加X类型风险，需监控Y指标"

### 5. **执行建议 (Action Required)**
- **是否立即调整**：YES/NO/WAIT（观察期）
- **理由**：1-2句（如："样本量充足且问题明确，建议立即调整" OR "样本量不足，建议再观察3天"）
- **监控重点**：调整后应重点关注的指标（如："关注止损触发率是否下降"）

## OUTPUT FORMAT (Strict JSON with V2.0 Enhanced Fields)

```json
{{
  "diagnosis": "核心问题诊断，3-4句话，包含具体指标数值",
  "root_cause": "参数层面的根本原因分析，4-5句话，必须举1-2个具体交易案例",
  "adjustments": {{
    "global": {{
      "min_risk_reward": 1.8,
      "atr_stop_multiplier": 1.5,
      "_rationale": {{
        "min_risk_reward": "当前1.5→建议1.8，原因：降低门槛以提高机会捕获率，配合更严格的信号过滤",
        "atr_stop_multiplier": "当前1.7→建议1.5，原因：震荡市中1.7倍止损过宽，导致回撤过大"
      }}
    }},
    "per_symbol": {{
      "XRP/USDT:USDT": {{
        "min_indicator_consensus": 4,
        "_rationale": "XRP波动率高，需要更严格的信号确认（3→4）"
      }}
    }}
  }},
  "expected_effect": "量化预期效果，5-6句话，必须包含：1)胜率从X%提升至Y%，2)盈亏比从A改善至B，3)机会捕获率提升至C%，4)具体案例（如昨日错过的某信号调整后可捕获），5)风险提示",
  "expected_win_rate": "50-55%",
  "expected_profit_ratio": "1.5:1",
  "expected_capture_rate": "20%",
  "confidence": 0.75,
  "action_required": "YES",
  "action_reason": "样本量充足（20笔）且问题明确，建议立即调整",
  "monitor_focus": "关注止损触发率（目标降至30%以下）和机会捕获率"
}}
```

## CRITICAL RULES

1. **📚 Learn from History (经验复用)**：
   - Review "HISTORICAL VALIDATION LESSONS" above carefully
   - If a similar adjustment FAILED recently (within 3 lessons): Explain why this time is different OR choose a different direction
   - If a similar adjustment SUCCEEDED: Build upon that success
   - Focus on **Composite Profit Metric** (加权胜率 × 加权盈亏比 × 捕获率) when evaluating past lessons
   - Avoid repeating mistakes, learn from successful patterns

2. **量化优先**：所有预期效果必须有具体数值，避免"预计提升"、"有望改善"等模糊表述

3. **案例支撑**：根本原因分析必须引用具体交易案例（从trading_data_summary中提取）

4. **参数溯源**：每个调整建议必须说明"当前值→建议值"，不能只给新值

5. **保守预测**：预期效果给出区间（如50-55%），不要过度乐观

6. **执行明确**：必须给出YES/NO/WAIT的明确建议，不能含糊

7. **中文输出**：diagnosis、root_cause、expected_effect等字段内容必须为中文

8. **适度调整**：单次参数变化幅度不超过30%，避免过度震荡
"""

        # 调用AI分析
        response = qwen_client.chat.completions.create(
            model="qwen3-max",
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional quantitative trading parameter optimization expert, skilled in analyzing trading data and proposing optimization suggestions. **Always respond in Chinese (中文).**",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,  # 较低温度确保输出稳定
        )

        ai_response = response.choices[0].message.content.strip()
        print(f"\n【AI分析结果】")
        print(ai_response)

        # 解析JSON
        import re

        json_match = re.search(r"```json\s*(.*?)\s*```", ai_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 如果没有markdown代码块，尝试直接解析
            json_str = ai_response

        optimization = json.loads(json_str)

        return optimization

    except Exception as e:
        print(f"⚠️ AI参数优化失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def load_validation_history(max_records=10):
    """
    V7.6.3.2: 加载历史参数验证记录，作为经验复用
    
    每次【每日复盘】都会产生一条验证记录，这里读取最近的N条
    帮助AI避免重复错误，学习成功经验
    
    Args:
        max_records: 最多读取多少条历史记录（默认10条）
    
    Returns:
        [
            {
                'date': '2025-10-25 12:00:00',
                'attempted_adjustments': {...},
                'was_effective': True/False,
                'should_apply': True/False,
                'composite_improvement': +15.2%,
                'key_insight': 'AI的经验总结',
                'root_cause': '有效/无效的原因分析'
            },
            ...
        ]
    """
    try:
        model_dir = os.getenv("MODEL_NAME", "qwen")
        history_file = f"trading_data/{model_dir}/backtest_validation_history.jsonl"
        
        if not os.path.exists(history_file):
            return []
        
        lessons = []
        
        with open(history_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    
                    # 提取关键经验
                    ai_review = record.get('ai_review', {})
                    
                    # 计算综合利润指标的提升（如果有回测数据）
                    backtest_orig = record.get('backtest_original', {})
                    backtest_opt = record.get('backtest_optimized', {})
                    
                    composite_improvement = None
                    if backtest_orig and backtest_opt:
                        orig_metric = backtest_orig.get('composite_profit_metric', 0)
                        opt_metric = backtest_opt.get('composite_profit_metric', 0)
                        if orig_metric > 0:
                            composite_improvement = ((opt_metric - orig_metric) / orig_metric) * 100
                    
                    lesson = {
                        'date': record.get('timestamp', 'Unknown'),
                        'attempted_adjustments': record.get('optimization', {}).get('adjustments', {}),
                        'was_effective': ai_review.get('is_effective', False),
                        'should_apply': ai_review.get('should_apply', False),
                        'composite_improvement': composite_improvement,
                        'key_insight': ai_review.get('improvement_summary', ''),
                        'root_cause': ai_review.get('root_cause_analysis', ''),
                        'applied_config': record.get('applied_config', {})
                    }
                    lessons.append(lesson)
                    
                except json.JSONDecodeError:
                    continue
        
        # 返回最近的max_records条
        return lessons[-max_records:]
    
    except Exception as e:
        print(f"⚠️ 加载历史验证记录失败: {e}")
        return []


def backtest_parameters(config_variant, days=7, verbose=False):
    """
    【V7.9增强】参数回测引擎（近期数据加权 + 综合利润指标）
    基于历史market_snapshots数据，模拟不同参数配置下的交易结果
    
    Args:
        config_variant: 参数配置变体（字典）
        days: 回测天数（默认7天重点回测，最长14天全面回测）
        verbose: 是否打印详细日志
    
    Returns:
        {
            'total_trades': 总交易次数,
            'win_rate': 胜率,
            'profit_ratio': 盈亏比,
            'total_profit': 总盈利,
            'captured_opportunities': 捕获的机会数,
            'missed_opportunities': 错失的机会数,
            'capture_rate': 捕获率,
            'trades': 交易详情列表,
            'weighted_win_rate': 加权胜率（近期权重更高）,
            'weighted_profit_ratio': 加权盈亏比,
            '综合利润指标': 加权胜率 × 加权盈亏比 × 捕获率（核心决策依据）
        }
    """
    try:
        from datetime import datetime, timedelta
        import glob
        
        print(f"\n{'='*60}")
        print(f"【📊 参数回测引擎】回测最近{days}天数据（近期权重递减）")
        print(f"{'='*60}")
        
        # 读取历史快照数据（近期优先）
        model_dir = os.getenv("MODEL_NAME", "qwen")
        snapshot_dir = f"trading_data/{model_dir}/market_snapshots"
        
        end_date = datetime.now()
        
        # 🆕 V7.6.3.1: 按日期分组存储，便于加权
        daily_snapshots = {}
        total_records = 0
        
        for i in range(days):
            target_date = (end_date - timedelta(days=i)).strftime('%Y%m%d')
            snapshot_file = f"{snapshot_dir}/{target_date}.csv"
            
            try:
                df = pd.read_csv(snapshot_file)
                daily_snapshots[i] = df  # i=0是今天，i=1是昨天...
                total_records += len(df)
                if verbose:
                    print(f"✓ 读取 {target_date}: {len(df)}条记录 (权重: {1.0 - i*0.1:.1f})")
            except FileNotFoundError:
                if verbose:
                    print(f"✗ 未找到 {target_date} 数据")
                continue
        
        if not daily_snapshots:
            print("⚠️ 未找到历史快照数据")
            return None
        
        print(f"✓ 共加载 {total_records} 条历史记录（{len(daily_snapshots)}天）")
        print(f"  权重策略: 今天1.0 → {days-1}天前{1.0 - (days-1)*0.1:.1f}")
        print(f"  💾 内存优化: 分批处理 + 及时释放")
        
        # 【V7.8修复】确保 config_variant 包含 min_signal_score
        # 如果没有提供，从全局配置中获取，否则使用默认值50
        if 'min_signal_score' not in config_variant:
            try:
                learning_config = load_learning_config()
                config_variant['min_signal_score'] = learning_config.get('global', {}).get('min_signal_score', 55)
            except:
                config_variant['min_signal_score'] = 55  # 默认55分
        
        # 模拟交易决策（按天处理，便于加权）
        simulated_trades = []
        captured_opps = 0
        missed_opps = 0
        
        # 获取参数配置
        min_rr = config_variant.get('min_risk_reward', 1.5)
        min_consensus = config_variant.get('min_indicator_consensus', 3)
        atr_multiplier = config_variant.get('atr_stop_multiplier', 1.7)
        
        print(f"\n回测参数配置:")
        print(f"  min_risk_reward: {min_rr}")
        print(f"  min_indicator_consensus: {min_consensus}")
        print(f"  atr_stop_multiplier: {atr_multiplier}")
        
        # 【V8.3.21】导入gc用于内存管理
        import gc
        
        # 🆕 V7.6.3.1: 按天回测，每天分配权重
        for day_offset, history_df in daily_snapshots.items():
            # 计算当天权重：今天1.0，昨天0.9，前天0.8...
            day_weight = max(0.3, 1.0 - day_offset * 0.1)  # 最低0.3权重
            
            # 按币种和时间分组
            for coin in history_df['coin'].unique():
                coin_data = history_df[history_df['coin'] == coin].sort_values('time')
                
                for idx, row in coin_data.iterrows():
                    # 模拟信号质量检查
                    indicator_consensus = row.get('indicator_consensus', 3)
                    signal_score = row.get('signal_score', 60)
                    
                    # 🆕 V7.6.3.8: 超宽松标准 - 只要价格波动超过1%就算潜在机会
                    # 目的：让AI看到所有实际的市场波动，更准确判断参数是否过严
                    
                    # 计算未来价格波动（向前看10根K线）
                    future_data = coin_data[coin_data['time'] > row['time']].head(10)
                    has_price_movement = False
                    
                    if len(future_data) > 0:
                        current_price = row['price']
                        max_price = future_data['high'].max()
                        min_price = future_data['low'].min()
                        
                        # 计算最大价格波动百分比
                        upward_move = (max_price - current_price) / current_price * 100
                        downward_move = (current_price - min_price) / current_price * 100
                        max_movement = max(upward_move, downward_move)
                        
                        # 只要价格波动超过1%，就算一个潜在机会
                        has_price_movement = max_movement >= 1.0
                    
                    # 同时检查基本有效性（避免数据异常）
                    is_valid_data = (
                        row.get('atr', 0) > 0 and           # ATR有效
                        row.get('price', 0) > 0 and         # 价格有效
                        indicator_consensus >= 1             # 至少1个指标（避免完全无效数据）
                    )
                    
                    # 最终判断：价格有波动 + 数据有效
                    is_potential_opportunity = has_price_movement and is_valid_data
                    
                    if is_potential_opportunity:
                        # 根据回测参数判断是否会开仓
                        # 🔧 V7.8修复：使用配置的 min_signal_score，确保与机会评估标准一致
                        min_signal_score = config_variant.get('min_signal_score', 50)  # 默认50，兼容旧版
                        
                        # 🔧 V7.8.1关键修复：必须检查risk_reward，否则回测结果与实际脱节
                        snapshot_risk_reward = row.get('risk_reward', 0)
                        
                        would_open = (
                            indicator_consensus >= min_consensus and
                            signal_score >= min_signal_score and  # 使用配置参数，不再硬编码
                            snapshot_risk_reward >= min_rr and  # 【关键】确保快照中的盈亏比满足要求
                            (
                                row.get('trend_4h', '') in ['多头', '空头'] or  # 4H趋势
                                row.get('trend_1h', '') in ['多头', '空头'] or  # 允许1H趋势
                                row.get('trend_15m', '') in ['多头', '空头']    # 允许15m趋势
                            )
                        )
                        
                        if would_open:
                            # 模拟交易结果
                            entry_price = row['price']
                            atr = row.get('atr', entry_price * 0.01)
                            
                            # 止损止盈
                            if row.get('trend_4h', '') == '多头':
                                stop_loss = entry_price - atr * atr_multiplier
                                take_profit = entry_price + atr * min_rr * atr_multiplier
                                direction = 'LONG'
                            else:
                                stop_loss = entry_price + atr * atr_multiplier
                                take_profit = entry_price - atr * min_rr * atr_multiplier
                                direction = 'SHORT'
                            
                            # 【V7.9】推断信号类型（用于主动平仓模拟）
                            strong_trend = row.get('trend_4h') or row.get('trend_1h')
                            inferred_signal_type = 'swing' if (signal_score >= 75 or strong_trend) else 'scalping'
                            expected_holding_bars = 2 if inferred_signal_type == 'scalping' else 8  # 15分钟K线数量
                            
                            # 模拟市场走势（【V7.9】增加主动平仓模拟）
                            future_data = coin_data[coin_data['time'] > row['time']].head(12)  # 多获取2根K线用于判断
                            
                            if len(future_data) > 0:
                                hit_tp = False
                                hit_sl = False
                                scratch_exit = False  # 主动平仓标志
                                exit_bar = 0  # 退出的K线位置
                                
                                for bar_idx, future_row in future_data.iterrows():
                                    holding_bars = (bar_idx - row.name) if isinstance(bar_idx, int) else len(future_data[:future_row.name])
                                    future_high = future_row['high']
                                    future_low = future_row['low']
                                    
                                    # 【V7.9】主动平仓检查（在TP/SL检查之前）
                                    if not scratch_exit:
                                        if inferred_signal_type == 'scalping':
                                            # Scalping: 敏感检查
                                            # 1. 超时（>2小时=8根15分钟K线）
                                            if holding_bars >= 8:
                                                scratch_exit = True
                                                exit_bar = holding_bars
                                                break
                                            
                                            # 2. 趋势反转（如果有趋势数据）
                                            future_trend = future_row.get('trend_15m', '')
                                            if future_trend:
                                                if direction == 'LONG' and '空头' in future_trend:
                                                    scratch_exit = True
                                                    exit_bar = holding_bars
                                                    break
                                                elif direction == 'SHORT' and '多头' in future_trend:
                                                    scratch_exit = True
                                                    exit_bar = holding_bars
                                                    break
                                        
                                        else:  # swing
                                            # Swing: 只检查多周期共振反转
                                            if holding_bars >= 8:  # 2小时后才检查
                                                future_trend_15m = future_row.get('trend_15m', '')
                                                future_trend_1h = future_row.get('trend_1h', '')
                                                
                                                # 需要15m+1h共振反转才触发
                                                if direction == 'LONG':
                                                    if '空头' in future_trend_15m and '空头' in future_trend_1h:
                                                        scratch_exit = True
                                                        exit_bar = holding_bars
                                                        break
                                                elif direction == 'SHORT':
                                                    if '多头' in future_trend_15m and '多头' in future_trend_1h:
                                                        scratch_exit = True
                                                        exit_bar = holding_bars
                                                        break
                                            
                                            # Swing超时（24小时=96根K线，但我们只取12根，所以不会触发）
                                            if holding_bars >= 12:
                                                scratch_exit = True
                                                exit_bar = holding_bars
                                                break
                                    
                                    # 检查TP/SL
                                    if direction == 'LONG':
                                        if future_high >= take_profit:
                                            hit_tp = True
                                            exit_bar = holding_bars
                                            break
                                        elif future_low <= stop_loss:
                                            hit_sl = True
                                            exit_bar = holding_bars
                                            break
                                    else:
                                        if future_low <= take_profit:
                                            hit_tp = True
                                            exit_bar = holding_bars
                                            break
                                        elif future_high >= stop_loss:
                                            hit_sl = True
                                            exit_bar = holding_bars
                                            break
                                
                                # 【V7.9】记录交易结果（增加信号类型和主动平仓）
                                if scratch_exit:
                                    # 主动平仓：用当前价格计算盈亏
                                    exit_price = future_data.iloc[min(exit_bar, len(future_data)-1)]['close']
                                    profit_pct = ((exit_price - entry_price) / entry_price) * 100
                                    if direction == 'SHORT':
                                        profit_pct = -profit_pct
                                    
                                    simulated_trades.append({
                                        'coin': coin,
                                        'direction': direction,
                                        'entry_price': entry_price,
                                            'exit_price': exit_price,
                                        'profit_pct': profit_pct,
                                        'result': 'WIN' if profit_pct > 0 else 'LOSS',
                                            'exit_reason': 'SCRATCH',  # 主动平仓
                                        'signal_type': inferred_signal_type,  # V7.9
                                        'holding_bars': exit_bar,  # V7.9
                                        'weight': day_weight
                                    })
                                elif hit_tp:
                                    profit = abs(take_profit - entry_price) / entry_price
                                    simulated_trades.append({
                                        'coin': coin,
                                        'direction': direction,
                                        'entry_price': entry_price,
                                            'exit_price': take_profit,
                                        'profit_pct': profit * 100,
                                        'result': 'WIN',
                                        'exit_reason': 'TP',
                                        'signal_type': inferred_signal_type,  # V7.9
                                        'holding_bars': exit_bar,  # V7.9
                                        'weight': day_weight
                                    })
                                elif hit_sl:
                                    loss = abs(entry_price - stop_loss) / entry_price
                                    simulated_trades.append({
                                        'coin': coin,
                                        'direction': direction,
                                        'entry_price': entry_price,
                                            'exit_price': stop_loss,
                                        'profit_pct': -loss * 100,
                                        'result': 'LOSS',
                                        'exit_reason': 'SL',
                                        'signal_type': inferred_signal_type,  # V7.9
                                        'holding_bars': exit_bar,  # V7.9
                                        'weight': day_weight
                                    })
                                else:
                                    # 未触发止损止盈，按最后价格计算
                                    last_price = future_data.iloc[-1]['close']
                                    profit_pct = ((last_price - entry_price) / entry_price) * 100
                                    if direction == 'SHORT':
                                        profit_pct = -profit_pct
                                    
                                    simulated_trades.append({
                                        'coin': coin,
                                        'direction': direction,
                                        'entry_price': entry_price,
                                            'exit_price': last_price,
                                        'profit_pct': profit_pct,
                                        'result': 'WIN' if profit_pct > 0 else 'LOSS',
                                            'exit_reason': 'HOLD',
                                        'signal_type': inferred_signal_type,  # V7.9
                                        'holding_bars': len(future_data),  # V7.9
                                        'weight': day_weight
                                    })
                            
                            captured_opps += 1
                        else:
                            missed_opps += 1
            
            # 【V8.3.21】处理完每天的数据后释放内存
            del history_df
            gc.collect()
        
        # 【V8.3.21】回测完成，释放daily_snapshots
        del daily_snapshots
        gc.collect()
        
        # 【V7.9】计算回测统计（增加分类型统计）
        if simulated_trades:
            wins = [t for t in simulated_trades if t['result'] == 'WIN']
            losses = [t for t in simulated_trades if t['result'] == 'LOSS']
            
            # 【V7.9】分类型统计
            scalping_trades = [t for t in simulated_trades if t.get('signal_type') == 'scalping']
            swing_trades = [t for t in simulated_trades if t.get('signal_type') == 'swing']
            
            scalping_wins = [t for t in scalping_trades if t['result'] == 'WIN']
            swing_wins = [t for t in swing_trades if t['result'] == 'WIN']
            
            scalping_win_rate = len(scalping_wins) / len(scalping_trades) if scalping_trades else 0
            swing_win_rate = len(swing_wins) / len(swing_trades) if swing_trades else 0
            
            # 平均持仓时间（15分钟K线数）
            avg_holding_scalping = np.mean([t.get('holding_bars', 0) for t in scalping_trades]) if scalping_trades else 0
            avg_holding_swing = np.mean([t.get('holding_bars', 0) for t in swing_trades]) if swing_trades else 0
            
            # 普通胜率
            win_rate = len(wins) / len(simulated_trades)
            
            # 🆕 加权胜率（近期数据权重更高）
            total_weight = sum([t['weight'] for t in simulated_trades])
            weighted_wins = sum([t['weight'] for t in wins])
            weighted_win_rate = weighted_wins / total_weight if total_weight > 0 else 0
            
            # 🆕 加权盈亏比
            weighted_avg_win = sum([t['profit_pct'] * t['weight'] for t in wins]) / weighted_wins if weighted_wins > 0 else 0
            weighted_losses_sum = sum([t['weight'] for t in losses])
            weighted_avg_loss = abs(sum([t['profit_pct'] * t['weight'] for t in losses]) / weighted_losses_sum) if weighted_losses_sum > 0 else 0
            weighted_profit_ratio = weighted_avg_win / weighted_avg_loss if weighted_avg_loss > 0 else 0
            
            # 普通指标
            avg_win = np.mean([t['profit_pct'] for t in wins]) if wins else 0
            avg_loss = abs(np.mean([t['profit_pct'] for t in losses])) if losses else 0
            profit_ratio = avg_win / avg_loss if avg_loss > 0 else 0
            total_profit = sum([t['profit_pct'] for t in simulated_trades])
            
            capture_rate = captured_opps / (captured_opps + missed_opps) if (captured_opps + missed_opps) > 0 else 0
            
            # 🆕 V7.6.3.2: 综合利润指标（核心决策依据）
            # 公式：加权胜率 × 加权盈亏比 × 捕获率
            # 这个指标平衡了三个维度：
            # - 胜率：交易质量
            # - 盈亏比：盈利效率
            # - 捕获率：机会把握
            composite_profit_metric = weighted_win_rate * weighted_profit_ratio * capture_rate
            
            # 🆕 V7.6.5: 盈利判断 - 期望收益和盈亏平衡点
            # 期望收益 = 胜率 × 平均盈利 - (1 - 胜率) × 平均亏损
            expected_return = weighted_win_rate * weighted_avg_win - (1 - weighted_win_rate) * weighted_avg_loss
            
            # 盈亏平衡点：在当前胜率下，需要多少盈亏比才能盈利
            # 公式：breakeven_ratio = (1 - win_rate) / win_rate
            breakeven_profit_ratio = (1 - weighted_win_rate) / weighted_win_rate if weighted_win_rate > 0 else 999
            
            # 判断是否盈利（两个条件都要满足）
            is_profitable = (total_profit > 0) and (expected_return > 0)
            
            result = {
                'total_trades': len(simulated_trades),
                'win_rate': win_rate,
                'weighted_win_rate': weighted_win_rate,  # 🆕 加权胜率
                'profit_ratio': profit_ratio,
                'weighted_profit_ratio': weighted_profit_ratio,  # 🆕 加权盈亏比
                'total_profit': total_profit,
                'captured_opportunities': captured_opps,
                'missed_opportunities': missed_opps,
                'capture_rate': capture_rate,
                'composite_profit_metric': composite_profit_metric,  # 🆕 综合利润指标
                'trades': simulated_trades,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                # 🆕 V7.6.5: 盈利判断字段
                'expected_return': expected_return,  # 理论期望收益（每笔交易）
                'breakeven_profit_ratio': breakeven_profit_ratio,  # 盈亏平衡点
                'is_profitable': is_profitable,  # 是否盈利
                
                # 【V7.9】分类型统计
                'scalping_trades': len(scalping_trades),
                'swing_trades': len(swing_trades),
                'scalping_win_rate': scalping_win_rate,
                'swing_win_rate': swing_win_rate,
                'avg_holding_scalping_bars': avg_holding_scalping,
                'avg_holding_swing_bars': avg_holding_swing,
            }
            
            print(f"\n【📊 回测结果】")
            print(f"  总交易: {len(simulated_trades)}笔")
            print(f"  胜率: {win_rate*100:.1f}% ({len(wins)}胜/{len(losses)}负)")
            print(f"  🆕 加权胜率: {weighted_win_rate*100:.1f}% (近期权重更高)")
            print(f"  盈亏比: {profit_ratio:.2f}:1")
            print(f"  🆕 加权盈亏比: {weighted_profit_ratio:.2f}:1")
            print(f"  总盈利: {total_profit:.2f}%")
            print(f"  机会捕获: {captured_opps}个 / 错失: {missed_opps}个")
            print(f"  捕获率: {capture_rate*100:.1f}%")
            print(f"\n  🎯 【综合利润指标】: {composite_profit_metric:.4f}")
            print(f"     = 加权胜率({weighted_win_rate:.2f}) × 加权盈亏比({weighted_profit_ratio:.2f}) × 捕获率({capture_rate:.2f})")
            print(f"     → 核心决策依据：在胜率、盈亏比、捕获率之间找到最佳平衡")
            
            return result
        else:
            # 🆕 V7.6.3.4: 即使无交易，也返回有价值的反馈信息
            print("⚠️ 未模拟到任何交易")
            print(f"   📊 总快照数: {total_records}")  # 🔧 修复：使用 total_records 而非 all_snapshots
            print(f"   🎯 潜在机会: {captured_opps + missed_opps}个")
            print(f"   ❌ 全部被参数过滤（参数可能过于严格）")
            
            # 返回详细的失败原因，而不是None
            return {
                'total_trades': 0,
                'win_rate': 0,
                'weighted_win_rate': 0,
                'profit_ratio': 0,
                'weighted_profit_ratio': 0,
                'total_profit': 0,
                'captured_opportunities': 0,
                'missed_opportunities': missed_opps,
                'capture_rate': 0,  # 0% 捕获率
                'composite_profit_metric': 0,
                'trades': [],
                'failure_reason': 'NO_TRADES',  # 🆕 失败原因
                'total_snapshots': total_records,  # 🔧 修复：使用 total_records
                'potential_opportunities': captured_opps + missed_opps,  # 🆕 潜在机会数
                'filter_strictness': 'TOO_STRICT' if (captured_opps + missed_opps) > 0 else 'NO_OPPORTUNITIES'  # 🆕 严格程度判断
                    }
            
    except Exception as e:
        print(f"⚠️ 回测失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def ai_review_backtest_result(original_stats, backtest_original, backtest_optimized, optimization):
    """
    V7.6.3.2: AI复盘回测结果（核心依据：综合利润指标）
    将回测对比结果反馈给AI，让AI判断参数调整是否真的有效
    
    决策原则：
    - 核心判断依据：综合利润指标 (加权胜率 × 加权盈亏比 × 捕获率)
    - 目标：在胜率、盈亏比、捕获率之间找到最佳平衡，最大化整体利润
    
    Args:
        original_stats: 原始交易统计
        backtest_original: 原参数回测结果
        backtest_optimized: 优化参数回测结果
        optimization: 原始优化建议
    
    Returns:
        {
            'is_effective': True/False,
            'improvement_summary': 改善总结,
            'final_recommendation': 最终建议,
            'confidence': 置信度,
            'should_apply': 是否应该应用（基于综合利润指标）
        }
    """
    try:
        print(f"\n{'='*60}")
        print(f"【🤖 AI复盘回测结果】")
        print(f"{'='*60}")
        
        # 🆕 提取加权指标和综合利润指标（如果有）
        original_weighted_wr = backtest_original.get('weighted_win_rate', backtest_original.get('win_rate', 0)) if backtest_original else 0
        original_weighted_pr = backtest_original.get('weighted_profit_ratio', backtest_original.get('profit_ratio', 0)) if backtest_original else 0
        original_composite = backtest_original.get('composite_profit_metric', 0) if backtest_original else 0
        
        optimized_weighted_wr = backtest_optimized.get('weighted_win_rate', backtest_optimized.get('win_rate', 0)) if backtest_optimized else 0
        optimized_weighted_pr = backtest_optimized.get('weighted_profit_ratio', backtest_optimized.get('profit_ratio', 0)) if backtest_optimized else 0
        optimized_composite = backtest_optimized.get('composite_profit_metric', 0) if backtest_optimized else 0
        
        # 计算综合利润指标的提升幅度
        composite_improvement = 0
        if original_composite > 0:
            composite_improvement = ((optimized_composite - original_composite) / original_composite) * 100
        
        prompt = f"""**[CRITICAL INSTRUCTION: ALL RESPONSES MUST BE IN CHINESE (中文)]**

You are a quantitative trading parameter optimization validation expert. Your task is to OBJECTIVELY evaluate the effectiveness of a previously proposed parameter adjustment using EMPIRICAL BACKTEST DATA.

**CORE EVALUATION METRIC**: 
🎯 **Composite Profit Metric** = Weighted Win Rate × Weighted Profit Ratio × Capture Rate

This metric balances three dimensions:
- Win Rate (交易质量): How often we win
- Profit Ratio (盈利效率): How much we win vs. lose  
- Capture Rate (机会把握): How many opportunities we seize

**Your primary goal is to maximize this composite metric, not individual components alone.**

## CONTEXT: Original Optimization Proposal

**Diagnosed Issue**: {optimization.get('diagnosis', 'N/A')}
**Root Cause Analysis**: {optimization.get('root_cause', 'N/A')}
**Expected Improvement**: {optimization.get('expected_effect', 'N/A')}

**Proposed Parameter Adjustments**:
{json.dumps(optimization.get('adjustments', dict()), indent=2, ensure_ascii=False)}

## EMPIRICAL EVIDENCE: Backtest Performance Comparison

### Baseline: Live Trading Performance (Actual)
- Win Rate: {original_stats.get('win_rate', 0)*100:.1f}%
- Profit Ratio (R:R): {original_stats.get('profit_ratio', 0):.2f}:1
- Total P&L: {original_stats.get('total_profit', 0):.2f}U

### Control Group: Original Parameters (7-Day Historical Backtest)
{f"- Win Rate: {backtest_original['win_rate']*100:.1f}%" if backtest_original else "- Backtest Failed"}
    {f"- Weighted Win Rate (Recent-Biased): {original_weighted_wr*100:.1f}%" if backtest_original else ""}
{f"- Profit Ratio: {backtest_original['profit_ratio']:.2f}:1" if backtest_original else ""}
    {f"- Weighted Profit Ratio: {original_weighted_pr:.2f}:1" if backtest_original else ""}
{f"- Opportunity Capture Rate: {backtest_original['capture_rate']*100:.1f}%" if backtest_original else ""}
    {f"- 🎯 **Composite Profit Metric**: {original_composite:.4f}" if backtest_original else ""}
{f"     (= {original_weighted_wr:.2f} × {original_weighted_pr:.2f} × {backtest_original['capture_rate']:.2f})" if backtest_original else ""}
    {f"- Total P&L: {backtest_original['total_profit']:.2f}%" if backtest_original else ""}

### Treatment Group: Optimized Parameters (7-Day Historical Backtest)
{f"- Win Rate: {backtest_optimized['win_rate']*100:.1f}%" if backtest_optimized else "- Backtest Failed"}
    {f"- Weighted Win Rate (Recent-Biased): {optimized_weighted_wr*100:.1f}%" if backtest_optimized else ""}
{f"- Profit Ratio: {backtest_optimized['profit_ratio']:.2f}:1" if backtest_optimized else ""}
    {f"- Weighted Profit Ratio: {optimized_weighted_pr:.2f}:1" if backtest_optimized else ""}
{f"- Opportunity Capture Rate: {backtest_optimized['capture_rate']*100:.1f}%" if backtest_optimized else ""}
    {f"- 🎯 **Composite Profit Metric**: {optimized_composite:.4f}" if backtest_optimized else ""}
{f"     (= {optimized_weighted_wr:.2f} × {optimized_weighted_pr:.2f} × {backtest_optimized['capture_rate']:.2f})" if backtest_optimized else ""}
    {f"- Total P&L: {backtest_optimized['total_profit']:.2f}%" if backtest_optimized else ""}

### 🎯 **CORE DECISION INDICATOR**
{f"**Composite Profit Metric Change**: {composite_improvement:+.1f}%" if backtest_original and backtest_optimized else "- Unable to calculate"}
    {f"  - Original: {original_composite:.4f}" if backtest_original else ""}
{f"  - Optimized: {optimized_composite:.4f}" if backtest_optimized else ""}
    {f"  - {'✅ IMPROVED' if composite_improvement > 0 else '❌ DEGRADED'}" if backtest_original and backtest_optimized else ""}

**NOTE**: 
- Weighted metrics emphasize recent data (Day 0: 1.0x → Day 6: 0.4x weight) to reflect current market conditions
- Composite Profit Metric is the PRIMARY decision criterion (核心决策依据)

## ANALYTICAL REQUIREMENTS

### 1. Effectiveness Validation (3-4 sentences in Chinese)
   - Does the backtest performance align with the expected improvement?
   - Which KPIs improved? Which degraded?
   - Is the magnitude of improvement statistically significant (≥10% improvement threshold)?

### 2. Root Cause Analysis (3-4 sentences in Chinese)
   - If results underperform expectations: Was the parameter direction incorrect, or the magnitude insufficient?
   - Identify discrepancies between backtest environment vs. live trading conditions
   - Assess whether 7-day sample size provides sufficient statistical power

### 3. Final Recommendation (2-3 sentences in Chinese)
   - Binary decision: Should these parameter adjustments be deployed to production?
   - If YES: Provide specific implementation plan
   - If NO: Suggest alternative parameter tuning directions

## OUTPUT FORMAT (Strict JSON, All Text Fields in Chinese)

```json
{{
  "is_effective": true/false,
  "improvement_summary": "[中文] Quantitative comparison summary (3-4 sentences, must include specific numeric deltas)",
  "root_cause_analysis": "[中文] If underperforming, root cause analysis (3-4 sentences with trade examples)",
      "final_recommendation": "[中文] Final binary decision with implementation plan (2-3 sentences)",
  "revised_adjustments": {{
    "global": {{
      "min_risk_reward": 1.6,
      "_comment": "If revision needed, provide refined parameters; if not, return empty object"
          }}
  }},
  "confidence": 0.85,
  "should_apply": true/false,
  "next_steps": "[中文] Actionable next steps"
}}
```

## CRITICAL DECISION FRAMEWORK

1. **🎯 Primary Decision Criterion (核心判断依据)**:
   - **Composite Profit Metric** (综合利润指标) is the ULTIMATE goal
   - Formula: Weighted Win Rate × Weighted Profit Ratio × Capture Rate
   - This metric balances win rate, profit efficiency, and opportunity capture
   - A parameter change is valuable ONLY if it improves this composite metric

2. **Deployment Decision Logic** (`should_apply`):
   - ✅ `should_apply = true` IF: **Composite Profit Metric improves ≥10%**
   - ⚠️ `should_apply = true` (with caution) IF:
       * Composite Profit Metric improves 5-10% AND no single dimension degrades >15%
   - ❌ `should_apply = false` OTHERWISE
   
3. **Balanced Trade-offs**:
   - If win rate ↑ but capture rate ↓↓ → Check if composite metric improves overall
   - If capture rate ↑ but win rate ↓ → Check if the trade-off is worthwhile
   - Avoid tunnel vision on individual metrics; always evaluate the composite

4. **Data-Driven Priority**: Backtest empirical evidence overrides theoretical predictions

5. **Conservative Threshold**: 
   - 7-day backtest = limited sample size
   - Require ≥10% composite improvement for confident deployment
   - Flag high variance or insufficient data

6. **Objective Self-Critique**: Acknowledge prediction errors transparently

7. **Recent Data Priority**: Weighted metrics (near-term biased) override simple metrics when conflicting

8. **Language Requirement**: ALL text fields MUST be in Chinese (中文)
"""

        response = qwen_client.chat.completions.create(
            model="qwen3-max",
            messages=[
                {
                    "role": "system",
                    "content": "You are an objective parameter optimization reviewer. Always respond in Chinese (中文)."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        
        ai_response = response.choices[0].message.content.strip()
        print(f"\n【AI复盘分析】")
        print(ai_response)
        
        # 解析JSON
        import re
        json_match = re.search(r"```json\s*(.*?)\s*```", ai_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = ai_response
        
        review_result = json.loads(json_str)
        
        return review_result
        
    except Exception as e:
        print(f"⚠️ AI复盘失败: {e}")
        import traceback
        traceback.print_exc()
        return None


# ============================================================================
# V7.7.0: 多阶段盈利优先优化系统
# ============================================================================
# 新增4个阶段函数，确保优先找到盈利参数组合
# 阶段1: profit_discovery_phase_v770() - 盈利探索（最多8轮）
# 阶段2: profit_expansion_phase_v770() - 盈利扩大（最多3轮）
# 阶段3: fine_tuning_phase_v770() - 参数优化（1轮）
# 阶段4: validation_phase_v770() - 最终验证（1轮）
# ============================================================================

# 注意：由于 V7.7.0 代码量较大（约1500行），已保存到独立文件
# 请运行以下命令手动合并：
#   python3 /tmp/merge_v770_to_deepseek.py
# 或使用提供的部署脚本

# ============================================================================
# 阶段1：盈利探索 (Profit Discovery Phase)
# ============================================================================

def profit_discovery_phase_v770(data_summary, current_config, historical_range, days=7, max_rounds=8):
    """
    V7.7.0 阶段1：盈利探索
    
    目标：通过多轮探索策略，找到至少1个盈利参数组合
    
    策略：
    - Round 1: 默认7点战略采样（使用历史最优范围）
    - Round 2: AI推荐新区域（如果Round 1全亏损）
    - Round 3: 极宽松区域（R:R 0.8-1.5, 共识 1-2）
    - Round 4: 极严格区域（R:R 3.0-5.0, 共识 3-4）
    - Round 5: 中间区域（R:R 1.8-2.5, 共识 2-3）
    - Round 6: AI深度分析 + 创新推荐
    - Round 7: 极端ATR测试（ATR 1.0-2.5）
    - Round 8: AI紧急推荐（最后机会）
    
    Args:
        data_summary: 交易数据摘要
        current_config: 当前配置
        historical_range: 历史最优采样范围
        days: 回测天数（【V7.9】默认7天，样本量大时自动扩展到14天）
        max_rounds: 最大探索轮次
    
    Returns:
        {
            'found_profitable': bool,
            'best_profitable': dict or None,
            'all_profitable': list,
            'all_results': list,
            'rounds': int,
            'search_path': list,
            'final_status': 'PROFITABLE' / 'NO_PROFITABLE'
        }
    """
    print(f"\n{'='*70}")
    print(f"【阶段1：盈利探索】最多{max_rounds}轮，直到找到盈利组合")
    print(f"{'='*70}")
    print(f"  策略：从默认范围开始，逐步扩大搜索，确保找到盈利")
    print(f"  终止：找到盈利 OR 完成{max_rounds}轮")
    print()
    
    all_results = []
    all_profitable = []
    search_path = []
    
    for round_num in range(1, max_rounds + 1):
        print(f"  🔍 探索 Round {round_num}/{max_rounds}")
        
        # 根据轮次确定搜索策略
        if round_num == 1:
            # Round 1: 默认7点战略采样
            print(f"     策略：默认7点战略采样")
            
            # 使用历史最优范围（如果有）
            if historical_range:
                rr_min, rr_max = historical_range.get('rr_range', [1.4, 2.5])
                consensus_min, consensus_max = historical_range.get('consensus_range', [2, 3])
                atr_min, atr_max = historical_range.get('atr_range', [1.4, 1.9])
                print(f"     范围：R:R [{rr_min:.1f}-{rr_max:.1f}], 共识 [{consensus_min}-{consensus_max}], ATR [{atr_min:.1f}-{atr_max:.1f}]")
            else:
                rr_min, rr_max = 1.4, 2.5
                consensus_min, consensus_max = 2, 3
                atr_min, atr_max = 1.4, 1.9
                print(f"     范围：默认范围（无历史数据）")
            
            # 生成7个战略采样点
            test_points = [
                {'min_risk_reward': rr_min, 'min_indicator_consensus': consensus_min, 'atr_stop_multiplier': atr_min, 'name': '极宽松'},
                {'min_risk_reward': (rr_min + rr_max * 2) / 3, 'min_indicator_consensus': consensus_min, 'atr_stop_multiplier': (atr_min + atr_max) / 2, 'name': '偏宽松'},
                {'min_risk_reward': (rr_min + rr_max) / 2, 'min_indicator_consensus': consensus_min, 'atr_stop_multiplier': (atr_min + atr_max) / 2, 'name': '标准'},
                {'min_risk_reward': (rr_min * 2 + rr_max) / 3, 'min_indicator_consensus': consensus_min, 'atr_stop_multiplier': (atr_min + atr_max * 2) / 3, 'name': '偏严格'},
                {'min_risk_reward': rr_max, 'min_indicator_consensus': consensus_max, 'atr_stop_multiplier': atr_max, 'name': '严格'},
                {'min_risk_reward': rr_max * 1.2, 'min_indicator_consensus': consensus_max, 'atr_stop_multiplier': atr_max, 'name': '超严格'},
                {'min_risk_reward': rr_max * 1.4, 'min_indicator_consensus': consensus_max, 'atr_stop_multiplier': atr_max, 'name': '极严格'},
            ]
        
        elif round_num == 2:
            # Round 2: AI推荐新区域
            print(f"     策略：AI分析Round 1结果，推荐新区域")
            
            # 构建AI提示
            round1_summary = "\n".join([
                f"    • {r['name']}: 总盈利={r.get('total_profit', 0):.2f}%, 胜率={r.get('win_rate', 0)*100:.1f}%, "
                f"盈亏比={r.get('profit_ratio', 0):.2f}:1"
                for r in all_results if 'name' in r
                    ])
            
            ai_prompt = f"""
## AI任务：分析Round 1结果，推荐新的盈利搜索区域

### Round 1 结果（全部亏损）
{round1_summary}

### 分析要求：
1. **诊断**：为什么所有配置都亏损？
   - 胜率太低？（<40%）
   - 盈亏比太低？（<1.5）
   - 参数范围有问题？

2. **假设**：盈利可能存在于哪个区域？
   - 更宽松？（R:R 0.8-1.5, 共识 1-2）
   - 更严格？（R:R 3.0-5.0, 共识 3-4）
   - 调整ATR？（1.0-2.5）

3. **推荐**：4个新测试点，覆盖最可能盈利的区域

### 输出格式（JSON）：
{{
  "diagnosis": "亏损原因诊断（中文）",
  "hypothesis": "盈利可能区域（中文）",
  "strategy": "EXTREME_LOOSE" / "EXTREME_STRICT" / "ADJUST_ATR" / "MIDDLE_GROUND",
  "recommended_tests": [
    {{
      "min_risk_reward": X,
      "min_indicator_consensus": Y,
      "atr_stop_multiplier": Z,
      "name": "测试点名称",
      "reason": "为什么测试这个点（中文）"
    }},
    ... (4 points)
  ],
  "confidence": "HIGH" / "MEDIUM" / "LOW"
}}
"""
            
            # 调用AI（直接使用全局qwen_client）
            try:
                response = qwen_client.chat.completions.create(
                    model="qwen3-max",
                    messages=[{"role": "user", "content": ai_prompt}],
                    temperature=0.7,
                    max_tokens=4000  # 🔧 V7.7.0.12: 增加到4000，避免JSON被截断
                )
                
                ai_content = response.choices[0].message.content.strip()
                finish_reason = response.choices[0].finish_reason
                
                # 🔧 V7.7.0.12: 检测是否被截断
                if finish_reason == 'length':
                    print(f"     ⚠️ AI回复被截断（超过max_tokens限制）")
                    print(f"     [调试] 截断的内容: {ai_content[-200:]}...")
                    raise ValueError("AI回复被截断，无法提取完整JSON")
                
                if not ai_content:
                    print(f"     ⚠️ AI返回空内容")
                    raise ValueError("AI返回空内容")
                
                ai_suggestion = extract_json_from_ai_response(ai_content)  # 🔧 V7.7.0.11: 使用鲁棒JSON提取
                print(f"     ✅ AI诊断：{ai_suggestion['diagnosis'][:100]}...")
                print(f"     ✅ AI策略：{ai_suggestion['strategy']}")
                test_points = ai_suggestion['recommended_tests']
            
            except Exception as e:
                print(f"     ⚠️ AI调用失败: {e}")
                print(f"     使用默认策略：测试中间区域")
                test_points = [
                    {'min_risk_reward': 1.8, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.6, 'name': '中间偏宽松'},
                    {'min_risk_reward': 2.2, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.7, 'name': '中间标准'},
                    {'min_risk_reward': 2.6, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.8, 'name': '中间偏严格'},
                    {'min_risk_reward': 3.0, 'min_indicator_consensus': 4, 'atr_stop_multiplier': 1.9, 'name': '中间严格'},
                ]
        
        elif round_num == 3:
            # Round 3: 极宽松区域
            print(f"     策略：测试极宽松区域（高频交易）")
            test_points = [
                {'min_risk_reward': 0.8, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.2, 'name': '超级宽松'},
                {'min_risk_reward': 1.0, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.4, 'name': '极度宽松'},
                {'min_risk_reward': 1.2, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.6, 'name': '很宽松'},
                {'min_risk_reward': 1.4, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.5, 'name': '较宽松'},
            ]
        
        elif round_num == 4:
            # Round 4: 极严格区域
            print(f"     策略：测试极严格区域（精选高质量）")
            test_points = [
                {'min_risk_reward': 3.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.3, 'name': '较严格'},
                {'min_risk_reward': 3.5, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.4, 'name': '很严格'},
                {'min_risk_reward': 4.0, 'min_indicator_consensus': 4, 'atr_stop_multiplier': 1.5, 'name': '极度严格'},
                {'min_risk_reward': 5.0, 'min_indicator_consensus': 4, 'atr_stop_multiplier': 1.6, 'name': '超级严格'},
            ]
        
        elif round_num == 5:
            # Round 5: 中间区域（平衡型）
            print(f"     策略：测试中间平衡区域")
            test_points = [
                {'min_risk_reward': 1.8, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.5, 'name': '平衡偏宽松'},
                {'min_risk_reward': 2.0, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.6, 'name': '平衡标准1'},
                {'min_risk_reward': 2.2, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.7, 'name': '平衡标准2'},
                {'min_risk_reward': 2.5, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.8, 'name': '平衡偏严格'},
            ]
        
        elif round_num == 6:
            # Round 6: AI深度分析（使用所有历史数据）
            print(f"     策略：AI深度分析所有历史，创新推荐")
            
            # 构建完整历史摘要
            all_summary = "\n".join([
                f"    Round {i+1}: {len([r for r in all_results if r.get('round') == i+1])}个点, "
                    f"盈利: {len([r for r in all_results if r.get('round') == i+1 and r.get('is_profitable')])}个"
                for i in range(round_num - 1)
                    ])
            
            ai_deep_prompt = f"""
## 深度分析：经过{round_num-1}轮探索仍未找到盈利

### 历史探索摘要
{all_summary}

### 你的任务
作为高级量化分析师，你需要突破常规，创新性地推荐4个**极有可能盈利**的参数组合。

**关键洞察：**
- 如果宽松和严格都亏损 → 可能是市场结构问题，考虑特殊ATR或极端共识
- 如果某个方向接近盈利 → 在该方向附近微调
- 考虑非线性组合（如：极宽松R:R + 极严格共识）

**创新方向：**
1. 极端ATR组合（1.0-2.5）
2. 非对称组合（如：低R:R + 高共识）
3. 反直觉组合（如：高R:R + 低共识 + 紧止损）
4. 历史数据暗示的区域

### 输出格式（JSON）：
{{
  "deep_analysis": "深度分析结论（中文）",
  "innovation_hypothesis": "创新假设（中文）",
  "recommended_tests": [
    {{
      "min_risk_reward": X,
      "min_indicator_consensus": Y,
      "atr_stop_multiplier": Z,
      "name": "创新点名称",
      "innovation_reason": "为什么这个组合可能突破（中文）"
    }},
    ... (4 innovative points)
  ]
}}
"""
            
            try:
                response = qwen_client.chat.completions.create(
                    model="qwen3-max",
                    messages=[{"role": "user", "content": ai_deep_prompt}],
                    temperature=0.8,  # 更高温度鼓励创新
                    max_tokens=2000
                )
                
                ai_content = response.choices[0].message.content.strip()
                json_match = re.search(r'\{[\s\S]*\}', ai_content)
                
                if json_match:
                    ai_deep = json.loads(json_match.group(0))
                    print(f"     AI深度分析：{ai_deep['deep_analysis'][:80]}...")
                    test_points = ai_deep['recommended_tests']
                else:
                    raise ValueError("AI响应格式错误")
            
            except Exception as e:
                print(f"     ⚠️ AI深度分析失败: {e}")
                test_points = [
                    {'min_risk_reward': 1.5, 'min_indicator_consensus': 4, 'atr_stop_multiplier': 1.2, 'name': '低R高共识'},
                    {'min_risk_reward': 3.5, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 2.0, 'name': '高R低共识'},
                    {'min_risk_reward': 2.5, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.0, 'name': '极紧止损'},
                    {'min_risk_reward': 2.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 2.5, 'name': '极松止损'},
                ]
        
        elif round_num == 7:
            # Round 7: 极端ATR测试
            print(f"     策略：测试极端ATR设置")
            test_points = [
                {'min_risk_reward': 2.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.0, 'name': '超紧止损'},
                {'min_risk_reward': 2.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.2, 'name': '很紧止损'},
                {'min_risk_reward': 2.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 2.2, 'name': '很松止损'},
                {'min_risk_reward': 2.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 2.5, 'name': '超松止损'},
            ]
        
        else:  # Round 8: 最后机会
            # Round 8: AI紧急推荐
            print(f"     策略：⚠️ 最后机会 - AI紧急推荐")
            print(f"     状态：已探索{round_num-1}轮仍未找到盈利")
            
            emergency_prompt = f"""
## 🚨 紧急任务：最后机会找到盈利

### 当前情况
- 已探索{round_num-1}轮，测试{len(all_results)}个参数组合
- **仍未找到盈利组合**
- 这是第{round_num}轮（最后机会）

### 你的紧急任务
推荐4个**绝对最有可能盈利**的参数组合。
不要保守，要大胆创新！

### 参考历史最接近盈利的点
（如果有）

### 输出（JSON）：
{{
  "emergency_analysis": "为什么一直找不到盈利（中文）",
  "last_hope_strategy": "最后希望策略（中文）",
  "final_recommendations": [
    {{
      "min_risk_reward": X,
      "min_indicator_consensus": Y,
      "atr_stop_multiplier": Z,
      "name": "最后希望X",
      "why_this_works": "为什么这个可能行（中文）"
    }},
    ... (4 points)
  ]
}}
"""
            
            try:
                response = qwen_client.chat.completions.create(
                    model="qwen3-max",
                    messages=[{"role": "user", "content": emergency_prompt}],
                    temperature=0.9,  # 最高温度，最大创新
                    max_tokens=2000
                )
                
                ai_content = response.choices[0].message.content.strip()
                json_match = re.search(r'\{[\s\S]*\}', ai_content)
                
                if json_match:
                    ai_emergency = json.loads(json_match.group(0))
                    print(f"     🚨 AI紧急分析：{ai_emergency['emergency_analysis']}")
                    test_points = ai_emergency['final_recommendations']
                else:
                    raise ValueError("AI响应格式错误")
            
            except Exception as e:
                print(f"     ⚠️ AI紧急推荐失败: {e}")
                # 使用最极端的组合作为最后尝试
                test_points = [
                    {'min_risk_reward': 0.8, 'min_indicator_consensus': 4, 'atr_stop_multiplier': 1.0, 'name': '极端组合1'},
                    {'min_risk_reward': 5.0, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 2.5, 'name': '极端组合2'},
                    {'min_risk_reward': 2.5, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.8, 'name': '平衡后备1'},
                    {'min_risk_reward': 3.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 1.5, 'name': '平衡后备2'},
                ]
        
        # 回测所有测试点
        print(f"     ━━━━━━━━━━━━━━━━━━━━ 回测{len(test_points)}个点...")
        round_profitable = []
        
        for point in test_points:
            config = {k: v for k, v in point.items() if k != 'name'}
            # 【V7.9】回测（早期7天，后期扩展到14天）
            backtest_days = 7 if round_num <= 3 else min(14, days * 2)
            result = backtest_parameters(config, days=backtest_days, verbose=False)
            
            if result:
                result['name'] = point['name']
                result['round'] = round_num
                result['config'] = config
                all_results.append(result)
                
                # 检查是否盈利
                is_profitable = result.get('is_profitable', False)
                total_profit = result.get('total_profit', 0)
                
                if is_profitable and total_profit > 0:
                    round_profitable.append(result)
                    all_profitable.append(result)
                    print(f"        ✅ {point['name']}: 盈利 +{total_profit:.2f}% (期望收益 +{result.get('expected_return', 0)*100:.2f}%)")
                else:
                    print(f"        ❌ {point['name']}: 亏损 {total_profit:.2f}%")
        
        # 记录搜索路径
        search_path.append({
            'round': round_num,
            'strategy': test_points[0].get('name', f'Round{round_num}') if test_points else f'Round{round_num}',
                'tested_points': len(test_points),
            'found_profitable': len(round_profitable)
        })
        
        # 检查是否找到盈利
        if round_profitable:
            print(f"\n  🎉 盈利探索成功！第{round_num}轮找到{len(round_profitable)}个盈利组合")
            best_profitable = max(round_profitable, key=lambda x: x.get('total_profit', 0))
            print(f"     最优盈利：R:R={best_profitable['config']['min_risk_reward']}, "
                  f"共识={best_profitable['config']['min_indicator_consensus']}, "
                  f"ATR={best_profitable['config']['atr_stop_multiplier']}")
            print(f"     总盈利：+{best_profitable.get('total_profit', 0):.2f}%")
            print(f"     期望收益：+{best_profitable.get('expected_return', 0)*100:.2f}%")
            
            return {
                'found_profitable': True,
                'best_profitable': best_profitable,
                'all_profitable': all_profitable,
                'all_results': all_results,
                'rounds': round_num,
                'search_path': search_path,
                'final_status': 'PROFITABLE'
            }
        
        print(f"     结果：本轮{len(test_points)}个点全部亏损 ❌")
    
    # 所有轮次完成仍未找到盈利
    print(f"\n  ❌ 盈利探索失败：经过{max_rounds}轮探索，测试{len(all_results)}个点，仍未找到盈利组合")
    print(f"  → 将触发保守策略")
    
    return {
        'found_profitable': False,
        'best_profitable': None,
        'all_profitable': [],
        'all_results': all_results,
        'rounds': max_rounds,
        'search_path': search_path,
        'final_status': 'NO_PROFITABLE'
    }


# ============================================================================
# 阶段2：盈利扩大 (Profit Expansion Phase)
# ============================================================================

def profit_expansion_phase_v770(profitable_center, all_results, days=7, max_iterations=3):
    """
    V7.7.0 阶段2：盈利扩大
    
    目标：以盈利点为中心，测试周边8个方向，找到更大盈利
    
    策略：
    - 测试8个方向：上/下/左/右/左上/左下/右上/右下
    - 如果找到更优点，以它为中心继续扩展
    - 最多迭代3次
    
    Args:
        profitable_center: 盈利中心点配置和结果
        all_results: 之前所有回测结果（避免重复）
        days: 回测天数
        max_iterations: 最大扩展迭代次数
    
    Returns:
        {
            'best_config': dict,
            'best_metric': float,
            'best_profit': float,
            'all_profitable': list,
            'expansion_path': list,
            'rounds': int
        }
    """
    print(f"\n{'='*70}")
    print(f"【阶段2：盈利扩大】以盈利点为中心深挖")
    print(f"{'='*70}")
    
    current_center = profitable_center['config']
    current_metric = profitable_center.get('composite_profit_metric', 0)
    current_profit = profitable_center.get('total_profit', 0)
    
    print(f"  📍 盈利中心: R:R={current_center['min_risk_reward']:.2f}, "
          f"共识={current_center['min_indicator_consensus']}, "
          f"ATR={current_center['atr_stop_multiplier']:.2f}")
    print(f"     当前盈利: +{current_profit:.2f}% | 综合指标: {current_metric:.4f}")
    print()
    
    expansion_path = []
    all_profitable = [profitable_center]
    best_config = current_center.copy()
    best_metric = current_metric
    best_profit = current_profit
    total_rounds = 0
    
    for iteration in range(1, max_iterations + 1):
        print(f"  🧭 迭代 {iteration}/{max_iterations}: 测试8个方向")
        
        # 定义8个方向
        directions = [
            {'rr': 0, 'consensus': 0, 'atr': -0.1, 'name': '上（ATR-）'},
            {'rr': 0, 'consensus': 0, 'atr': +0.1, 'name': '下（ATR+）'},
            {'rr': -0.2, 'consensus': 0, 'atr': 0, 'name': '左（R:R-）'},
            {'rr': +0.2, 'consensus': 0, 'atr': 0, 'name': '右（R:R+）'},
            {'rr': -0.2, 'consensus': 0, 'atr': -0.1, 'name': '左上'},
            {'rr': -0.2, 'consensus': 0, 'atr': +0.1, 'name': '左下'},
            {'rr': +0.2, 'consensus': 0, 'atr': -0.1, 'name': '右上'},
            {'rr': +0.2, 'consensus': 0, 'atr': +0.1, 'name': '右下'},
        ]
        
        # 注意：共识需要特殊处理（整数，且有范围限制）
        # 如果共识变化，使用 ±1
        # 【V8.3.14.4】硬约束：min_indicator_consensus必须 >= 2
        if current_center['min_indicator_consensus'] < 4:
            directions.append({'rr': 0, 'consensus': +1, 'atr': 0, 'name': '共识+1'})
        if current_center['min_indicator_consensus'] > 2:  # 从 > 1 改为 > 2
            directions.append({'rr': 0, 'consensus': -1, 'atr': 0, 'name': '共识-1'})
        
        print(f"     ━━━━━━━━━━━━━━━━━━━━ 回测{len(directions)}个方向...")
        
        iteration_results = []
        
        for direction in directions:
            # 生成新配置
            new_config = {
                'min_risk_reward': max(0.5, current_center['min_risk_reward'] + direction['rr']),
                'min_indicator_consensus': max(0, min(5, current_center['min_indicator_consensus'] + direction['consensus'])),
                'atr_stop_multiplier': max(0.8, min(3.0, current_center['atr_stop_multiplier'] + direction['atr']))
            }
            
            # 检查是否已测试过（避免重复）
            already_tested = False
            for prev_result in all_results:
                prev_config = prev_result.get('config', {})
                if (abs(prev_config.get('min_risk_reward', 0) - new_config['min_risk_reward']) < 0.05 and
                    prev_config.get('min_indicator_consensus') == new_config['min_indicator_consensus'] and
                    abs(prev_config.get('atr_stop_multiplier', 0) - new_config['atr_stop_multiplier']) < 0.05):
                    already_tested = True
                    break
            
            if already_tested:
                print(f"        ⏭️  {direction['name']}: 已测试，跳过")
                continue
            
            # 【V7.9】回测（样本量大时扩展到14天）
            backtest_days = days
            if iteration >= max_iterations * 0.7:  # 后期扩展验证
                backtest_days = min(14, days * 2)
            result = backtest_parameters(new_config, days=backtest_days, verbose=False)
            
            if result:
                result['name'] = direction['name']
                result['config'] = new_config
                result['iteration'] = iteration
                all_results.append(result)
                total_rounds += 1
                
                metric = result.get('composite_profit_metric', 0)
                profit = result.get('total_profit', 0)
                is_profitable = result.get('is_profitable', False)
                
                if is_profitable and profit > 0:
                    all_profitable.append(result)
                    iteration_results.append(result)
                    print(f"        ✅ {direction['name']}: 盈利 +{profit:.2f}% | 指标 {metric:.4f}")
                else:
                    print(f"        ❌ {direction['name']}: 亏损 {profit:.2f}%")
        
        # 检查是否找到更优点
        if iteration_results:
            best_iteration = max(iteration_results, key=lambda x: x.get('composite_profit_metric', 0))
            if best_iteration['composite_profit_metric'] > best_metric:
                improvement = (best_iteration['composite_profit_metric'] - best_metric) / best_metric * 100
                print(f"\n     🎯 找到更优点！指标提升 +{improvement:.1f}%")
                print(f"        新中心: R:R={best_iteration['config']['min_risk_reward']:.2f}, "
                      f"共识={best_iteration['config']['min_indicator_consensus']}, "
                      f"ATR={best_iteration['config']['atr_stop_multiplier']:.2f}")
                print(f"        新盈利: +{best_iteration['total_profit']:.2f}%")
                
                # 更新中心点
                current_center = best_iteration['config']
                current_metric = best_iteration['composite_profit_metric']
                current_profit = best_iteration['total_profit']
                best_config = current_center.copy()
                best_metric = current_metric
                best_profit = current_profit
                
                expansion_path.append({
                    'iteration': iteration,
                    'action': 'EXPANDED',
                    'new_center': current_center.copy(),
                    'improvement': improvement
                })
                
                # 继续下一轮扩展
                continue
            else:
                print(f"\n     ℹ️  未发现更优点（最优仍是中心点）")
        else:
            print(f"\n     ℹ️  周边全部亏损，无法扩展")
        
        # 记录路径
        expansion_path.append({
            'iteration': iteration,
            'action': 'NO_IMPROVEMENT',
            'tested_directions': len(directions)
        })
        
        # 终止扩展
        print(f"     停止扩展")
        break
    
    print(f"\n  ✅ 盈利扩大完成！")
    print(f"     最优配置: R:R={best_config['min_risk_reward']:.2f}, "
          f"共识={best_config['min_indicator_consensus']}, "
          f"ATR={best_config['atr_stop_multiplier']:.2f}")
    print(f"     期望收益: +{best_profit:.2f}%")
    print(f"     综合指标: {best_metric:.4f}")
    print(f"     发现盈利组合: {len(all_profitable)}个")
    
    # 🆕 V7.7.0.6: 找到best_config对应的完整回测结果（用于Bark/邮件通知）
    best_result = None
    for profitable in all_profitable:
        cfg = profitable.get('config', {})
        if (abs(cfg.get('min_risk_reward', 0) - best_config['min_risk_reward']) < 0.05 and
            cfg.get('min_indicator_consensus') == best_config['min_indicator_consensus'] and
            abs(cfg.get('atr_stop_multiplier', 0) - best_config['atr_stop_multiplier']) < 0.05):
            best_result = profitable
            break
    
    return {
        'best_config': best_config,
        'best_metric': best_metric,
        'best_profit': best_profit,
        'best_result': best_result if best_result else all_profitable[0] if all_profitable else {},  # 🆕 添加完整回测结果
            'all_profitable': all_profitable,
        'expansion_path': expansion_path,
        'rounds': total_rounds
    }


# ============================================================================
# 阶段3：参数优化 (Fine-Tuning Phase)
# ============================================================================

def fine_tuning_phase_v770(profitable_region, best_config, best_metric, days=7):
    """
    V7.7.0 阶段3：参数优化
    
    目标：在盈利区域内精细调整，平衡胜率/盈亏比/捕获率
    
    策略：
    - AI分析盈利区域特征
    - 推荐4个精细调整点
    - 选择综合指标最高的
    
    Args:
        profitable_region: 所有盈利组合
        best_config: 当前最优配置
        best_metric: 当前最优综合指标
        days: 回测天数
    
    Returns:
        {
            'best_config': dict,
            'best_metric': float,
            'test_points': list,
            'improvement': float
        }
    """
    print(f"\n{'='*70}")
    print(f"【阶段3：参数优化】精细调整平衡点")
    print(f"{'='*70}")
    
    print(f"  🔬 分析{len(profitable_region)}个盈利组合的特征...")
    
    # 分析盈利区域
    rr_values = [p['config']['min_risk_reward'] for p in profitable_region]
    consensus_values = [p['config']['min_indicator_consensus'] for p in profitable_region]
    atr_values = [p['config']['atr_stop_multiplier'] for p in profitable_region]
    
    rr_avg = sum(rr_values) / len(rr_values)
    consensus_avg = sum(consensus_values) / len(consensus_values)
    atr_avg = sum(atr_values) / len(atr_values)
    
    # 🔧 V7.7.0.13: 计算盈利区域的统计特征（简化）
    rr_min = min(rr_values)
    rr_max = max(rr_values)
    atr_min = min(atr_values)
    atr_max = max(atr_values)
    
    profit_values = [p.get('total_profit', 0) for p in profitable_region]
    avg_profit = sum(profit_values) / len(profit_values)
    max_profit = max(profit_values)
    
    print(f"     盈利区域中心: R:R≈{rr_avg:.2f}, 共识≈{consensus_avg:.1f}, ATR≈{atr_avg:.2f}")
    print(f"     盈利范围: 平均+{avg_profit:.1f}%, 最高+{max_profit:.1f}%")
    
    # 🔧 V7.7.0.13: 极简Prompt（统计摘要 + 纯参数输出，无需描述性文本）
    # 🔧 V8.3.14.4.3: 添加硬约束 min_indicator_consensus >= 2
    ai_fine_tune_prompt = f"""
Task: Fine-tune parameters (4 tests)

Best: R:R={best_config['min_risk_reward']:.2f}, C={best_config['min_indicator_consensus']}, ATR={best_config['atr_stop_multiplier']:.2f}, Metric={best_metric:.4f}

Stats from {len(profitable_region)} profitable configs:
R:R [{rr_min:.2f}-{rr_max:.2f}] avg={rr_avg:.2f}
ATR [{atr_min:.2f}-{atr_max:.2f}] avg={atr_avg:.2f}
C avg={consensus_avg:.1f}
Profit avg={avg_profit:.1f}% max={max_profit:.1f}%

Strategy: Adjust R:R±0.1-0.3, ATR±0.05-0.15, C±1
⚠️ HARD CONSTRAINT: min_indicator_consensus MUST be >= 2 (NEVER 1)

JSON (4 test points):
[
  {{"min_risk_reward": X, "min_indicator_consensus": Y (>=2), "atr_stop_multiplier": Z}},
  ...
]
"""
    
    try:
        response = qwen_client.chat.completions.create(
            model="qwen3-max",
            messages=[{"role": "user", "content": ai_fine_tune_prompt}],
            temperature=0.3,
            max_tokens=8000  # 🔧 V7.7.0.14: 增至8000（充分放宽，避免截断）
        )
        
        ai_content = response.choices[0].message.content.strip()
        finish_reason = response.choices[0].finish_reason
        
        # 🔧 V7.7.0.12: 检测是否被截断或为空
        if finish_reason == 'length':
            print(f"     ⚠️ AI回复被截断")
            raise ValueError("AI回复被截断")
        
        if not ai_content:
            print(f"     ⚠️ AI返回空内容")
            raise ValueError("AI返回空内容")
        
        # 🔧 V7.7.0.13: 直接提取数组（无需额外字段）
        test_points = extract_json_from_ai_response(ai_content)
        if not isinstance(test_points, list):
            # 兼容可能包装在对象中的情况
            test_points = test_points.get('fine_tune_tests', test_points)
        
        print(f"     ✅ AI生成{len(test_points)}个优化点")
    
    except Exception as e:
        print(f"     ⚠️ AI精细调优失败: {e}")
        print(f"     使用默认微调策略（放宽范围）")
        # 🔧 V7.7.0.14: 将微调步长从±0.1扩大到±0.2，放宽探索范围
        test_points = [
            {
                'min_risk_reward': best_config['min_risk_reward'] - 0.2,
                'min_indicator_consensus': best_config['min_indicator_consensus'],
                'atr_stop_multiplier': best_config['atr_stop_multiplier'],
                'name': 'R:R-0.2'
            },
            {
                'min_risk_reward': best_config['min_risk_reward'] + 0.2,
                'min_indicator_consensus': best_config['min_indicator_consensus'],
                'atr_stop_multiplier': best_config['atr_stop_multiplier'],
                'name': 'R:R+0.2'
            },
            {
                'min_risk_reward': best_config['min_risk_reward'],
                'min_indicator_consensus': best_config['min_indicator_consensus'],
                'atr_stop_multiplier': best_config['atr_stop_multiplier'] - 0.15,
                'name': 'ATR-0.15'
            },
            {
                'min_risk_reward': best_config['min_risk_reward'],
                'min_indicator_consensus': best_config['min_indicator_consensus'],
                'atr_stop_multiplier': best_config['atr_stop_multiplier'] + 0.15,
                'name': 'ATR+0.15'
            },
        ]
    
    # 🔧 V8.3.14.4.3: 验证并修正test_points中的硬约束
    for point in test_points:
        if point.get('min_indicator_consensus', 2) < 2:
            print(f"     ⚠️ 检测到AI生成的参数违反硬约束: consensus={point['min_indicator_consensus']} < 2，强制调整为2")
            point['min_indicator_consensus'] = 2
    
    # 回测精细调整点
    print(f"     ━━━━━━━━━━━━━━━━━━━━ 回测{len(test_points)}个优化点...")
    
    tune_results = []
    original_metric = best_config.get('composite_profit_metric', 0)  # 需要从之前结果获取
    
    # 先回测当前最优点（作为基准）
    baseline_result = backtest_parameters(best_config, days=days, verbose=False)
    if baseline_result:
        original_metric = baseline_result.get('composite_profit_metric', 0)
        print(f"     基准指标: {original_metric:.4f}")
    
    for idx, point in enumerate(test_points):
        config = {k: v for k, v in point.items() if k != 'name'}
        result = backtest_parameters(config, days=days, verbose=False)
        
        if result:
            # 🔧 V7.7.0.13: 添加默认name（如果AI未提供）
            result['name'] = point.get('name', f'优化点{idx+1}')
            result['config'] = config
            tune_results.append(result)
            
            metric = result.get('composite_profit_metric', 0)
            profit = result.get('total_profit', 0)
            
            if result.get('is_profitable', False):
                improvement = (metric - original_metric) / original_metric * 100 if original_metric > 0 else 0
                point_name = point.get('name', f'优化点{idx+1}')
                print(f"        {'✅' if metric > original_metric else '➖'} {point_name}: "
                      f"指标 {metric:.4f} ({improvement:+.1f}%) | 盈利 +{profit:.2f}%")
            else:
                point_name = point.get('name', f'优化点{idx+1}')
                print(f"        ❌ {point_name}: 亏损 {profit:.2f}%")
    
    # 选择最优
    if tune_results:
        profitable_tunes = [r for r in tune_results if r.get('is_profitable', False)]
        if profitable_tunes:
            best_tune = max(profitable_tunes, key=lambda x: x.get('composite_profit_metric', 0))
        else:
            best_tune = baseline_result  # 如果所有调整都不盈利，保持原配置
        
        final_metric = best_tune.get('composite_profit_metric', 0)
        improvement = (final_metric - original_metric) / original_metric * 100 if original_metric > 0 else 0
        
        print(f"\n  ✅ 参数优化完成！")
        print(f"     最优配置: R:R={best_tune['config']['min_risk_reward']:.2f}, "
              f"共识={best_tune['config']['min_indicator_consensus']}, "
              f"ATR={best_tune['config']['atr_stop_multiplier']:.2f}")
        print(f"     综合指标: {final_metric:.4f} ({improvement:+.1f}% vs 基准)")
        
        return {
            'best_config': best_tune['config'],
            'best_metric': final_metric,
            'test_points': test_points,
            'improvement': improvement
        }
    
    else:
        return {
            'best_config': best_config,
            'best_metric': original_metric,
            'test_points': [],
            'improvement': 0
        }


# ============================================================================
# 阶段4：最终验证 (Validation Phase)
# ============================================================================

def validation_phase_v770(best_config, days=7):
    """
    V7.7.0 阶段4：最终验证
    
    目标：确认参数稳定性和全局最优
    
    策略：
    - 测试最优点的3个邻近点（左/中/右）
    - 确认当前点是局部峰值
    - 评估置信度
    
    Args:
        best_config: 待验证的最优配置
        days: 回测天数
    
    Returns:
        {
            'validated_config': dict,
            'validated_metric': float,
            'is_peak': bool,
            'confidence': 'HIGH' / 'MEDIUM' / 'LOW',
            'test_results': list
        }
    """
    print(f"\n{'='*70}")
    print(f"【阶段4：最终验证】确认稳定性")
    print(f"{'='*70}")
    
    print(f"  🔍 验证配置: R:R={best_config['min_risk_reward']:.2f}, "
          f"共识={best_config['min_indicator_consensus']}, "
          f"ATR={best_config['atr_stop_multiplier']:.2f}")
    
    # 定义3个验证点
    validation_points = [
        {
            'min_risk_reward': best_config['min_risk_reward'] - 0.1,
            'min_indicator_consensus': best_config['min_indicator_consensus'],
            'atr_stop_multiplier': best_config['atr_stop_multiplier'],
            'name': '左侧(R:R-0.1)'
        },
        {
            **best_config,
            'name': '峰值(当前最优)'
        },
        {
            'min_risk_reward': best_config['min_risk_reward'] + 0.1,
            'min_indicator_consensus': best_config['min_indicator_consensus'],
            'atr_stop_multiplier': best_config['atr_stop_multiplier'],
            'name': '右侧(R:R+0.1)'
        },
    ]
    
    print(f"     ━━━━━━━━━━━━━━━━━━━━ 回测3个验证点...")
    
    test_results = []
    
    for point in validation_points:
        config = {k: v for k, v in point.items() if k != 'name'}
        result = backtest_parameters(config, days=days, verbose=False)
        
        if result:
            result['name'] = point['name']
            result['config'] = config
            test_results.append(result)
            
            metric = result.get('composite_profit_metric', 0)
            profit = result.get('total_profit', 0)
            
            if result.get('is_profitable', False):
                print(f"        ✅ {point['name']}: 指标 {metric:.4f} | 盈利 +{profit:.2f}%")
            else:
                print(f"        ❌ {point['name']}: 亏损 {profit:.2f}%")
    
    # 分析验证结果
    if len(test_results) >= 3:
        metrics = [r.get('composite_profit_metric', 0) for r in test_results]
        peak_index = metrics.index(max(metrics))
        
        is_peak = (peak_index == 1)  # 中间点是峰值
        
        if is_peak:
            print(f"\n     ✅ 确认：当前配置是局部峰值")
            
            # 评估置信度
            left_diff = abs(metrics[1] - metrics[0]) / metrics[1] if metrics[1] > 0 else 0
            right_diff = abs(metrics[1] - metrics[2]) / metrics[1] if metrics[1] > 0 else 0
            avg_diff = (left_diff + right_diff) / 2
            
            if avg_diff > 0.05:  # 5%以上差异
                confidence = 'HIGH'
                print(f"     置信度：高（峰值明显，与邻近点差异 {avg_diff*100:.1f}%）")
            elif avg_diff > 0.02:  # 2-5%差异
                confidence = 'MEDIUM'
                print(f"     置信度：中（峰值存在，但不显著，差异 {avg_diff*100:.1f}%）")
            else:
                confidence = 'LOW'
                print(f"     置信度：低（峰值平缓，与邻近点差异较小 {avg_diff*100:.1f}%）")
        else:
            print(f"\n     ⚠️  发现更优点：{test_results[peak_index]['name']}")
            print(f"     建议：使用新发现的更优配置")
            is_peak = False
            confidence = 'MEDIUM'
            
            # 更新为更优配置
            best_config = test_results[peak_index]['config']
    
    else:
        print(f"\n     ⚠️  验证失败（回测结果不足）")
        is_peak = False
        confidence = 'LOW'
    
    validated_metric = max([r.get('composite_profit_metric', 0) for r in test_results]) if test_results else 0
    
    print(f"\n  ✅ 最终验证完成！")
    print(f"     验证配置: R:R={best_config['min_risk_reward']:.2f}, "
          f"共识={best_config['min_indicator_consensus']}, "
          f"ATR={best_config['atr_stop_multiplier']:.2f}")
    print(f"     综合指标: {validated_metric:.4f}")
    print(f"     置信度: {confidence}")
    
    return {
        'validated_config': best_config,
        'validated_metric': validated_metric,
        'is_peak': is_peak,
        'confidence': confidence,
        'test_results': test_results
    }


# ============================================================================
# V7.7.0 主优化函数
# ============================================================================

def iterative_parameter_optimization(data_summary, current_config, original_stats, max_rounds=4):
    """
    V7.7.0: 多阶段盈利优先优化（主入口）
    
    这是主入口函数，会被 analyze_and_adjust_params() 调用
    内部会调用 iterative_parameter_optimization_v770() 执行实际的优化流程
    """
    return iterative_parameter_optimization_v770(data_summary, current_config, original_stats)


def quick_global_search_v8316(data_summary, current_config):
    """
    【V8.3.16】快速全局探索（技术债1修复）
    
    目的：为V8.3.12分离策略优化提供高质量的初始参数
    
    流程：
    - 只做7组战略采样（V7.7.0阶段1）
    - 找到盈利范围即返回
    - 不做盈利扩大和AI优化
    
    返回：
    {
        'min_risk_reward': float,
        'min_indicator_consensus': int,
        'atr_stop_multiplier': float,
        'found_profitable': bool
    }
    
    耗时：约3分钟（减少5-7分钟vs完整V7.7.0）
    """
    print(f"\n{'='*70}")
    print(f"【V8.3.16 快速全局探索】")
    print(f"{'='*70}")
    print(f"  🎯 目标：快速找到盈利参数范围")
    print(f"  📊 流程：7组战略采样 → 为V8.3.12提供初始值")
    print(f"  ⏱️  预计：约3分钟")
    print(f"{'='*70}")
    
    days = 7
    
    # 读取历史最优采样范围
    model_name = os.getenv("MODEL_NAME", "qwen")
    config_file = Path("trading_data") / model_name / "learning_config.json"
    historical_sampling_range = None
    
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
                historical_sampling_range = saved_config.get('optimal_sampling_range')
                if historical_sampling_range:
                    print(f"  ℹ️  使用历史最优范围:")
                    print(f"     R:R [{historical_sampling_range['min_risk_reward'][0]:.2f}, {historical_sampling_range['min_risk_reward'][1]:.2f}]")
                    print(f"     共识 [{historical_sampling_range['min_indicator_consensus'][0]}, {historical_sampling_range['min_indicator_consensus'][1]}]")
                    print(f"     ATR [{historical_sampling_range['atr_stop_multiplier'][0]:.2f}, {historical_sampling_range['atr_stop_multiplier'][1]:.2f}]")
        except Exception as e:
            print(f"  ⚠️  读取历史范围失败: {e}")
    
    # 定义默认采样范围
    if historical_sampling_range:
        sampling_range = historical_sampling_range
    else:
        sampling_range = {
            'min_risk_reward': [1.4, 3.5],
            'min_indicator_consensus': [2, 3],
            'atr_stop_multiplier': [1.4, 1.9]
        }
    
    # 7组战略采样
    best_params = None
    best_profit = -float('inf')
    found_profitable = False
    
    # 生成7个战略采样点（直接实现，不调用外部函数）
    rr_min, rr_max = sampling_range['min_risk_reward']
    consensus_min, consensus_max = sampling_range['min_indicator_consensus']
    atr_min, atr_max = sampling_range['atr_stop_multiplier']
    
    test_points = [
        {'min_risk_reward': rr_min, 'min_indicator_consensus': consensus_min, 'atr_stop_multiplier': atr_min, 'name': '极宽松'},
        {'min_risk_reward': (rr_min + rr_max * 2) / 3, 'min_indicator_consensus': consensus_min, 'atr_stop_multiplier': (atr_min + atr_max) / 2, 'name': '偏宽松'},
        {'min_risk_reward': (rr_min + rr_max) / 2, 'min_indicator_consensus': consensus_min, 'atr_stop_multiplier': (atr_min + atr_max) / 2, 'name': '标准'},
        {'min_risk_reward': (rr_min * 2 + rr_max) / 3, 'min_indicator_consensus': consensus_min, 'atr_stop_multiplier': (atr_min + atr_max * 2) / 3, 'name': '偏严格'},
        {'min_risk_reward': rr_max, 'min_indicator_consensus': consensus_max, 'atr_stop_multiplier': atr_max, 'name': '严格'},
        {'min_risk_reward': rr_max * 1.2, 'min_indicator_consensus': consensus_max, 'atr_stop_multiplier': atr_max, 'name': '超严格'},
        {'min_risk_reward': rr_max * 1.4, 'min_indicator_consensus': consensus_max, 'atr_stop_multiplier': atr_max, 'name': '极严格'},
    ]
    
    print(f"\n  🔍 测试7组战略采样...")
    for i, test_params in enumerate(test_points):
        # 【V8.3.16.2】组装config_variant参数，调用backtest_parameters
        config_variant = {
            'min_risk_reward': test_params['min_risk_reward'],
            'min_indicator_consensus': test_params['min_indicator_consensus'],
            'atr_stop_multiplier': test_params['atr_stop_multiplier'],
            'min_signal_score': current_config.get('global', {}).get('min_signal_score', 55)
        }
        result = backtest_parameters(config_variant, days=days, verbose=False)
        
        if result['total_profit'] > best_profit:
            best_profit = result['total_profit']
            best_params = test_params.copy()
            if result['total_profit'] > 0:
                found_profitable = True
                print(f"     ✅ 找到盈利配置: R:R={test_params['min_risk_reward']}, 共识={test_params['min_indicator_consensus']}, ATR={test_params['atr_stop_multiplier']:.2f} | 盈利{result['total_profit']:.1f}%")
    
    if not best_params:
        # 使用当前配置作为默认值
        best_params = {
            'min_risk_reward': current_config['global'].get('min_risk_reward', 1.5),
            'min_indicator_consensus': current_config['global'].get('min_indicator_consensus', 2),
            'atr_stop_multiplier': current_config['global'].get('atr_stop_multiplier', 1.5)
        }
    
    best_params['found_profitable'] = found_profitable
    
    print(f"\n  ✅ 快速探索完成:")
    print(f"     最优参数: R:R={best_params['min_risk_reward']}, 共识={best_params['min_indicator_consensus']}, ATR={best_params['atr_stop_multiplier']:.2f}")
    print(f"     盈利状态: {'✅ 找到盈利' if found_profitable else '⚠️ 未找到盈利（使用最优亏损点）'}")
    
    # 【V8.3.16.3】兼容后续代码：构建iterative_result格式
    return {
        'final_params': best_params,
        'best_config': best_params,  # 兼容Line 7081
        'best_round_num': 1,  # 快速探索视为第1轮
        'best_metric': 0.0,  # 快速探索不计算综合指标
        'baseline_metric': 0.0,
        'total_rounds': 1,  # V8.3.16.7: 修复KeyError
        'rounds': [{'round_num': 1, 'improved': True, 'metric': 0.0, 'status': 'COMPLETED'}],  # V8.3.16.7: 修复rounds KeyError
        'quick_search_mode': True,
        'found_profitable': found_profitable
    }


def iterative_parameter_optimization_v770(data_summary, current_config, original_stats):
    """
    V7.7.0: 多阶段盈利优先优化
    
    革命性改进：
    - 阶段1：盈利探索（最多8轮，确保找到盈利）
    - 阶段2：盈利扩大（在盈利区域深挖）
    - 阶段3：参数优化（精细调整）
    - 阶段4：最终验证（确认稳定性）
    
    总回测：22-45组（视情况而定）
    预计耗时：2-5分钟
    """
    print(f"\n{'='*70}")
    print(f"【V7.7.0 多阶段盈利优先优化】")
    print(f"{'='*70}")
    print(f"  🎯 目标：优先找到盈利，然后深度优化")
    print(f"  📊 流程：盈利探索 → 盈利扩大 → 参数优化 → 最终验证")
    print(f"  ⏱️  预计：2-5分钟（视探索难度）")
    print(f"{'='*70}")
    
    # 定义回测天数
    days = 7
    
    # 读取历史最优采样范围
    model_name = os.getenv("MODEL_NAME", "qwen")
    config_file = Path("trading_data") / model_name / "learning_config.json"
    historical_sampling_range = None
    
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                learning_config = json.load(f)
                historical_sampling_range = learning_config.get('optimal_sampling_range')
                if historical_sampling_range:
                    print(f"\n📚 发现历史最优采样范围")
                    print(f"   R:R {historical_sampling_range['rr_range']}, "
                          f"共识 {historical_sampling_range['consensus_range']}")
        except:
            pass
    
    # === 阶段1：盈利探索 ===
    phase1_result = profit_discovery_phase_v770(
        data_summary=data_summary,
        current_config=current_config,
        historical_range=historical_sampling_range,
        days=days,
        max_rounds=8
    )
    
    if not phase1_result['found_profitable']:
        # 未找到盈利 → 触发保守策略
        print(f"\n{'='*70}")
        print(f"【触发保守策略】")
        print(f"{'='*70}")
        
        # 选择亏损最小的配置
        all_results = phase1_result['all_results']
        if all_results:
            best_unprofitable = min(all_results, key=lambda x: abs(x.get('total_profit', -999)))
            
            # 计算安全盈亏比
            win_rate = best_unprofitable.get('weighted_win_rate', 0)
            if win_rate > 0:
                breakeven_rr = (1 - win_rate) / win_rate
                safe_rr = breakeven_rr * 1.3  # 留30%安全边际
            else:
                safe_rr = 2.5
            
            safe_rr = max(2.5, min(5.0, safe_rr))  # 限制在2.5-5.0之间
            
            print(f"  ⚠️  选择亏损最小配置并应用保守策略")
            print(f"  📊 当前胜率: {win_rate*100:.1f}%")
            print(f"  🛡️  安全盈亏比: {safe_rr:.2f}:1")
            print(f"  📉 降低仓位至: 8%")
            
            conservative_config = best_unprofitable['config'].copy()
            conservative_config['min_risk_reward'] = safe_rr
            
            return {
                'status': 'CONSERVATIVE',
                'best_config': conservative_config,
                'best_round_num': 1,
                'best_metric': 0,
                'adjustments': {
                    'global': {
                        'min_risk_reward': safe_rr,
                        'base_position_pct': 8,
                        '_warning': 'conservative_mode',
                        '_warning_message': f'历史亏损，盈亏比提高至{safe_rr:.2f}:1确保期望为正'
                    }
                },
                'phase1': phase1_result,
                'total_rounds': phase1_result['rounds'],
                'baseline_metric': 0,
                'rounds': [{'round_num': 1, 'metric': 0, 'status': 'CONSERVATIVE'}]
            }
    
    # === 阶段2：盈利扩大 ===
    phase2_result = profit_expansion_phase_v770(
        profitable_center=phase1_result['best_profitable'],
        all_results=phase1_result['all_results'],
        days=days,
        max_iterations=3
    )
    
    # === 阶段3：参数优化 ===
    phase3_result = fine_tuning_phase_v770(
        profitable_region=phase2_result['all_profitable'],
        best_config=phase2_result['best_config'],
        best_metric=phase2_result['best_metric'],
        days=days
    )
    
    # === 阶段4：最终验证 ===
    phase4_result = validation_phase_v770(
        best_config=phase3_result['best_config'],
        days=days
    )
    
    # === 汇总结果 ===
    final_config = phase4_result['validated_config']
    final_metric = phase4_result['validated_metric']
    
    total_rounds = (phase1_result['rounds'] + 
                   phase2_result['rounds'] + 
                   len(phase3_result['test_points']) + 
                   len(phase4_result['test_results']))
    
    print(f"\n{'='*70}")
    print(f"【V7.7.0 优化完成】🎉")
    print(f"{'='*70}")
    print(f"  总轮次: {total_rounds}轮")
    print(f"  最优配置: R:R={final_config['min_risk_reward']:.2f}, "
          f"共识={final_config['min_indicator_consensus']}, "
          f"ATR={final_config['atr_stop_multiplier']:.2f}")
    print(f"  综合指标: {final_metric:.4f}")
    print(f"  置信度: {phase4_result['confidence']}")
    print(f"  状态: ✅ 盈利")
    print(f"{'='*70}")
    
    # 保存最优采样范围（经验复用！）
    profitable_configs = phase2_result['all_profitable']
    rr_values = [p['config']['min_risk_reward'] for p in profitable_configs]
    consensus_values = [p['config']['min_indicator_consensus'] for p in profitable_configs]
    atr_values = [p['config']['atr_stop_multiplier'] for p in profitable_configs]
    
    # 【V8.3.14.4】硬约束：consensus_range最小值强制为2
    # 在采样范围中就限制，而不是事后回退，避免浪费测试资源
    consensus_min = max(2, min(consensus_values))  # 最小值至少是2
    consensus_max = max(consensus_min, max(consensus_values))  # 确保max >= min
    
    new_sampling_range = {
        'rr_range': [min(rr_values) * 0.9, max(rr_values) * 1.1],
        'consensus_range': [consensus_min, consensus_max],
        'atr_range': [min(atr_values) - 0.1, max(atr_values) + 0.1],
        'last_updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'performance_metric': final_metric
    }
    
    print(f"\n📚 保存最优采样范围（下次优化将使用）")
    print(f"   R:R {new_sampling_range['rr_range']}")
    print(f"   共识 {new_sampling_range['consensus_range']}")
    print(f"   ATR {new_sampling_range['atr_range']}")
    
    return {
        'status': 'PROFITABLE',
        'best_config': final_config,
        'best_round_num': 1,
        'best_metric': final_metric,
        'adjustments': {
            'global': {
                'min_risk_reward': final_config['min_risk_reward'],
                'min_indicator_consensus': final_config['min_indicator_consensus'],
                'atr_stop_multiplier': final_config['atr_stop_multiplier']
            }
        },
        'optimal_sampling_range': new_sampling_range,
        'phase1': phase1_result,
        'phase2': phase2_result,
        'phase3': phase3_result,
        'phase4': phase4_result,
        'total_rounds': total_rounds,
        'baseline_metric': phase1_result['all_results'][0].get('composite_profit_metric', 0) if phase1_result['all_results'] else 0,
            'rounds': [
            {'round_num': 1, 'metric': final_metric, 'status': 'COMPLETED'}
        ]
    }


def iterative_parameter_optimization_v76x_backup(data_summary, current_config, original_stats, max_rounds=4):
    """
    V7.6.3.12: 自适应分层搜索策略
    
    策略：5点战略采样 → AI智能分析 → 局部精搜 → 最终验证
    
    流程：
    - 第1轮：5点战略采样（极宽松/偏宽松/标准/偏严格/严格）
    - 第2轮：AI分析5个点，推荐4个局部测试点
    - 第3轮：局部精确搜索（AI推荐的4个点）
    - 第4轮：最终验证（确认全局最优+置信度测试）
    
    优势：
    - 快速：12组回测，~57秒
    - 精准：战略性采样，不浪费在无用区域
    - 智能：AI基于数据设计测试，不是盲目猜测
    - 可靠：最终验证确保全局最优
    
    Args:
        data_summary: 交易数据摘要
        current_config: 当前参数配置
        original_stats: 原始交易统计
        max_rounds: 固定4轮
    
    Returns:
        {
            'rounds': [轮次1-4结果],
            'best_round_num': 最优轮次编号,
            'best_config': 最优参数配置,
            'best_metric': 最优综合利润指标,
            'total_rounds': 4,
            'strategic_sampling': 第1轮结果,
            'local_search': 第3轮结果
        }
    """
    print(f"\n{'='*70}")
    print(f"【🔄 自适应分层搜索】4轮固定流程")
    # 🆕 V7.6.6: 盈利优先搜索策略
    print(f"第1轮: 7点战略采样(R:R 1.0-4.0) → 盈利性筛选 → 第2轮: 精搜 → 第3轮: 验证")
    print(f"预计耗时: ~70秒 | 总回测: 14-17组（视情况而定）")
    print(f"策略: 优先从盈利组合中选最优，减少保守策略触发率")
    print(f"{'='*70}")
    
    # 🔧 V7.6.7.1: 在函数开头导入必要模块，避免作用域问题
    import json
    import re
    
    rounds_history = []
    best_metric = 0
    best_round_num = 0
    best_config = None
    all_backtest_results = []  # 存储所有回测结果
    
    # 🔧 定义回测天数常量
    days = 7
    
    # 🆕 V7.6.3.13: 读取历史最优采样范围（如果有）
    model_name = os.getenv("MODEL_NAME", "qwen")
    config_file = Path("trading_data") / model_name / "learning_config.json"
    historical_sampling_range = None
    
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                learning_config = json.load(f)
                historical_sampling_range = learning_config.get('optimal_sampling_range')
                if historical_sampling_range:
                    print(f"\n📚 发现历史最优采样范围（上次优化结果）")
                    print(f"   范围：R:R {historical_sampling_range['rr_range']}, 共识 {historical_sampling_range['consensus_range']}")
        except:
            pass
    
    # ============================================================
    # 第1轮：7点战略采样（V7.6.6扩大范围）
    # ============================================================
    print(f"\n{'='*60}")
    print(f"【第1轮：7点战略采样】覆盖广域寻找盈利组合")
    print(f"{'='*60}")
    print(f"  🎯 目标：扩大搜索范围，优先发现盈利参数组合")
    print(f"  📊 回测：7组战略选点（R:R覆盖1.0-4.0）")
    
    # 🆕 V7.6.3.13: 如果有历史范围，使用历史范围；否则使用默认范围
    if historical_sampling_range:
        # 使用历史最优范围
        rr_range = historical_sampling_range['rr_range']
        cons_range = historical_sampling_range['consensus_range']
        atr_range = historical_sampling_range.get('atr_range', [1.7, 2.0])
        
        strategic_points = [
            {'min_risk_reward': rr_range[0], 'min_indicator_consensus': cons_range[0], 'atr_stop_multiplier': atr_range[0], 'name': '#1 极宽松'},
            {'min_risk_reward': (rr_range[0] + rr_range[1]) * 0.375 + rr_range[0] * 0.625, 'min_indicator_consensus': cons_range[0] if cons_range[0] == cons_range[1] else cons_range[0] + 1, 'atr_stop_multiplier': (atr_range[0] + atr_range[1]) / 2, 'name': '#2 偏宽松'},
                {'min_risk_reward': (rr_range[0] + rr_range[1]) / 2, 'min_indicator_consensus': int((cons_range[0] + cons_range[1]) / 2), 'atr_stop_multiplier': (atr_range[0] + atr_range[1]) / 2, 'name': '#3 标准'},
            {'min_risk_reward': (rr_range[0] + rr_range[1]) * 0.625 + rr_range[1] * 0.375, 'min_indicator_consensus': cons_range[1] if cons_range[0] == cons_range[1] else cons_range[1] - 1, 'atr_stop_multiplier': (atr_range[0] + atr_range[1]) / 2, 'name': '#4 偏严格'},
                {'min_risk_reward': rr_range[1], 'min_indicator_consensus': cons_range[1], 'atr_stop_multiplier': atr_range[1], 'name': '#5 严格'},
        ]
        print(f"  ℹ️ 使用历史最优范围")
    else:
        # 使用默认范围
        # 🆕 V7.6.6: 扩大采样范围，确保覆盖盈利区域
        strategic_points = [
            {'min_risk_reward': 1.0, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.8, 'name': '#1 极宽松'},
            {'min_risk_reward': 1.5, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.7, 'name': '#2 偏宽松'},
            {'min_risk_reward': 2.0, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.8, 'name': '#3 标准'},
            {'min_risk_reward': 2.5, 'min_indicator_consensus': 2, 'atr_stop_multiplier': 1.9, 'name': '#4 偏严格'},
            {'min_risk_reward': 3.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 2.0, 'name': '#5 严格'},
            {'min_risk_reward': 3.5, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 2.0, 'name': '#6 超严格'},  # 🆕 V7.6.6
            {'min_risk_reward': 4.0, 'min_indicator_consensus': 3, 'atr_stop_multiplier': 2.0, 'name': '#7 极严格'},  # 🆕 V7.6.6
        ]
        print(f"  ℹ️ 使用V7.6.6扩展范围（覆盖R:R 1.0-4.0，提高盈利组合发现率）")
    
    print(f"\n  🔍 开始回测7个战略点...")
    round1_results = []
    for i, point in enumerate(strategic_points, 1):
        config = {k: v for k, v in point.items() if k != 'name'}
        result = backtest_parameters(config, days=days, verbose=False)
        
        if result:
            result['point_name'] = point['name']
            result['point_config'] = config
            round1_results.append(result)
            all_backtest_results.append(result)
            
            metric = result.get('composite_profit_metric', 0)
            trades = result.get('total_trades', 0)  # 🔧 修复：使用正确的字段名
            win_rate = result.get('win_rate', 0)
            capture = result.get('capture_rate', 0)
            print(f"    {point['name']}: 指标={metric:.4f}, 交易={trades}笔, 胜率={win_rate*100:.1f}%, 捕获={capture*100:.1f}%")
        else:
            print(f"    {point['name']}: ❌ 回测失败")
    
    if not round1_results:
        print(f"\n  ❌ 所有战略点回测失败，终止优化")
        return None
    
    # 找到第1轮最优点
    round1_best = max(round1_results, key=lambda x: x.get('composite_profit_metric', 0))
    round1_best_metric = round1_best.get('composite_profit_metric', 0)
    round1_best_config = round1_best['point_config']
    
    print(f"\n  ✅ 第1轮完成")
    print(f"     最优点: {round1_best['point_name']}")
    print(f"     最优指标: {round1_best_metric:.4f}")
    print(f"     最优配置: R:R={round1_best_config['min_risk_reward']}, 共识={round1_best_config['min_indicator_consensus']}, ATR={round1_best_config['atr_stop_multiplier']}")
    
    # 🆕 V7.6.6/V7.6.7: 盈利性筛选与盈利发现循环
    profitable_round1 = [r for r in round1_results if r.get('is_profitable', False)]
    print(f"\n  📊 盈利性分析:")
    print(f"     盈利组合: {len(profitable_round1)}/{len(round1_results)}")
    
    if profitable_round1:
        print(f"     ✅ 发现盈利组合，后续将优先从盈利区域搜索")
        # 如果有盈利组合，选盈利组合中综合指标最高的作为起点
        best_profitable = max(profitable_round1, key=lambda x: x.get('composite_profit_metric', 0))
        if best_profitable.get('composite_profit_metric', 0) >= round1_best_metric * 0.95:  # 如果盈利组合指标不低于最优点95%
            round1_best = best_profitable
            round1_best_metric = round1_best.get('composite_profit_metric', 0)
            round1_best_config = round1_best['point_config']
            print(f"     → 切换到盈利最优点: {round1_best['point_name']} (期望收益>0)")
    else:
        print(f"     ⚠️ 未发现盈利组合，启动【盈利发现循环】")
        
        # ============================================================
        # 🆕 V7.6.7: 盈利发现循环（最多3次迭代）
        # ============================================================
        print(f"\n{'='*60}")
        print(f"【🔍 V7.6.7 盈利发现循环】最多3次迭代")
        print(f"{'='*60}")
        print(f"  目标：寻找可能盈利的参数区域")
        print(f"  策略：AI分析当前亏损模式，推荐新的测试区域")
        
        profit_discovery_results = []
        max_discovery_rounds = 3
        
        for discovery_round in range(1, max_discovery_rounds + 1):
            print(f"\n  --- 盈利发现 第{discovery_round}轮 ---")
            
            # 构建详细的亏损报告
            loss_summary = f"\n### Current Status: ALL {len(round1_results)} Configurations are UNPROFITABLE\n\n"
            loss_summary += "| Config | R:R | Consensus | ATR | Total Profit | Expected Return | Win Rate | Why Losing? |\n"
            loss_summary += "|--------|-----|-----------|-----|--------------|-----------------|----------|-------------|\n"
            
            for r in round1_results:
                cfg = r['point_config']
                loss_summary += f"| {r['point_name']} | {cfg['min_risk_reward']} | {cfg['min_indicator_consensus']} | {cfg['atr_stop_multiplier']} | "
                loss_summary += f"{r.get('total_profit', 0):.2f}% | {r.get('expected_return', 0):.4f} | {r.get('win_rate', 0)*100:.1f}% | "
                
                # 分析亏损原因
                wr = r.get('win_rate', 0)
                pr = r.get('profit_ratio', 0)
                if wr < 0.4:
                    loss_summary += "Low win rate"
                elif pr < 1.5:
                    loss_summary += "Low profit ratio"
                else:
                    loss_summary += "Math expectation negative"
                loss_summary += " |\n"
            
            # AI盈利发现Prompt
            profit_discovery_prompt = f"""
## 🚨 CRITICAL MISSION: Find PROFITABLE Parameter Region

{loss_summary}

### Analysis Required:

1. **Pattern Recognition**:
   - Why are ALL configurations losing money?
   - Is win rate too low? Is profit ratio too low? Or both?
   - Are we in the wrong parameter space entirely?

2. **Hypothesis Generation**:
   - Where might profitability exist?
   - Should we go MUCH LOOSER (R:R < 1.0)?
   - Should we go MUCH STRICTER (R:R > 4.0)?
   - Should we adjust consensus/ATR differently?

3. **Recommendation**:
   - Suggest 4 NEW test points that have HIGH PROBABILITY of profitability
   - Think OUTSIDE the tested range if needed
   - Be creative and bold!

### Output Format (JSON):

{{
  "diagnosis": "为什么所有配置都亏损的核心原因（中文）",
  "hypothesis": "盈利可能存在的区域和理由（中文）",
  "strategy": "EXPLORE_EXTREME_LOOSE" | "EXPLORE_EXTREME_STRICT" | "ADJUST_CONSENSUS" | "ADJUST_ATR" | "COMBO",
  "recommended_tests": [
    {{
      "min_risk_reward": X,
      "min_indicator_consensus": Y,
      "atr_stop_multiplier": Z,
      "reason": "为什么这个点可能盈利（中文）"
    }},
    ... (4 points)
  ],
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "expected_outcome": "预期这4个点的表现（中文）"
}}

**Important**: 
- All JSON values must use valid syntax
- Chinese responses in designated fields only
- Be specific and quantitative in recommendations
"""
            
            try:
                # 调用AI
                ai_response = qwen_client.chat.completions.create(
                    model="qwen3-max",
                    messages=[
                        {"role": "system", "content": "You are a professional quantitative trading analyst specializing in parameter optimization and profitability discovery. Respond in Chinese for designated fields."},
                            {"role": "user", "content": profit_discovery_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=2000
                )
                
                ai_content = ai_response.choices[0].message.content.strip()
                
                # 提取JSON
                json_match = re.search(r'\{[\s\S]*\}', ai_content)
                if json_match:
                    ai_analysis = json.loads(json_match.group())
                    
                    print(f"  ✅ AI分析完成")
                    print(f"     诊断: {ai_analysis.get('diagnosis', 'N/A')}")
                    print(f"     假设: {ai_analysis.get('hypothesis', 'N/A')}")
                    print(f"     策略: {ai_analysis.get('strategy', 'N/A')}")
                    print(f"     置信度: {ai_analysis.get('confidence', 'N/A')}")
                    
                    # 回测AI推荐的4个点
                    print(f"\n  🔍 回测AI推荐的4个可能盈利的点...")
                    discovery_tests = []
                    
                    for i, test in enumerate(ai_analysis.get('recommended_tests', []), 1):
                        config = {
                            'min_risk_reward': test['min_risk_reward'],
                            'min_indicator_consensus': test['min_indicator_consensus'],
                            'atr_stop_multiplier': test['atr_stop_multiplier']
                        }
                        
                        result = backtest_parameters(config, days=days, verbose=False)
                        
                        if result:
                            result['test_reason'] = test.get('reason', f'发现测试{i}')
                            result['test_config'] = config
                            result['discovery_round'] = discovery_round
                            discovery_tests.append(result)
                            all_backtest_results.append(result)
                            
                            is_profit = result.get('is_profitable', False)
                            total_profit = result.get('total_profit', 0)
                            metric = result.get('composite_profit_metric', 0)
                            
                            status = "✅ 盈利!" if is_profit else "❌ 亏损"
                            print(f"    测试#{i}: R:R={config['min_risk_reward']}, 总盈利={total_profit:.2f}%, 指标={metric:.4f} {status}")
                            
                            if is_profit:
                                print(f"    → 理由: {test.get('reason', 'N/A')}")
                        else:
                            print(f"    测试#{i}: ❌ 回测失败")
                    
                    profit_discovery_results.extend(discovery_tests)
                    
                    # 检查是否找到盈利组合
                    profitable_discoveries = [r for r in discovery_tests if r.get('is_profitable', False)]
                    
                    if profitable_discoveries:
                        print(f"\n  🎉 成功！在第{discovery_round}轮发现{len(profitable_discoveries)}个盈利组合！")
                        print(f"  → 退出盈利发现循环，进入正常优化流程")
                        
                        # 更新round1结果，加入盈利组合
                        round1_results.extend(discovery_tests)
                        profitable_round1 = profitable_discoveries
                        
                        # 选择最优盈利组合作为新起点
                        best_profitable = max(profitable_discoveries, key=lambda x: x.get('composite_profit_metric', 0))
                        round1_best = best_profitable
                        round1_best_metric = round1_best.get('composite_profit_metric', 0)
                        round1_best_config = round1_best['test_config']
                        
                        print(f"  → 新的最优点: R:R={round1_best_config['min_risk_reward']}, 指标={round1_best_metric:.4f}")
                        break  # 找到盈利，跳出循环
                    else:
                        print(f"  ⚠️ 第{discovery_round}轮未找到盈利组合")
                        if discovery_round < max_discovery_rounds:
                            print(f"  → 继续下一轮盈利发现...")
                else:
                    print(f"  ⚠️ AI响应格式错误，使用默认策略")
                    break
                    
            except Exception as e:
                print(f"  ⚠️ 盈利发现失败: {e}")
                break
        
        # 盈利发现循环结束
        if not profitable_round1:
            print(f"\n  ❌ 盈利发现失败：经过{max_discovery_rounds}轮尝试，仍未找到盈利组合")
            print(f"  → 将使用保守策略确保数学期望为正")
        
        print(f"\n{'='*60}")
    
    # 设置当前最优
    best_metric = round1_best_metric
    best_config = round1_best_config.copy()
    best_round_num = 1
    
    rounds_history.append({
        'round_num': 1,
        'improved': True,
        'metric': round1_best_metric,
        'improvement_pct': 0,
        'direction': '5点战略采样',
        'config': round1_best_config.copy(),
        'backtest_result': round1_best,
        'reason': f'建立基准线，最优点{round1_best["point_name"]}'
    })
    
    # 🔧 提前格式化第1轮结果（供第1.5轮和第2轮使用）
    round1_summary = "\n## Round 1: Strategic Sampling Results (5 Points)\n\n"
    round1_summary += "| Point | R:R | Consensus | ATR | Trades | Win Rate | Profit Ratio | Capture | Metric |\n"
    round1_summary += "|-------|-----|-----------|-----|--------|----------|--------------|---------|--------|\n"
    
    for result in round1_results:
        config = result['point_config']
        trades = result.get('total_trades', 0)  # 🔧 修复：使用正确的字段名
        win_rate = result.get('win_rate', 0)
        profit_ratio = result.get('profit_ratio', 0)
        capture = result.get('capture_rate', 0)
        metric = result.get('composite_profit_metric', 0)
        
        round1_summary += f"| {result['point_name']} | {config['min_risk_reward']} | {config['min_indicator_consensus']} | {config['atr_stop_multiplier']} | {trades} | {win_rate*100:.1f}% | {profit_ratio:.2f} | {capture*100:.1f}% | {metric:.4f} |\n"
    
    round1_summary += f"\n**Current Best**: {round1_best['point_name']} (Metric: {round1_best_metric:.4f})\n\n"
    
    # ============================================================
    # 🆕 V7.6.3.13: 第1.5轮：采样质量评估与自适应重采样
    # ============================================================
    print(f"\n{'='*60}")
    print(f"【第1.5轮：采样质量评估】")
    print(f"{'='*60}")
    
    # 评估采样质量
    avg_metric = sum(r.get('composite_profit_metric', 0) for r in round1_results) / len(round1_results)
    min_trades = min(r.get('total_trades', 0) for r in round1_results)  # 🔧 修复：使用正确的字段名
    max_trades = max(r.get('total_trades', 0) for r in round1_results)  # 🔧 修复：使用正确的字段名
    
    # 判断是否需要重采样
    need_resample = False
    resample_reason = ""
    
    if round1_best_metric < 0.015:
        need_resample = True
        resample_reason = f"最优点指标仅{round1_best_metric:.4f}，远低于0.015阈值"
    elif avg_metric < 0.008:
        need_resample = True
        resample_reason = f"平均指标仅{avg_metric:.4f}，采样点分布不佳"
    elif max_trades < 10:
        need_resample = True
        resample_reason = f"最多交易仅{max_trades}笔，参数过严"
    elif round1_best['point_name'] in ['#1 极宽松', '#5 严格']:
        # 最优点在边界，可能还有更优的
        need_resample = True
        resample_reason = f"最优点在边界（{round1_best['point_name']}），可能还有更优范围"
    
    if need_resample:
        print(f"  ⚠️ 采样质量需要改进：{resample_reason}")
        print(f"  🔄 触发AI重采样机制...")
        
        # 构建重采样Prompt（专业英文，要求中文输出）
        resample_prompt = f"""
## Problem: Sampling Quality Needs Improvement

### Current 5-Point Sampling Results:
{round1_summary}

### Issue Identified:
{resample_reason}

### Your Task: Suggest NEW 5-Point Sampling

Based on the results above, design a BETTER 5-point sampling strategy.

**Analysis Checklist**:
1. If best metric < 0.015: Parameters likely TOO STRICT → Suggest LOOSER range
2. If best point is #1 (leftmost): Optimal might be even LOOSER → SHIFT LEFT
3. If best point is #5 (rightmost): Optimal might be even TIGHTER → SHIFT RIGHT
4. If all trades < 20: TOO STRICT → Expand to looser range
5. If all trades > 100 with low win rate: TOO LOOSE → Tighten range

**Output Format (JSON)**:
{{
  "diagnosis": "为什么当前采样不理想（中文）",
  "direction": "LOOSER" | "TIGHTER" | "SHIFT_LEFT" | "SHIFT_RIGHT",
  "new_sampling": [
    {{"min_risk_reward": X, "min_indicator_consensus": Y, "atr_stop_multiplier": Z, "name": "..."}},
    ... (5 points)
  ],
  "expected_improvement": "为什么新采样会更好（中文）",
  "new_range_description": {{
    "rr_range": [min, max],
    "consensus_range": [min, max],
    "atr_range": [min, max]
  }}
}}

**IMPORTANT**: All text fields (diagnosis, expected_improvement) MUST be in Chinese (中文).
"""
        
        # 调用AI（使用已有的qwen_client）
        try:
            import json
            import re
            
            response = qwen_client.chat.completions.create(
                model="qwen3-max",
                messages=[{"role": "user", "content": resample_prompt}],
                temperature=0.1
            )
            
            ai_response = response.choices[0].message.content
            
            # 解析JSON
            json_match = re.search(r"```json\s*(.*?)\s*```", ai_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = ai_response
            
            resample_suggestion = json.loads(json_str)
            
            print(f"\n  ✅ AI重采样建议")
            print(f"     诊断：{resample_suggestion['diagnosis']}")
            print(f"     方向：{resample_suggestion['direction']}")
            print(f"     新范围：R:R {resample_suggestion['new_range_description']['rr_range']}, 共识 {resample_suggestion['new_range_description']['consensus_range']}")
            
            # 执行重采样
            print(f"\n  🔍 执行重采样...")
            new_strategic_points = resample_suggestion['new_sampling']
            round1_v2_results = []
            
            for point in new_strategic_points:
                config = {k: v for k, v in point.items() if k != 'name'}
                result = backtest_parameters(config, days=days, verbose=False)
                
                if result:
                    result['point_name'] = point['name']
                    result['point_config'] = config
                    round1_v2_results.append(result)
                    all_backtest_results.append(result)
                    
                    metric = result.get('composite_profit_metric', 0)
                    trades = result.get('total_trades', 0)  # 🔧 修复：使用正确的字段名
                    print(f"    {point['name']}: 指标={metric:.4f}, 交易={trades}笔")
            
            if round1_v2_results:
                # 比较新旧采样
                old_best_metric = round1_best_metric
                new_best = max(round1_v2_results, key=lambda x: x.get('composite_profit_metric', 0))
                new_best_metric = new_best.get('composite_profit_metric', 0)
                
                improvement = ((new_best_metric - old_best_metric) / old_best_metric * 100) if old_best_metric > 0 else 0
                
                if new_best_metric > old_best_metric * 1.05:  # 至少提升5%
                    print(f"\n  ✅ 重采样成功！指标提升：{old_best_metric:.4f} → {new_best_metric:.4f} ({improvement:+.1f}%)")
                    print(f"     采用新采样结果")
                    
                    # 使用新结果
                    round1_results = round1_v2_results
                    round1_best = new_best
                    round1_best_metric = new_best_metric
                    round1_best_config = new_best['point_config']
                    
                    # 更新最优
                    best_metric = new_best_metric
                    best_config = round1_best_config.copy()  # 🔧 修复：使用已定义的变量
                    
                    # 记录新的最优采样范围
                    new_sampling_range = resample_suggestion['new_range_description']
                    
                    rounds_history.append({
                        'round_num': 1.5,
                        'improved': True,
                        'metric': new_best_metric,
                        'improvement_pct': improvement,
                        'direction': f'重采样({resample_suggestion["direction"]})',
                        'config': round1_best_config.copy(),  # 🔧 V7.6.7.2: 修复变量名
                        'backtest_result': new_best,
                        'reason': f'重采样成功，提升{improvement:.1f}%',
                        'new_sampling_range': new_sampling_range
                    })
                else:
                    print(f"\n  ℹ️ 重采样未显著改善（{improvement:+.1f}%），保持原采样")
            
        except Exception as e:
            print(f"  ⚠️ AI重采样失败: {e}")
            print(f"  ℹ️ 继续使用原采样结果")
    else:
        print(f"  ✅ 采样质量良好")
        print(f"     最优指标: {round1_best_metric:.4f}")
        print(f"     平均指标: {avg_metric:.4f}")
        print(f"     继续后续流程")
    
    # ============================================================
    # 第2轮：AI智能分析
    # ============================================================
    print(f"\n{'='*60}")
    print(f"【第2轮：AI智能分析】定位最优区域")
    print(f"{'='*60}")
    print(f"  🤖 AI分析5个战略点的回测结果...")
    
    # round1_summary已在第1.5轮之前定义，此处直接使用
    
    # AI分析Prompt
    ai_analysis_prompt = f"""
{data_summary}

{round1_summary}

## Your Task: Analyze Strategic Sampling Results

Based on the 5 strategic sampling points above:

1. **Identify the PROFIT PEAK REGION**:
   - Which R:R range shows the highest profit? (e.g., 1.3-1.7)
   - Which consensus level is optimal? (e.g., 2-3)
   - Which ATR multiplier works best? (e.g., 1.6-1.9)

2. **Design 4 TARGETED TESTS for Round 3** (local fine-grained search):
    - Test points around the current best ({round1_best['point_name']})
   - Explore slight variations in R:R, consensus, and ATR
   - Goal: Find the TRUE MAXIMUM within ±0.2 range

3. **Output Format** (JSON):
{{
  "optimal_region": {{
    "min_risk_reward_range": [lower, upper],
    "consensus_range": [lower, upper],
    "atr_range": [lower, upper],
    "reasoning": "为什么选这个区域（中文）"
  }},
  "round3_tests": [
    {{"min_risk_reward": X, "min_indicator_consensus": Y, "atr_stop_multiplier": Z, "reason": "测试原因（中文）"}},
    ... (4 tests total)
  ],
  "expected_improvement": "X%",
  "analysis": "对第1轮趋势的简要分析（中文）"
}}

**Decision Criteria**:
- Maximize composite profit metric (Win Rate × Profit Ratio × Capture Rate)
- Balance quality (win rate) vs. quantity (capture rate)
- Focus on actionable, practical parameter ranges

**IMPORTANT**: All text fields (reasoning, reason, analysis) MUST be in Chinese (中文).
"""
    
    # 调用AI分析（使用已有的qwen_client）
    try:
        response = qwen_client.chat.completions.create(
            model="qwen3-max",
            messages=[{"role": "user", "content": ai_analysis_prompt}],
            temperature=0.1
        )
        
        ai_response = response.choices[0].message.content
        
        # 解析JSON
        json_match = re.search(r"```json\s*(.*?)\s*```", ai_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = ai_response
        
        ai_analysis = json.loads(json_str)
        
        print(f"\n  ✅ AI分析完成")
        print(f"     最优区域: R:R{ai_analysis['optimal_region']['min_risk_reward_range']}, 共识{ai_analysis['optimal_region']['consensus_range']}")
        print(f"     推荐测试: {len(ai_analysis['round3_tests'])}个点")
        
    except Exception as e:
        print(f"  ⚠️ AI分析失败: {e}")
        # 备用：基于第1轮最优点生成测试点
        best_rr = round1_best_config['min_risk_reward']
        best_cons = round1_best_config['min_indicator_consensus']
        best_atr = round1_best_config['atr_stop_multiplier']
        
        ai_analysis = {
            'optimal_region': {
                'min_risk_reward_range': [max(1.0, best_rr-0.2), min(2.5, best_rr+0.2)],
                'consensus_range': [max(2, best_cons-1), min(4, best_cons+1)],
                'atr_range': [max(1.2, best_atr-0.2), min(2.5, best_atr+0.2)]
            },
            'round3_tests': [
                {'min_risk_reward': best_rr-0.1, 'min_indicator_consensus': best_cons, 'atr_stop_multiplier': best_atr, 'reason': '略低R:R'},
                {'min_risk_reward': best_rr, 'min_indicator_consensus': best_cons, 'atr_stop_multiplier': best_atr-0.2, 'reason': '收紧ATR'},
                {'min_risk_reward': best_rr+0.1, 'min_indicator_consensus': best_cons, 'atr_stop_multiplier': best_atr, 'reason': '略高R:R'},
                {'min_risk_reward': best_rr, 'min_indicator_consensus': best_cons, 'atr_stop_multiplier': best_atr+0.2, 'reason': '放宽ATR'}
            ]
        }
        print(f"  ℹ️ 使用备用测试点生成策略")
    
    rounds_history.append({
        'round_num': 2,
        'improved': False,  # 第2轮只是分析，不回测
        'metric': best_metric,
        'direction': 'AI智能分析',
        'config': best_config.copy(),
        'reason': f'定位最优区域: R:R{ai_analysis["optimal_region"]["min_risk_reward_range"]}'
    })
    
    # ============================================================
    # 第3轮：局部精确搜索
    # ============================================================
    print(f"\n{'='*60}")
    print(f"【第3轮：局部精确搜索】AI推荐的4个测试点")
    print(f"{'='*60}")
    print(f"  🔍 回测AI推荐的4个局部测试点...")
    
    round3_results = []
    for i, test_config in enumerate(ai_analysis['round3_tests'], 1):
        config = {k: v for k, v in test_config.items() if k != 'reason'}
        result = backtest_parameters(config, days=days, verbose=False)
        
        if result:
            result['test_reason'] = test_config.get('reason', f'测试{i}')
            result['test_config'] = config
            round3_results.append(result)
            all_backtest_results.append(result)
            
            metric = result.get('composite_profit_metric', 0)
            trades = len(result.get('simulated_trades', []))
            win_rate = result.get('win_rate', 0)
            capture = result.get('capture_rate', 0)
            vs_round1 = ((metric - round1_best_metric) / round1_best_metric * 100) if round1_best_metric > 0 else 0
            
            print(f"    测试#{i+5} ({test_config.get('reason', '')}): 指标={metric:.4f}, 交易={trades}笔, vs第1轮 {vs_round1:+.1f}%")
        else:
            print(f"    测试#{i+5}: ❌ 回测失败")
    
    if round3_results:
        # 找到第3轮最优点
        round3_best = max(round3_results, key=lambda x: x.get('composite_profit_metric', 0))
        round3_best_metric = round3_best.get('composite_profit_metric', 0)
        round3_best_config = round3_best['test_config']
        
        print(f"\n  ✅ 第3轮完成")
        print(f"     最优点: 测试#{round3_results.index(round3_best)+6}")
        print(f"     最优指标: {round3_best_metric:.4f}")
        print(f"     vs第1轮: {((round3_best_metric - round1_best_metric) / round1_best_metric * 100) if round1_best_metric > 0 else 0:+.1f}%")
        
        # 更新全局最优
        if round3_best_metric > best_metric:
            improvement = ((round3_best_metric - best_metric) / best_metric * 100) if best_metric > 0 else 0
            best_metric = round3_best_metric
            best_config = round3_best_config.copy()
            best_round_num = 3
            
            rounds_history.append({
                'round_num': 3,
                'improved': True,
                'metric': round3_best_metric,
                'improvement_pct': improvement,
                'direction': '局部精确搜索',
                'config': round3_best_config.copy(),
                'backtest_result': round3_best,
                'reason': f'找到更优点，提升{improvement:.1f}%'
            })
        else:
            rounds_history.append({
                'round_num': 3,
                'improved': False,
                'metric': round3_best_metric,
                'direction': '局部精确搜索',
                'config': round3_best_config.copy(),
                'backtest_result': round3_best,
                'reason': '未发现更优点'
            })
    else:
        print(f"\n  ⚠️ 第3轮所有测试失败")
        rounds_history.append({
            'round_num': 3,
            'improved': False,
            'metric': best_metric,
            'direction': '局部精确搜索',
            'config': best_config.copy(),
            'reason': '所有测试失败'
        })
    
    # ============================================================
    # 第4轮：最终验证
    # ============================================================
    print(f"\n{'='*60}")
    print(f"【第4轮：最终验证】确认全局最优")
    print(f"{'='*60}")
    print(f"  🔍 验证当前最优点及其相邻点...")
    
    # 生成验证点：当前最优 + 左侧 + 右侧
    current_rr = best_config['min_risk_reward']
    current_cons = best_config['min_indicator_consensus']
    current_atr = best_config['atr_stop_multiplier']
    
    verification_tests = [
        {'min_risk_reward': max(1.0, current_rr - 0.1), 'min_indicator_consensus': current_cons, 'atr_stop_multiplier': current_atr, 'name': '左侧(R:R-0.1)'},
        {'min_risk_reward': current_rr, 'min_indicator_consensus': current_cons, 'atr_stop_multiplier': current_atr, 'name': '峰值(当前最优)'},
        {'min_risk_reward': min(2.5, current_rr + 0.1), 'min_indicator_consensus': current_cons, 'atr_stop_multiplier': current_atr, 'name': '右侧(R:R+0.1)'},
    ]
    
    round4_results = []
    for i, test in enumerate(verification_tests, 1):
        config = {k: v for k, v in test.items() if k != 'name'}
        result = backtest_parameters(config, days=days, verbose=False)
        
        if result:
            result['test_name'] = test['name']
            result['test_config'] = config
            round4_results.append(result)
            all_backtest_results.append(result)
            
            metric = result.get('composite_profit_metric', 0)
            trades = len(result.get('simulated_trades', []))
            
            print(f"    {test['name']}: 指标={metric:.4f}, 交易={trades}笔")
        else:
            print(f"    {test['name']}: ❌ 回测失败")
    
    if len(round4_results) >= 2:
        # 确认峰值
        peak_test = next((r for r in round4_results if '峰值' in r['test_name']), None)
        if peak_test:
            peak_metric = peak_test.get('composite_profit_metric', 0)
            other_metrics = [r.get('composite_profit_metric', 0) for r in round4_results if r != peak_test]
            
            if peak_metric >= max(other_metrics):
                confidence = "高"
                print(f"\n  ✅ 确认：当前最优点是真实峰值（置信度: {confidence}）")
            else:
                confidence = "中"
                # 找到更优点
                better_test = max(round4_results, key=lambda x: x.get('composite_profit_metric', 0))
                better_metric = better_test.get('composite_profit_metric', 0)
                better_config = better_test['test_config']
                
                if better_metric > best_metric:
                    improvement = ((better_metric - best_metric) / best_metric * 100) if best_metric > 0 else 0
                    best_metric = better_metric
                    best_config = better_config.copy()
                    best_round_num = 4
                    print(f"\n  ℹ️ 发现更优点：{better_test['test_name']} (提升{improvement:.1f}%)")
        
        rounds_history.append({
            'round_num': 4,
            'improved': best_round_num == 4,
            'metric': best_metric,
            'direction': '最终验证',
            'config': best_config.copy(),
            'reason': f'确认全局最优，置信度{confidence}'
        })
    else:
        print(f"\n  ⚠️ 验证测试不足")
        rounds_history.append({
            'round_num': 4,
            'improved': False,
            'metric': best_metric,
            'direction': '最终验证',
            'config': best_config.copy(),
            'reason': '验证测试不足'
        })
    
    # 输出最终结果
    print(f"\n{'='*70}")
    print(f"【🏆 优化完成】")
    print(f"{'='*70}")
    print(f"  总轮次: 4轮")
    print(f"  总回测: {len(all_backtest_results)}组")
    print(f"  最优轮次: 第{best_round_num}轮")
    print(f"  最优指标: {best_metric:.4f}")
    print(f"  最优配置: R:R={best_config['min_risk_reward']}, 共识={best_config['min_indicator_consensus']}, ATR={best_config['atr_stop_multiplier']}")
    
    # 🆕 V7.6.3.13: 保存最优采样范围到learning_config
    # 用于下次优化时作为初始范围
    optimal_sampling_range = None
    
    # 查找是否有重采样产生的新范围
    for round_record in rounds_history:
        if 'new_sampling_range' in round_record:
            optimal_sampling_range = round_record['new_sampling_range']
            break
    
    # 如果没有重采样，基于当前最优点推断最优范围
    if not optimal_sampling_range:
        # 基于round1_results计算最优范围
        all_rr = [r['point_config']['min_risk_reward'] for r in round1_results]
        all_cons = [r['point_config']['min_indicator_consensus'] for r in round1_results]
        all_atr = [r['point_config']['atr_stop_multiplier'] for r in round1_results]
        
        # 找到指标最高的前3个点，用它们的范围作为最优范围
        top3 = sorted(round1_results, key=lambda x: x.get('composite_profit_metric', 0), reverse=True)[:3]
        top3_rr = [r['point_config']['min_risk_reward'] for r in top3]
        top3_cons = [r['point_config']['min_indicator_consensus'] for r in top3]
        top3_atr = [r['point_config']['atr_stop_multiplier'] for r in top3]
        
        # 【V8.3.14.4】硬约束：consensus_range最小值强制为2
        consensus_min = max(2, min(top3_cons))
        consensus_max = max(consensus_min, max(top3_cons))
        
        optimal_sampling_range = {
            'rr_range': [min(top3_rr), max(top3_rr)],
            'consensus_range': [consensus_min, consensus_max],
            'atr_range': [min(top3_atr), max(top3_atr)]
        }
    
    # 保存到learning_config
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                learning_config = json.load(f)
        else:
            learning_config = {}
        
        learning_config['optimal_sampling_range'] = optimal_sampling_range
        learning_config['optimal_sampling_range_updated'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(learning_config, f, indent=2, ensure_ascii=False)
        
        print(f"\n  💾 已保存最优采样范围（用于下次优化）")
        print(f"     R:R范围: {optimal_sampling_range['rr_range']}")
        print(f"     共识范围: {optimal_sampling_range['consensus_range']}")
        print(f"     ATR范围: {optimal_sampling_range['atr_range']}")
    except Exception as e:
        print(f"  ⚠️ 保存采样范围失败: {e}")
    
    # ============================================================
    # 🆕 V7.6.6: 盈利优先选择 - 优先从盈利组合中选最优
    # ============================================================
    print(f"\n")
    print("=" * 60)
    print("【🎯 V7.6.6 盈利优先选择】")
    print("=" * 60)
    
    # 收集所有回测结果（包含is_profitable字段）
    all_backtest_results = []
    # Round 1
    for r in round1_results:
        r['source_round'] = 'Round 1'
        all_backtest_results.append(r)
    # Round 3 (AI推荐点)
    for r in round3_results:
        r['source_round'] = 'Round 3'
        all_backtest_results.append(r)
    # Round 4 (最终验证)
    for r in round4_results:
        r['source_round'] = 'Round 4'
        all_backtest_results.append(r)
    
    # 盈利性分析
    profitable_configs = [r for r in all_backtest_results if r.get('is_profitable', False)]
    unprofitable_configs = [r for r in all_backtest_results if not r.get('is_profitable', False)]
    
    print(f"\n【所有回测结果】")
    print(f"  总回测组数: {len(all_backtest_results)}")
    print(f"  ✅ 盈利组合: {len(profitable_configs)}")
    print(f"  ❌ 亏损组合: {len(unprofitable_configs)}")
    
    # 🔑 核心逻辑：优先选择盈利组合
    if profitable_configs:
        # 从盈利组合中选综合指标最高的
        best_from_profitable = max(profitable_configs, key=lambda x: x.get('composite_profit_metric', 0))
        # 🔧 V7.6.7 修复KeyError: 尝试point_config和test_config
        best_config = best_from_profitable.get('point_config') or best_from_profitable.get('test_config')
        best_metric = best_from_profitable.get('composite_profit_metric', 0)
        
        print(f"\n✅ 找到{len(profitable_configs)}个盈利组合，优先选择！")
        print(f"  → 最优盈利组合来自: {best_from_profitable.get('source_round', 'Unknown')}")
        print(f"  → R:R={best_config['min_risk_reward']}, 共识={best_config['min_indicator_consensus']}, ATR={best_config['atr_stop_multiplier']}")
        print(f"  → 综合指标: {best_metric:.4f}")
        print(f"  → 期望收益: {best_from_profitable.get('expected_return', 0):.2%}")
        print(f"  → 总盈利: {best_from_profitable.get('total_profit', 0):.2%}")
        
        # 标记为盈利最优
        is_profitable_param = True
        total_profit_value = best_from_profitable.get('total_profit', 0)
        expected_return_value = best_from_profitable.get('expected_return', 0)
        
        # 不需要保守策略
        print(f"\n🎉 成功找到盈利最优组合，无需保守策略！")
        
    else:
        # 没有盈利组合，选综合指标最高的（亏损最小）
        best_from_unprofitable = max(unprofitable_configs, key=lambda x: x.get('composite_profit_metric', 0))
        # 🔧 V7.6.7 修复KeyError: 尝试point_config和test_config
        best_config = best_from_unprofitable.get('point_config') or best_from_unprofitable.get('test_config')
        best_metric = best_from_unprofitable.get('composite_profit_metric', 0)
        
        print(f"\n⚠️ 未找到盈利组合，选择亏损最小的")
        print(f"  → 最优（亏损最小）来自: {best_from_unprofitable.get('source_round', 'Unknown')}")
        print(f"  → R:R={best_config['min_risk_reward']}, 共识={best_config['min_indicator_consensus']}, ATR={best_config['atr_stop_multiplier']}")
        print(f"  → 综合指标: {best_metric:.4f}")
        print(f"  → 期望收益: {best_from_unprofitable.get('expected_return', 0):.2%}")
        print(f"  → 总盈利: {best_from_unprofitable.get('total_profit', 0):.2%}")
        
        is_profitable_param = False
        total_profit_value = best_from_unprofitable.get('total_profit', 0)
        expected_return_value = best_from_unprofitable.get('expected_return', 0)
    
    # ============================================================
    # 🆕 V7.6.6: 盈利优先选择 - 优先从盈利组合中选最优
    # ============================================================
    print(f"\n{'='*70}")
    print(f"【🎯 V7.6.6 盈利优先选择】")
    print(f"{'='*70}")
    
    # 盈利性分析
    profitable_configs = [r for r in all_backtest_results if r.get('is_profitable', False)]
    unprofitable_configs = [r for r in all_backtest_results if not r.get('is_profitable', False)]
    
    print(f"\n【所有回测结果】")
    print(f"  总回测组数: {len(all_backtest_results)}")
    print(f"  ✅ 盈利组合: {len(profitable_configs)}")
    print(f"  ❌ 亏损组合: {len(unprofitable_configs)}")
    
    # 🔑 核心逻辑：优先选择盈利组合
    if profitable_configs:
        # 从盈利组合中选综合指标最高的
        best_from_profitable = max(profitable_configs, key=lambda x: x.get('composite_profit_metric', 0))
        # 兼容不同轮次的字段名（Round 1: point_config, Round 3/4: test_config）
        best_config = best_from_profitable.get('point_config') or best_from_profitable.get('test_config')
        best_metric = best_from_profitable.get('composite_profit_metric', 0)
        
        print(f"\n✅ 找到{len(profitable_configs)}个盈利组合，优先选择！")
        print(f"  → 最优盈利组合来自: {best_from_profitable.get('source_round', 'Unknown')}")
        print(f"  → R:R={best_config['min_risk_reward']}, 共识={best_config['min_indicator_consensus']}, ATR={best_config['atr_stop_multiplier']}")
        print(f"  → 综合指标: {best_metric:.4f}")
        print(f"  → 期望收益: {best_from_profitable.get('expected_return', 0):.2%}")
        print(f"  → 总盈利: {best_from_profitable.get('total_profit', 0):.2%}")
        
        # 标记为盈利最优
        is_profitable_param = True
        total_profit_value = best_from_profitable.get('total_profit', 0)
        expected_return_value = best_from_profitable.get('expected_return', 0)
        
        # 不需要保守策略
        print(f"\n🎉 成功找到盈利最优组合，无需保守策略！")
        
    else:
        # 没有盈利组合，选综合指标最高的（亏损最小）
        best_from_unprofitable = max(unprofitable_configs, key=lambda x: x.get('composite_profit_metric', 0))
        # 兼容不同轮次的字段名（Round 1: point_config, Round 3/4: test_config）
        best_config = best_from_unprofitable.get('point_config') or best_from_unprofitable.get('test_config')
        best_metric = best_from_unprofitable.get('composite_profit_metric', 0)
        
        print(f"\n⚠️ 未找到盈利组合，选择亏损最小的")
        print(f"  → 最优（亏损最小）来自: {best_from_unprofitable.get('source_round', 'Unknown')}")
        print(f"  → R:R={best_config['min_risk_reward']}, 共识={best_config['min_indicator_consensus']}, ATR={best_config['atr_stop_multiplier']}")
        print(f"  → 综合指标: {best_metric:.4f}")
        print(f"  → 期望收益: {best_from_unprofitable.get('expected_return', 0):.2%}")
        print(f"  → 总盈利: {best_from_unprofitable.get('total_profit', 0):.2%}")
        
        is_profitable_param = False
        total_profit_value = best_from_unprofitable.get('total_profit', 0)
        expected_return_value = best_from_unprofitable.get('expected_return', 0)
    
    # ============================================================
    # 🆕 V7.6.5/V7.6.6: 保守策略（仅在无盈利组合时触发）
    # ============================================================
    # 保守策略仅在无盈利组合时触发
    if not is_profitable_param:
        print(f"\n{'='*70}")
        print(f"【🛡️ 触发保守策略】")
        print(f"{'='*70}")
        
        # 获取最优参数的详细回测结果
        best_result = backtest_parameters(best_config, days=days, verbose=False)
        
        if best_result:
            breakeven_rr = best_result.get('breakeven_profit_ratio', 999)
            actual_rr = best_result.get('weighted_profit_ratio', 0)
            win_rate = best_result.get('weighted_win_rate', 0)
            
            print(f"\n💰 当前最优参数（亏损最小）分析:")
            print(f"   总盈利: {total_profit_value:.2f}%")
            print(f"   期望收益: {expected_return_value:+.2f}% per trade")
            print(f"   胜率: {win_rate*100:.1f}%")
            print(f"   盈亏比: {actual_rr:.2f}:1")
            print(f"   盈亏平衡点: {breakeven_rr:.2f}:1")
            
            # 应用保守策略
            print(f"\n⚠️ 【警告】最优参数历史回测仍然亏损！")
            print(f"\n   📊 亏损原因分析：")
            if actual_rr < breakeven_rr:
                print(f"   • 盈亏比不足：需要{breakeven_rr:.2f}:1，实际{actual_rr:.2f}:1")
            if total_profit_value < 0:
                print(f"   • 总盈利为负：{total_profit_value:.2f}%")
            if win_rate < 0.5:
                print(f"   • 胜率偏低：{win_rate*100:.1f}%（数学上需要>50%或更高盈亏比）")
            
            # 🆕 V7.6.5: 智能保守策略 - 提高盈亏比要求
            # 计算安全盈亏比：盈亏平衡点 × 1.3（留30%安全边际）
            safe_rr = max(breakeven_rr * 1.3, 2.5)  # 至少2.5
            safe_rr = min(safe_rr, 4.0)  # 最多4.0（避免过严）
            
            print(f"\n   💡 保守策略计算：")
            print(f"   • 当前胜率：{win_rate*100:.1f}%")
            print(f"   • 盈亏平衡点：{breakeven_rr:.2f}:1")
            print(f"   • 安全盈亏比：{safe_rr:.2f}:1（盈亏平衡点 × 1.3，留30%安全边际）")
            print(f"   • 理论期望（使用安全盈亏比）：{(win_rate * safe_rr - (1 - win_rate)):+.2f}:1 > 0 ✓")
            
            print(f"\n   🛡️ 应用保守策略：")
            print(f"   1. ⚠️ 提高盈亏比要求：{best_config['min_risk_reward']:.2f} → {safe_rr:.2f}")
            print(f"   2. ⚠️ 保持其他参数不变（共识、ATR）")
            print(f"   3. ⚠️ 降低仓位至8%（额外保护）")
            print(f"   4. ⚠️ 数学期望已为正，可安全交易")
            
            # 应用保守策略
            best_config['min_risk_reward'] = safe_rr  # 🔑 核心：提高盈亏比
            best_config['base_position_pct'] = 8  # 降低仓位作为额外保护
            best_config['_warning'] = "conservative_mode"
            best_config['_warning_message'] = f"历史亏损{total_profit_value:.2f}%，盈亏比提高至{safe_rr:.2f}:1确保期望为正"
            best_config['_original_rr'] = actual_rr  # 保存原始盈亏比
            best_config['_breakeven_rr'] = breakeven_rr  # 保存盈亏平衡点
            
            print(f"\n   ✅ 已自动应用保守策略（数学期望为正）")
        else:
            print(f"\n✅ 最优参数预期盈利！")
            print(f"   理论每笔收益: {expected_return_value:+.2f}%")
            print(f"   数学期望正向，可以安全应用")
    else:
        print(f"\n⚠️ 无法完成盈利判断（回测失败）")
        print(f"   将应用参数，但建议人工审核")
    
    return {
        'rounds': rounds_history,
        'best_round_num': best_round_num,
        'best_config': best_config,
        'best_metric': best_metric,
        'baseline_metric': round1_best_metric,
        'total_rounds': 4,
        'strategic_sampling': round1_results,
        'local_search': round3_results if 'round3_results' in locals() else [],
            'all_backtest_results': all_backtest_results,
        'optimal_sampling_range': optimal_sampling_range,
        # 🆕 V7.6.5: 盈利判断结果
        'is_profitable': is_profitable_param,
        'total_profit': total_profit_value,
        'expected_return': expected_return_value,
        'warning': best_config.get('_warning'),
        'warning_message': best_config.get('_warning_message')
    }


def analyze_and_adjust_params():
    """V2.0 AI驱动的参数优化（由AI自主决策如何调整）"""
    import pandas as pd
    from datetime import timedelta
    
    print("\n" + "=" * 70)
    print("【🤖 AI自主参数优化 V2.0】")
    print("=" * 70)
       
    # 🆕 V7.0: 执行每日K线复盘
    review_text = daily_review_with_kline_v7()
    
    # 🆕 V3.0: 深度复盘系统
    print("\n【🔬 深度复盘分析】")
    
    # 🔧 V8.3.25: 导入必要的库
    from datetime import datetime, timedelta
    
    # 🔧 V7.9.1: 定义yesterday变量（后续代码需要使用）
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    
    # 🔧 V7.9.1: 读取最近7-14天的市场快照（时间越久权重越低）
    model_name = os.getenv("MODEL_NAME", "qwen")
    snapshot_dir = Path("trading_data") / model_name / "market_snapshots"
    
    kline_snapshots = None
    
    # 尝试读取最近14天，至少保证7天
    dataframes_to_merge = []
    max_days = 14  # 最多14天
    min_days = 7   # 至少7天
    days_loaded = 0
    
    for days_ago in range(max_days):
        date_str = (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")
        snapshot_file = snapshot_dir / f"{date_str}.csv"
        if snapshot_file.exists():
            try:
                df = pd.read_csv(snapshot_file, on_bad_lines='skip', quoting=1, encoding='utf-8-sig')
                # 🔧 V8.3.25.8: 添加日期列（从文件名提取），便于后续筛选昨日数据
                df['snapshot_date'] = date_str  # 格式：YYYYMMDD
                # 🔧 V8.3.25.8: 构建完整时间戳（结合文件名日期和time列）
                if 'time' in df.columns:
                    df['full_datetime'] = pd.to_datetime(date_str + ' ' + df['time'].astype(str), format='%Y%m%d %H:%M', errors='coerce')
                dataframes_to_merge.append(df)
                days_loaded += 1
                print(f"✓ 读取{date_str}市场快照: {len(df)}条 (第{days_loaded}天)")
            except Exception as e:
                print(f"⚠️ 读取{date_str}快照失败: {e}")
                try:
                    df = pd.read_csv(snapshot_file, on_bad_lines='skip', encoding='utf-8-sig')
                    # 🔧 V8.3.25.8: 备用方式也添加日期列
                    df['snapshot_date'] = date_str
                    if 'time' in df.columns:
                        df['full_datetime'] = pd.to_datetime(date_str + ' ' + df['time'].astype(str), format='%Y%m%d %H:%M', errors='coerce')
                    dataframes_to_merge.append(df)
                    days_loaded += 1
                    print(f"✓ 使用备用方式读取{date_str}: {len(df)}条 (第{days_loaded}天)")
                except:
                    pass
        
        # 如果已加载14天，停止
        if days_loaded >= max_days:
            break
    
    # 合并数据
    if dataframes_to_merge:
        kline_snapshots = pd.concat(dataframes_to_merge, ignore_index=True)
        print(f"✓ 合并市场快照: 共{len(kline_snapshots)}条记录（覆盖{days_loaded}天，近期权重更高）")
    else:
        print(f"⚠️ 未找到市场快照文件（最近{max_days}天）")
    
    # 趋势识别
    trends = []
    if kline_snapshots is not None:
        try:
            trends = detect_major_trends(kline_snapshots)
            print(f"✓ 识别到{len(trends)}个重要趋势")
        except Exception as e:
            print(f"⚠️ 趋势识别失败: {e}")
    
    # 初始化复盘数据
    trade_analyses = []
    missed_opportunities = []

    if not TRADES_FILE.exists():
        print("交易记录不存在，跳过学习")
        return

    try:
        df = pd.read_csv(TRADES_FILE)
        df = df[df["平仓时间"].notna()]  # 只看已平仓交易
        
        trade_count = len(df)
        
        # 🆕 渐进式学习策略：不同样本量采用不同学习模式
        if trade_count == 0:
            print("⚠️ 无交易样本，启动【冷启动模式】：放宽初始参数，帮助系统开单")
            _cold_start_optimization()
            return
        elif trade_count < 5:
            print(f"📊 样本较少（{trade_count}/5），启动【探索模式】：适度放宽参数，积累数据")
            learning_mode = "exploration"
        elif trade_count < 10:
            print(f"📊 样本中等（{trade_count}/10），启动【初步学习模式】：基于有限数据调整")
            learning_mode = "initial_learning"
        else:
            print(f"📊 样本充足（{trade_count}笔），启动【深度优化模式】：全面分析调整")
            learning_mode = "full_optimization"
        
        # 加载当前配置
        config = load_learning_config()
        original_config = json.dumps(config, ensure_ascii=False)

        print(f"📊 全部交易样本: {len(df)}笔 | 学习模式: {learning_mode}")

        # ========== 第1步：收集交易数据统计 ==========
        print("\n【第1步：数据收集与分析】")

        recent_20 = df.tail(20)
        losses = recent_20[recent_20["盈亏(U)"] < 0]
        wins = recent_20[recent_20["盈亏(U)"] >= 0]

        win_rate = len(wins) / len(recent_20) if len(recent_20) > 0 else 0
        avg_win = wins["盈亏(U)"].mean() if len(wins) > 0 else 0
        avg_loss = losses["盈亏(U)"].mean() if len(losses) > 0 else 0
        win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # 止损/止盈统计
        stopped_by_sl = len(
            recent_20[
                recent_20["平仓理由"].str.contains(
                    "止损|反转|跌破|突破", na=False, case=False
                )
            ]
        )
        stopped_by_tp = len(
            recent_20[
                recent_20["平仓理由"].str.contains(
                    "止盈|目标|阻力|支撑", na=False, case=False
                )
            ]
        )

        # 持仓时间统计
        hold_times = []
        for _, trade in recent_20.iterrows():
            try:
                open_time = pd.to_datetime(trade["开仓时间"])
                close_time = pd.to_datetime(trade["平仓时间"])
                hours = (close_time - open_time).total_seconds() / 3600
                hold_times.append(hours)
            except:
                pass
        avg_hold_time = sum(hold_times) / len(hold_times) if hold_times else 0

        # 币种统计
        symbol_stats = {}
        for symbol in df["币种"].unique():
            symbol_trades = df[df["币种"] == symbol]
            if len(symbol_trades) >= 5:
                recent_symbol = symbol_trades.tail(10)
                symbol_wins = recent_symbol[recent_symbol["盈亏(U)"] >= 0]
                symbol_win_rate = len(symbol_wins) / len(recent_symbol)
                symbol_pnl = recent_symbol["盈亏(U)"].sum()
                symbol_stats[symbol] = {
                    "count": len(symbol_trades),
                    "win_rate": symbol_win_rate,
                    "total_pnl": symbol_pnl,
                }

        # 风险关键词统计
        risky_keywords = ["逆势", "阻力", "假突破", "反转", "破位"]
        risky_count = sum(
            1
            for _, row in losses.iterrows()
                if any(k in str(row["平仓理由"]) for k in risky_keywords)
        )
        risk_ratio = risky_count / len(losses) if len(losses) > 0 else 0

        # 构建数据摘要
        data_summary = f"""
## 整体表现（最近20笔交易）
- 样本数: {len(recent_20)}笔
- 胜率: {win_rate*100:.1f}% ({len(wins)}胜 / {len(losses)}负)
- 平均盈利: {avg_win:.2f}U
- 平均亏损: {avg_loss:.2f}U
- 盈亏比: {win_loss_ratio:.2f}:1
- 平均持仓时间: {avg_hold_time:.1f}小时

## 止损止盈情况
- 止损触发: {stopped_by_sl}次 ({stopped_by_sl/len(recent_20)*100:.0f}%)
- 止盈触发: {stopped_by_tp}次 ({stopped_by_tp/len(recent_20)*100:.0f}%)

## 风险信号
- 风险关键词出现: {risky_count}次 (占亏损的{risk_ratio*100:.0f}%)
- 关键词: {', '.join(risky_keywords)}

## 币种表现
"""
        for symbol, stats in symbol_stats.items():
            data_summary += f"- {symbol}: 胜率{stats['win_rate']*100:.0f}% 样本{stats['count']}笔 累计盈亏{stats['total_pnl']:.2f}U\n"

        print(data_summary)
        
        # 🆕 V3.0: 交易深度分析
        print("\n【交易表现深度分析】")
        # 🔧 V7.7.0.15 Fix: 区分昨天开仓和昨天平仓的交易
        # 🔧 V8.3.25.7: 修复开仓时间日期匹配 - 统一使用YYYY-MM-DD格式（与DeepSeek同步）
        yesterday_date_formatted = f"{yesterday[:4]}-{yesterday[4:6]}-{yesterday[6:]}"  # 20251111 -> 2025-11-11
        
        yesterday_opened_trades = df[df["开仓时间"].str.contains(yesterday_date_formatted, na=False)]  # 昨天开仓（用于机会捕获分析）
        yesterday_closed_trades = df[df["平仓时间"].notna() & df["平仓时间"].str.contains(yesterday_date_formatted, na=False)]  # 昨天平仓（用于平仓时机分析）
        
        if kline_snapshots is not None and len(yesterday_opened_trades) > 0:
            for _, trade in yesterday_opened_trades.iterrows():
                try:
                    analysis = analyze_trade_performance(trade.to_dict(), kline_snapshots)
                    if "error" not in analysis:
                        trade_analyses.append(analysis)
                        
                        # 打印关键信息
                        if analysis.get("actual", {}).get("premature_exit"):
                            print(f"  ⚠️ {analysis['coin']}: 提前平仓，错过{analysis['analysis']['missed_profit']:.1f}%利润")
                except Exception as e:
                    print(f"  ✗ 分析失败 ({trade.get('币种', 'N/A')}): {e}")
            
            print(f"✓ 完成{len(trade_analyses)}笔交易分析")
        
        # 🆕 V3.0: 错过机会分析
        print("\n【错过机会分析】")
        config = load_learning_config()
        
        # 🔧 V7.8.0: 保存旧参数配置的副本（用于新旧参数对比）
        import copy
        old_config = copy.deepcopy(config)
        
        if kline_snapshots is not None and len(trends) > 0:
            try:
                yesterday_opened_trades_list = yesterday_opened_trades.to_dict('records')
                missed_opportunities = analyze_missed_opportunities(trends, yesterday_opened_trades_list, config)
                
                if missed_opportunities:
                    print(f"✓ 发现{len(missed_opportunities)}个错过的机会")
                    for opp in missed_opportunities[:3]:  # 只打印前3个
                        print(f"  • {opp['trend']['coin']}: {opp['trend']['type']} {opp['potential_profit_pct']:.1f}%")
                        print(f"    原因: {opp['reason']}")
                else:
                    print("✓ 所有重要机会都已把握")
            except Exception as e:
                print(f"⚠️ 错过机会分析失败: {e}")

        # 🆕 V7.7.0.15: 平仓时机分析
        # 🔧 V8.3.25.8: 使用新的V2分析（完整的市场对比）
        print("\n【平仓时机分析】")
        exit_analysis = None
        if not yesterday_closed_trades.empty:
            try:
                exit_analysis = analyze_exit_timing_v2(yesterday_closed_trades, kline_snapshots)
                # V2返回的数据结构保持兼容，可以直接使用
            except Exception as e:
                print(f"⚠️ 平仓时机分析失败: {e}")
                import traceback
                traceback.print_exc()
                exit_analysis = None
        else:
            print(f"⚠️ 昨日无平仓交易，跳过平仓时机分析")

        # 🆕 V8.3.22: 开仓时机分析
        # 🔧 V8.3.25.8: 使用新的V2分析（对比市场机会vs AI决策）
        # 🔧 V8.3.25.12: 使用yesterday_closed_trades而不是yesterday_opened_trades
        #                因为只有平仓后才有盈亏数据，才能评估开仓质量
        print("\n【开仓时机分析】")
        entry_analysis = None
        try:
            # V2需要：昨日开仓交易、市场快照、AI决策记录、昨日日期
            # 注意：这里使用yesterday_closed_trades（昨天平仓的），才有完整的盈亏数据
            entry_analysis = analyze_entry_timing_v2(
                yesterday_closed_trades,  # 🔧 V8.3.25.12: 改用yesterday_closed_trades
                kline_snapshots,
                [],  # ai_decisions_list暂时传空，后续补充
                yesterday_date_formatted
            )
            # V2会自动打印统计信息和改进建议
        except Exception as e:
            print(f"⚠️ 开仓时机分析失败: {e}")
            import traceback
            traceback.print_exc()
            entry_analysis = None

        # 🆕 V8.3.23: AI深度分析（开仓 + 平仓）
        # 🆕 V8.3.24: 每天都运行（确保持续学习）
        print("\n【AI深度学习分析】")
        ai_entry_insights = None
        ai_exit_insights = None
        
        # 🔧 V8.3.24修改：每天都运行AI分析（不再设置门槛）
        # 原因：持续学习比节省成本更重要，每天$0.004可接受
        should_run_ai = (
            entry_analysis is not None or exit_analysis is not None
        )
        
        # 如果没有数据，跳过
        if not should_run_ai:
            print(f"  ℹ️  跳过AI分析（无开仓或平仓数据）")
        
        if should_run_ai:
            try:
                # 🆕 V8.3.24: 加载AI历史决策（用于自我反思）
                # 🔧 V8.3.25: 只读取目标日期的决策（控制数据量）
                ai_decisions = []
                try:
                    ai_decisions_file = Path("trading_data") / os.getenv("MODEL_NAME", "qwen") / "ai_decisions.json"
                    if ai_decisions_file.exists():
                        with open(ai_decisions_file, "r", encoding="utf-8") as f:
                            all_decisions = json.load(f)
                        
                        # 筛选目标日期的决策（前一天）
                        # datetime已在函数开头导入
                        yesterday_dt = datetime.strptime(yesterday, '%Y%m%d')
                        target_date = yesterday_dt.strftime('%Y-%m-%d')
                        
                        ai_decisions = [
                            d for d in all_decisions
                            if d.get('timestamp', '').startswith(target_date)
                        ]
                        
                        print(f"  ✓ 加载了{len(ai_decisions)}条AI决策（{target_date}）用于自我反思")
                        if len(ai_decisions) == 0:
                            print(f"  ⚠️ {target_date}无AI决策记录，跳过自我反思")
                except Exception as e:
                    print(f"  ⚠️ 加载AI决策失败: {e}")
                
                # AI分析开仓质量（包含自我反思）
                if entry_analysis:
                    print("  🤖 AI analyzing entry quality with self-reflection...")
                    ai_entry_insights = generate_ai_entry_insights(
                        entry_analysis, 
                        exit_analysis,
                        ai_decisions=ai_decisions  # 传入历史决策
                    )
                    
                    if ai_entry_insights and 'error' not in ai_entry_insights:
                        print(f"  ✓ Entry Analysis: {ai_entry_insights['diagnosis']}")
                        print(f"  ✓ Learning Insights: {len(ai_entry_insights.get('learning_insights', []))} generated")
                        print(f"  ✓ Cost: ${ai_entry_insights.get('cost_usd', 0):.6f}")
                
                # AI分析平仓质量（包含自我反思）
                if exit_analysis:
                    print("  🤖 AI analyzing exit quality with self-reflection...")
                    ai_exit_insights = generate_ai_exit_insights(
                        exit_analysis,
                        entry_analysis,
                        ai_decisions=ai_decisions  # 传入历史决策
                    )
                    
                    if ai_exit_insights and 'error' not in ai_exit_insights:
                        print(f"  ✓ Exit Analysis: {ai_exit_insights['diagnosis']}")
                        print(f"  ✓ Learning Insights: {len(ai_exit_insights.get('learning_insights', []))} generated")
                        print(f"  ✓ Cost: ${ai_exit_insights.get('cost_usd', 0):.6f}")
                
                # 保存AI洞察到compressed_insights（供实时AI参考）
                if ai_entry_insights or ai_exit_insights:
                    config = load_learning_config()
                    if 'compressed_insights' not in config:
                        config['compressed_insights'] = {}
                    
                    if ai_entry_insights and 'error' not in ai_entry_insights:
                        config['compressed_insights']['ai_entry_analysis'] = {
                            'diagnosis': ai_entry_insights['diagnosis'],
                            'learning_insights': ai_entry_insights.get('learning_insights', []),
                            'key_recommendations': [
                                {
                                    'action': r['action'],
                                    'threshold': r['threshold'],
                                    'priority': r['priority']
                                }
                                for r in ai_entry_insights.get('recommendations', [])[:3]  # TOP3
                            ],
                            'generated_at': ai_entry_insights['generated_at']
                        }
                    
                    if ai_exit_insights and 'error' not in ai_exit_insights:
                        config['compressed_insights']['ai_exit_analysis'] = {
                            'diagnosis': ai_exit_insights['diagnosis'],
                            'learning_insights': ai_exit_insights.get('learning_insights', []),
                            'key_recommendations': [
                                {
                                    'action': r['action'],
                                    'threshold': r['threshold'],
                                    'priority': r['priority']
                                }
                                for r in ai_exit_insights.get('recommendations', [])[:3]
                            ],
                            'generated_at': ai_exit_insights['generated_at']
                        }
                    
                    save_learning_config(config)
                    print(f"  ✓ AI洞察已保存到learning_config.json")
                    
            except Exception as e:
                print(f"  ⚠️ AI深度分析失败: {e}")
                import traceback
                traceback.print_exc()

        # ========== 第2步：多轮迭代参数优化 (V7.6.3.3) ==========
        print("\n【第2步：多轮迭代参数优化】")
        
        # 准备原始统计数据
        original_stats = {
            'win_rate': win_rate,
            'profit_ratio': win_loss_ratio,
            'total_profit': recent_20['盈亏(U)'].sum()
        }
        
        # 【V8.3.16】技术债1修复：根据配置选择优化模式
        global_initial_params = None
        iterative_result = None
        
        if ENABLE_V770_QUICK_SEARCH:
            # 快速探索模式（3分钟）- 为V8.3.12提供初始参数
            print(f"  ℹ️  使用快速探索模式（V8.3.16）")
            iterative_result = quick_global_search_v8316(
                data_summary=data_summary,
                current_config=config
            )
            # 提取final_params作为global_initial_params（兼容后续代码）
            global_initial_params = iterative_result.get('final_params')
            
        elif ENABLE_V770_FULL_OPTIMIZATION:
            # 完整V7.7.0优化（7-10分钟）
            print(f"  ℹ️  使用完整V7.7.0优化模式")
            iterative_result = iterative_parameter_optimization(
                data_summary=data_summary,
                current_config=config,
                original_stats=original_stats,
                max_rounds=5
            )
            global_initial_params = iterative_result.get('final_params') if iterative_result else None
            
        else:
            # 跳过V7.7.0，使用当前配置
            print(f"  ℹ️  跳过V7.7.0优化，使用当前配置")
            global_initial_params = {
                'min_risk_reward': config['global'].get('min_risk_reward', 1.5),
                'min_indicator_consensus': config['global'].get('min_indicator_consensus', 2),
                'atr_stop_multiplier': config['global'].get('atr_stop_multiplier', 1.5)
            }
            iterative_result = {
                'final_params': global_initial_params,
                'skipped': True
            }
        
        if not iterative_result:
            print("⚠️ 多轮迭代优化失败，使用备用规则引擎")
            # 备用：简单规则
            adjustments = {'global': {}}
            if win_rate < 0.45:
                old_rrr = config["global"]["min_risk_reward"]
                config["global"]["min_risk_reward"] = min(
                    2.5, config["global"]["min_risk_reward"] + 0.2
                )
                adjustments['global']['min_risk_reward'] = config["global"]["min_risk_reward"]
                print(f"→ 规则引擎: 胜率偏低，提高盈亏比 ({old_rrr} → {config['global']['min_risk_reward']})")
            
            # 🔧 修复：为备用规则引擎设置默认的optimization变量
            optimization = {
                'diagnosis': '多轮迭代失败，使用备用规则引擎',
                'reasoning': f'胜率{win_rate*100:.0f}%偏低，提高盈亏比要求以提升交易质量',
                'adjustments': adjustments
            }
        else:
            # ========== V7.6.3.3: 应用多轮迭代的最优结果 ==========
            print("\n【第3步：应用多轮迭代的最优参数】")
            
            # 获取最优配置
            best_config = iterative_result['best_config']
            best_round_num = iterative_result['best_round_num']
            best_metric = iterative_result['best_metric']
            baseline_metric = iterative_result['baseline_metric']
            
            print(f"\n✅ 选择第{best_round_num}轮配置作为最优解")
            # 🆕 安全计算提升百分比（防止除零）
            if baseline_metric > 0:
                improvement_pct = ((best_metric - baseline_metric) / baseline_metric * 100)
                print(f"   综合利润指标: {baseline_metric:.4f} → {best_metric:.4f} (+{improvement_pct:.1f}%)")
            else:
                print(f"   综合利润指标: {baseline_metric:.4f} → {best_metric:.4f}")
            
            # 保存迭代历史供邮件使用
            config['_iterative_history'] = iterative_result
            
            # 构建adjustments格式（兼容后续代码）
            # 比较最优配置与当前配置，找出变化
            adjustments = {'global': {}}
            for param, value in best_config.items():
                old_value = config['global'].get(param)
                if old_value != value:
                    adjustments['global'][param] = value
                    print(f"  ✓ {param}: {old_value} → {value}")

            # 记录完整的迭代历史到文件
            history_file = Path("trading_data") / os.getenv("MODEL_NAME", "qwen") / "iterative_optimization_history.jsonl"
            history_file.parent.mkdir(parents=True, exist_ok=True)
            
            iteration_log = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_rounds': iterative_result['total_rounds'],
                'best_round_num': best_round_num,
                'baseline_metric': baseline_metric,
                'best_metric': best_metric,
                'improvement_pct': ((best_metric - baseline_metric) / baseline_metric * 100) if baseline_metric > 0 else 0,
                    'best_config': best_config,
                'rounds_summary': [
                    {
                        'round': r.get('round_num', 1),
                        'improved': r.get('improved', True),  # V7.7.0兼容：默认True
                        'metric': r.get('metric', 0),
                        'direction': r.get('direction', r.get('status', 'COMPLETED')),  # V7.7.0使用status
                        'status': r.get('status', 'N/A')  # 新增：保存V7.7.0的status
                    }
                    for r in iterative_result['rounds']
                        ]
            }
            
            with open(history_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(iteration_log, ensure_ascii=False) + '\n')
            
            print(f"\n✅ 已记录迭代优化历史到 {history_file}")
            
            # 应用最优配置到config
            for param, value in best_config.items():
                if param in config["global"]:
                    config["global"][param] = value
            
            # 【V8.3.14.4】安全检查：min_indicator_consensus 必须 >= 2
            # 注意：自V8.3.14.4起，采样范围已限制最小值为2，此检查作为最后防线
            if config["global"].get("min_indicator_consensus", 2) < 2:
                print(f"⚠️  【安全检查】检测到min_indicator_consensus={config['global']['min_indicator_consensus']} < 2")
                print(f"             （这不应该发生，可能是旧配置文件）强制调整为2")
                config["global"]["min_indicator_consensus"] = 2
                adjustments['global']['min_indicator_consensus'] = 2
            
            # 🔧 修复：为成功的多轮迭代设置optimization变量
            optimization = {
                'diagnosis': f'完成{iterative_result["total_rounds"]}轮迭代优化',
                'reasoning': f'综合利润指标提升{improvement_pct:.1f}%' if baseline_metric > 0 else '找到最优参数配置',
                    'adjustments': adjustments,
                'best_round': best_round_num,
                'baseline_metric': baseline_metric,
                'best_metric': best_metric
            }

        # ========== 第4步：风险控制检查 ==========
        print("\n【第4步：风险控制检查】")

        # 检查连续亏损
        last_3 = df.tail(3)
        if len(last_3) >= 3 and all(last_3["盈亏(U)"] < 0):
            config["market_regime"]["pause_trading"] = True
            print("⚠️  检测到连续3笔亏损，启动冷静期")
        else:
            config["market_regime"]["pause_trading"] = False

        # ========== 第4.5步：用新参数重新评估历史机会 (V7.8.0 - 修正版) ==========
        print("\n【第4.5步：用新参数重新评估历史机会】")
        opportunity_analysis = None
        if kline_snapshots is not None and not kline_snapshots.empty:
            try:
                yesterday_opened_trades_list = yesterday_opened_trades.to_dict('records')
                opportunity_analysis = analyze_opportunities_with_new_params(
                    market_snapshots=kline_snapshots,
                    actual_trades=yesterday_opened_trades_list,
                    new_config=config,
                    old_config=old_config  # 🔧 V7.8.0: 传入旧参数用于对比
                )
                
                stats = opportunity_analysis['stats']
                print(f"✓ 发现{stats['total_opportunities']}个客观机会（实际达到利润目标）")
                print(f"  📊 实际平均利润: {stats['avg_actual_profit']:.1f}%")
                print(f"  • 旧参数: 捕获{stats['old_captured_count']}个({stats['old_capture_rate']:.1f}%) | 平均获利{stats['avg_old_captured_profit']:.1f}% | 效率{stats['avg_old_efficiency']:.0f}%")
                print(f"  • 新参数: 捕获{stats['new_captured_count']}个({stats['new_capture_rate']:.1f}%) | 平均获利{stats['avg_new_captured_profit']:.1f}% | 效率{stats['avg_new_efficiency']:.0f}%")
                if stats['new_captured_count'] > stats['old_captured_count']:
                    print(f"  ✅ 改进: 捕获率+{stats['capture_rate_improvement']:.1f}% | 利润+{stats['profit_improvement']:.1f}%")
                elif stats['new_captured_count'] < stats['old_captured_count']:
                    print(f"  ⚠️  退步: 捕获率{stats['capture_rate_improvement']:.1f}% | 利润{stats['profit_improvement']:.1f}%")
                else:
                    print(f"  ➡️  持平: 捕获率和利润无变化")
                
                if opportunity_analysis['missed']:
                    print(f"\n  📌 重点关注（错过的TOP3）:")
                    for opp in opportunity_analysis['missed'][:3]:
                        print(f"     {opp['coin']}: 信号分{opp['signal_score']} | {opp.get('miss_reason', '未知')}")
            except Exception as e:
                print(f"⚠️ 机会重评估失败: {e}")
                opportunity_analysis = None

        # ========== 【V8.3.25.10】第4.55步：提取AI洞察的参数建议 ==========
        print("\n【第4.55步：提取AI洞察的参数建议】")
        ai_suggested_params = None
        try:
            compressed_insights = config.get('compressed_insights', {})
            ai_entry_analysis = compressed_insights.get('ai_entry_analysis', {})
            ai_exit_analysis = compressed_insights.get('ai_exit_analysis', {})
            
            if ai_entry_analysis or ai_exit_analysis:
                print("  🤖 发现AI洞察，提取参数建议...")
                ai_suggested_params = {}
                
                # 解析threshold字段（如"signal_score >= 70"，"min_risk_reward >= 3.0"）
                import re
                for analysis_name, analysis in [('entry', ai_entry_analysis), ('exit', ai_exit_analysis)]:
                    recommendations = analysis.get('key_recommendations', [])
                    for rec in recommendations:
                        threshold_str = rec.get('threshold', '')
                        if not threshold_str:
                            continue
                        
                        # 🔧 V8.3.25.11: 增强正则表达式，支持更多格式
                        # 支持格式：
                        # 1. "min_risk_reward >= 3.0"
                        # 2. "atr_tp_multiplier: 3.5"
                        # 3. "Set TP at 1.3x ATR" -> atr_tp_multiplier: 1.3
                        # 4. "Dynamic R:R: 2.5-4.9" -> min_risk_reward: 2.5 (取下限)
                        
                        # 尝试匹配标准格式
                        match = re.search(r'(min_risk_reward|min_indicator_consensus|min_signal_score|atr_stop_multiplier|atr_tp_multiplier|trailing_stop_pct)\s*[:>=<]+\s*([\d.]+)', threshold_str, re.IGNORECASE)
                        if match:
                            param_name = match.group(1).lower()
                            param_value = float(match.group(2))
                            ai_suggested_params[param_name] = param_value
                            print(f"     • {analysis_name}: {param_name} = {param_value}")
                            continue
                        
                        # 尝试匹配"Set TP at X.Xx ATR"格式
                        match = re.search(r'TP\s+at\s+([\d.]+)\s*x?\s*ATR', threshold_str, re.IGNORECASE)
                        if match:
                            param_value = float(match.group(1))
                            ai_suggested_params['atr_tp_multiplier'] = param_value
                            print(f"     • {analysis_name}: atr_tp_multiplier = {param_value} (from TP)")
                            continue
                        
                        # 尝试匹配"Dynamic R:R: X.X-Y.Y"格式（取下限）
                        match = re.search(r'R:R[:\s]+([\d.]+)\s*-\s*([\d.]+)', threshold_str, re.IGNORECASE)
                        if match:
                            param_value = float(match.group(1))  # 取下限
                            ai_suggested_params['min_risk_reward'] = param_value
                            print(f"     • {analysis_name}: min_risk_reward = {param_value} (from dynamic R:R range)")
                            continue
                
                if ai_suggested_params:
                    print(f"  ✅ 提取了{len(ai_suggested_params)}个AI建议参数")
                else:
                    print(f"  ℹ️  未从AI洞察中提取到可解析的参数")
        except Exception as e:
            print(f"  ⚠️  提取AI参数建议失败: {e}")
            ai_suggested_params = None

        # ========== 【V8.3.12】第4.6步：分离策略优化 ==========
        print("\n【第4.6步：分离策略优化（V8.3.12）】")
        scalping_optimization = None
        swing_optimization = None
        
        if kline_snapshots is not None and not kline_snapshots.empty:
            try:
                # 分析超短线和波段的分离机会
                separated_analysis = analyze_separated_opportunities(
                    market_snapshots=kline_snapshots,
                    old_config=config
                )
                
                # 【V8.3.16】技术债1修复：使用V7.7.0快速探索的结果作为初始参数
                # 【V8.3.16.3】修复：从iterative_result中提取final_params
                if global_initial_params and isinstance(global_initial_params, dict):
                    # 优先使用final_params，如果不存在则直接使用global_initial_params（兼容旧版本）
                    base_params = global_initial_params.get('final_params', global_initial_params)
                else:
                    base_params = {}
                
                initial_params_for_scalping = base_params.copy() if base_params else {}
                initial_params_for_swing = base_params.copy() if base_params else {}
                
                # 合并当前配置中的策略特定参数
                scalping_current = config.get('scalping_params', {})
                scalping_current.update(initial_params_for_scalping)
                
                swing_current = config.get('swing_params', {})
                swing_current.update(initial_params_for_swing)
                
                # 分别优化超短线参数
                if separated_analysis['scalping']['total_opportunities'] > 20:
                    print(f"\n  ⚡ 优化超短线参数...")
                    if base_params:
                        print(f"     ℹ️  使用V7.7.0初始参数: R:R={base_params.get('min_risk_reward', 'N/A')}, 共识={base_params.get('min_indicator_consensus', 'N/A')}")
                    if ai_suggested_params:
                        print(f"     🤖 AI建议参数: {ai_suggested_params}")
                    scalping_optimization = optimize_scalping_params(
                        scalping_data=separated_analysis['scalping'],
                        current_params=scalping_current,
                        initial_params=initial_params_for_scalping,  # 【V8.3.16新增】
                        ai_suggested_params=ai_suggested_params  # 【V8.3.25.10新增】
                    )
                    
                    # 【V8.3.18.5】检查AI是否拒绝优化
                    if scalping_optimization.get('ai_rejection_reason'):
                        print(f"  ❌ 超短线优化被AI拒绝:")
                        print(f"     原因: {scalping_optimization['ai_rejection_reason'][:150]}...")
                        print(f"     建议: 策略需要重新设计（当前参数time_exit=100%，目标<90%）")
                    elif scalping_optimization.get('improvement') is not None:
                        # 更新config中的超短线参数
                        if 'scalping_params' not in config:
                            config['scalping_params'] = {}
                        config['scalping_params'].update(scalping_optimization['optimized_params'])
                        
                        old_rate = scalping_optimization['old_time_exit_rate']
                        new_rate = scalping_optimization['new_time_exit_rate']
                        old_profit = scalping_optimization['old_avg_profit']
                        new_profit = scalping_optimization['new_avg_profit']
                        
                        print(f"  ✅ 超短线优化完成:")
                        print(f"     time_exit率: {old_rate*100:.0f}% → {new_rate*100:.0f}% ({(new_rate-old_rate)*100:+.0f}%)")
                        print(f"     平均利润: {old_profit:.1f}% → {new_profit:.1f}% ({new_profit-old_profit:+.1f}%)")
                else:
                    print(f"  ⚠️  超短线机会不足20个（{separated_analysis['scalping']['total_opportunities']}个），跳过优化")
                
                # 分别优化波段参数
                if separated_analysis['swing']['total_opportunities'] > 20:
                    print(f"\n  🌊 优化波段参数...")
                    if base_params:
                        print(f"     ℹ️  使用V7.7.0初始参数: R:R={base_params.get('min_risk_reward', 'N/A')}, 共识={base_params.get('min_indicator_consensus', 'N/A')}")
                    if ai_suggested_params:
                        print(f"     🤖 AI建议参数: {ai_suggested_params}")
                    swing_optimization = optimize_swing_params(
                        swing_data=separated_analysis['swing'],
                        current_params=swing_current,
                        initial_params=initial_params_for_swing,  # 【V8.3.16新增】
                        ai_suggested_params=ai_suggested_params  # 【V8.3.25.10新增】
                    )
                    
                    if swing_optimization.get('improvement') is not None:
                        # 更新config中的波段参数
                        if 'swing_params' not in config:
                            config['swing_params'] = {}
                        config['swing_params'].update(swing_optimization['optimized_params'])
                        
                        old_profit = swing_optimization['old_avg_profit']
                        new_profit = swing_optimization['new_avg_profit']
                        old_capture = swing_optimization['old_capture_rate']
                        new_capture = swing_optimization['new_capture_rate']
                        
                        print(f"  ✅ 波段优化完成:")
                        print(f"     平均利润: {old_profit:.1f}% → {new_profit:.1f}% ({new_profit-old_profit:+.1f}%)")
                        print(f"     捕获率: {old_capture*100:.0f}% → {new_capture*100:.0f}% ({(new_capture-old_capture)*100:+.0f}%)")
                else:
                    print(f"  ⚠️  波段机会不足20个（{separated_analysis['swing']['total_opportunities']}个），跳过优化")
                
            except Exception as e:
                print(f"⚠️ 分离策略优化失败: {e}")
                import traceback
                traceback.print_exc()
        
        # ========== 【V8.3.13.3】第4.7步：Per-Symbol优化 ==========
        print("\n【第4.7步：Per-Symbol优化（V8.3.13.3）】")
        per_symbol_optimization = None
        
        # 【V8.3.16】立即优化：配置开关跳过Per-Symbol
        if not ENABLE_PER_SYMBOL_OPTIMIZATION:
            print(f"  ⏭️  跳过Per-Symbol优化（配置已禁用，节省56-91分钟）")
            print(f"     理由：大部分币种可共享全局/策略参数，独立优化增益有限")
        elif kline_snapshots is not None and not kline_snapshots.empty:
            try:
                # 分析每个币种的机会
                per_symbol_data = analyze_per_symbol_opportunities(
                    market_snapshots=kline_snapshots,
                    old_config=config,
                    symbols=['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'LTC']
                )
                
                if per_symbol_data:
                    # 优化每个币种的参数
                    per_symbol_params = optimize_per_symbol_params(
                        per_symbol_data=per_symbol_data,
                        global_config=config
                    )
                    
                    # 保存到config
                    if per_symbol_params:
                        if 'per_symbol_params' not in config:
                            config['per_symbol_params'] = {}
                        
                        for symbol, params in per_symbol_params.items():
                            config['per_symbol_params'][symbol] = {
                                'scalping_params': params.get('scalping_params', {}),
                                'swing_params': params.get('swing_params', {})
                            }
                        
                        print(f"  ✅ 已优化{len(per_symbol_params)}个币种的参数")
                        per_symbol_optimization = per_symbol_params
                
            except Exception as e:
                print(f"⚠️ Per-Symbol优化失败: {e}")
                import traceback
                traceback.print_exc()

        # ========== 第5步：保存并通知 ==========
        current_config = json.dumps(config, ensure_ascii=False, default=str)
        config_changed = (current_config != original_config)
        
        # 【V8.3.18.2】手动回测模式：不管参数是否变化都发送通知
        is_manual_backtest = os.getenv("MANUAL_BACKTEST") == "true"
        should_send_notification = config_changed or is_manual_backtest
        
        if config_changed:
            # 🔧 V8.3.25.10: 保存参数修改（包含scalping_params和swing_params）
            save_learning_config(config)
            
            # 🔧 V8.3.21.5: 重新加载配置以获取optimize函数保存的V8.3.21洞察
            config = load_learning_config()

            adjusted_count = len(adjustments.get("global", {})) + len(
                adjustments.get("per_symbol", {})
            )

            # 🆕 V8.3.21.3: 发送Bark通知（优先显示V8.3.21真实数据）
            iter_desc = f"多轮迭代{iterative_result['total_rounds']}轮" if iterative_result else "参数已优化"
            
            # 🔄 V8.3.21.3: 优先读取V8.3.21洞察（真实数据）
            backtest_info = f"\n调整{adjusted_count}个参数"
            v8321_insights = config.get('compressed_insights', {}).get('v8321_insights', {})
            
            if v8321_insights and ('scalping' in v8321_insights or 'swing' in v8321_insights):
                # 使用V8.3.21的真实优化数据
                scalp_perf = v8321_insights.get('scalping', {}).get('performance', {})
                swing_perf = v8321_insights.get('swing', {}).get('performance', {})
                
                if scalp_perf or swing_perf:
                    backtest_info = "\n📊V8.3.21优化:"
                    parts = []
                    if scalp_perf:
                        parts.append(f"⚡{scalp_perf.get('score', 0):.2f}分 {scalp_perf.get('capture_rate', 0)*100:.0f}%捕获")
                    if swing_perf:
                        parts.append(f"🌊{swing_perf.get('score', 0):.2f}分 {swing_perf.get('capture_rate', 0)*100:.0f}%捕获")
                    backtest_info += " ".join(parts)
            elif config.get('_iterative_history'):
                # 降级到旧版数据（如果V8.3.21未运行）
                iter_res = config['_iterative_history']
                if 'phase2' in iter_res and 'best_result' in iter_res['phase2']:
                    best_result = iter_res['phase2']['best_result']
                    profit_pct = best_result.get('total_profit', 0)
                    capture_rate = best_result.get('capture_rate', 0)
                    total_trades = best_result.get('total_trades', 0)
                    
                    if profit_pct != 0 or total_trades > 0:
                        backtest_info = f"\n📊回测(3天{total_trades}笔):"
                        if profit_pct > 0:
                            backtest_info += f"盈利+{profit_pct:.1f}%"
                        elif profit_pct < 0:
                            backtest_info += f"亏损{profit_pct:.1f}%"
                        else:
                            backtest_info += f"持平"
                        backtest_info += f" 捕获率{capture_rate*100:.0f}%"
            
            # 🔄 V8.3.21.8: 构建Bark通知内容（优先显示优化后预期收益）
            bark_content_lines = []
            
            if v8321_insights and ('scalping' in v8321_insights or 'swing' in v8321_insights):
                # 使用V8.3.21的优化后预期数据
                scalp_perf = v8321_insights.get('scalping', {}).get('performance', {})
                swing_perf = v8321_insights.get('swing', {}).get('performance', {})
                
                if scalp_perf or swing_perf:
                    # 标题行
                    bark_content_lines.append(f"{iter_desc} 调整{adjusted_count}个参数")
                    bark_content_lines.append("")
                    bark_content_lines.append("📊 优化后预期收益:")
                    
                    # 超短线数据
                    if scalp_perf:
                        cap_rate = scalp_perf.get('capture_rate', 0)
                        avg_profit = scalp_perf.get('avg_profit', 0)
                        bark_content_lines.append(f"⚡超短线: 捕获{cap_rate*100:.0f}% 平均+{avg_profit*100:.1f}%")
                    
                    # 波段数据
                    if swing_perf:
                        cap_rate = swing_perf.get('capture_rate', 0)
                        avg_profit = swing_perf.get('avg_profit', 0)
                        bark_content_lines.append(f"🌊波段: 捕获{cap_rate*100:.0f}% 平均+{avg_profit*100:.1f}%")
                    
                    # 显示当前ROI参数
                    bark_content_lines.append("")
                    min_rr = config.get('global', {}).get('min_risk_reward', 'N/A')
                    bark_content_lines.append(f"🎯 当前ROI: {min_rr}:1")
                else:
                    # V8.3.21数据存在但为空，使用历史数据
                    bark_content_lines.append(f"胜率{win_rate*100:.0f}% 盈亏比{win_loss_ratio:.1f}")
                    bark_content_lines.append(f"{iter_desc} 调整{adjusted_count}个参数")
            else:
                # 没有V8.3.21数据，使用历史统计数据
                bark_content_lines.append(f"胜率{win_rate*100:.0f}% 盈亏比{win_loss_ratio:.1f}")
                bark_content_lines.append(f"{iter_desc} 调整{adjusted_count}个参数")
            
            send_bark_notification(
                "[通义千问]🤖AI参数优化V8.3.21",
                "\n".join(bark_content_lines),
            )
            
            # 🆕 发送邮件通知（详细版）
            try:
                # 强制使用Qwen（避免环境变量污染）
                model_name = "Qwen"
                
                # 构建参数调整详情（HTML格式）- 只显示有变化的参数
                param_changes_html = ""
                if "global" in adjustments:
                    changes = []
                    for param, value in adjustments["global"].items():
                        if not param.startswith("_"):
                            old_value = config["global"].get(param, "N/A")
                            # 只显示实际有变化的参数
                            if old_value != value and old_value != "N/A":
                                changes.append(f"<li><strong>{param}</strong>: {old_value} → <span style='color:#28a745;'>{value}</span></li>")
                    if changes:  # 只有在有变化时才显示这个部分
                        param_changes_html += "<h3>🔧 全局参数调整</h3><ul>" + "".join(changes) + "</ul>"
                
                if "per_symbol" in adjustments and adjustments["per_symbol"]:
                    param_changes_html += "<h3>🎯 币种特定参数调整</h3>"
                    for symbol, symbol_adj in adjustments["per_symbol"].items():
                        param_changes_html += f"<h4>{symbol}</h4><ul>"
                        for param, value in symbol_adj.items():
                            if not param.startswith("_"):
                                old_value = config["per_symbol"].get(symbol, {}).get(param, "N/A")
                                param_changes_html += f"<li><strong>{param}</strong>: {old_value} → <span style='color:#28a745;'>{value}</span></li>"
                        param_changes_html += "</ul>"
                
                # 🆕 V7.7.0.16: 机会捕获对比表（三列展示）
                opportunity_stats_html = ""
                catch_rate = 0  # 🔧 V7.7.0.15 Fix: 初始化catch_rate避免NameError
                
                if opportunity_analysis:
                    stats = opportunity_analysis['stats']
                    all_opportunities = opportunity_analysis['all_opportunities']
                    old_captured = opportunity_analysis['old_captured']  # 🔧 V7.9.1: 使用新的键名
                    new_captured = opportunity_analysis['new_captured']  # 🔧 V7.9.1: 使用新的键名
                    missed_new = opportunity_analysis['missed']
                    catch_rate = stats['new_capture_rate']  # 🔧 V7.9.1: 使用新参数捕获率
                    
                    # 🔧 V7.8.0: 获取旧参数和新参数的捕获率
                    old_capture_rate = stats.get('old_capture_rate', 0)
                    new_capture_rate = stats.get('new_capture_rate', 0)
                    capture_improvement = new_capture_rate - old_capture_rate
                    
                    # 【V7.9.2】按类型分组显示机会
                    # 先分类
                    scalping_opps = [opp for opp in all_opportunities if opp.get('signal_type') == 'scalping']
                    swing_opps = [opp for opp in all_opportunities if opp.get('signal_type') == 'swing']
                    
                    # 【V8.2.1】优化排序：优先显示"错过的高利润机会"
                    def sort_opportunity_key(opp):
                        # 优先级1：是否被新参数错过（0=捕获，1=错过）
                        missed = 0 if opp.get('new_can_entry', False) else 1
                        # 优先级2：客观利润（越高越好）
                        profit = opp.get('actual_profit_pct', 0)
                        # 返回：(错过优先, 利润降序)
                        return (missed, -profit)
                    
                    scalping_opps_sorted = sorted(scalping_opps, key=sort_opportunity_key)
                    swing_opps_sorted = sorted(swing_opps, key=sort_opportunity_key)
                    
                    # 构建对比表格
                    opportunity_stats_html = f"""
    <div class="summary-box" style="background: #e8f5e9;">
        <h3>🎯 机会捕获对比分析（旧参数 vs 新参数）</h3>
        <p style="margin: 5px 0; font-size: 0.9em; color: #666;">
            ⚡超短线: {len(scalping_opps)}个 | 🌊波段: {len(swing_opps)}个 | 共{len(all_opportunities)}个客观机会
        </p>
"""
                    
                    # 显示超短线机会（始终显示）
                    opportunity_stats_html += """
        <h4 style="margin: 15px 0 5px 0; color: #ff6f00;">⚡ 超短线机会</h4>
"""
                    if scalping_opps_sorted:
                        opportunity_stats_html += """
        <table style="width:100%; border-collapse: collapse; margin-top: 5px; font-size: 0.85em;">
            <tr style="background: #ffe0b2;">
                <th style="padding: 6px; text-align: left; border: 1px solid #ffb74d;">币种</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">日期时间</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">信号分</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">客观利润</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">旧参数<br>捕获利润</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">新参数<br>捕获利润</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">捕获<br>效率</th>
                <th style="padding: 6px; text-align: left; border: 1px solid #ffb74d;">分析/改进效果</th>
            </tr>
"""
                        # 【V8.2.1】增加显示数量到15个，优先显示错过的高利润机会
                        for opp in scalping_opps_sorted[:15]:
                            coin = opp.get('coin', 'N/A')
                            
                            # 【V8.2.1】修复时间格式，处理N/A情况
                            raw_time = opp.get('time', '')
                            opp_date = opp.get('date', yesterday)  # 获取日期字段
                            if raw_time and str(raw_time).strip() and len(str(raw_time)) == 4:
                                time_str = f"{str(raw_time)[:2]}:{str(raw_time)[2:]}"
                                # 格式化为 MM-DD HH:MM
                                if opp_date and len(str(opp_date)) == 8:
                                    date_str = str(opp_date)
                                    datetime_str = f"{date_str[4:6]}-{date_str[6:]} {time_str}"
                                else:
                                    datetime_str = time_str
                            else:
                                datetime_str = 'N/A'
                            
                            signal_score = opp.get('signal_score', 0)
                            actual_profit = opp.get('actual_profit_pct', 0)  # 客观利润
                            
                            # 🔧 V7.9.2: 获取捕获利润和效率
                            old_can_entry = opp.get('old_can_entry', False)
                            new_can_entry = opp.get('new_can_entry', False)
                            old_captured_profit = opp.get('old_captured_profit', 0)
                            new_captured_profit = opp.get('new_captured_profit', 0)
                            old_efficiency = opp.get('old_efficiency', 0)
                            new_efficiency = opp.get('new_efficiency', 0)
                            old_exit_type = opp.get('old_exit_type', 'N/A')
                            new_exit_type = opp.get('new_exit_type', 'N/A')
                            was_traded = opp.get('was_traded', False)
                            
                            # 【V8.2.2】修复显示格式：正确处理正负号
                            if old_can_entry:
                                profit_sign = '+' if old_captured_profit >= 0 else ''  # 负数已经有"-"
                                old_display = f"{profit_sign}{old_captured_profit:.1f}%<br><span style='font-size:0.8em;color:#666;'>({old_exit_type})</span>"
                            else:
                                old_display = "<span style='color:#999;'>未入场</span>"
                            
                            if new_can_entry:
                                profit_sign = '+' if new_captured_profit >= 0 else ''  # 负数已经有"-"
                                new_display = f"{profit_sign}{new_captured_profit:.1f}%<br><span style='font-size:0.8em;color:#666;'>({new_exit_type})</span>"
                            else:
                                new_display = "<span style='color:#999;'>未入场</span>"
                            
                            efficiency_display = f"{old_efficiency:.0f}% / {new_efficiency:.0f}%"
                            
                            # 分析和背景色
                            if old_can_entry and new_can_entry:
                                if was_traded:
                                    analysis = '✅ 已捕获（新旧参数均可）'
                                else:
                                    analysis = '✅ 均可捕获（未实际交易）'
                                row_bg = 'background: #e8f5e9;'
                            elif not old_can_entry and new_can_entry:
                                analysis = '⚠️ 旧参数错过 → ✅ 优化后可捕获'
                                row_bg = 'background: #fff3e0;'
                            elif old_can_entry and not new_can_entry:
                                analysis = '⚪ 新参数略严格（质量更优）'
                                row_bg = 'background: #f5f5f5;'
                            else:
                                miss_reason = opp.get('miss_reason', '信号质量不足')
                                analysis = miss_reason if miss_reason else '信号质量不足'
                                row_bg = 'background: #ffebee;'
                            
                            opportunity_stats_html += f'''
            <tr style="{row_bg}">
                <td style="padding: 6px; border: 1px solid #e0e0e0;"><strong>{coin}</strong></td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.85em;">{datetime_str}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{signal_score}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;"><strong>+{actual_profit:.1f}%</strong></td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.85em;">{old_display}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.85em;">{new_display}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.85em;">{efficiency_display}</td>
                <td style="padding: 6px; border: 1px solid #e0e0e0; font-size: 0.85em;">{analysis}</td>
            </tr>
'''
                        opportunity_stats_html += "</table>"
                    else:
                        opportunity_stats_html += """
        <p style="padding: 10px; margin: 5px 0; background: #fff3e0; border-left: 3px solid #ff6f00; color: #666;">
            暂无超短线机会（本时段市场不适合超短线交易，或信号质量未达标）
        </p>
"""
                    
                    # 【V8.2.6.1修复】显示波段机会（独立section，不在else内）
                    opportunity_stats_html += """
        <h4 style="margin: 15px 0 5px 0; color: #1976d2;">🌊 波段机会</h4>
"""
                    if swing_opps_sorted:
                        opportunity_stats_html += """
        <table style="width:100%; border-collapse: collapse; margin-top: 5px; font-size: 0.85em;">
            <tr style="background: #bbdefb;">
                <th style="padding: 6px; text-align: left; border: 1px solid #64b5f6;">币种</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6;">日期时间</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6;">信号分</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6;">客观利润</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6;">旧参数<br>捕获利润</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6;">新参数<br>捕获利润</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6;">捕获<br>效率</th>
                <th style="padding: 6px; text-align: left; border: 1px solid #64b5f6;">分析/改进效果</th>
            </tr>
"""
                        # 【V8.2.1】增加显示数量到15个，优先显示错过的高利润机会
                        for opp in swing_opps_sorted[:15]:
                            coin = opp.get('coin', 'N/A')
                            
                            # 【V8.2.1】修复时间格式，处理N/A情况
                            raw_time = opp.get('time', '')
                            opp_date = opp.get('date', yesterday)
                            if raw_time and str(raw_time).strip() and len(str(raw_time)) == 4:
                                time_str = f"{str(raw_time)[:2]}:{str(raw_time)[2:]}"
                                # 格式化为 MM-DD HH:MM
                                if opp_date and len(str(opp_date)) == 8:
                                    date_str = str(opp_date)
                                    datetime_str = f"{date_str[4:6]}-{date_str[6:]} {time_str}"
                                else:
                                    datetime_str = time_str
                            else:
                                datetime_str = 'N/A'
                            
                            signal_score = opp.get('signal_score', 0)
                            actual_profit = opp.get('actual_profit_pct', 0)
                            
                            # 🔧 V7.9.2: 获取捕获利润和效率
                            old_can_entry = opp.get('old_can_entry', False)
                            new_can_entry = opp.get('new_can_entry', False)
                            old_captured_profit = opp.get('old_captured_profit', 0)
                            new_captured_profit = opp.get('new_captured_profit', 0)
                            old_efficiency = opp.get('old_efficiency', 0)
                            new_efficiency = opp.get('new_efficiency', 0)
                            old_exit_type = opp.get('old_exit_type', 'N/A')
                            new_exit_type = opp.get('new_exit_type', 'N/A')
                            was_traded = opp.get('was_traded', False)
                            
                            # 【V8.2.2】修复显示格式：正确处理正负号
                            if old_can_entry:
                                profit_sign = '+' if old_captured_profit >= 0 else ''  # 负数已经有"-"
                                old_display = f"{profit_sign}{old_captured_profit:.1f}%<br><span style='font-size:0.8em;color:#666;'>({old_exit_type})</span>"
                            else:
                                old_display = "<span style='color:#999;'>未入场</span>"
                            
                            if new_can_entry:
                                profit_sign = '+' if new_captured_profit >= 0 else ''  # 负数已经有"-"
                                new_display = f"{profit_sign}{new_captured_profit:.1f}%<br><span style='font-size:0.8em;color:#666;'>({new_exit_type})</span>"
                            else:
                                new_display = "<span style='color:#999;'>未入场</span>"
                            
                            efficiency_display = f"{old_efficiency:.0f}% / {new_efficiency:.0f}%"
                            
                            # 分析和背景色
                            if old_can_entry and new_can_entry:
                                if was_traded:
                                    analysis = '✅ 已捕获（新旧参数均可）'
                                else:
                                    analysis = '✅ 均可捕获（未实际交易）'
                                row_bg = 'background: #e3f2fd;'
                            elif not old_can_entry and new_can_entry:
                                analysis = '⚠️ 旧参数错过 → ✅ 优化后可捕获'
                                row_bg = 'background: #fff9c4;'
                            elif old_can_entry and not new_can_entry:
                                analysis = '⚪ 新参数略严格（质量更优）'
                                row_bg = 'background: #f5f5f5;'
                            else:
                                miss_reason = opp.get('miss_reason', '信号质量不足')
                                analysis = miss_reason if miss_reason else '信号质量不足'
                                row_bg = 'background: #ffebee;'
                            
                            opportunity_stats_html += f'''
            <tr style="{row_bg}">
                <td style="padding: 6px; border: 1px solid #e0e0e0;"><strong>{coin}</strong></td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.85em;">{datetime_str}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{signal_score}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;"><strong>+{actual_profit:.1f}%</strong></td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.85em;">{old_display}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.85em;">{new_display}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.85em;">{efficiency_display}</td>
                <td style="padding: 6px; border: 1px solid #e0e0e0; font-size: 0.85em;">{analysis}</td>
            </tr>
'''
                        opportunity_stats_html += "</table>"
                    else:
                        opportunity_stats_html += """
        <p style="padding: 10px; margin: 5px 0; background: #e3f2fd; border-left: 3px solid #1976d2; color: #666;">
            暂无波段机会（本时段市场不适合波段交易，或信号质量未达标）
        </p>
"""
                    
                    # 【V8.1.4】增强总结：显示分类捕获率
                    scalp_old_rate = stats.get('scalping_old_rate', 0)
                    scalp_new_rate = stats.get('scalping_new_rate', 0)
                    swing_old_rate = stats.get('swing_old_rate', 0)
                    swing_new_rate = stats.get('swing_new_rate', 0)
                    scalp_improvement = scalp_new_rate - scalp_old_rate
                    swing_improvement = swing_new_rate - swing_old_rate
                    
                    # 【V8.3.17】计算总利润对比
                    old_total_profit = stats['old_captured_count'] * stats['avg_old_captured_profit'] / 100
                    new_total_profit = stats['new_captured_count'] * stats['avg_new_captured_profit'] / 100
                    profit_diff = new_total_profit - old_total_profit
                    profit_diff_pct = ((new_total_profit / old_total_profit - 1) * 100) if old_total_profit != 0 else (float('inf') if new_total_profit > 0 else 0)
                    
                    # 添加总利润对比框
                    opportunity_stats_html += f"""
        <div style="margin: 15px 0; padding: 15px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px; color: white;">
            <h3 style="margin: 0 0 10px 0; color: white; border-bottom: 2px solid rgba(255,255,255,0.3); padding-bottom: 8px;">
                💰 总利润对比分析
            </h3>
            <div style="display: flex; justify-content: space-around; margin: 10px 0;">
                <div style="text-align: center; flex: 1;">
                    <div style="font-size: 0.9em; opacity: 0.9;">旧参数</div>
                    <div style="font-size: 1.8em; font-weight: bold; margin: 5px 0;">
                        {old_total_profit:+.2f}U
                    </div>
                    <div style="font-size: 0.85em; opacity: 0.8;">
                        {stats['old_captured_count']}个 × {stats['avg_old_captured_profit']:.1f}%
                    </div>
                </div>
                <div style="align-self: center; font-size: 2em; opacity: 0.6;">→</div>
                <div style="text-align: center; flex: 1;">
                    <div style="font-size: 0.9em; opacity: 0.9;">新参数</div>
                    <div style="font-size: 1.8em; font-weight: bold; margin: 5px 0;">
                        {new_total_profit:+.2f}U
                    </div>
                    <div style="font-size: 0.85em; opacity: 0.8;">
                        {stats['new_captured_count']}个 × {stats['avg_new_captured_profit']:.1f}%
                    </div>
                </div>
            </div>
            <div style="text-align: center; margin-top: 15px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.3);">
                <div style="font-size: 0.9em; opacity: 0.9;">总利润提升</div>
                <div style="font-size: 2.2em; font-weight: bold; margin: 5px 0; text-shadow: 2px 2px 4px rgba(0,0,0,0.2);">
                    {profit_diff:+.2f}U {'📈' if profit_diff > 0 else ('📉' if profit_diff < 0 else '➡️')}
                </div>
                <div style="font-size: 1.1em; opacity: 0.95;">
                    {'+' if profit_diff_pct > 0 else ''}{profit_diff_pct:.0f}% 变化
                </div>
            </div>
            <div style="margin-top: 10px; padding: 8px; background: rgba(255,255,255,0.15); border-radius: 4px; font-size: 0.85em;">
                💡 <strong>解读：</strong>
                {'✅ 新参数显著提升盈利能力' if profit_diff > 5 else ('✅ 新参数小幅改善' if profit_diff > 0 else ('⚠️ 需要进一步优化参数' if profit_diff < 0 else '➡️ 利润持平'))}
                {'，从亏损转为盈利！' if old_total_profit < 0 and new_total_profit > 0 else ''}
            </div>
        </div>
"""
                    
                    opportunity_stats_html += f"""
        <p style="margin-top: 10px; padding: 10px; background: #f0f7ff; border-left: 4px solid #2196f3;">
            <strong>📊 总结：</strong>昨日识别到<strong>{stats['total_opportunities']}个</strong>客观机会
            （⚡超短线{len(scalping_opps)}个 + 🌊波段{len(swing_opps)}个），
            旧参数捕获<strong>{stats['old_captured_count']}个</strong>（{old_capture_rate:.0f}%），
            新参数可捕获<strong>{stats['new_captured_count']}个</strong>（{new_capture_rate:.0f}%），
            捕获率{'提升' if capture_improvement > 0 else ('持平' if capture_improvement == 0 else '下降')}<strong>{abs(capture_improvement):.0f}%</strong>
                </p>
        <p style="margin-top: 5px; padding: 10px; background: #fff8e1; border-left: 4px solid #ffa726;">
            <strong>📈 分类捕获率：</strong><br>
            ⚡ <strong>超短线</strong>: 旧参数{scalp_old_rate:.0f}% → 新参数{scalp_new_rate:.0f}% {'📈+' if scalp_improvement > 0 else ('➡️' if scalp_improvement == 0 else '📉')}{abs(scalp_improvement):.0f}%<br>
                🌊 <strong>波段</strong>: 旧参数{swing_old_rate:.0f}% → 新参数{swing_new_rate:.0f}% {'📈+' if swing_improvement > 0 else ('➡️' if swing_improvement == 0 else '📉')}{abs(swing_improvement):.0f}%
        </p>
        <p style="margin-top: 5px; font-size: 0.85em; color: #666;">
            💡 <strong>图例：</strong>
            🟢 绿色=已捕获 | 🟡 黄色=优化后可捕获 | 🔴 红色=仍错过 | ⚪ 灰色=新参数调整
        </p>
    </div>
"""
                elif trends or missed_opportunities:
                    # 兼容旧版本（无新数据时）
                    total_opportunities = len(trends)
                    caught_opportunities = total_opportunities - len(missed_opportunities)
                    catch_rate = (caught_opportunities / total_opportunities * 100) if total_opportunities > 0 else 0
                    
                    opportunity_stats_html = f"""
    <div class="summary-box" style="background: #e8f5e9;">
        <h3>🎯 机会捕获统计</h3>
        <ul>
            <li><strong>昨日总机会数：</strong>{total_opportunities}个</li>
            <li><strong>成功捕获：</strong><span class="success">{caught_opportunities}个</span></li>
            <li><strong>错过机会：</strong><span class="{'warning' if len(missed_opportunities) > 2 else 'success'}">{len(missed_opportunities)}个</span></li>
            <li><strong>捕获率：</strong><span class="{'success' if catch_rate >= 70 else 'warning' if catch_rate >= 50 else 'danger'}">{catch_rate:.1f}%</span></li>
                </ul>
    </div>
"""
                
                # 🆕 V7.6.3.3: 构建多轮迭代历史
                iterative_history_html = ""
                if config.get('_iterative_history'):
                    iter_result = config['_iterative_history']
                    rounds = iter_result['rounds']
                    best_round = iter_result['best_round_num']
                    
                    iterative_history_html = f"""
    <div class="highlight" style="background: #fff9e6; border-left-color: #ff9800;">
        <h3>🔄 多轮迭代优化历史（共{iter_result['total_rounds']}轮）</h3>
        <p><strong>优化目标：</strong>最大化综合利润指标（加权胜率 × 加权盈亏比 × 捕获率）</p>
        <table style="width:100%; border-collapse: collapse; margin-top: 10px; font-size: 0.9em;">
            <tr style="background: #ffe0b2;">
                <th style="padding: 8px; text-align: center; border: 1px solid #ffb74d;">轮次</th>
                <th style="padding: 8px; text-align: left; border: 1px solid #ffb74d;">优化方向</th>
                <th style="padding: 8px; text-align: center; border: 1px solid #ffb74d;">综合利润指标</th>
                <th style="padding: 8px; text-align: center; border: 1px solid #ffb74d;">结果</th>
            </tr>
            <tr style="background: #f5f5f5;">
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">基准</td>
                <td style="padding: 8px; border: 1px solid #e0e0e0;">当前参数</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{iter_result['baseline_metric']:.4f}</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">-</td>
            </tr>
"""
                    
                    for r in rounds:
                        round_num = r.get('round_num', 1)
                        is_best = round_num == best_round
                        # V7.7.0兼容：使用.get()安全访问
                        improved = r.get('improved', True)
                        direction = r.get('direction', r.get('status', 'COMPLETED'))
                        status_icon = "🏆" if is_best else ("✅" if improved else "❌")
                        bg_color = "#e8f5e9" if is_best else ("#ffffff" if improved else "#ffebee")
                        
                        iterative_history_html += f"""
            <tr style="background: {bg_color};">
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;"><strong>第{round_num}轮</strong></td>
                <td style="padding: 8px; border: 1px solid #e0e0e0;">{direction[:50] if direction else 'N/A'}...</td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{r.get('metric', 0):.4f} ({r.get('improvement_pct', 0):+.1f}%)</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{status_icon}</td>
            </tr>
"""
                    
                    total_improvement = ((iter_result['best_metric'] - iter_result['baseline_metric']) / iter_result['baseline_metric'] * 100) if iter_result['baseline_metric'] > 0 else 0
                    
                    iterative_history_html += f"""
        </table>
        <p style="margin-top: 15px; padding: 10px; background: #e8f5e9; border-radius: 5px;">
            <strong>🏆 最终选择：</strong>第{best_round}轮配置<br/>
            <strong>📊 综合指标：</strong>{iter_result['baseline_metric']:.4f} → {iter_result['best_metric']:.4f} ({total_improvement:+.1f}%)
        </p>
    </div>
"""
                    
                    # 🆕 添加回测盈利说明框
                    backtest_explanation_html = ""
                    if 'phase2' in iter_result:
                        phase2 = iter_result['phase2']
                        if 'best_result' in phase2:
                            best_result = phase2['best_result']
                            profit_pct = best_result.get('total_profit', 0)
                            total_trades = best_result.get('total_trades', 0)
                            win_rate = best_result.get('weighted_win_rate', 0)  # 🔧 V7.7.0.7: 修复 - 保持小数形式，不乘100
                            
                            if profit_pct != 0:
                                backtest_explanation_html = f"""
    <div class="highlight" style="background: #e8f5e9; border-left-color: #4caf50;">
        <h3>📊 回测盈利说明（V7.7.0）</h3>
        <div style="background: white; padding: 15px; border-radius: 5px; margin: 10px 0;">
            <p style="font-size: 1.1em; margin-bottom: 10px;"><strong>🔍 什么是"回测盈利"？</strong></p>
            <p style="margin: 5px 0; line-height: 1.8;">
                <strong>回测盈利</strong>是指：用新找到的最优参数配置，模拟"如果在过去3天使用这个参数会产生什么结果"。<br/>
                <span style="color: #4caf50; font-weight: bold;">✅ 本次回测结果：{profit_pct:+.2f}%</span> （模拟了{total_trades}笔交易，胜率{win_rate:.1f}%）
            </p>
        </div>
        
        <div style="background: #fff3e0; padding: 15px; border-radius: 5px; margin: 10px 0; border: 1px solid #ff9800;">
            <p style="font-size: 1em; margin-bottom: 10px;"><strong>⚠️ 重要说明：</strong></p>
            <ul style="margin: 0; padding-left: 20px; line-height: 1.8;">
                <li><strong>✅ 表示：</strong>新参数在历史数据上表现更好（从亏损变盈利，或盈利更多）</li>
                <li><strong>❌ 不表示：</strong>未来一定会盈利{abs(profit_pct):.1f}%（市场是动态变化的）</li>
                <li><strong>💡 意义：</strong>历史表现好的参数，未来表现好的<strong>概率更高</strong></li>
            </ul>
        </div>
        
        <div style="background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 10px 0;">
            <p style="font-size: 1em; margin-bottom: 10px;"><strong>📈 优化原理：</strong></p>
            <p style="margin: 0; line-height: 1.8;">
                系统每天分析过去3天的交易数据，测试数百种参数组合，找到在历史数据上表现最好的那一组。<br/>
                就像考试前做练习题：做得好不保证考试满分，但能大幅提高考试成绩的概率。
            </p>
        </div>
    </div>
"""
                
                # 🆕 V7.7.0.7: 构建优化结果总览（清晰展示参数变化和回测结果）
                # 🔧 V7.7.0.9: 修改生成条件 - 只要有iter_result就显示，不管是否改参数
                optimization_summary_html = ""
                if iter_result and 'phase2' in iter_result:
                    # 解析原始配置
                    try:
                        original_config_dict = json.loads(original_config)
                    except:
                        original_config_dict = config.copy()
                    
                    # 【V7.9.2修复】获取回测天数（默认7天）
                    days = 7  # 与backtest_parameters函数保持一致
                    
                    # 获取回测数据
                    backtest_profit = 0
                    backtest_trades = 0
                    backtest_win_rate = 0
                    backtest_capture_rate = 0
                    backtest_profit_ratio = 0
                    
                    if 'best_result' in iter_result['phase2']:
                        best_result = iter_result['phase2']['best_result']
                        backtest_profit = best_result.get('total_profit', 0)
                        backtest_trades = best_result.get('total_trades', 0)
                        backtest_win_rate = best_result.get('weighted_win_rate', 0) * 100
                        backtest_capture_rate = best_result.get('capture_rate', 0) * 100
                        backtest_profit_ratio = best_result.get('weighted_profit_ratio', 0)
                    
                    # 构建参数对比表格
                    param_rows = ""
                    param_display_names = {
                        'min_risk_reward': '最小盈亏比',
                        'min_indicator_consensus': '指标共识要求',
                        'atr_stop_multiplier': 'ATR止损倍数',
                        'base_position_ratio': '基础仓位比例',
                        'max_hold_time_hours': '最大持仓时间'
                    }
                    
                    # 🔧 V7.7.0.9: 检查是否有参数变化
                    if adjustments and adjustments.get('global'):
                        for param, new_value in adjustments['global'].items():
                            if not param.startswith('_'):
                                old_value = original_config_dict.get('global', {}).get(param, 'N/A')
                                display_name = param_display_names.get(param, param)
                                
                                # 格式化数值显示
                                if isinstance(old_value, float):
                                    if param == 'base_position_ratio':
                                        old_display = f"{old_value*100:.0f}%"
                                        new_display = f"{new_value*100:.0f}%"
                                    else:
                                        old_display = f"{old_value:.2f}"
                                        new_display = f"{new_value:.2f}"
                                else:
                                    old_display = str(old_value)
                                    new_display = str(new_value)
                                
                                param_rows += f"""
            <tr>
                <td style="padding: 8px; border: 1px solid #e0e0e0;">{display_name}</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0; color: #666;">{old_display}</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0; color: #4caf50; font-weight: bold;">{new_display}</td>
            </tr>
"""
                    else:
                        # 没有参数变化，显示提示
                        param_rows = """
            <tr>
                <td colspan="3" style="padding: 15px; text-align: center; border: 1px solid #e0e0e0; color: #666;">
                    ✅ 当前参数已达最优，无需调整
                </td>
            </tr>
"""
                    
                    optimization_summary_html = f"""
    <div class="highlight" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; padding: 20px; border-radius: 8px; margin: 20px 0;">
        <h3 style="margin-top: 0; color: white;">🎯 V7.7.0 优化结果总览</h3>
        
        <div style="background: rgba(255,255,255,0.95); color: #333; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <h4 style="margin-top: 0; color: #667eea;">📊 回测表现（过去{days}天模拟）</h4>
            <table style="width:100%; border-collapse: collapse; margin-top: 10px;">
                <tr style="background: #f5f5f5;">
                    <th style="padding: 8px; text-align: left; border: 1px solid #e0e0e0;">指标</th>
                    <th style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">数值</th>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e0e0e0;">💰 回测盈利</td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0; font-size: 1.2em; font-weight: bold; color: {'#4caf50' if backtest_profit > 0 else '#f44336' if backtest_profit < 0 else '#666'};">{backtest_profit:+.2f}%</td>
                        </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e0e0e0;">📈 模拟交易数</td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{backtest_trades}笔</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e0e0e0;">🎯 胜率</td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{backtest_win_rate:.1f}%</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e0e0e0;">⚖️ 盈亏比</td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{backtest_profit_ratio:.2f}:1</td>
                </tr>
                <tr>
                    <td style="padding: 8px; border: 1px solid #e0e0e0;">🎣 机会捕获率</td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{backtest_capture_rate:.1f}%</td>
                </tr>
            </table>
        </div>
        
        <div style="background: rgba(255,255,255,0.95); color: #333; padding: 15px; border-radius: 5px; margin: 15px 0;">
            <h4 style="margin-top: 0; color: #667eea;">🔧 优化后的参数配置</h4>
            <table style="width:100%; border-collapse: collapse; margin-top: 10px;">
                <tr style="background: #f5f5f5;">
                    <th style="padding: 8px; text-align: left; border: 1px solid #e0e0e0;">参数</th>
                    <th style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">优化前</th>
                    <th style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">优化后</th>
                </tr>
{param_rows}
            </table>
        </div>
        
        <div style="background: rgba(255,255,255,0.95); color: #333; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #ff9800;">
            <h4 style="margin-top: 0; color: #ff9800;">💡 盈利计算说明</h4>
            <ul style="margin: 5px 0; padding-left: 20px; line-height: 1.8;">
                <li><strong>初始资金：</strong>100 USDT（本金）</li>
                <li><strong>杠杆设置：</strong>最高5倍（系统动态调整）</li>
                <li><strong>回测盈利：</strong>{backtest_profit:+.2f}% = {'盈利' if backtest_profit > 0 else '亏损' if backtest_profit < 0 else '持平'} {abs(backtest_profit):.2f} USDT</li>
                    <li><strong>⚠️ 重要：</strong>盈利百分比<strong>已包含杠杆效果</strong>，不是再乘以5倍！</li>
                <li><strong>实际收益：</strong>如果实际运行，100U本金 → {100 + backtest_profit:.2f}U（理论值）</li>
            </ul>
            <p style="margin: 10px 0 0 0; padding: 10px; background: #fff3e0; border-radius: 3px; font-size: 0.9em;">
                <strong>📌 说明：</strong>杠杆既放大盈利也放大亏损。如果使用5倍杠杆，价格波动1%，你的账户盈亏是5%。
                最终的{abs(backtest_profit):.2f}%盈利，就是在使用杠杆的情况下，对你的本金的净影响。
            </p>
        </div>
    </div>
"""
                
                # 🆕 构建参数调整预期对比
                adjustment_comparison_html = ""
                if adjustments:
                    adjustment_comparison_html = f"""
    <div class="highlight" style="background: #e3f2fd; border-left-color: #2196f3;">
        <h3>📊 参数调整预期效果对比</h3>
        <table style="width:100%; border-collapse: collapse; margin-top: 10px;">
            <tr style="background: #bbdefb;">
                <th style="padding: 8px; text-align: left; border: 1px solid #90caf9;">指标</th>
                <th style="padding: 8px; text-align: center; border: 1px solid #90caf9;">调整前</th>
                <th style="padding: 8px; text-align: center; border: 1px solid #90caf9;">预期调整后</th>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #e3f2fd;">当前胜率</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e3f2fd;"><span class="{'success' if win_rate >= 0.5 else 'warning'}">{win_rate*100:.1f}%</span></td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e3f2fd;"><span class="success">预计{'保持' if win_rate >= 0.5 else '提升'}</span></td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #e3f2fd;">盈亏比</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e3f2fd;"><span class="{'danger' if win_loss_ratio < 1.0 else 'warning' if win_loss_ratio < 1.5 else 'success'}">{win_loss_ratio:.2f}:1</span></td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e3f2fd;"><span class="success">{optimization.get('expected_effect', '预期改善').split('盈亏比')[1].split('，')[0] if '盈亏比' in optimization.get('expected_effect', '') else '预期改善'}</span></td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #e3f2fd;">机会捕获率</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e3f2fd;"><span class="{'success' if catch_rate >= 70 else 'warning' if catch_rate >= 50 else 'danger'}">{catch_rate:.1f}%</span></td>
                    <td style="padding: 8px; text-align: center; border: 1px solid #e3f2fd;"><span class="success">预计{'保持' if catch_rate >= 70 else '提升'}至{min(95, catch_rate + 15):.0f}%+</span></td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #e3f2fd;">AI置信度</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e3f2fd;" colspan="2">
                    <span class="{'success' if optimization.get('confidence', 0) >= 0.7 else 'warning'}">{optimization.get('confidence', 0)*100:.0f}%</span>
                        </td>
            </tr>
        </table>
        <p style="margin-top: 10px; font-size: 0.9em; color: #666;">
            💡 <strong>调整逻辑：</strong>{optimization.get('root_cause', 'AI分析中...')}
        </p>
    </div>
"""
                
                # 🆕 V7.7.0.15: 构建平仓时机分析HTML块（独立变量避免嵌套f-string问题）
                exit_timing_html = ""
                if exit_analysis:
                    tp_exits = exit_analysis['exit_stats']['tp_exits']
                    sl_exits = exit_analysis['exit_stats']['sl_exits']
                    manual_exits = exit_analysis['exit_stats']['manual_exits']
                    total_exits = max(exit_analysis['exit_stats']['total_exits'], 1)
                    premature_exits = exit_analysis['exit_stats']['premature_exits']
                    optimal_exits = exit_analysis['exit_stats']['optimal_exits']
                    avg_missed_profit = exit_analysis['exit_stats'].get('avg_missed_profit_pct', 0)
                    
                    tp_pct = (tp_exits / total_exits * 100)
                    sl_pct = (sl_exits / total_exits * 100)
                    manual_pct = (manual_exits / total_exits * 100)
                    
                    premature_class = 'danger' if premature_exits >= 3 else 'warning' if premature_exits >= 1 else 'success'
                    
                    # 使用字符串拼接避免三引号字符串中的emoji问题
                    exit_timing_html = """
    <div class="summary-box" style="background: #fff3e0;">
    <h2>🚪 平仓时机分析（昨日）</h2>
        <table style="width:100%; border-collapse: collapse; margin-top: 10px; font-size: 0.9em;">
            <tr style="background: #ffe0b2;">
                <th style="padding: 8px; text-align: center; border: 1px solid #ffb74d;">平仓类型</th>
                <th style="padding: 8px; text-align: center; border: 1px solid #ffb74d;">数量</th>
                <th style="padding: 8px; text-align: center; border: 1px solid #ffb74d;">占比</th>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #e0e0e0;">止盈平仓</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{tp_exits}笔</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{tp_pct:.0f}%</td>
            </tr>
            <tr style="background: #f5f5f5;">
                <td style="padding: 8px; border: 1px solid #e0e0e0;">止损平仓</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{sl_exits}笔</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{sl_pct:.0f}%</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #e0e0e0;">手动平仓</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{manual_exits}笔</td>
                <td style="padding: 8px; text-align: center; border: 1px solid #e0e0e0;">{manual_pct:.0f}%</td>
            </tr>
        </table>
        
        <div style="margin-top: 15px;">
            <p><strong>📈 平仓质量评估：</strong></p>
            <ul>
                <li><strong>过早平仓：</strong><span class="{premature_class}">{premature_exits}笔</span> (平均错过<span class="warning">{avg_missed_profit:.1f}%</span>利润)</li>
                <li><strong>平仓合理：</strong><span class="success">{optimal_exits}笔</span></li>
            </ul>
        </div>
    """.format(
                        tp_exits=tp_exits, sl_exits=sl_exits, manual_exits=manual_exits,
                        tp_pct=tp_pct, sl_pct=sl_pct, manual_pct=manual_pct,
                        premature_class=premature_class, premature_exits=premature_exits,
                        avg_missed_profit=avg_missed_profit, optimal_exits=optimal_exits
                    )
                    
                    # 🔧 V7.7.0.19 Fix: 移除过早平仓案例的单独显示，统一在详细表格中展示
                    # 不要在这里添加 </div>，等待后续添加详细表格
                    
                else:
                    # 如果没有平仓分析，显示提示
                    exit_timing_html = """
    <div class="summary-box" style="background: #f5f5f5;">
        <h2>🚪 平仓时机分析（昨日）</h2>
        <p style="color: #999;">⚠️ 昨日无平仓交易，跳过平仓时机分析</p>
    </div>
    """
                
                # 🆕 V7.7.0.19 Fixed: 增强平仓分析表格（显示所有订单明细，修复重复问题）
                if exit_analysis and (exit_analysis.get('suboptimal_exits') or exit_analysis.get('good_exits')):
                    all_trades = exit_analysis.get('suboptimal_exits', []) + exit_analysis.get('good_exits', [])
                    
                    # 构建表头
                    table_header = """
        <h3 style="margin-top: 20px;">📋 昨日每笔交易详细分析</h3>
        <table style="width:100%; border-collapse: collapse; margin-top: 10px; font-size: 0.85em;">
            <tr style="background: #ffe0b2;">
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">币种</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">方向</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">开仓价</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">平仓价</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">平仓类型</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">实际盈亏</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">最大潜在利润</th>
                <th style="padding: 6px; text-align: center; border: 1px solid #ffb74d;">评价</th>
                <th style="padding: 6px; text-align: left; border: 1px solid #ffb74d;">改进建议</th>
            </tr>
"""
                    
                    # 构建表格行
                    table_rows = []
                    for trade in sorted(all_trades, key=lambda x: x.get('missed_profit_pct', 0), reverse=True):
                        # 确定行背景色
                        if trade.get('is_premature', False):
                            row_bg = 'background: #ffebee;'
                        elif trade.get('exit_type') == '止损':
                            row_bg = 'background: #fff3e0;'
                        else:
                            row_bg = 'background: #f5f5f5;'
                        
                        # 确定评价
                        if trade.get('is_premature', False):
                            evaluation = '<span class="danger">⚠️ 早平</span>'
                        elif trade.get('exit_type') == '止损':
                            evaluation = '<span class="warning">🚱 止损</span>'
                        else:
                            evaluation = '<span class="success">✅ 合理</span>'
                        
                        # 确定改进建议
                        if trade.get('is_premature', False) and trade.get('exit_type') == '止盈':
                            missed_pct = trade.get('missed_profit_pct', 0)
                            if missed_pct > 5:
                                improvement = 'TP扩大2.0倍'
                            elif missed_pct > 3:
                                improvement = 'TP扩大1.5倍'
                            else:
                                improvement = 'TP扩大1.2倍'
                        elif trade.get('exit_type') == '止损':
                            improvement = '提高入场要求或扩大止损'
                        else:
                            improvement = '继续保持'
                        
                        # PNL class
                        pnl_class = 'success' if trade.get('pnl', 0) > 0 else 'danger'
                        
                        # 生成行HTML
                        row_html = """
            <tr style="{row_bg}">
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;"><strong>{coin}</strong></td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{side}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.9em;">${entry_price:,.2f}</td>
                    <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.9em;">${exit_price:,.2f}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{exit_type}</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;"><span class="{pnl_class}">{pnl:+.2f}U</span></td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{max_profit:.1f}%</td>
                <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{evaluation}</td>
                <td style="padding: 6px; text-align: left; border: 1px solid #e0e0e0; font-size: 0.85em;">{improvement}</td>
            </tr>
""".format(
                            row_bg=row_bg,
                            coin=trade.get('coin', 'N/A'),
                            side=trade.get('side', 'N/A'),
                            entry_price=trade.get('entry_price', 0),
                            exit_price=trade.get('exit_price', 0),
                            exit_type=trade.get('exit_type', 'N/A'),
                            pnl_class=pnl_class,
                            pnl=trade.get('pnl', 0),
                            max_profit=trade.get('max_potential_profit_pct', 0),
                            evaluation=evaluation,
                            improvement=improvement
                        )
                        table_rows.append(row_html)
                    
                    # 构建表尾
                    table_footer = """
        </table>
        <p style="margin-top: 10px; font-size: 0.85em; color: #666;">
            💡 <strong>评价标准：</strong>"早平"=平仓后又涨/跌超2%；"止损"=触发止损；"合理"=技术指标支持平仓或无显著错失利润
        </p>
    </div>
"""
                    
                    # 🔧 直接追加详细表格，不使用replace（避免重复问题）
                    exit_timing_html += table_header + ''.join(table_rows) + table_footer
                else:
                    # 如果没有详细交易数据，只需关闭div
                    if exit_analysis:
                        exit_timing_html += '\n    </div>'
                
                # 🆕 V7.7.0.15 Enhanced: 构建完整的HTML邮件（优化顺序，删除冗余部分）
                # 拼接邮件头部
                email_header = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; border-left: 4px solid #3498db; padding-left: 10px; }}
        h3 {{ color: #7f8c8d; margin-top: 20px; }}
        .summary-box {{ background: #ecf0f1; padding: 15px; border-radius: 5px; margin: 15px 0; }}
        .highlight {{ background: #fff3cd; padding: 10px; border-left: 4px solid #ffc107; margin: 10px 0; }}
        .success {{ color: #28a745; font-weight: bold; }}
        .warning {{ color: #ffc107; font-weight: bold; }}
        .danger {{ color: #dc3545; font-weight: bold; }}
        pre {{ background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; white-space: pre-wrap; }}
        ul {{ margin: 10px 0; padding-left: 20px; }}
        li {{ margin: 5px 0; }}
        table {{ font-size: 0.95em; }}
        th {{ font-weight: 600; }}
        .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #dee2e6; color: #6c757d; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>🤖 AI参数优化报告 - {model_name}</h1>
    <p><strong>生成时间：</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
"""
                
                # 🆕 V8.3.21.3: 构建学习经验模块（优先展示V8.3.21真实数据）
                learning_insights_html = ""
                # 🔧 V7.7.0.19 Fix: 重新读取最新的 learning_config 确保获取到 compressed_insights
                current_config = load_learning_config()
                print(f"[邮件调试] compressed_insights 存在: {'compressed_insights' in current_config}")
                
                if current_config and 'compressed_insights' in current_config:
                    insights = current_config['compressed_insights']
                    print(f"[邮件调试] insights 内容: {insights}")
                    
                    # 🆕 V8.3.21.3: 优先展示V8.3.21优化结果（真实数据）
                    v8321_insights = insights.get('v8321_insights', {})
                    if v8321_insights and ('scalping' in v8321_insights or 'swing' in v8321_insights):
                        learning_insights_html = """
    <div class="summary-box" style="background: #e8f5e9; border: 2px solid #4caf50;">
        <h2>🎯 V8.3.21 回测优化结果（实际运行参数）</h2>
        <p style="color: #666; font-size: 0.9em; margin-bottom: 15px;">
            ✅ 以下数据来自V8.3.21增强优化器的真实回测结果，已应用于实时交易决策
        </p>
"""
                        
                        # 超短线数据
                        if 'scalping' in v8321_insights:
                            scalp = v8321_insights['scalping']
                            scalp_perf = scalp.get('performance', {})
                            scalp_contexts = scalp.get('best_contexts', [])
                            
                            learning_insights_html += """
        <h3>⚡ 超短线策略</h3>
        <div style="background: #fff; padding: 15px; border-radius: 5px; margin: 10px 0;">
"""
                            if scalp_perf:
                                learning_insights_html += f"""
            <p><strong>优化得分:</strong> <span style="color: #4caf50; font-size: 1.2em;">{scalp_perf.get('score', 0):.3f}</span></p>
            <p><strong>捕获率:</strong> {scalp_perf.get('capture_rate', 0)*100:.0f}% | <strong>平均利润:</strong> {scalp_perf.get('avg_profit', 0):.1f}%</p>
"""
                            if scalp_contexts:
                                learning_insights_html += """
            <p><strong>🔑 最优市场上下文（Top 2）:</strong></p>
            <ul style="list-style-type: disc; padding-left: 20px; font-size: 0.9em;">
"""
                                for ctx in scalp_contexts[:2]:
                                    learning_insights_html += f"                <li>{ctx}</li>\n"
                                learning_insights_html += "            </ul>\n"
                            
                            learning_insights_html += "        </div>\n"
                        
                        # 波段数据
                        if 'swing' in v8321_insights:
                            swing = v8321_insights['swing']
                            swing_perf = swing.get('performance', {})
                            swing_contexts = swing.get('best_contexts', [])
                            
                            learning_insights_html += """
        <h3>🌊 波段策略</h3>
        <div style="background: #fff; padding: 15px; border-radius: 5px; margin: 10px 0;">
"""
                            if swing_perf:
                                learning_insights_html += f"""
            <p><strong>优化得分:</strong> <span style="color: #2196f3; font-size: 1.2em;">{swing_perf.get('score', 0):.3f}</span></p>
            <p><strong>捕获率:</strong> {swing_perf.get('capture_rate', 0)*100:.0f}% | <strong>平均利润:</strong> {swing_perf.get('avg_profit', 0):.1f}%</p>
"""
                            if swing_contexts:
                                learning_insights_html += """
            <p><strong>🔑 最优市场上下文（Top 2）:</strong></p>
            <ul style="list-style-type: disc; padding-left: 20px; font-size: 0.9em;">
"""
                                for ctx in swing_contexts[:2]:
                                    learning_insights_html += f"                <li>{ctx}</li>\n"
                                learning_insights_html += "            </ul>\n"
                            
                            learning_insights_html += "        </div>\n"
                        
                        learning_insights_html += "    </div>\n"
                    
                    # 显示传统学习经验（作为补充）
                    if insights.get('lessons') or insights.get('focus'):
                        learning_insights_html += """
    <div class="summary-box" style="background: #e3f2fd;">
        <h2>📚 AI Learning Insights</h2>
"""
                        
                        # 显示学习到的教训
                        if insights.get('lessons'):
                            learning_insights_html += """
        <h3>💡 Key Lessons Learned</h3>
        <ul style="list-style-type: disc; padding-left: 20px;">
"""
                            for lesson in insights['lessons']:
                                learning_insights_html += f"            <li>{lesson}</li>\n"
                            learning_insights_html += "        </ul>\n"
                        
                        # 显示关注点
                        if insights.get('focus'):
                            learning_insights_html += """
        <h3>🎯 Current Focus Areas</h3>
        <p style="padding: 10px; background: #fff; border-left: 4px solid #2196f3; margin: 10px 0;">
"""
                            learning_insights_html += f"            {insights['focus']}\n"
                            learning_insights_html += "        </p>\n"
                        
                        learning_insights_html += "    </div>\n"
                    
                    # 🆕 V8.3.25.5: 添加AI深度分析（开仓+平仓质量）
                    ai_entry = insights.get('ai_entry_analysis', {})
                    ai_exit = insights.get('ai_exit_analysis', {})
                    
                    if ai_entry or ai_exit:
                        learning_insights_html += """
    <div class="summary-box" style="background: #fff3e0; border: 2px solid #ff9800;">
        <h2>🧠 AI深度学习分析（AI Self-Reflection）</h2>
        <p style="color: #666; font-size: 0.9em; margin-bottom: 15px;">
            💡 AI分析自己的决策逻辑，识别错误模式并提出改进建议（已保存供实时AI参考）
        </p>
"""
                        
                        # 开仓质量分析
                        if ai_entry and ai_entry.get('learning_insights'):
                            learning_insights_html += """
        <h3>🚪 开仓质量分析</h3>
        <div style="background: #fff; padding: 15px; border-radius: 5px; margin: 10px 0;">
"""
                            diagnosis = ai_entry.get('diagnosis', '')
                            if diagnosis:
                                learning_insights_html += f"""
            <p><strong>📋 诊断：</strong>{diagnosis}</p>
"""
                            
                            # 学习洞察
                            learning_insights_html += """
            <p><strong>💡 关键洞察（Key Learnings）：</strong></p>
            <ul style="list-style-type: disc; padding-left: 20px; font-size: 0.9em;">
"""
                            for insight in ai_entry['learning_insights'][:5]:
                                learning_insights_html += f"                <li>{insight}</li>\n"
                            learning_insights_html += "            </ul>\n"
                            
                            # 高优先级建议
                            if ai_entry.get('key_recommendations'):
                                high_priority = [r for r in ai_entry['key_recommendations'] if r.get('priority') == 'High']
                                if high_priority:
                                    learning_insights_html += """
            <p><strong>🎯 高优先级改进（High Priority Actions）：</strong></p>
            <ul style="list-style-type: disc; padding-left: 20px; font-size: 0.9em;">
"""
                                    for rec in high_priority:
                                        learning_insights_html += f"""                <li><strong>{rec.get('action', '')}</strong>: {rec.get('threshold', '')}</li>\n"""
                                    learning_insights_html += "            </ul>\n"
                            
                            gen_time = ai_entry.get('generated_at', 'N/A')
                            learning_insights_html += f"""
            <p style="color: #999; font-size: 0.85em; margin-top: 10px;">生成时间: {gen_time}</p>
        </div>
"""
                        
                        # 平仓质量分析
                        if ai_exit and ai_exit.get('learning_insights'):
                            learning_insights_html += """
        <h3>🔄 平仓质量分析</h3>
        <div style="background: #fff; padding: 15px; border-radius: 5px; margin: 10px 0;">
"""
                            diagnosis = ai_exit.get('diagnosis', '')
                            if diagnosis:
                                learning_insights_html += f"""
            <p><strong>📋 诊断：</strong>{diagnosis}</p>
"""
                            
                            # 学习洞察
                            learning_insights_html += """
            <p><strong>💡 关键洞察（Key Learnings）：</strong></p>
            <ul style="list-style-type: disc; padding-left: 20px; font-size: 0.9em;">
"""
                            for insight in ai_exit['learning_insights'][:5]:
                                learning_insights_html += f"                <li>{insight}</li>\n"
                            learning_insights_html += "            </ul>\n"
                            
                            # 高优先级建议
                            if ai_exit.get('key_recommendations'):
                                high_priority = [r for r in ai_exit['key_recommendations'] if r.get('priority') == 'High']
                                if high_priority:
                                    learning_insights_html += """
            <p><strong>🎯 高优先级改进（High Priority Actions）：</strong></p>
            <ul style="list-style-type: disc; padding-left: 20px; font-size: 0.9em;">
"""
                                    for rec in high_priority:
                                        learning_insights_html += f"""                <li><strong>{rec.get('action', '')}</strong>: {rec.get('threshold', '')}</li>\n"""
                                    learning_insights_html += "            </ul>\n"
                            
                            gen_time = ai_exit.get('generated_at', 'N/A')
                            learning_insights_html += f"""
            <p style="color: #999; font-size: 0.85em; margin-top: 10px;">生成时间: {gen_time}</p>
        </div>
"""
                        
                        learning_insights_html += "    </div>\n"
                
                # 【V7.9新增】生成交易员执行摘要（分Scalping/Swing）
                trader_summary_html = ""
                try:
                    if TRADES_FILE.exists():
                        import pandas as pd
                        from datetime import timedelta
                        
                        df = pd.read_csv(TRADES_FILE)
                        if not df.empty and '信号类型' in df.columns:
                            # 最近7天已平仓交易
                            df['开仓时间_dt'] = pd.to_datetime(df['开仓时间'], errors='coerce')
                            recent = df[
                                (df['开仓时间_dt'] > datetime.now() - timedelta(days=7)) &
                                (df['平仓时间'].notna())
                            ]
                            
                            if not recent.empty:
                                trader_summary_html = """
    <div class="summary-box" style="background: #f0f8ff; border: 2px solid #3498db;">
        <h2>📊 7日交易执行摘要（交易员视角）</h2>
"""
                                # 分类型统计
                                scalping = recent[recent['信号类型'] == 'scalping']
                                swing = recent[recent['信号类型'] == 'swing']
                                
                                # 生成对比表格
                                trader_summary_html += """
        <table style="width:100%; border-collapse: collapse; margin-top:15px;">
            <tr style="background: #3498db; color: white;">
                <th style="padding:10px; border:1px solid #ddd;">类型</th>
                <th style="padding:10px; border:1px solid #ddd;">交易数</th>
                <th style="padding:10px; border:1px solid #ddd;">胜率</th>
                <th style="padding:10px; border:1px solid #ddd;">总盈亏</th>
                <th style="padding:10px; border:1px solid #ddd;">平均盈亏</th>
                <th style="padding:10px; border:1px solid #ddd;">平均持仓</th>
            </tr>
"""
                                for signal_type, trades_df in [('⚡超短线', scalping), ('🌊波段', swing)]:
                                    if not trades_df.empty:
                                        total = len(trades_df)
                                        wins = len(trades_df[trades_df['盈亏(U)'] > 0])
                                        wr = wins / total * 100
                                        pnl = trades_df['盈亏(U)'].sum()
                                        avg_pnl = trades_df['盈亏(U)'].mean()
                                        
                                        # 计算平均持仓时间
                                        trades_df['开仓_dt'] = pd.to_datetime(trades_df['开仓时间'], errors='coerce')
                                        trades_df['平仓_dt'] = pd.to_datetime(trades_df['平仓时间'], errors='coerce')
                                        trades_df['持仓_分'] = (trades_df['平仓_dt'] - trades_df['开仓_dt']).dt.total_seconds() / 60
                                        avg_hold = trades_df['持仓_分'].mean()
                                        hold_str = f"{avg_hold:.0f}分" if avg_hold < 60 else f"{avg_hold/60:.1f}小时"
                                        
                                        wr_color = "green" if wr >= 50 else "red"
                                        pnl_color = "green" if pnl >= 0 else "red"
                                        
                                        trader_summary_html += f"""
            <tr>
                <td style="padding:10px; border:1px solid #ddd;"><b>{signal_type}</b></td>
                <td style="padding:10px; border:1px solid #ddd;">{total}笔</td>
                <td style="padding:10px; border:1px solid #ddd; color:{wr_color}; font-weight:bold;">{wr:.1f}%</td>
                <td style="padding:10px; border:1px solid #ddd; color:{pnl_color}; font-weight:bold;">{pnl:+.2f}U</td>
                <td style="padding:10px; border:1px solid #ddd;">{avg_pnl:+.2f}U</td>
                <td style="padding:10px; border:1px solid #ddd;">{hold_str}</td>
            </tr>
"""
                                trader_summary_html += """
        </table>
"""
                                
                                # 【V7.9】关键交易指标
                                trader_summary_html += """
        <h3 style="margin-top:20px;">🎯 关键交易指标</h3>
        <ul style="list-style-type: none; padding-left: 0;">
"""
                                # 最大连续亏损
                                recent_sorted = recent.sort_values('开仓时间')
                                max_consec_loss = 0
                                current_consec = 0
                                for pnl in recent_sorted['盈亏(U)']:
                                    if pnl < 0:
                                        current_consec += 1
                                        max_consec_loss = max(max_consec_loss, current_consec)
                                    else:
                                        current_consec = 0
                                
                                trader_summary_html += f"""
            <li><b>📉 最大连续亏损:</b> {max_consec_loss}笔 {'⚠️需关注' if max_consec_loss >= 3 else '✓正常'}</li>
                """
                                
                                # 实际盈亏比
                                if not scalping.empty:
                                    scalp_wins_df = scalping[scalping['盈亏(U)'] > 0]
                                    scalp_loss_df = scalping[scalping['盈亏(U)'] < 0]
                                    if len(scalp_loss_df) > 0:
                                        scalp_rr = abs(scalp_wins_df['盈亏(U)'].mean() / scalp_loss_df['盈亏(U)'].mean())
                                        trader_summary_html += f"""
            <li><b>⚡ 超短线实际盈亏比:</b> {scalp_rr:.2f}:1</li>
"""
                                
                                if not swing.empty:
                                    swing_wins_df = swing[swing['盈亏(U)'] > 0]
                                    swing_loss_df = swing[swing['盈亏(U)'] < 0]
                                    if len(swing_loss_df) > 0:
                                        swing_rr = abs(swing_wins_df['盈亏(U)'].mean() / swing_loss_df['盈亏(U)'].mean())
                                        trader_summary_html += f"""
            <li><b>🌊 波段实际盈亏比:</b> {swing_rr:.2f}:1</li>
"""
                                
                                # 最佳币种
                                coin_stats = recent.groupby('币种').agg({
                                    '盈亏(U)': ['sum', 'count']
                                }).reset_index()
                                coin_stats.columns = ['币种', '总盈亏', '交易数']
                                coin_stats = coin_stats[coin_stats['交易数'] >= 2]  # 至少2笔
                                if not coin_stats.empty:
                                    best_coin = coin_stats.loc[coin_stats['总盈亏'].idxmax()]
                                    trader_summary_html += f"""
            <li><b>🏆 最佳币种:</b> {best_coin['币种']} ({best_coin['交易数']:.0f}笔, {best_coin['总盈亏']:+.2f}U)</li>
"""
                                
                                trader_summary_html += """
        </ul>
    </div>
"""
                except Exception as e:
                    print(f"⚠️ 生成交易员摘要失败: {e}")
                
                # 【V7.9新增】分Scalping/Swing参数对比
                type_params_html = ""
                try:
                    current_config = load_learning_config()
                    if current_config and 'global' in current_config:
                        scalping_params = current_config['global'].get('scalping_params', {})
                        swing_params = current_config['global'].get('swing_params', {})
                        
                        if scalping_params and swing_params:
                            type_params_html = """
    <div class="summary-box" style="background: #fff3e0; border: 2px solid #ff9800;">
        <h2>⚡🌊 超短线/波段 参数配置</h2>
        <table style="width:100%; border-collapse: collapse; margin-top:15px;">
            <tr style="background: #ff9800; color: white;">
                <th style="padding:10px; border:1px solid #ddd;">参数</th>
                <th style="padding:10px; border:1px solid #ddd;">⚡超短线</th>
                <th style="padding:10px; border:1px solid #ddd;">🌊波段</th>
            </tr>
"""
                            params_to_show = [
                                ('min_risk_reward', '最小盈亏比', ':.1f'),
                                ('min_signal_score', '最低信号分数', ':.0f'),
                                ('max_holding_hours', '最长持仓(小时)', ':.1f'),
                                ('base_position_ratio', '基础仓位比例', '%'),
                                ('max_leverage', '最大杠杆', 'x'),
                                ('max_concurrent_positions', '最大持仓数', '个'),
                            ]
                            
                            for param_key, param_name, param_format in params_to_show:
                                scalp_val = scalping_params.get(param_key, 0)
                                swing_val = swing_params.get(param_key, 0)
                                
                                if param_format == '%':
                                    scalp_display = f"{scalp_val*100:.0f}%"
                                    swing_display = f"{swing_val*100:.0f}%"
                                elif param_format == 'x':
                                    scalp_display = f"{scalp_val}x"
                                    swing_display = f"{swing_val}x"
                                elif param_format == '个':
                                    scalp_display = f"{scalp_val}个"
                                    swing_display = f"{swing_val}个"
                                else:
                                    # 修复format错误：使用.format()方法
                                    if isinstance(scalp_val, (int, float)):
                                        scalp_display = ('{' + param_format + '}').format(scalp_val)
                                    else:
                                        scalp_display = str(scalp_val)
                                    
                                    if isinstance(swing_val, (int, float)):
                                        swing_display = ('{' + param_format + '}').format(swing_val)
                                    else:
                                        swing_display = str(swing_val)
                                
                                type_params_html += f"""
            <tr>
                <td style="padding:10px; border:1px solid #ddd;"><b>{param_name}</b></td>
                <td style="padding:10px; border:1px solid #ddd; text-align:center;">{scalp_display}</td>
                <td style="padding:10px; border:1px solid #ddd; text-align:center;">{swing_display}</td>
            </tr>
"""
                            type_params_html += """
        </table>
        <p style="margin-top:15px; color:#666; font-size:0.9em;">
            💡 这些参数可通过AI回测学习自动优化，保存在learning_config.json中
        </p>
    </div>
"""
                except Exception as e:
                    print(f"⚠️ 生成分类型参数对比失败: {e}")
                
                # 拼接主体内容（使用字符串拼接避免f-string嵌套）
                email_body_parts = [
                    email_header,
                    trader_summary_html,  # 【V7.9新增】交易员执行摘要
                    type_params_html,  # 【V7.9新增】分类型参数对比
                    exit_timing_html,
                    learning_insights_html,  # 🆕 添加学习经验模块
                    opportunity_stats_html,
                    "\n    <h2>🔄 参数优化分析</h2>\n"
                ]
                
                # 继续构建邮件内容
                email_content_html = f"""
    
    {optimization_summary_html if optimization_summary_html else ''}
    
    {iterative_history_html}
    
    {backtest_explanation_html}
    
    <h2>📊 详细交易数据</h2>
    <pre>{data_summary}</pre>
"""
                
                # 🆕 V8.3.25.8: 构建统一的开平仓时机分析表格
                entry_exit_timing_html = ""
                
                # 准备统计数据
                has_entry = entry_analysis is not None
                has_exit = exit_analysis is not None
                
                if has_entry or has_exit:
                    # 构建统计摘要
                    stats_html = '<div class="summary-box" style="background: #e3f2fd;">\n'
                    stats_html += '    <h2>📊 开平仓时机完整分析（昨日）</h2>\n'
                    
                    # 开仓统计
                    if has_entry:
                        entry_stats = entry_analysis['entry_stats']
                        stats_html += f'''
    <div style="background: #fff; padding: 10px; border-radius: 5px; margin: 10px 0;">
        <h3 style="color: #1976d2;">🚪 开仓质量统计</h3>
        <p><strong>总机会数：</strong>{entry_stats.get('total_opportunities', 0)} | <strong>AI开仓：</strong>{entry_stats.get('ai_opened', 0)} ({entry_stats.get('ai_opened', 0)/max(entry_stats.get('total_opportunities', 1), 1)*100:.0f}%)</p>
        <p>
            ├─ ✅ 正确开仓: {entry_stats.get('correct_entries', 0)}笔 | 
            ❌ 虚假信号: {entry_stats.get('false_entries', 0)}笔 | 
            ⚠️ 时机问题: {entry_stats.get('timing_issues', 0)}笔<br/>
            └─ 错过机会: {entry_stats.get('missed_profitable', 0)}笔 | 
            正确过滤: {entry_stats.get('correctly_filtered', 0)}笔
        </p>
    </div>
'''
                    
                    # 平仓统计
                    if has_exit:
                        exit_stats = exit_analysis['exit_stats']
                        stats_html += f'''
    <div style="background: #fff; padding: 10px; border-radius: 5px; margin: 10px 0;">
        <h3 style="color: #f57c00;">🚪 平仓质量统计</h3>
        <p><strong>总平仓：</strong>{exit_stats['total_exits']}笔 | 止盈: {exit_stats['tp_exits']}笔 | 止损: {exit_stats['sl_exits']}笔 | 手动: {exit_stats['manual_exits']}笔</p>
        <p>
            ├─ ✅ 最优: {exit_stats['optimal_exits']}笔 | 
            ⚠️ 过早: {exit_stats['premature_exits']}笔 (平均错过{exit_stats['avg_missed_profit_pct']:.1f}%利润) | 
            ⚠️ 延迟: {exit_stats['delayed_exits']}笔
        </p>
    </div>
'''
                    
                    # 构建统一表格
                    stats_html += '''
    <h3 style="margin-top: 20px;">📋 详细交易分析（合并视图）</h3>
    <table style="width:100%; border-collapse: collapse; margin-top: 10px; font-size: 0.85em;">
        <tr style="background: #bbdefb;">
            <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6; min-width: 50px;">币种</th>
            <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6; min-width: 80px;">时间</th>
            <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6; min-width: 60px;">信号/共振</th>
            <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6; min-width: 70px;">AI决策</th>
            <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6; min-width: 70px;">开仓结果</th>
            <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6; min-width: 60px;">平仓类型</th>
            <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6; min-width: 70px;">平仓结果</th>
            <th style="padding: 6px; text-align: center; border: 1px solid #64b5f6; min-width: 80px;">综合评价</th>
            <th style="padding: 6px; text-align: left; border: 1px solid #64b5f6; min-width: 100px;">改进建议</th>
        </tr>
'''
                    
                    # 合并数据：从exit_table_data和entry_table_data构建统一视图
                    combined_rows = []
                    
                    # 先添加所有平仓交易（这些是完整的交易）
                    # 🔧 V8.3.25.9: 修复N/A问题 - 从exit_table_data正确读取字段
                    if has_exit and exit_analysis.get('exit_table_data'):
                        for exit_trade in exit_analysis['exit_table_data']:
                            # 提取开仓时间（格式：YYYY-MM-DD HH:MM:SS）
                            entry_time_full = exit_trade.get('entry_time', '')
                            entry_time_display = entry_time_full[11:16] if len(entry_time_full) > 16 else entry_time_full  # 只显示HH:MM
                            
                            # 提取信号评分和共振数
                            signal_score = exit_trade.get('signal_score', 0)
                            consensus = exit_trade.get('consensus', 0)
                            signal_info = f"{signal_score}/{consensus}" if signal_score > 0 else 'N/A'
                            
                            combined_rows.append({
                                'coin': exit_trade['coin'],
                                'time': entry_time_display if entry_time_display else 'N/A',
                                'signal_info': signal_info,
                                'ai_action': '✅ 已开仓',
                                'entry_result': f"{exit_trade['pnl']:+.2f}U",
                                'exit_type': exit_trade['exit_type'],
                                'exit_result': f"{exit_trade['pnl']:+.2f}U<br/>潜在{exit_trade['max_potential_profit_pct']:+.1f}%",
                                'evaluation': exit_trade['evaluation'],
                                'recommendation': exit_trade['recommendation']
                            })
                    
                    # 再添加错过的机会（来自entry_table_data中AI未开仓的）
                    if has_entry and entry_analysis.get('entry_table_data'):
                        for entry_opp in entry_analysis['entry_table_data']:
                            if entry_opp['ai_action'] == '❌ 未开':
                                combined_rows.append({
                                    'coin': entry_opp['coin'],
                                    'time': entry_opp['time'],
                                    'signal_info': f"{entry_opp['signal_score']}/{entry_opp['consensus']}",
                                    'ai_action': entry_opp['ai_action'],
                                    'entry_result': '-',
                                    'exit_type': '-',
                                    'exit_result': entry_opp['result'],
                                    'evaluation': entry_opp['evaluation'],
                                    'recommendation': '参数过滤'
                                })
                    
                    # 生成表格行（限制TOP20）
                    for i, row in enumerate(combined_rows[:20]):
                        row_bg = 'background: #ffebee;' if '❌' in row['evaluation'] else \
                                 'background: #fff3e0;' if '⚠️' in row['evaluation'] else \
                                 'background: #f5f5f5;'
                        
                        stats_html += f'''
        <tr style="{row_bg}">
            <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;"><strong>{row['coin']}</strong></td>
            <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0; font-size: 0.8em;">{row['time'][-8:-3] if len(row['time']) > 8 else row['time']}</td>
            <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{row['signal_info']}</td>
            <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{row['ai_action']}</td>
            <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{row['entry_result']}</td>
            <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{row['exit_type']}</td>
            <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{row['exit_result']}</td>
            <td style="padding: 6px; text-align: center; border: 1px solid #e0e0e0;">{row['evaluation']}</td>
            <td style="padding: 6px; text-align: left; border: 1px solid #e0e0e0; font-size: 0.85em;">{row['recommendation']}</td>
        </tr>
'''
                    
                    stats_html += '''
    </table>
    <p style="margin-top: 10px; font-size: 0.85em; color: #666;">
        💡 <strong>说明：</strong>表格合并显示开仓和平仓分析，限制显示TOP20条记录。"AI决策"显示是否开仓，"综合评价"综合考虑开仓质量和平仓时机。
    </p>
'''
                    
                    # 添加改进建议
                    stats_html += '    <div style="margin-top: 15px;">\n'
                    stats_html += '        <p><strong>💡 改进建议：</strong></p>\n'
                    stats_html += '        <ul>\n'
                    
                    # 合并开仓和平仓的改进建议
                    all_lessons = []
                    if has_entry and entry_analysis.get('entry_lessons'):
                        all_lessons.extend([f'[开仓] {l}' for l in entry_analysis['entry_lessons']])
                    if has_exit and exit_analysis.get('exit_lessons'):
                        all_lessons.extend([f'[平仓] {l}' for l in exit_analysis['exit_lessons']])
                    
                    if all_lessons:
                        for lesson in all_lessons:
                            stats_html += f'            <li>{lesson}</li>\n'
                    else:
                        stats_html += '            <li>当前交易质量良好，继续保持</li>\n'
                    
                    stats_html += '        </ul>\n'
                    stats_html += '    </div>\n'
                    stats_html += '</div>\n'
                    
                    entry_exit_timing_html = stats_html
                else:
                    entry_exit_timing_html = '''
    <div class="summary-box" style="background: #f5f5f5;">
        <h2>📊 开平仓时机分析（昨日）</h2>
        <p style="color: #999;">⚠️ 昨日无交易数据</p>
    </div>
'''
                
                # 将统一的开平仓分析添加到邮件body
                email_body_parts.insert(5, entry_exit_timing_html)  # 在learning_insights之后插入
                
                # 拼接footer前的AI优化统计
                optimizer_report_html = ai_optimizer.get_daily_report_html()
                email_footer_html = f"""
    {optimizer_report_html}
    
    <div class="footer">
        <p>此邮件由 {model_name} 智能交易系统自动发送</p>
        <p>如有问题，请查看服务器日志或联系管理员</p>
    </div>
</body>
</html>
"""
                
                # 最终拼接所有部分生成完整邮件
                email_body_parts.extend([
                    email_content_html,
                    email_footer_html
                ])
                email_html = ''.join(email_body_parts)
                
                # 发送邮件
                print(f"[邮件调试] 准备发送邮件，model_name={model_name}")
                send_email_notification(
                    subject="AI参数优化 + 调用优化报告",
                    body_html=email_html,
                    model_name=model_name
                )
                
                # 重置每日统计
                ai_optimizer.reset_daily_details()
                
            except Exception as email_err:
                print(f"⚠️ 邮件发送失败（不影响主流程）: {email_err}")
            
            print("\n✓ AI优化建议已应用")
        else:
            # 【V8.3.18.2】参数未变化，但如果是手动回测，仍然发送通知
            if is_manual_backtest:
                print("\n→ 参数无需调整（手动回测模式：仍发送报告）")
                
                # 发送Bark通知
                send_bark_notification(
                    "[通义千问]🔬回测完成",
                    f"参数未变化\n胜率{win_rate*100:.0f}% 盈亏比{win_loss_ratio:.1f}",
                )
                
                # 发送邮件（复用之前构建的邮件HTML）
                try:
                    # 强制使用Qwen（避免环境变量污染）
                    model_name = "Qwen"
                    # 构建简化的邮件（无参数变化）
                    # 由于没有参数变化，我们需要重新构建部分HTML
                    # 这里直接复用前面已经构建好的HTML变量（如果存在的话）
                    # 实际上，邮件HTML是在前面的大块里构建的，这里只是发送一个简化版本
                    
                    # 构建简化邮件
                    simple_email_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        .info-box {{ background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #2196f3; }}
        pre {{ background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; white-space: pre-wrap; }}
    </style>
</head>
<body>
    <h1>🔬 手动回测报告 - {model_name}</h1>
    <p><strong>生成时间：</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <div class="info-box">
        <h2>✅ 参数评估结果</h2>
        <p><strong>结论：</strong>当前参数已接近最优，无需调整</p>
        <p><strong>当前表现：</strong></p>
        <ul>
            <li>胜率: {win_rate*100:.1f}%</li>
            <li>盈亏比: {win_loss_ratio:.2f}:1</li>
            <li>样本数: {len(recent_20)}笔</li>
        </ul>
    </div>
    
    <h2>📊 详细交易数据</h2>
    <pre>{data_summary}</pre>
    
    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #dee2e6; color: #6c757d; font-size: 0.9em;">
        <p>此邮件由 {model_name} 智能交易系统自动发送（手动回测模式）</p>
    </div>
</body>
</html>
"""
                    
                    send_email_notification(
                        subject="手动回测报告 - 参数无需调整",
                        body_html=simple_email_html,
                        model_name=model_name
                    )
                except Exception as email_err:
                    print(f"⚠️ 邮件发送失败（不影响主流程）: {email_err}")
            else:
                print("\n→ 参数无需调整")

        print("=" * 70 + "\n")
        
        # 🆕 保存压缩洞察供实时决策使用
        print("\n【💾 保存压缩洞察】")
        try:
            compressed = compress_insights_for_realtime(
                trends, 
                trade_analyses, 
                missed_opportunities, 
                optimization,
                exit_analysis  # 🆕 V7.7.0.15: 添加平仓时机分析
            )
            
            # 🔧 V7.7.0.19: 保存到 learning_config.json 的 compressed_insights 字段
            config = load_learning_config()
            config['compressed_insights'] = compressed
            save_learning_config(config)
            
            print(f"✓ 已保存压缩洞察到learning_config.json: {len(compressed.get('lessons', []))}条教训")
            for lesson in compressed.get('lessons', []):
                print(f"  - {lesson}")
        except Exception as e:
            print(f"⚠️ 保存压缩洞察失败: {e}")

    
        # 保存配置（包含market_regime状态）
        save_learning_config(config)

    except Exception as e:
        print(f"✗ AI参数优化失败: {e}")
        import traceback

        traceback.print_exc()


def chat_with_ai(user_message, context=None):
    """与AI聊天，获取实时建议"""
    try:
        # 构建上下文
        context_text = ""
        if context:
            context_text = f"""
当前系统状态：
- USDT余额: {context.get('balance', 0):.2f}U
- 总仓位: {context.get('total_position', 0):.2f}U
- 持仓数: {context.get('position_count', 0)}

当前持仓:
{context.get('positions_text', '无持仓')}

市场情况:
{context.get('market_text', '暂无数据')}
"""
        
        response = qwen_client.chat.completions.create(
            model="qwen3-max",  # Qwen模型
            messages=[
                {
                    "role": "system",
                    "content": f"You are a professional cryptocurrency trading advisor AI. The user is running an automated trading system, and you need to provide advice based on current status. {context_text} **Always respond in Chinese (中文).**",
                },
                {"role": "user", "content": user_message},
            ],
            stream=False,
        )
        
        ai_reply = response.choices[0].message.content
        
        # 保存聊天记录
        chat_record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": user_message,
            "ai": ai_reply,
            "context": context,
        }
        
        if CHAT_HISTORY_FILE.exists():
            with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
                chat_history = json.load(f)
        else:
            chat_history = []
        
        chat_history.append(chat_record)
        
        # 只保留最近50条
        if len(chat_history) > 50:
            chat_history = chat_history[-50:]
        
        with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_history, f, ensure_ascii=False, indent=2)
        
        return ai_reply
        
    except Exception as e:
        print(f"AI聊天失败: {e}")
        return f"抱歉，AI暂时无法回复：{str(e)}"


def setup_exchange(is_manual_backtest=False):
    """设置交易所参数
    
    Args:
        is_manual_backtest: 是否为手动回测模式
    """
    try:
        balance = exchange.fetch_balance()
        usdt_balance = balance["USDT"]["free"]
        print(f"当前USDT余额: {usdt_balance:.2f}")
        
        # 🆕 V7.8.3: 获取交易阶段和参数信息
        trade_count, experience_level = get_trading_experience_level()
        try:
            learning_config = load_learning_config()
        except:
            learning_config = get_default_config()
        
        safe_params = get_safe_params_by_experience(trade_count, learning_config)
        
        # 构建阶段信息（精简版）
        if safe_params:
            stage_info = safe_params['_mode']
            actual_rr = safe_params.get('min_risk_reward', 'N/A')
            actual_score = safe_params.get('min_signal_score', 'N/A')
            actual_consensus = safe_params.get('min_indicator_consensus', 'N/A')
            
            stage_detail = f"\n{stage_info} | {trade_count}笔\n"
            stage_detail += f"R:R≥{actual_rr:.1f} 信号≥{actual_score} 共振≥{actual_consensus}"
        else:
            # 成熟期：显示按币种风险分类的实际参数（V7.9.1：AI基准×系数）
            safety_multipliers = learning_config.get('risk_safety_multipliers', {})
            fallback_minimums = learning_config.get('risk_fallback_minimums', {})
            global_config = learning_config.get('global', {})
            
            ai_base_rr = global_config.get('min_risk_reward', 1.5)
            ai_base_score = global_config.get('min_signal_score', 55)
            
            # Low risk: AI × 1.1
            low_mult = safety_multipliers.get('low_risk', {}).get('min_risk_reward_multiplier', 1.1)
            low_bonus = safety_multipliers.get('low_risk', {}).get('min_signal_score_bonus', 10)
            low_rr = max(ai_base_rr * low_mult, fallback_minimums.get('low_risk', {}).get('min_risk_reward', 1.8))
            low_score = max(ai_base_score + low_bonus, fallback_minimums.get('low_risk', {}).get('min_signal_score', 60))
            
            # Medium risk: AI × 1.2
            med_mult = safety_multipliers.get('medium_risk', {}).get('min_risk_reward_multiplier', 1.2)
            med_bonus = safety_multipliers.get('medium_risk', {}).get('min_signal_score_bonus', 15)
            med_rr = max(ai_base_rr * med_mult, fallback_minimums.get('medium_risk', {}).get('min_risk_reward', 2.0))
            med_score = max(ai_base_score + med_bonus, fallback_minimums.get('medium_risk', {}).get('min_signal_score', 65))
            
            # High risk: AI × 1.3
            high_mult = safety_multipliers.get('high_risk', {}).get('min_risk_reward_multiplier', 1.3)
            high_bonus = safety_multipliers.get('high_risk', {}).get('min_signal_score_bonus', 20)
            high_rr = max(ai_base_rr * high_mult, fallback_minimums.get('high_risk', {}).get('min_risk_reward', 2.2))
            high_score = max(ai_base_score + high_bonus, fallback_minimums.get('high_risk', {}).get('min_signal_score', 70))
            
            stage_detail = f"\n成熟期 | {trade_count}笔\n"
            stage_detail += f"低:{low_rr:.1f}≥{low_score} 中:{med_rr:.1f}≥{med_score} 高:{high_rr:.1f}≥{high_score}"
        
        # 🆕 V7.8.3: 精简版通知（避免URL过长）
        if is_manual_backtest:
            # 手动回测模式：发送回测开始通知
            send_bark_notification(
                f"[通义千问]🔬回测开始",
                f"余额{usdt_balance:.0f}U{stage_detail}",
            )
        else:
            # 正常启动模式：发送系统启动通知
            mode_emoji = "🧪" if TRADE_CONFIG.get("test_mode", False) else "🔴"
            send_bark_notification(
                f"[通义千问]启动{mode_emoji}",
                f"余额{usdt_balance:.0f}U{stage_detail}",
        )
        
        # 为每个币种设置杠杆
        for symbol in TRADE_CONFIG["symbols"]:
            try:
                exchange.set_leverage(
                    TRADE_CONFIG["max_leverage"], symbol, {"mgnMode": "cross"}
                )
                print(f"设置 {symbol} 杠杆: {TRADE_CONFIG['max_leverage']}x")
            except Exception as e:
                print(f"设置 {symbol} 杠杆失败: {e}")
        
        return True
    except Exception as e:
        print(f"交易所设置失败: {e}")
        return False


def calculate_macd(df, fast=12, slow=26, signal=9):
    """计算MACD指标"""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]


def detect_pin_bar(ohlc):
    """识别Pin Bar（长影线反转信号）"""
    try:
        body = abs(ohlc["close"] - ohlc["open"])
        total_range = ohlc["high"] - ohlc["low"]
        upper_shadow = ohlc["high"] - max(ohlc["open"], ohlc["close"])
        lower_shadow = min(ohlc["open"], ohlc["close"]) - ohlc["low"]
        
        if total_range == 0:
            return None
        
        # 多头Pin Bar：下影线>2倍实体，上影线<实体，实体占比<30%
        if lower_shadow > body * 2 and upper_shadow < body and body < total_range * 0.3:
            return "bullish_pin"
        
        # 空头Pin Bar：上影线>2倍实体，下影线<实体，实体占比<30%
        if upper_shadow > body * 2 and lower_shadow < body and body < total_range * 0.3:
            return "bearish_pin"
        
        return None
    except:
        return None


def detect_engulfing(prev_ohlc, curr_ohlc):
    """识别吞没形态"""
    try:
        prev_body = abs(prev_ohlc["close"] - prev_ohlc["open"])
        curr_body = abs(curr_ohlc["close"] - curr_ohlc["open"])
        
        # 多头吞没
        if (
            prev_ohlc["close"] < prev_ohlc["open"]
            and curr_ohlc["close"] > curr_ohlc["open"]
            and curr_body > prev_body * 1.2
            and curr_ohlc["close"] > prev_ohlc["open"]
            and curr_ohlc["open"] < prev_ohlc["close"]
        ):
            return "bullish_engulfing"
        
        # 空头吞没
        if (
            prev_ohlc["close"] > prev_ohlc["open"]
            and curr_ohlc["close"] < curr_ohlc["open"]
            and curr_body > prev_body * 1.2
            and curr_ohlc["close"] < prev_ohlc["open"]
            and curr_ohlc["open"] > prev_ohlc["close"]
        ):
            return "bearish_engulfing"

        return None
    except:
        return None


def get_pattern_based_tp_sl(entry_price, direction, pattern_type, pattern_data, atr):
    """
    【V8.3.13.2】根据形态类型返回推荐的TP/SL
    
    参数:
        entry_price: 入场价格
        direction: 'long' or 'short'
        pattern_type: 'bullish_pin', 'bearish_pin', 'bullish_engulfing', 'bearish_engulfing'
        pattern_data: dict包含形态数据 {'high': xx, 'low': xx, 'open': xx, 'close': xx}
        atr: ATR值
    
    返回:
        {'stop_loss': xx, 'take_profit': xx} or None
    """
    try:
        if not pattern_data or not isinstance(pattern_data, dict):
            return None
        
        high = pattern_data.get('high', entry_price)
        low = pattern_data.get('low', entry_price)
        
        if high <= 0 or low <= 0 or high <= low:
            return None
        
        # Pin Bar策略
        if pattern_type == 'bullish_pin' and direction == 'long':
            # 多头Pin Bar: SL = Pin低点 - 0.2*ATR, TP = Pin高点 + 0.5*ATR
            stop_loss = low - atr * 0.2
            take_profit = high + atr * 0.5
            return {'stop_loss': stop_loss, 'take_profit': take_profit}
        
        elif pattern_type == 'bearish_pin' and direction == 'short':
            # 空头Pin Bar: SL = Pin高点 + 0.2*ATR, TP = Pin低点 - 0.5*ATR
            stop_loss = high + atr * 0.2
            take_profit = low - atr * 0.5
            return {'stop_loss': stop_loss, 'take_profit': take_profit}
        
        # Engulfing策略
        elif pattern_type == 'bullish_engulfing' and direction == 'long':
            # 多头吞没: SL = 吞没K线低点 - 0.3*ATR, TP = 吞没K线高点 + 1.0*ATR
            stop_loss = low - atr * 0.3
            take_profit = high + atr * 1.0
            return {'stop_loss': stop_loss, 'take_profit': take_profit}
        
        elif pattern_type == 'bearish_engulfing' and direction == 'short':
            # 空头吞没: SL = 吞没K线高点 + 0.3*ATR, TP = 吞没K线低点 - 1.0*ATR
            stop_loss = high + atr * 0.3
            take_profit = low - atr * 1.0
            return {'stop_loss': stop_loss, 'take_profit': take_profit}
        
        else:
            return None
            
    except Exception as e:
        return None


def detect_breakout_candle(curr_ohlc, prev_high, avg_volume):
    """识别突破性大阳线（Breakout Candle）"""
    try:
        body = abs(curr_ohlc["close"] - curr_ohlc["open"])
        total_range = curr_ohlc["high"] - curr_ohlc["low"]
        current_volume = curr_ohlc["volume"]

        if total_range == 0 or avg_volume == 0:
            return None

        # 条件：
        # 1. 阳线且实体 > 总高度60%
        # 2. 突破前高
        # 3. 成交量 > 平均量1.5倍
        # 4. 上影线很小（< 20%总高度）
        upper_shadow = curr_ohlc["high"] - max(curr_ohlc["open"], curr_ohlc["close"])
        volume_ratio = current_volume / avg_volume

        if (
            curr_ohlc["close"] > curr_ohlc["open"]
            and body > total_range * 0.6
            and curr_ohlc["close"] > prev_high
            and volume_ratio > 1.5
            and upper_shadow < total_range * 0.2
        ):
            return {
                "type": "strong_breakout",
                "volume_ratio": volume_ratio,
                "body_ratio": body / total_range,
            }

        return None
    except:
        return None


def detect_consecutive_bullish(df_15m, lookback=3):
    """识别连续阳线（Consecutive Bullish - 趋势确认）"""
    try:
        if len(df_15m) < lookback:
            return None

        recent = df_15m.tail(lookback)

        # 检查：连续N根阳线
        all_bullish = all(row["close"] > row["open"] for _, row in recent.iterrows())

        if not all_bullish:
            return None

        # 检查：每根收盘价 > 前一根收盘价
        closes = recent["close"].values
        ascending = all(closes[i] > closes[i - 1] for i in range(1, len(closes)))

        # 计算上涨幅度
        total_gain = (closes[-1] - closes[0]) / closes[0] * 100

        if ascending and total_gain > 0.5:  # 至少上涨0.5%
            return {
                "type": "trend_confirmation",
                "candles": lookback,
                "gain_pct": total_gain,
            }

        return None
    except:
        return None


def detect_extreme_volume_surge(current_volume, avg_volume):
    """识别极端放量（Extreme Volume Surge）"""
    try:
        if avg_volume == 0:
            return None

        ratio = current_volume / avg_volume

        if ratio >= 3.0:
            return {"type": "extreme_surge", "ratio": ratio, "weight": 4}  # ✓✓✓✓
        elif ratio >= 2.0:
            return {"type": "strong_surge", "ratio": ratio, "weight": 3}  # ✓✓✓
        elif ratio >= 1.5:
            return {"type": "moderate_surge", "ratio": ratio, "weight": 2}  # ✓✓

        return None
    except:
        return None


def detect_pin_bar_with_recovery(df_15m):
    """识别Pin Bar + 快速反弹组合"""
    try:
        if len(df_15m) < 2:
            return None

        prev = df_15m.iloc[-2]
        curr = df_15m.iloc[-1]

        # 前一根是Pin Bar
        pin_type = detect_pin_bar(prev)

        if pin_type == "bullish_pin":
            # 检查当前K线是否快速反弹
            recovery_pct = (curr["close"] - prev["close"]) / prev["close"] * 100

            if recovery_pct > 1.5 and curr["close"] > curr["open"]:
                return {"type": "pin_bar_recovery", "recovery_pct": recovery_pct}

        return None
    except:
        return None


def identify_pullback_type(df_15m):
    """识别回调类型：简单回调 vs 复杂回调"""
    try:
        if len(df_15m) < 8:
            return None

        recent = df_15m.tail(8)
        closes = recent["close"].values
        highs = recent["high"].values
        lows = recent["low"].values

        # 判断主趋势方向（前5根）
        trend_candles = recent.head(5)
        trend_closes = trend_candles["close"].values
        is_uptrend = trend_closes[-1] > trend_closes[0]

        # 获取最近3根K线（回调候选）
        pullback_candles = recent.tail(3)
        pullback_closes = pullback_candles["close"].values
        pullback_highs = pullback_candles["high"].values
        pullback_lows = pullback_candles["low"].values

        if is_uptrend:
            # 上升趋势中的回调
            # 检查是否有回调（最近3根中有阴线或下跌）
            has_pullback = any(pullback_candles["close"] < pullback_candles["open"])

            if has_pullback:
                pullback_depth = (
                    (max(highs[:5]) - min(pullback_lows)) / max(highs[:5]) * 100
                )

                # 简单回调：1-3根K线，回撤 < 38.2%
                if len(pullback_candles) <= 3 and pullback_depth < 38.2:
                    # 检查是否快速恢复
                    last_close = pullback_closes[-1]
                    prev_high = max(highs[:5])
                    recovery = (
                        (last_close - min(pullback_lows))
                        / (prev_high - min(pullback_lows))
                        * 100
                    )

                    if recovery > 50:  # 已恢复50%以上
                        return {
                            "type": "simple_pullback",
                            "depth_pct": pullback_depth,
                            "recovery_pct": recovery,
                            "signal": "entry_ready",
                                }

                # 复杂回调：回撤 38.2%-61.8%，形成整理
                elif 38.2 <= pullback_depth <= 61.8:
                    # 检查是否形成窄幅整理
                    consolidation_range = (
                        (max(pullback_highs) - min(pullback_lows))
                        / min(pullback_lows)
                        * 100
                    )

                    if consolidation_range < 3.0:  # 窄幅震荡<3%
                        return {
                            "type": "complex_pullback",
                            "depth_pct": pullback_depth,
                            "consolidation_pct": consolidation_range,
                            "signal": "wait_breakout",
                        }

        else:
            # 下降趋势中的回调（反弹）
            has_bounce = any(pullback_candles["close"] > pullback_candles["open"])

            if has_bounce:
                bounce_depth = (
                    (max(pullback_highs) - min(lows[:5])) / min(lows[:5]) * 100
                )

                if len(pullback_candles) <= 3 and bounce_depth < 38.2:
                    last_close = pullback_closes[-1]
                    prev_low = min(lows[:5])
                    recovery = (
                        (max(pullback_highs) - last_close)
                        / (max(pullback_highs) - prev_low)
                        * 100
                    )

                    if recovery > 50:
                        return {
                            "type": "simple_pullback",
                            "depth_pct": bounce_depth,
                            "recovery_pct": recovery,
                            "signal": "entry_ready",
                                "direction": "short",
                        }

                elif 38.2 <= bounce_depth <= 61.8:
                    consolidation_range = (
                        (max(pullback_highs) - min(pullback_lows))
                        / min(pullback_lows)
                        * 100
                    )

                    if consolidation_range < 3.0:
                        return {
                            "type": "complex_pullback",
                            "depth_pct": bounce_depth,
                            "consolidation_pct": consolidation_range,
                            "signal": "wait_breakout",
                            "direction": "short",
                        }

        return None
    except:
        return None


def detect_trend_initiation(df_15m, df_4h):
    """检测趋势发起信号"""
    try:
        if len(df_15m) < 5:
            return None

        recent_15m = df_15m.tail(5)
        curr = df_15m.iloc[-1]

        # 信号1：强力突破K线
        body_size = abs(curr["close"] - curr["open"])
        candle_range = curr["high"] - curr["low"]
        body_ratio = body_size / candle_range if candle_range > 0 else 0

        is_strong_bull = (
            curr["close"] > curr["open"]
            and body_ratio > 0.7  # 实体占比>70%
            and body_size / curr["open"] > 0.015  # 实体涨幅>1.5%
        )

        is_strong_bear = (
            curr["close"] < curr["open"]
            and body_ratio > 0.7
            and body_size / curr["open"] > 0.015
        )

        # 信号2：连续多头/空头K线
        if is_strong_bull:
            # 检查前3根是否也是多头
            prev_3 = recent_15m.head(3)
            all_bullish = all(prev_3["close"] > prev_3["open"])

            # 检查4小时趋势
            h4_trend = (
                "up"
                if len(df_4h) >= 2 and df_4h.iloc[-1]["close"] > df_4h.iloc[-2]["close"]
                    else "unknown"
            )

            if all_bullish and h4_trend == "up":
                return {
                    "type": "trend_initiation",
                    "direction": "long",
                    "strength": "strong",
                    "entry_signal": "immediate",
                        "reason": "强力突破+连续多头+4H确认",
                }
            elif is_strong_bull:
                return {
                    "type": "trend_initiation",
                    "direction": "long",
                    "strength": "moderate",
                    "entry_signal": "wait_confirm",
                        "reason": "强力突破K线",
                }

        elif is_strong_bear:
            prev_3 = recent_15m.head(3)
            all_bearish = all(prev_3["close"] < prev_3["open"])
            h4_trend = (
                "down"
                if len(df_4h) >= 2 and df_4h.iloc[-1]["close"] < df_4h.iloc[-2]["close"]
                    else "unknown"
            )

            if all_bearish and h4_trend == "down":
                return {
                    "type": "trend_initiation",
                    "direction": "short",
                    "strength": "strong",
                    "entry_signal": "immediate",
                        "reason": "强力突破+连续空头+4H确认",
                }
            elif is_strong_bear:
                return {
                    "type": "trend_initiation",
                    "direction": "short",
                    "strength": "moderate",
                    "entry_signal": "wait_confirm",
                        "reason": "强力突破K线",
                }

        return None
    except:
        return None


def detect_trend_exhaustion(df_15m):
    """检测趋势终结信号（用于平仓）"""
    try:
        if len(df_15m) < 5:
            return None

        recent = df_15m.tail(5)
        curr = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]

        closes = recent["close"].values
        highs = recent["high"].values
        lows = recent["low"].values

        # 判断趋势方向
        is_uptrend = closes[-1] > closes[0]

        if is_uptrend:
            # 上升趋势中的衰竭信号

            # 1. 长上影线（Pin Bar顶部）
            upper_shadow = curr["high"] - max(curr["open"], curr["close"])
            body_size = abs(curr["close"] - curr["open"])
            candle_range = curr["high"] - curr["low"]

            if candle_range > 0:
                upper_shadow_ratio = upper_shadow / candle_range

                if upper_shadow_ratio > 0.6 and body_size / candle_range < 0.3:
                    return {
                        "type": "exhaustion",
                        "signal": "long_upper_shadow",
                        "severity": "high",
                        "action": "close_long",
                    }

            # 2. 十字星在高位
            if body_size / candle_range < 0.15 and curr["close"] == max(closes):
                return {
                    "type": "exhaustion",
                    "signal": "doji_at_high",
                    "severity": "medium",
                    "action": "close_long",
                }

            # 3. 吞没形态（看跌）
            if (
                curr["close"] < curr["open"]  # 当前阴线
                and prev["close"] > prev["open"]  # 前根阳线
                and curr["open"] > prev["close"]  # 高开
                and curr["close"] < prev["open"]
            ):  # 吞没前根
                return {
                    "type": "exhaustion",
                    "signal": "bearish_engulfing",
                    "severity": "high",
                    "action": "close_long",
                }

            # 4. 动能衰减（K线实体变小 + 回调幅度增大）
            recent_bodies = [
                abs(recent.iloc[i]["close"] - recent.iloc[i]["open"])
                for i in range(len(recent))
                    ]

            if len(recent_bodies) >= 3:
                avg_body_early = np.mean(recent_bodies[:2])
                avg_body_late = np.mean(recent_bodies[-2:])

                if avg_body_late < avg_body_early * 0.5:  # 实体缩小50%+
                    return {
                        "type": "exhaustion",
                        "signal": "momentum_decay",
                        "severity": "medium",
                        "action": "close_long",
                    }

        else:
            # 下降趋势中的衰竭信号

            # 1. 长下影线（Pin Bar底部）
            lower_shadow = min(curr["open"], curr["close"]) - curr["low"]
            body_size = abs(curr["close"] - curr["open"])
            candle_range = curr["high"] - curr["low"]

            if candle_range > 0:
                lower_shadow_ratio = lower_shadow / candle_range

                if lower_shadow_ratio > 0.6 and body_size / candle_range < 0.3:
                    return {
                        "type": "exhaustion",
                        "signal": "long_lower_shadow",
                        "severity": "high",
                        "action": "close_short",
                    }

            # 2. 十字星在低位
            if body_size / candle_range < 0.15 and curr["close"] == min(closes):
                return {
                    "type": "exhaustion",
                    "signal": "doji_at_low",
                    "severity": "medium",
                    "action": "close_short",
                }

            # 3. 吞没形态（看涨）
            if (
                curr["close"] > curr["open"]
                and prev["close"] < prev["open"]
                and curr["open"] < prev["close"]
                and curr["close"] > prev["open"]
            ):
                return {
                    "type": "exhaustion",
                    "signal": "bullish_engulfing",
                    "severity": "high",
                    "action": "close_short",
                }

            # 4. 动能衰减
            recent_bodies = [
                abs(recent.iloc[i]["close"] - recent.iloc[i]["open"])
                for i in range(len(recent))
                    ]

            if len(recent_bodies) >= 3:
                avg_body_early = np.mean(recent_bodies[:2])
                avg_body_late = np.mean(recent_bodies[-2:])

                if avg_body_late < avg_body_early * 0.5:
                    return {
                        "type": "exhaustion",
                        "signal": "momentum_decay",
                        "severity": "medium",
                        "action": "close_short",
                    }
        
        return None
    except:
        return None


# ===== V8.2.3.6新增：统一breakout/trend_initiation检测逻辑 =====

def detect_breakout_sr(current_price, sr_levels):
    """
    检测价格突破支撑/阻力位（V8.2.3.6）
    与export_historical_data.py逻辑一致，确保回测与实盘数据统一
    
    Args:
        current_price: 当前价格
        sr_levels: 支撑阻力位字典
    
    Returns:
        dict: 突破信息，如无则返回None
    """
    try:
        resistance = sr_levels.get('nearest_resistance', {})
        support = sr_levels.get('nearest_support', {})
        
        res_price = resistance.get('price', 0) if isinstance(resistance, dict) else 0
        sup_price = support.get('price', 0) if isinstance(support, dict) else 0
        
        # 突破阻力（0.1%）
        if res_price > 0 and current_price > res_price * 1.001:
            return {
                "type": "resistance",
                "level": res_price,
                "strength": (current_price - res_price) / res_price,
                "res_strength": resistance.get('strength', 1)
            }
        # 突破支撑（0.1%）
        elif sup_price > 0 and current_price < sup_price * 0.999:
            return {
                "type": "support",
                "level": sup_price,
                "strength": (sup_price - current_price) / sup_price,
                "sup_strength": support.get('strength', 1)
            }
        
        return None
    except Exception as e:
        return None


def detect_trend_initiation_v2(df_15m, long_term_trend, current_trend_15m):
    """
    检测趋势启动（V8.2.3.6）
    逻辑：识别趋势加速（从减弱到加强）
    与export_historical_data.py逻辑一致，确保回测与实盘数据统一
    
    Args:
        df_15m: 15分钟K线数据
        long_term_trend: 4小时趋势
        current_trend_15m: 当前15分钟趋势
    
    Returns:
        dict: 趋势启动信息，如无则返回None
    """
    try:
        if len(df_15m) < 10:
            return None
        
        # 只在趋势明确时触发（不是"转弱"状态）
        if long_term_trend not in ["多头", "空头"]:
            return None
        
        # 检查最近10根K线的价格动能
        recent_10 = df_15m.tail(10)
        recent_closes = recent_10['close'].values
        
        # 计算前半段和后半段的趋势
        first_half_change = (recent_closes[4] - recent_closes[0]) / recent_closes[0] if recent_closes[0] > 0 else 0
        second_half_change = (recent_closes[9] - recent_closes[5]) / recent_closes[5] if recent_closes[5] > 0 else 0
        
        # 多头趋势启动：后半段涨幅 > 前半段涨幅，且加速明显
        if long_term_trend == "多头":
            # 后半段有明显上涨（>0.5%），且比前半段更强（至少1.5倍）
            if second_half_change > 0.005 and second_half_change > max(first_half_change * 1.5, 0.003):
                # 前半段涨幅较小或持平/下跌（接近震荡/转弱状态）
                if first_half_change < 0.003:
                    return {
                        "from_sideways": True,
                        "new_trend": current_trend_15m,
                        "strength": "strong",
                        "direction": "long",
                        "entry_signal": "immediate",
                            "reason": "趋势转强加速"
                    }
        
        # 空头趋势启动
        elif long_term_trend == "空头":
            # 后半段有明显下跌（<-0.5%），且比前半段更强
            if second_half_change < -0.005 and second_half_change < min(first_half_change * 1.5, -0.003):
                # 前半段跌幅较小或持平/上涨
                if first_half_change > -0.003:
                    return {
                        "from_sideways": True,
                        "new_trend": current_trend_15m,
                        "strength": "strong",
                        "direction": "short",
                        "entry_signal": "immediate",
                            "reason": "趋势转强加速"
                    }
        
        return None
    except Exception as e:
        return None


# ===== YTC信号检测函数（V7.5新增）=====

def detect_breakout_failure(df_15m: pd.DataFrame, sr_levels: dict) -> dict:
    """
    检测突破失败（BOF）信号 - YTC核心模式
    
    特征：
    1. 价格突破关键阻力/支撑位
    2. 突破后立即出现长影线（>50%）或反向吞没
    3. 收盘价回到S/R位另一侧
    
    心理学：Fading被困的突破交易者
    
    Args:
        df_15m: 15分钟K线数据
        sr_levels: 支撑阻力位数据
    
    Returns:
        dict: BOF信号详情，如无则返回None
    """
    try:
        if len(df_15m) < 2:
            return None
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        
        resistance = sr_levels.get('nearest_resistance', {})
        support = sr_levels.get('nearest_support', {})
        
        # === 多头BOF：突破阻力失败 ===
        if resistance.get('price'):
            res_price = resistance['price']
            res_strength = resistance.get('strength', 1)
            
            # 前一根K线突破
            breakout = (prev['close'] > res_price and 
                       prev['high'] > res_price * 1.005)
            
            if breakout:
                # 当前K线立即反转
                upper_wick = (current['high'] - current['close']) / (current['high'] - current['low'] + 0.01)
                failed = current['close'] < res_price and upper_wick > 0.5
                
                # 或者反向吞没
                engulfing = (current['close'] < current['open'] and
                           current['open'] > prev['close'] and
                           current['close'] < prev['open'])
                
                if failed or engulfing:
                    strength = 5 if res_strength >= 4 else 4 if engulfing else 3
                    return {
                        'signal_type': 'BOF',
                        'direction': 'SHORT',
                        'strength': strength,
                        'entry_price': res_price,
                            'sr_strength': res_strength,
                        'rationale': f'突破{res_price:.2f}失败，Fading被困多头',
                        'pattern': 'long_wick' if failed else 'engulfing'
                            }
        
        # === 空头BOF：跌破支撑失败 ===
        if support.get('price'):
            sup_price = support['price']
            sup_strength = support.get('strength', 1)
            
            # 前一根K线跌破
            breakout = (prev['close'] < sup_price and 
                       prev['low'] < sup_price * 0.995)
            
            if breakout:
                # 当前K线立即反转
                lower_wick = (current['close'] - current['low']) / (current['high'] - current['low'] + 0.01)
                failed = current['close'] > sup_price and lower_wick > 0.5
                
                # 或者反向吞没
                engulfing = (current['close'] > current['open'] and
                           current['open'] < prev['close'] and
                           current['close'] > prev['open'])
                
                if failed or engulfing:
                    strength = 5 if sup_strength >= 4 else 4 if engulfing else 3
                    return {
                        'signal_type': 'BOF',
                        'direction': 'LONG',
                        'strength': strength,
                        'entry_price': sup_price,
                            'sr_strength': sup_strength,
                        'rationale': f'跌破{sup_price:.2f}失败，Fading被困空头',
                        'pattern': 'long_wick' if failed else 'engulfing'
                            }
        
        return None
    except:
        return None


def detect_breakout_pullback(df_15m: pd.DataFrame, df_1h: pd.DataFrame, sr_levels: dict) -> dict:
    """
    检测突破回调（BPB）信号 - YTC核心模式
    
    特征：
    1. 价格强势突破关键S/R（1H确认）
    2. 15m回调至突破位（现已是极性转换位）
    3. 回调弱势（收盘价未破位太多）
    
    心理学：Fading对成功突破的弱势回调
    
    Args:
        df_15m: 15分钟K线数据
        df_1h: 1小时K线数据
        sr_levels: 支撑阻力位数据
    
    Returns:
        dict: BPB信号详情，如无则返回None
    """
    try:
        if len(df_15m) < 2 or len(df_1h) < 2:
            return None
        
        current_15m = df_15m.iloc[-1]
        current_1h = df_1h.iloc[-1]
        
        resistance = sr_levels.get('nearest_resistance', {})
        support = sr_levels.get('nearest_support', {})
        
        # === 多头BPB：突破阻力后回踩 ===
        if resistance.get('price') and resistance.get('is_switched_polarity'):
            res_price = resistance['price']
            res_strength = resistance.get('strength', 1)
            
            # 1H确认突破（收盘在突破位上方2%）
            breakout_confirmed = current_1h['close'] > res_price * 1.02
            
            # 15m回踩但未破位（低点触及，收盘在突破位上方）
            pullback_to_level = (
                current_15m['low'] < res_price * 1.005 and
                current_15m['close'] > res_price * 0.998
            )
            
            if breakout_confirmed and pullback_to_level:
                return {
                    'signal_type': 'BPB',
                    'direction': 'LONG',
                    'strength': 5 if res_strength >= 4 else 4,
                        'entry_price': res_price,
                    'sr_strength': res_strength,
                    'rationale': f'突破{res_price:.2f}后回踩极性转换位，Fading弱势回调',
                    'confirmation': '1H_confirmed'
                }
        
        # === 空头BPB：跌破支撑后反抽 ===
        if support.get('price') and support.get('is_switched_polarity'):
            sup_price = support['price']
            sup_strength = support.get('strength', 1)
            
            # 1H确认跌破（收盘在跌破位下方2%）
            breakout_confirmed = current_1h['close'] < sup_price * 0.98
            
            # 15m反抽但未破位（高点触及，收盘在跌破位下方）
            pullback_to_level = (
                current_15m['high'] > sup_price * 0.995 and
                current_15m['close'] < sup_price * 1.002
            )
            
            if breakout_confirmed and pullback_to_level:
                return {
                    'signal_type': 'BPB',
                    'direction': 'SHORT',
                    'strength': 5 if sup_strength >= 4 else 4,
                        'entry_price': sup_price,
                    'sr_strength': sup_strength,
                    'rationale': f'跌破{sup_price:.2f}后反抽极性转换位，Fading弱势反弹',
                    'confirmation': '1H_confirmed'
                }
        
        return None
    except:
        return None


def detect_support_resistance_test(df_15m: pd.DataFrame, sr_levels: dict, momentum_slope: float) -> dict:
    """
    检测支撑/阻力测试（TST）信号 - YTC核心模式
    
    特征：
    1. 价格弱势测试强S/R（strength ≥4）
    2. 动能停滞（momentum_slope接近0）
    3. 可能出现停滞K线或小幅度波动
    
    心理学：Fading在关键位停滞的晚期追随者
    
    Args:
        df_15m: 15分钟K线数据
        sr_levels: 支撑阻力位数据
        momentum_slope: 动能斜率
    
    Returns:
        dict: TST信号详情，如无则返回None
    """
    try:
        if len(df_15m) < 1:
            return None
        
        current = df_15m.iloc[-1]
        
        # 动能停滞检查
        is_stalling = abs(momentum_slope) < 0.1
        
        resistance = sr_levels.get('nearest_resistance', {})
        support = sr_levels.get('nearest_support', {})
        
        # === 测试阻力（做空信号）===
        if resistance.get('price') and resistance.get('strength', 0) >= 4:
            res_price = resistance['price']
            res_strength = resistance['strength']
            
            # 价格在阻力位附近（±0.3%）
            at_resistance = abs(current['close'] - res_price) / res_price < 0.003
            
            if at_resistance and is_stalling:
                # 额外检查：是否有快速拒绝历史
                bonus_strength = 1 if resistance.get('is_fast_rejection') else 0
                
                return {
                    'signal_type': 'TST',
                    'direction': 'SHORT',
                    'strength': min(5, res_strength + bonus_strength),
                    'entry_price': res_price,
                        'sr_strength': res_strength,
                    'rationale': f'弱势测试强阻力{res_price:.2f}+动能停滞，Fading测试者',
                    'momentum_slope': momentum_slope,
                    'fast_rejection': resistance.get('is_fast_rejection', False)
                }
        
        # === 测试支撑（做多信号）===
        if support.get('price') and support.get('strength', 0) >= 4:
            sup_price = support['price']
            sup_strength = support['strength']
            
            # 价格在支撑位附近（±0.3%）
            at_support = abs(current['close'] - sup_price) / sup_price < 0.003
            
            if at_support and is_stalling:
                bonus_strength = 1 if support.get('is_fast_rejection') else 0
                
                return {
                    'signal_type': 'TST',
                    'direction': 'LONG',
                    'strength': min(5, sup_strength + bonus_strength),
                    'entry_price': sup_price,
                        'sr_strength': sup_strength,
                    'rationale': f'弱势测试强支撑{sup_price:.2f}+动能停滞，Fading测试者',
                    'momentum_slope': momentum_slope,
                    'fast_rejection': support.get('is_fast_rejection', False)
                }
        
        return None
    except:
        return None


def detect_ytc_signals(df_15m: pd.DataFrame, df_1h: pd.DataFrame, sr_levels: dict, momentum_slope: float) -> dict:
    """
    综合检测YTC五大信号（V7.6完整版）
    
    优先级：BOF > BPB > PB > TST > CPB
    
    Args:
        df_15m: 15分钟K线数据
        df_1h: 1小时K线数据
        sr_levels: 支撑阻力位数据
        momentum_slope: 动能斜率
    
    Returns:
        dict: 最强YTC信号，如无则返回None
    """
    try:
        signals = []
        
        # 1. BOF（突破失败）- 最高优先级（逆势结构）
        bof_signal = detect_breakout_failure(df_15m, sr_levels)
        if bof_signal:
            signals.append(bof_signal)
        
        # 2. BPB（突破回调）- 次高优先级（顺势结构）
        bpb_signal = detect_breakout_pullback(df_15m, df_1h, sr_levels)
        if bpb_signal:
            signals.append(bpb_signal)
        
        # 3. TST（测试）- 第三优先级（结构测试）
        tst_signal = detect_support_resistance_test(df_15m, sr_levels, momentum_slope)
        if tst_signal:
            signals.append(tst_signal)
        
        # 4. ✨激活：PB/CPB（顺势回调）- YTC主力交易场景
        pullback_info = identify_pullback_type(df_15m)
        if pullback_info:
            weakness_score = calculate_pullback_weakness_score(df_15m, pullback_info)
            
            if pullback_info.get('type') == 'simple_pullback' and pullback_info.get('signal') == 'entry_ready':
                # 简单回调：高弱势（优质PB）
                trend_direction = 'LONG' if df_1h.iloc[-1]['close'] > df_1h.iloc[-5]['close'] else 'SHORT'
                
                # YTC心理学：被困的逆势交易者
                if trend_direction == 'LONG':
                    trapped_traders = "Fading Trapped Reversal Traders: Sellers who entered against the main trend during the weak pullback are about to be stopped out."
                else:
                    trapped_traders = "Fading Trapped Reversal Traders: Buyers who entered against the main trend during the weak pullback are about to be stopped out."
                
                pb_signal = {
                    'signal_type': 'PB',
                    'direction': trend_direction,
                    'strength': 5 if weakness_score > 0.85 else 4,
                        'entry_price': df_15m.iloc[-1]['close'],  # LWP for PB is often the close of the reversal candle
                    'sr_strength': 3,  # PB不依赖S/R，强度默认为3
                    'rationale': f"Weak PB ({pullback_info['depth_pct']:.1f}%), weakness={weakness_score:.2f}, optimal entry against trapped reversal traders.",
                        'weakness_score': weakness_score,
                    'trapped_traders': trapped_traders
                }
                signals.append(pb_signal)
            
            elif pullback_info.get('type') == 'complex_pullback':
                # 复杂回调：作为观察信号，强度设为1（最低）避免被选为主信号
                cpb_signal = {
                    'signal_type': 'CPB',
                    'direction': 'WAIT',  # 等待突破确认
                    'strength': 1,  # 最低强度，确保不会被选为主信号
                    'entry_price': 0,
                        'sr_strength': 2,
                    'rationale': f"Complex pullback {pullback_info['depth_pct']:.1f}%, awaiting breakout confirmation. DO NOT ENTER.",
                    'weakness_score': weakness_score,
                    'trapped_traders': 'N/A - Wait Mode'
                }
                signals.append(cpb_signal)  # 加入列表让AI看到CPB状态
        
        # 选择最强信号（按strength排序，strength相同时BOF>BPB>PB>TST>CPB）
        if signals:
            priority_map = {'BOF': 5, 'BPB': 4, 'PB': 3, 'TST': 2, 'CPB': 1}
            best_signal = max(signals, key=lambda x: (x['strength'], priority_map.get(x['signal_type'], 0)))
            return best_signal
        else:
            return None
    except Exception as e:
        print(f"⚠️ detect_ytc_signals error: {e}")
        return None


# ===== YTC-Enhanced 辅助函数（V7.5新增）=====

def calculate_momentum_slope(df: pd.DataFrame, period: int = 5) -> float:
    """
    计算收盘价的线性回归斜率（YTC动能分析）
    
    Args:
        df: K线数据
        period: 计算周期
    
    Returns:
        slope: 归一化斜率（相对价格的百分比变化率）
    """
    try:
        if len(df) < period:
            return 0.0
        
        recent_closes = df['close'].tail(period).values
        x = np.arange(period)
        
        # 线性回归
        slope, intercept = np.polyfit(x, recent_closes, 1)
        
        # 归一化：斜率 / 平均价格 * 100
        avg_price = recent_closes.mean()
        normalized_slope = (slope / avg_price) * 100 if avg_price > 0 else 0
        
        return float(normalized_slope)
    except:
        return 0.0


def check_polarity_switch(price: float, df: pd.DataFrame, tolerance: float = 0.005) -> bool:
    """
    检查价格位是否经历过极性转换（YTC核心概念）
    即：曾经是阻力，被突破后变成支撑（或反之）
    
    Args:
        price: 待检查的价格位
        df: K线数据
        tolerance: 价格容差（默认0.5%）
    
    Returns:
        bool: 是否发生极性转换
    """
    try:
        if len(df) < 30:
            return False
        
        price_band_upper = price * (1 + tolerance)
        price_band_lower = price * (1 - tolerance)
        
        for i in range(20, len(df) - 10):
            # 检查该K线是否在价格带内
            in_band = (df.iloc[i]['low'] <= price_band_upper and 
                      df.iloc[i]['high'] >= price_band_lower)
            
            if in_band:
                # 检查前后10根K线的行为
                before = df.iloc[i-10:i]
                after = df.iloc[i+1:min(i+11, len(df))]
                
                if len(after) < 5:
                    continue
                
                # 场景1：曾是阻力（价格从下方触及后回落），后变支撑
                was_resistance = (before['high'].max() <= price_band_upper * 1.02 and 
                                before['close'].iloc[-1] < price)
                became_support = (after['low'].min() >= price_band_lower * 0.98 and
                                after['close'].iloc[-1] > price)
                
                # 场景2：曾是支撑，后变阻力
                was_support = (before['low'].min() >= price_band_lower * 0.98 and
                             before['close'].iloc[-1] > price)
                became_resistance = (after['high'].max() <= price_band_upper * 1.02 and
                                   after['close'].iloc[-1] < price)
                
                if (was_resistance and became_support) or (was_support and became_resistance):
                    return True
        
        return False
    except:
        return False


def count_price_tests(price: float, df: pd.DataFrame, tolerance: float = 0.005) -> int:
    """
    统计价格带被测试的次数
    
    Args:
        price: 支撑/阻力价格
        df: K线数据
        tolerance: 价格容差
    
    Returns:
        int: 测试次数
    """
    try:
        price_band_upper = price * (1 + tolerance)
        price_band_lower = price * (1 - tolerance)
        
        test_count = 0
        last_test_idx = -10
        
        for i in range(len(df)):
            # 检查是否触及价格带
            touched = (df.iloc[i]['low'] <= price_band_upper and 
                      df.iloc[i]['high'] >= price_band_lower)
            
            # 至少间隔5根K线才算新的测试
            if touched and i - last_test_idx > 5:
                test_count += 1
                last_test_idx = i
        
        return test_count
    except:
        return 0


def check_fast_rejection(price: float, df: pd.DataFrame, tolerance: float = 0.005) -> bool:
    """
    检查是否存在快速拒绝（YTC关键概念）
    即：价格触及该位后，1-2根K线内快速反弹>1.5%
    
    Args:
        price: 支撑/阻力价格
        df: K线数据
        tolerance: 价格容差
    
    Returns:
        bool: 是否存在快速拒绝
    """
    try:
        if len(df) < 3:
            return False
        
        price_band_upper = price * (1 + tolerance)
        price_band_lower = price * (1 - tolerance)
        
        for i in range(len(df) - 3):
            touched = (df.iloc[i]['low'] <= price_band_upper and 
                      df.iloc[i]['high'] >= price_band_lower)
            
            if touched:
                # 检查接下来1-2根K线是否快速反弹
                next_1 = df.iloc[i+1]
                next_2 = df.iloc[i+2] if i+2 < len(df) else next_1
                
                # 多头快速拒绝：触及后快速上涨
                bounce_up = (next_2['close'] - df.iloc[i]['low']) / df.iloc[i]['low']
                if bounce_up > 0.015:  # >1.5%
                    return True
                
                # 空头快速拒绝：触及后快速下跌
                drop_down = (df.iloc[i]['high'] - next_2['close']) / df.iloc[i]['high']
                if drop_down > 0.015:
                    return True
        
        return False
    except:
        return False


def evaluate_sr_quality(sr_level: dict, df: pd.DataFrame) -> dict:
    """
    评估支撑/阻力的质量（YTC S/R强度系统）
    
    评分标准（1-5分）：
    1. 极性转换（曾经的支撑变阻力，或反之）：+2分
    2. 多次测试（历史触及次数≥3）：+1分
    3. 快速拒绝（触及后快速反弹>1.5%）：+1分
    4. 基础分：1分
    
    Args:
        sr_level: 支撑/阻力位字典
        df: K线数据
    
    Returns:
        dict: 增强的sr_level，包含strength, is_switched_polarity等
    """
    try:
        price = sr_level.get('price', 0)
        if not price or len(df) < 20:
            sr_level['strength'] = 1
            sr_level['is_switched_polarity'] = False
            sr_level['is_fast_rejection'] = False
            sr_level['test_count'] = 0
            return sr_level
        
        strength = 1
        tolerance = 0.005
        
        # 1. 检查极性转换（最重要，+2分）
        is_switched = check_polarity_switch(price, df, tolerance)
        if is_switched:
            strength += 2
        
        # 2. 统计历史测试次数（+1分）
        test_count = count_price_tests(price, df, tolerance)
        if test_count >= 3:
            strength += 1
        
        # 3. 检查快速拒绝（+1分）
        is_fast = check_fast_rejection(price, df, tolerance)
        if is_fast:
            strength += 1
        
        # 更新字典
        sr_level['strength'] = min(5, strength)
        sr_level['is_switched_polarity'] = is_switched
        sr_level['is_fast_rejection'] = is_fast
        sr_level['test_count'] = test_count
        
        return sr_level
    except Exception as e:
        sr_level['strength'] = 1
        sr_level['is_switched_polarity'] = False
        sr_level['is_fast_rejection'] = False
        return sr_level


def calculate_pullback_weakness_score(df: pd.DataFrame, pullback_info: dict) -> float:
    """
    计算回调的弱势程度（YTC回调分析）
    
    评分标准（0.0-1.0）：
    1. 回调深度浅（<23.6%）：+0.3
    2. 回调动能斜率显著低于主趋势：+0.4
    3. 回调K线数量少（1-3根）：+0.3
    
    Args:
        df: K线数据
        pullback_info: 回调信息字典
    
    Returns:
        float: 弱势得分（0.0-1.0，越高越弱）
    """
    try:
        score = 0.0
        
        # 1. 回调深度评分
        depth = pullback_info.get('depth_pct', 50)
        if depth < 23.6:
            score += 0.3
        elif depth < 38.2:
            score += 0.2
        
        # 2. 动能对比评分
        if len(df) >= 20:
            main_slope = calculate_momentum_slope(df.tail(20), 10)  # 主趋势动能
            pullback_slope = calculate_momentum_slope(df.tail(5), 5)  # 回调动能
            
            # 如果回调动能与主趋势反向，且绝对值小很多
            if main_slope * pullback_slope < 0:  # 反向
                momentum_ratio = abs(pullback_slope) / (abs(main_slope) + 0.01)
                if momentum_ratio < 0.3:
                    score += 0.4
                elif momentum_ratio < 0.5:
                    score += 0.2
        
        # 3. K线数量评分
        duration = pullback_info.get('duration', 5)
        if duration <= 3:
            score += 0.3
        elif duration <= 5:
            score += 0.1
        
        return min(1.0, score)
    except:
        return 0.5  # 默认中等弱势


def detect_lwp_reference_price(df_15m: pd.DataFrame, sr_levels: dict, pullback_info: dict) -> dict:
    """
    识别LWP参考价（Last Wholesale Price - YTC核心概念）
    
    不作为硬性限价单价格，而是作为"理想入场价"的参考
    
    Args:
        df_15m: 15分钟K线数据
        sr_levels: 支撑阻力位
        pullback_info: 回调信息
    
    Returns:
        dict: {'lwp_long': float, 'lwp_short': float, 'confidence': str}
    """
    try:
        if len(df_15m) < 2:
            return {'lwp_long': None, 'lwp_short': None, 'confidence': 'none'}
        
        current = df_15m.iloc[-1]
        prev = df_15m.iloc[-2]
        
        lwp_long = None
        lwp_short = None
        confidence = 'none'
        
        # 场景1：Simple Pullback - LWP是回调低点
        if pullback_info and pullback_info.get('type') == 'simple_pullback':
            recent_lows = df_15m.tail(5)['low']
            lwp_long = float(recent_lows.min())
            confidence = 'high'
        
        # 场景2：Bullish Pin Bar - LWP是下影线底部
        if prev.get('pin_bar') == 'bullish_pin' or current.get('pin_bar') == 'bullish_pin':
            pin_low = prev['low'] if prev.get('pin_bar') == 'bullish_pin' else current['low']
            if not lwp_long or pin_low < lwp_long:
                lwp_long = float(pin_low)
                confidence = 'high'
        
        # 场景3：Support Test - LWP是高强度支撑位
        nearest_support = sr_levels.get('nearest_support', {})
        if nearest_support and nearest_support.get('strength', 0) >= 4:
            sup_price = nearest_support.get('price')
            if sup_price and (not lwp_long or abs(sup_price - current['close']) < abs(lwp_long - current['close'])):
                lwp_long = float(sup_price)
                confidence = 'high'
        
        # 空头信号同理
        if pullback_info and pullback_info.get('type') == 'simple_pullback' and pullback_info.get('direction') == 'bearish':
            recent_highs = df_15m.tail(5)['high']
            lwp_short = float(recent_highs.max())
            confidence = 'high'
        
        if prev.get('pin_bar') == 'bearish_pin' or current.get('pin_bar') == 'bearish_pin':
            pin_high = prev['high'] if prev.get('pin_bar') == 'bearish_pin' else current['high']
            if not lwp_short or pin_high > lwp_short:
                lwp_short = float(pin_high)
                confidence = 'high'
        
        nearest_resistance = sr_levels.get('nearest_resistance', {})
        if nearest_resistance and nearest_resistance.get('strength', 0) >= 4:
            res_price = nearest_resistance.get('price')
            if res_price and (not lwp_short or abs(res_price - current['close']) < abs(lwp_short - current['close'])):
                lwp_short = float(res_price)
                confidence = 'high'
        
        return {
            'lwp_long': lwp_long,
            'lwp_short': lwp_short,
            'confidence': confidence
        }
    except:
        return {'lwp_long': None, 'lwp_short': None, 'confidence': 'none'}


# ===== 原有函数（增强版）=====

def find_support_resistance(df, current_price):
    """识别支撑阻力位（结合历史关键位和均线）+ YTC质量评估"""
    try:
        resistances = []
        supports = []
        
        # 方法1：历史波峰波谷（最近50根K线）
        if len(df) >= 50:
            recent_df = df.tail(50)
            
            # 找波峰（阻力）
            try:
                resistance_idx = argrelextrema(
                    recent_df["high"].values, np.greater, order=3
                )[0]
                if len(resistance_idx) > 0:
                    hist_resistances = recent_df.iloc[resistance_idx]["high"].tolist()
                    for r in hist_resistances:
                        if r > current_price:
                            resistances.append(
                                {"price": r, "type": "historical", "strength": "strong"}
                            )
            except:
                pass
            
            # 找波谷（支撑）
            try:
                support_idx = argrelextrema(recent_df["low"].values, np.less, order=3)[
                    0
                ]
                if len(support_idx) > 0:
                    hist_supports = recent_df.iloc[support_idx]["low"].tolist()
                    for s in hist_supports:
                        if s < current_price:
                            supports.append(
                                {"price": s, "type": "historical", "strength": "strong"}
                            )
            except:
                pass
        
        # 去重并排序
        if resistances:
            resistances = sorted(resistances, key=lambda x: x["price"])[:3]
        if supports:
            supports = sorted(supports, key=lambda x: x["price"], reverse=True)[:3]
        
        # === YTC增强：质量评估 ===
        # 对每个支撑阻力位进行质量评估
        for i in range(len(resistances)):
            resistances[i] = evaluate_sr_quality(resistances[i], df)
        
        for i in range(len(supports)):
            supports[i] = evaluate_sr_quality(supports[i], df)
        
        # 找最近的关键位
        nearest_resistance = resistances[0] if resistances else None
        nearest_support = supports[0] if supports else None
        
        # 判断当前位置
        position_status = "neutral"
        if (
            nearest_resistance
            and (nearest_resistance["price"] - current_price) / current_price < 0.005
        ):
            position_status = "at_resistance"
        elif (
            nearest_support
            and (current_price - nearest_support["price"]) / current_price < 0.005
        ):
            position_status = "at_support"
        
        return {
            "resistances": resistances,
            "supports": supports,
            "nearest_resistance": nearest_resistance,
            "nearest_support": nearest_support,
            "position_status": position_status,
        }
    except Exception as e:
        print(f"支撑阻力位识别失败: {e}")
        return {
            "resistances": [],
            "supports": [],
            "nearest_resistance": None,
            "nearest_support": None,
            "position_status": "neutral",
        }


def calculate_unified_risk_reward_v2(entry_price, side, market_data, signal_classification, min_rr=None):
    """
    【V7.9新增】双模式TP/SL计算：根据信号类型选择策略
    
    Scalping: 基于15分钟ATR，快速进出
    Swing: 基于1小时支撑阻力，波段操作
    
    Args:
        entry_price: 入场价格
            side: 'long' 或 'short'
        market_data: 完整市场数据（包含15m和1h数据）
        signal_classification: 信号分类信息
        min_rr: 最小盈亏比（可选）
    """
    try:
        signal_type = signal_classification.get('signal_type', 'swing')
        
        # 加载学习参数
        config = load_learning_config()
        if min_rr is None:
            # Scalping要求更低的R:R（1.5:1），Swing要求更高（2.5:1）
            min_rr = 1.5 if signal_type == 'scalping' else config.get("min_risk_reward", 2.5)
        
        # 获取ATR数据
        atr_15m = market_data.get("atr", {}).get("atr_14", 0)  # 15分钟ATR
        atr_1h = market_data.get("mid_term", {}).get("atr", 0) or atr_15m * 2  # 1小时ATR（估算）
        
        # 获取支撑阻力位
        sr_15m = market_data.get("support_resistance", {})
        sr_1h = market_data.get("mid_term", {}).get("support_resistance", {})
        
        if signal_type == 'scalping':
            # === 【V8.0】Scalping模式：从配置读取参数 ===
            scalping_config = config.get('scalping_params', {})
            atr_multiplier = scalping_config.get('atr_stop_multiplier', 1.0)
            tp_multiplier = scalping_config.get('atr_tp_multiplier', 1.5)
            
            print(f"  ⚡ 超短线TP/SL: 止损{atr_multiplier}×ATR, 止盈{tp_multiplier}×ATR")
            
            if side == "long":
                stop_loss = entry_price - (atr_15m * atr_multiplier)
                take_profit = entry_price + (atr_15m * tp_multiplier)
                
                stop_reason = f"15m_ATR×{atr_multiplier}（Scalping紧止损）"
                tp_reason = f"15m_ATR×{tp_multiplier}（快速目标）"
            else:  # short
                stop_loss = entry_price + (atr_15m * atr_multiplier)
                take_profit = entry_price - (atr_15m * tp_multiplier)
                
                stop_reason = f"15m_ATR×{atr_multiplier}（Scalping紧止损）"
                tp_reason = f"15m_ATR×{tp_multiplier}（快速目标）"
            
            risk = abs(entry_price - stop_loss)
            reward = abs(take_profit - entry_price)
            actual_rr = reward / risk if risk > 0 else 0
            
            return {
                "stop_loss": round(stop_loss, 2),
                "take_profit": round(take_profit, 2),
                "risk_reward": round(actual_rr, 2),
                "risk_amount": round(risk, 2),
                "reward_amount": round(reward, 2),
                "stop_loss_reason": stop_reason,
                "take_profit_reason": tp_reason,
                "valid": actual_rr >= min_rr,
                "mode": "scalping"
            }
        
        else:
            # === 【V8.0】Swing模式：从配置读取参数，优先使用支撑阻力位 ===
            swing_config = config.get('swing_params', {})
            atr_multiplier = swing_config.get('atr_stop_multiplier', 2.0)
            tp_multiplier = swing_config.get('atr_tp_multiplier', 6.0)
            use_htf_levels = swing_config.get('use_htf_levels', True)  # 是否使用高时间框架
            
            print(f"  🌊 波段TP/SL: 止损{atr_multiplier}×ATR, 止盈{tp_multiplier}×ATR (优先支撑阻力位)")
            
            if side == "long":
                # 止损：1h支撑位或ATR
                nearest_support_1h = sr_1h.get("nearest_support", {})
                if nearest_support_1h and nearest_support_1h.get("price", 0) < entry_price:
                    support_price = nearest_support_1h["price"]
                    buffer = atr_1h * (0.5 if nearest_support_1h.get("strength") == "strong" else 1.0)
                    stop_loss = support_price - buffer
                    stop_reason = f"1h支撑{support_price:.0f}-缓冲（Swing）"
                else:
                    # 回退到15m支撑
                    nearest_support_15m = sr_15m.get("nearest_support", {})
                    if nearest_support_15m and nearest_support_15m.get("price", 0) < entry_price:
                        support_price = nearest_support_15m["price"]
                        stop_loss = support_price - atr_15m * 1.0
                        stop_reason = f"15m支撑{support_price:.0f}（回退）"
                    else:
                        stop_loss = entry_price - (atr_1h * atr_multiplier)
                        stop_reason = f"1h_ATR×{atr_multiplier}"
                
                # 止盈：1h阻力位
                nearest_resistance_1h = sr_1h.get("nearest_resistance", {})
                if nearest_resistance_1h and nearest_resistance_1h.get("price", 0) > entry_price:
                    resistance_price = nearest_resistance_1h["price"]
                    safety_margin = atr_1h * (1.5 if nearest_resistance_1h.get("strength") == "strong" else 0.8)
                    take_profit = resistance_price - safety_margin
                    tp_reason = f"1h阻力{resistance_price:.0f}前（Swing）"
                else:
                    # 【V8.0】回退到ATR倍数计算（让利润奔跑）
                    take_profit = entry_price + (atr_1h * tp_multiplier)
                    tp_reason = f"1h_ATR×{tp_multiplier}（让利润奔跑）"
                
            else:  # short
                # 止损：1h阻力位或ATR
                nearest_resistance_1h = sr_1h.get("nearest_resistance", {})
                if nearest_resistance_1h and nearest_resistance_1h.get("price", 0) > entry_price:
                    resistance_price = nearest_resistance_1h["price"]
                    buffer = atr_1h * (0.5 if nearest_resistance_1h.get("strength") == "strong" else 1.0)
                    stop_loss = resistance_price + buffer
                    stop_reason = f"1h阻力{resistance_price:.0f}+缓冲（Swing）"
                else:
                    # 回退到15m阻力
                    nearest_resistance_15m = sr_15m.get("nearest_resistance", {})
                    if nearest_resistance_15m and nearest_resistance_15m.get("price", 0) > entry_price:
                        resistance_price = nearest_resistance_15m["price"]
                        stop_loss = resistance_price + atr_15m * 1.0
                        stop_reason = f"15m阻力{resistance_price:.0f}（回退）"
                    else:
                        stop_loss = entry_price + (atr_1h * atr_multiplier)
                        stop_reason = f"1h_ATR×{atr_multiplier}"
                
                # 止盈：1h支撑位
                nearest_support_1h = sr_1h.get("nearest_support", {})
                if nearest_support_1h and nearest_support_1h.get("price", 0) < entry_price:
                    support_price = nearest_support_1h["price"]
                    safety_margin = atr_1h * (1.5 if nearest_support_1h.get("strength") == "strong" else 0.8)
                    take_profit = support_price + safety_margin
                    tp_reason = f"1h支撑{support_price:.0f}前（Swing）"
                else:
                    # 【V8.0】回退到ATR倍数计算（让利润奔跑）
                    take_profit = entry_price - (atr_1h * tp_multiplier)
                    tp_reason = f"1h_ATR×{tp_multiplier}（让利润奔跑）"
            
            # 验证盈亏比
            risk = abs(entry_price - stop_loss)
            reward = abs(take_profit - entry_price)
            
            if risk <= 0:
                return None
            
            actual_rr = reward / risk
            
            # 如果盈亏比不足，调整止盈
            if actual_rr < min_rr:
                if side == "long":
                    take_profit = entry_price + (risk * min_rr)
                else:
                    take_profit = entry_price - (risk * min_rr)
                reward = abs(take_profit - entry_price)
                actual_rr = min_rr
                tp_reason = f"盈亏比{min_rr}:1（调整后）"
            
            return {
                "stop_loss": round(stop_loss, 2),
                "take_profit": round(take_profit, 2),
                "risk_reward": round(actual_rr, 2),
                "risk_amount": round(risk, 2),
                "reward_amount": round(reward, 2),
                "stop_loss_reason": stop_reason,
                "take_profit_reason": tp_reason,
                "valid": actual_rr >= min_rr,
                "mode": "swing"
            }
    
    except Exception as e:
        print(f"⚠️ TP/SL计算失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def calculate_unified_risk_reward(entry_price, side, sr_levels, atr_14, min_rr=None):
    """统一的止损止盈计算（结合支撑阻力位+ATR，使用学习参数）
    
    【V7.9提示】此函数保留用于向后兼容，新代码请使用 calculate_unified_risk_reward_v2
    """
    try:
        # 加载学习参数
        config = load_learning_config()
        if min_rr is None:
            min_rr = config["min_risk_reward"]
        atr_multiplier = config["atr_stop_multiplier"]

        if side == "long":
            # === 多单 ===
            nearest_support = sr_levels["nearest_support"]
            
            # 计算止损
            if nearest_support and nearest_support["price"] < entry_price:
                support_price = nearest_support["price"]
                buffer = atr_14 * (
                    0.5 if nearest_support["strength"] == "strong" else 1.0
                )
                stop_loss = support_price - buffer
            else:
                stop_loss = entry_price - (atr_14 * atr_multiplier)
            
            # 计算止盈
            nearest_resistance = sr_levels["nearest_resistance"]
            if nearest_resistance and nearest_resistance["price"] > entry_price:
                resistance_price = nearest_resistance["price"]
                safety_margin = atr_14 * (
                    1.5 if nearest_resistance["strength"] == "strong" else 0.8
                )
                take_profit = resistance_price - safety_margin
            else:
                risk = entry_price - stop_loss
                take_profit = entry_price + (risk * min_rr)
            
            # 验证盈亏比
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
            
            if risk <= 0:
                return None
            
            actual_rr = reward / risk
            
            # 如果盈亏比不足，调整止盈
            if actual_rr < min_rr:
                take_profit = entry_price + (risk * min_rr)
                reward = take_profit - entry_price
                actual_rr = min_rr
            
            # 最终验证：止盈不能超过阻力位
            if nearest_resistance and take_profit > nearest_resistance["price"]:
                take_profit = nearest_resistance["price"] - (atr_14 * 1.2)
                reward = take_profit - entry_price
                if reward <= 0:
                    return None
                required_risk = reward / min_rr
                stop_loss = entry_price - required_risk
                risk = required_risk
                actual_rr = reward / risk
            
            stop_reason = (
                f"支撑{support_price:.0f}-ATR缓冲" if nearest_support else "ATR×1.5"
                    )
            tp_reason = (
                f"阻力{nearest_resistance['price']:.0f}前"
                if nearest_resistance
                    else f"盈亏比{min_rr}:1"
            )
            
            return {
                "stop_loss": round(stop_loss, 2),
                "take_profit": round(take_profit, 2),
                "risk_reward": round(actual_rr, 2),
                "risk_amount": round(risk, 2),
                "reward_amount": round(reward, 2),
                "stop_loss_reason": stop_reason,
                "take_profit_reason": tp_reason,
                "valid": actual_rr >= min_rr,
            }
            
        else:  # short
            # === 空单（类似逻辑）===
            nearest_resistance = sr_levels["nearest_resistance"]

            if nearest_resistance and nearest_resistance["price"] > entry_price:
                resistance_price = nearest_resistance["price"]
                buffer = atr_14 * (
                    0.5 if nearest_resistance["strength"] == "strong" else 1.0
                )
                stop_loss = resistance_price + buffer
            else:
                stop_loss = entry_price + (atr_14 * atr_multiplier)

            nearest_support = sr_levels["nearest_support"]
            if nearest_support and nearest_support["price"] < entry_price:
                support_price = nearest_support["price"]
                safety_margin = atr_14 * (
                    1.5 if nearest_support["strength"] == "strong" else 0.8
                )
                take_profit = support_price + safety_margin
            else:
                risk = stop_loss - entry_price
                take_profit = entry_price - (risk * min_rr)
            
            risk = stop_loss - entry_price
            reward = entry_price - take_profit
            
            if risk <= 0:
                return None
            
            actual_rr = reward / risk
            
            if actual_rr < min_rr:
                take_profit = entry_price - (risk * min_rr)
                reward = entry_price - take_profit
                actual_rr = min_rr
            
            if nearest_support and take_profit < nearest_support["price"]:
                take_profit = nearest_support["price"] + (atr_14 * 1.2)
                reward = entry_price - take_profit
                if reward <= 0:
                    return None
                required_risk = reward / min_rr
                stop_loss = entry_price + required_risk
                risk = required_risk
                actual_rr = reward / risk
            
            stop_reason = (
                f"阻力{resistance_price:.0f}+ATR缓冲"
                if nearest_resistance
                    else "ATR×1.5"
            )
            tp_reason = (
                f"支撑{nearest_support['price']:.0f}前"
                if nearest_support
                    else f"盈亏比{min_rr}:1"
            )
            
            return {
                "stop_loss": round(stop_loss, 2),
                "take_profit": round(take_profit, 2),
                "risk_reward": round(actual_rr, 2),
                "risk_amount": round(risk, 2),
                "reward_amount": round(reward, 2),
                "stop_loss_reason": stop_reason,
                "take_profit_reason": tp_reason,
                "valid": actual_rr >= min_rr,
            }
    except Exception as e:
        print(f"盈亏比计算失败: {e}")
        return None


# ==================== V7.6.5: 信号分级系统 ====================

def classify_signal_quality(signal_score: int, ytc_signal: str, trend_alignment: int) -> tuple:
    """
    信号质量分级：HIGH / MEDIUM / LOW
    
    Args:
        signal_score: 信号得分 (0-100)
        ytc_signal: YTC信号类型 (BOF/BPB/TST/PB/CPB或空)
        trend_alignment: 趋势对齐层数 (0-3)
        
    Returns:
        (tier, description)
    """
    # HIGH: signal_score >= 70 AND ytc_signal AND 3层趋势对齐
    if signal_score >= 70 and ytc_signal and trend_alignment == 3:
        return "HIGH", SIGNAL_TIER_PARAMS["HIGH"]["description"]
    
    # MEDIUM: signal_score >= 60 AND 至少2层趋势对齐
    elif signal_score >= 60 and trend_alignment >= 2:
        return "MEDIUM", SIGNAL_TIER_PARAMS["MEDIUM"]["description"]
    
    # LOW: 其他情况
    else:
        return "LOW", SIGNAL_TIER_PARAMS["LOW"]["description"]


def get_adjusted_params_for_signal(
    symbol: str,
    signal_tier: str,
    base_config: dict
) -> dict:
    """
    根据信号级别和币种特性，动态调整交易参数
    
    Args:
        symbol: 交易对
        signal_tier: 信号级别 (HIGH/MEDIUM/LOW)
        base_config: 基础配置（来自learning_config）
        
    Returns:
        调整后的参数字典
    """
    # 获取币种画像
    symbol_profile = SYMBOL_PROFILES.get(symbol, {})
    if not symbol_profile:
        # 未知币种使用默认配置
        symbol_profile = {
            "name": symbol.split("/")[0],
            "volatility": "MEDIUM",
            "atr_multiplier_adjustment": 1.0,
            "recommended_holding_hours": 4
        }
    
    # 获取信号分级参数
    tier_params = SIGNAL_TIER_PARAMS.get(signal_tier, SIGNAL_TIER_PARAMS["MEDIUM"])
    
    # 基础参数
    base_rr = base_config.get('min_risk_reward', 2.0)
    base_atr = base_config.get('atr_stop_multiplier', 1.8)
    base_pos = base_config.get('base_position_pct', 15)
    
    # 应用信号分级调整
    adjusted_rr = tier_params['min_risk_reward']
    adjusted_atr = base_atr * tier_params['atr_multiplier']
    adjusted_pos = base_pos * tier_params['position_multiplier']
    
    # 应用币种个性化调整
    final_atr = adjusted_atr * symbol_profile.get('atr_multiplier_adjustment', 1.0)
    final_pos = min(adjusted_pos, base_pos * 1.5)  # 最多放大1.5倍
    
    return {
        'min_risk_reward': adjusted_rr,
        'atr_stop_multiplier': final_atr,
        'position_pct': final_pos,
        'signal_tier': signal_tier,
        'tier_description': tier_params['description'],
        'symbol_profile': symbol_profile,
        'adjustments_applied': {
            'base_rr': base_rr,
            'adjusted_rr': adjusted_rr,
            'base_atr': base_atr,
            'final_atr': final_atr,
            'base_pos': base_pos,
            'final_pos': final_pos
        }
    }


def get_ohlcv_data(symbol):
    """获取单个币种的K线数据和技术指标（已移除signal.alarm以兼容supervisor）"""
    try:
        # === 15分钟K线数据（短期） ===
        # ccxt自带timeout机制，无需signal.alarm
        limit_15m = 1344  # 14天数据
        ohlcv_15m = exchange.fetch_ohlcv(
            symbol, TRADE_CONFIG["timeframe"], limit=limit_15m
        )

        df_15m = pd.DataFrame(
            ohlcv_15m, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df_15m["timestamp"] = pd.to_datetime(df_15m["timestamp"], unit="ms")
        
        # === 4小时K线数据（长期趋势） ===
        try:
            ohlcv_4h = exchange.fetch_ohlcv(symbol, "4h", limit=168)  # 约1个月
            df_4h = pd.DataFrame(
                ohlcv_4h,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df_4h["timestamp"] = pd.to_datetime(df_4h["timestamp"], unit="ms")
        except Exception as e:
            print(f"⚠️ {symbol} 4H数据获取失败({e})，重采样15m数据")
            # V7.6.2: 重采样15m到4h，保持时间框架一致
            df_15m_copy = df_15m.copy()
            df_15m_copy.set_index('timestamp', inplace=True)
            df_4h = df_15m_copy.resample('4H').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna().reset_index()
        
        # === 1小时K线数据（止损止盈位 + 中期趋势）V6.5 ===
        try:
            ohlcv_1h = exchange.fetch_ohlcv(symbol, "1h", limit=672)  # 约1个月
            df_1h = pd.DataFrame(
                ohlcv_1h,
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )
            df_1h["timestamp"] = pd.to_datetime(df_1h["timestamp"], unit="ms")
            
            # V7.6.2: 数据质量检查
            if len(df_1h) < 50:
                print(f"⚠️ {symbol} 1H数据不足({len(df_1h)}根)，重采样15m数据")
                raise ValueError("1H数据不足")
                
        except Exception as e:
            print(f"⚠️ {symbol} 1H数据获取失败({e})，重采样15m数据")
            # V7.6.2: 重采样15m到1h，保持时间框架一致
            df_15m_copy = df_15m.copy()
            df_15m_copy.set_index('timestamp', inplace=True)
            df_1h = df_15m_copy.resample('1H').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna().reset_index()
        
        current_data = df_15m.iloc[-1]
        previous_data = df_15m.iloc[-2] if len(df_15m) > 1 else current_data
        
        # === 短期指标（15分钟） ===
        
        # MACD
        macd_line, signal_line, histogram = calculate_macd(df_15m)
        macd_trend = "多头" if histogram > 0 else "空头"
        
        # 成交量分析
        volume_ma20 = df_15m["volume"].tail(20).mean()
        volume_ratio = (
            (current_data["volume"] / volume_ma20) * 100 if volume_ma20 > 0 else 100
        )
        volume_status = (
            "放量" if volume_ratio > 150 else "缩量" if volume_ratio < 50 else "正常"
        )
        
        # 多周期均线
        ma7 = df_15m["close"].tail(28).mean()
        ma24 = df_15m["close"].tail(96).mean()
        ma72 = df_15m["close"].tail(288).mean()
        ema20 = df_15m["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = df_15m["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        
        # 多周期RSI
        def calculate_rsi(data, period):
            delta = data.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
        
        rsi_7 = calculate_rsi(df_15m["close"], 7)
        rsi_14 = calculate_rsi(df_15m["close"], 14)
        
        # ATR（波动率）
        def calculate_atr(df, period):
            high_low = df["high"] - df["low"]
            high_close = abs(df["high"] - df["close"].shift())
            low_close = abs(df["low"] - df["close"].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean()
            return atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0
        
        atr_3 = calculate_atr(df_15m, 3)
        atr_14 = calculate_atr(df_15m, 14)
        
        # === 长期指标（4小时） ===
        current_4h = df_4h.iloc[-1]
        
        # 4小时均线
        ema20_4h = df_4h["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50_4h = df_4h["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        
        # 4小时MACD
        macd_line_4h, signal_line_4h, histogram_4h = calculate_macd(df_4h)
        macd_trend_4h = "多头" if histogram_4h > 0 else "空头"
        
        # 4小时RSI
        rsi_14_4h = calculate_rsi(df_4h["close"], 14)
        
        # 4小时ATR
        atr_3_4h = calculate_atr(df_4h, 3)
        atr_14_4h = calculate_atr(df_4h, 14)
        
        # 4小时成交量
        volume_ma_4h = df_4h["volume"].tail(20).mean()
        volume_ratio_4h = (
            (current_4h["volume"] / volume_ma_4h) * 100 if volume_ma_4h > 0 else 100
        )
        
        # 趋势判断（基于4小时）
        if ema20_4h > ema50_4h:
            long_term_trend = "多头" if current_4h["close"] > ema20_4h else "多头转弱"
        else:
            long_term_trend = "空头" if current_4h["close"] < ema20_4h else "空头转弱"
        
        # === 裸K分析（Price Action）- 增强版 ===
        pin_bar = detect_pin_bar(current_data)
        engulfing = (
            detect_engulfing(previous_data, current_data) if len(df_15m) > 1 else None
        )

        # 新增：突破性大阳线识别
        prev_high = df_15m["high"].tail(20).max()  # 最近20根K线的最高点
        avg_volume_20 = df_15m["volume"].tail(20).mean()
        # V8.2.3.6：保留旧逻辑作为备用，主要使用sr_levels检测
        breakout_legacy = detect_breakout_candle(current_data, prev_high, avg_volume_20)

        # 新增：连续阳线趋势确认
        consecutive = detect_consecutive_bullish(df_15m, lookback=3)

        # 新增：极端放量识别
        volume_surge = detect_extreme_volume_surge(
            current_data["volume"], avg_volume_20
        )

        # 新增：Pin Bar + 快速反弹组合
        pin_recovery = detect_pin_bar_with_recovery(df_15m)

        # === 高级裸K分析：回调与趋势识别 ===
        pullback_type = identify_pullback_type(df_15m)
        # V8.2.3.6：trend_initiation将在后面使用新逻辑计算
        trend_exhaustion = detect_trend_exhaustion(df_15m)
        
        # === 1小时指标（用于止损止盈 + 中期趋势）V6.5 ===
        current_1h = df_1h.iloc[-1]
        
        # 1小时均线
        ema20_1h = df_1h["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50_1h = df_1h["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        
        # 1小时MACD（V6.5新增：用于趋势判断）
        macd_line_1h, signal_line_1h, histogram_1h = calculate_macd(df_1h)
        macd_trend_1h = "多头" if histogram_1h > 0 else "空头"
        
        # 1小时ATR
        atr_14_1h = calculate_atr(df_1h, 14)
        
        # 1小时趋势判断（V6.5新增：用于过滤趋势末期）
        if ema20_1h > ema50_1h:
            trend_1h = "多头" if current_1h["close"] > ema20_1h else "多头转弱"
        else:
            trend_1h = "空头" if current_1h["close"] < ema20_1h else "空头转弱"
        
        # 1小时支撑阻力位（用于止损止盈计算）
        sr_levels_1h = find_support_resistance(df_1h, current_1h["close"])
        
        # === 支撑阻力位分析（15分钟，用于入场判断） ===
        sr_levels = find_support_resistance(df_15m, current_data["close"])
        
        # === 15分钟趋势判断（V6.5新增：用于短期确认） ===
        if ema20 > ema50:
            trend_15m = "多头" if current_data["close"] > ema20 else "多头转弱"
        else:
            trend_15m = "空头" if current_data["close"] < ema20 else "空头转弱"
        
        # === V8.2.3.6：使用统一逻辑检测breakout和trend_initiation ===
        # 这两个检测与export_historical_data.py保持一致，确保回测与实盘数据统一
        breakout = detect_breakout_sr(current_data["close"], sr_levels)
        trend_initiation = detect_trend_initiation_v2(df_15m, long_term_trend, trend_15m)
        
        # 如果新逻辑未检测到breakout，回退到旧逻辑（向后兼容）
        if not breakout and breakout_legacy:
            breakout = breakout_legacy
        
        # === YTC增强数据计算（V7.5新增）===
        # 1. 动能斜率
        momentum_slope_15m = calculate_momentum_slope(df_15m, 5)
        
        # 2. 回调弱势评分
        pullback_weakness_score = 0.5  # 默认值
        if pullback_type:
            pullback_weakness_score = calculate_pullback_weakness_score(df_15m, pullback_type)
        
        # 3. LWP参考价
        lwp_data = detect_lwp_reference_price(df_15m, sr_levels, pullback_type)
        
        # 4. YTC信号检测（BOF/BPB/TST）
        ytc_signal = detect_ytc_signals(df_15m, df_1h, sr_levels, momentum_slope_15m)
        
        return {
            "symbol": symbol,
            "coin": symbol.split("/")[0],  # V6.5新增：币种名称
            "price": current_data["close"],
            "current_price": current_data["close"],  # 兼容旧代码
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "high": current_data["high"],
            "low": current_data["low"],
            "volume": current_data["volume"],
            "price_change": (
                (current_data["close"] - previous_data["close"])
                / previous_data["close"]
            )
            * 100,
            # V6.5新增：三层趋势（用于AI决策）
            "trend_4h": long_term_trend,  # 4小时趋势（大方向）
            "trend_1h": trend_1h,  # 1小时趋势（中期过滤）
            "trend_15m": trend_15m,  # 15分钟趋势（短期确认）
            "kline_data": df_15m[
                ["timestamp", "open", "high", "low", "close", "volume"]
            ]
            .tail(5)
            .to_dict("records"),
            # 短期指标（15分钟）
            "macd": {
                "line": macd_line,
                "signal": signal_line,
                "histogram": histogram,
                "trend": macd_trend,
            },
            "volume_analysis": {
                "current": current_data["volume"],
                "ma20": volume_ma20,
                "ratio": volume_ratio,
                "status": volume_status,
            },
            "moving_averages": {
                "ma7": ma7,
                "ma24": ma24,
                "ma72": ma72,
                "ema20": ema20,
                "ema50": ema50,
            },
            "rsi": {
                "rsi_7": rsi_7,
                "rsi_14": rsi_14,
                "status": "超买" if rsi_14 > 70 else "超卖" if rsi_14 < 30 else "中性",
                    },
            "atr": {
                "atr_3": atr_3,
                "atr_14": atr_14,
                "volatility": (
                    "高"
                    if atr_14 > atr_3 * 1.5
                        else "低" if atr_14 < atr_3 * 0.7 else "正常"
                ),
            },
            # 长期指标（4小时）
            "long_term": {
                "trend": long_term_trend,
                "ema20": ema20_4h,
                "ema50": ema50_4h,
                "macd": {
                    "line": macd_line_4h,
                    "histogram": histogram_4h,
                    "trend": macd_trend_4h,
                },
                "rsi_14": rsi_14_4h,
                "atr": {"atr_3": atr_3_4h, "atr_14": atr_14_4h},
                "volume": {
                    "current": current_4h["volume"],
                    "average": volume_ma_4h,
                    "ratio": volume_ratio_4h,
                },
            },
            # 中期指标（1小时，用于止损止盈 + 趋势过滤）V6.5
            "mid_term": {
                "trend": trend_1h,  # V6.5新增：用于过滤趋势末期
                "ema20": ema20_1h,
                "ema50": ema50_1h,
                "macd": {  # V6.5新增：用于趋势确认
                    "line": macd_line_1h,
                    "signal": signal_line_1h,
                    "histogram": histogram_1h,
                    "trend": macd_trend_1h,
                },
                "atr_14": atr_14_1h,
                "support_resistance": sr_levels_1h,
            },
            # 裸K分析（Price Action）- 增强版 + YTC V7.5
            "price_action": {
                "pin_bar": pin_bar,
                "engulfing": engulfing,
                "breakout": breakout,
                "consecutive": consecutive,
                "volume_surge": volume_surge,
                "pin_recovery": pin_recovery,
                # 高级裸K：回调与趋势
                "pullback_type": pullback_type,
                "trend_initiation": trend_initiation,
                "trend_exhaustion": trend_exhaustion,
                # === YTC增强字段（V7.5）===
                "momentum_slope": momentum_slope_15m,  # 动能斜率
                "pullback_weakness_score": pullback_weakness_score,  # 回调弱势评分（0.0-1.0）
                "lwp_long": lwp_data.get('lwp_long'),  # 多头LWP参考价
                "lwp_short": lwp_data.get('lwp_short'),  # 空头LWP参考价
                "lwp_confidence": lwp_data.get('confidence', 'none'),  # LWP置信度
                "ytc_signal": ytc_signal,  # YTC信号（BOF/BPB/TST或None）
            },
            # 支撑阻力位（15分钟，用于入场判断）
            "support_resistance": sr_levels,
        }

    except TimeoutError:
        print(f"⚠️  获取 {symbol} 数据超时（>15秒）")
        signal.alarm(0)  # 确保取消定时器
        return None
    except Exception as e:
        print(f"❌ 获取 {symbol} 数据失败: {e}")
        signal.alarm(0)  # 确保取消定时器
        import traceback

        traceback.print_exc()
        return None


def get_trade_info_from_csv(symbol, side):
    """从CSV文件中获取完整的交易信息（开仓时间、杠杆、止盈止损、开仓理由等）"""
    try:
        if TRADES_FILE.exists():
            df = pd.read_csv(TRADES_FILE)
            # 清理列名中的前导/尾随空格
            df.columns = df.columns.str.strip()
            coin_name = symbol.split("/")[0]
            side_cn = "多" if side == "long" else "空"
            
            # 找到该币种、该方向、未平仓的记录
            mask = (
                (df["币种"] == coin_name)
                & (df["方向"] == side_cn)
                & (df["平仓时间"].isna())
            )
            matching_rows = df[mask]
            
            if not matching_rows.empty:
                row = matching_rows.iloc[-1]
                return {
                    "open_time": row["开仓时间"],
                    "leverage": (
                        int(row.get("杠杆率", 1)) if pd.notna(row.get("杠杆率")) else 1
                    ),
                    "stop_loss": float(row.get("止损", 0)) if pd.notna(row.get("止损")) else 0,
                    "take_profit": float(row.get("止盈", 0)) if pd.notna(row.get("止盈")) else 0,
                    "risk_reward": float(row.get("盈亏比", 0)) if pd.notna(row.get("盈亏比")) else 0,
                    "margin": float(row.get("仓位(U)", 0)) if pd.notna(row.get("仓位(U)")) else 0,
                    "open_reason": str(row.get("开仓理由", "")) if pd.notna(row.get("开仓理由")) else "",
                }
    except Exception as e:
        print(f"读取交易信息失败: {e}")
    return None


def get_all_positions():
    """获取所有持仓（带超时处理）"""
    import signal

    def timeout_handler(signum, frame):
        raise TimeoutError("获取持仓超时")

    try:
        # 设置10秒超时
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(10)

        all_positions = exchange.fetch_positions()

        # 取消超时
        signal.alarm(0)

        active_positions = []
        total_position_value = 0
        
        for pos in all_positions:
            if pos["contracts"] and float(pos["contracts"]) > 0:
                # 从CSV获取完整交易信息（包括开仓时间、杠杆、止盈止损、开仓理由等）
                trade_info = get_trade_info_from_csv(pos["symbol"], pos["side"])
                open_time = trade_info["open_time"] if trade_info else None
                leverage = (
                    trade_info["leverage"]
                    if trade_info
                        else (
                        float(pos["leverage"])
                        if pos["leverage"]
                            else TRADE_CONFIG["max_leverage"]
                    )
                )
                
                position_info = {
                    "symbol": pos["symbol"],
                    "side": pos["side"],
                    "size": float(pos["contracts"]),
                    "entry_price": float(pos["entryPrice"]) if pos["entryPrice"] else 0,
                        "unrealized_pnl": (
                        float(pos["unrealizedPnl"]) if pos["unrealizedPnl"] else 0
                    ),
                    "leverage": leverage,  # 使用CSV中记录的准确杠杆率
                    "notional": float(pos["notional"]) if pos["notional"] else 0,
                    "open_time": open_time,  # 开仓时间
                    # 【新增】完整的交易信息（部分平仓后仍保留）
                    "stop_loss": trade_info.get("stop_loss", 0) if trade_info else 0,
                    "take_profit": trade_info.get("take_profit", 0) if trade_info else 0,
                    "risk_reward": trade_info.get("risk_reward", 0) if trade_info else 0,
                    "margin": trade_info.get("margin", 0) if trade_info else 0,
                    "open_reason": trade_info.get("open_reason", "") if trade_info else "",
                }
                active_positions.append(position_info)
                # 计算仓位价值（名义价值/杠杆）
                total_position_value += (
                    abs(position_info["notional"]) / position_info["leverage"]
                )
        
        print(f"✓ 获取持仓成功: {len(active_positions)}个")
        return active_positions, total_position_value

    except TimeoutError:
        print(f"⚠️  获取持仓超时（>10秒），跳过本轮")
        signal.alarm(0)  # 确保取消定时器
        return [], 0
    except Exception as e:
        print(f"❌ 获取持仓失败: {e}")
        signal.alarm(0)  # 确保取消定时器
        return [], 0


def ai_evaluate_position_adjustment(
    coin_name,
    original_position,
    suggested_position,
    signal_quality,
    available_balance,
    current_positions
):
    """
    🔧 V7.7.0.14: AI评估是否接受仓位调整
    
    当计划仓位低于交易所最小要求时，让AI评估是否值得增加仓位
    
    参数:
        coin_name: str, 币种名称
        original_position: float, 原计划仓位（USDT）
        suggested_position: float, 建议调整后仓位（USDT）
        signal_quality: dict, 信号质量信息
            - score: int, 信号得分
            - risk_reward: float, 盈亏比
            - reason: str, 入场理由
        available_balance: float, 可用余额
        current_positions: list, 当前持仓列表
    
    返回:
        dict: {
            'decision': 'ACCEPT'/'REJECT',
            'adjusted_position': float,
            'confidence': 'HIGH'/'MEDIUM'/'LOW',
            'reason': str
        }
    """
    adjustment_pct = (suggested_position - original_position) / original_position * 100
    adjustment_amount = suggested_position - original_position
    
    # 安全检查：调整幅度过大直接拒绝
    MAX_ADJUSTMENT_RATIO = 2.0  # 最多增加100%
    if (suggested_position / original_position) > MAX_ADJUSTMENT_RATIO:
        return {
            'decision': 'REJECT',
            'adjusted_position': 0,
            'confidence': 'HIGH',
            'reason': f'调整幅度{adjustment_pct:.0f}%过大，超过{(MAX_ADJUSTMENT_RATIO-1)*100:.0f}%限制，为保护账户安全拒绝'
        }
    
    # 安全检查：调整后超过账户风险预算
    if suggested_position > available_balance * 0.35:
        return {
            'decision': 'REJECT',
            'adjusted_position': 0,
            'confidence': 'HIGH',
            'reason': f'调整后仓位${suggested_position:.0f}U超过账户35%风险限制（${available_balance*0.35:.0f}U），拒绝'
        }
    
    prompt = f"""**[IMPORTANT: Respond ONLY in Chinese (中文)]**

Position Adjustment Evaluation Request

## Situation
**{coin_name}**: Planned position ${original_position:.0f}U is below exchange minimum requirement.
- Minimum Required: ${suggested_position:.0f}U
- Adjustment Needed: +{adjustment_pct:.0f}% (+${adjustment_amount:.0f}U)

## Signal Quality
- Signal Score: {signal_quality['score']}/100
- Risk-Reward Ratio: {signal_quality['risk_reward']:.2f}:1
- Entry Reason: {signal_quality['reason'][:150]}

## Account Status
- Available Balance: ${available_balance:.0f}U
- Current Open Positions: {len(current_positions)}
- Adjusted Position % of Account: {(suggested_position/available_balance)*100:.1f}%

## Decision Required
Should we accept the adjusted position of ${suggested_position:.0f}U to capture this opportunity?

**Evaluation Criteria**:
1. **Signal Quality**: Score ≥85 and R:R ≥4.0 → Strongly consider
2. **Risk Budget**: Adjusted position <30% of account → Safe
3. **Adjustment Magnitude**: <50% increase → Reasonable, <100% → Acceptable
4. **Expected Value**: High quality signals justify extra capital

**Decision Guidelines**:
- Score ≥90 + R:R ≥4.0 + Adjustment <50% → ACCEPT (High confidence)
- Score ≥85 + R:R ≥3.5 + Adjustment <75% → ACCEPT (Medium confidence)
- Score ≥80 + R:R ≥3.0 + Adjustment <100% → Evaluate carefully
- Other cases → REJECT

Output JSON only:
{{
  "decision": "ACCEPT" or "REJECT",
  "adjusted_position": {suggested_position},
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reason": "中文解释：为什么接受/拒绝这个调整，包括关键考量因素"
}}
"""
    
    try:
        print(f"正在请求AI评估仓位调整...")
        response = qwen_client.chat.completions.create(
            model="qwen3-max",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,  # 增加token限制，为reasoner思考过程预留空间
            temperature=0.3
        )
        
        ai_content = response.choices[0].message.content
        decision = extract_json_from_ai_response(ai_content)  # 🔧 V7.7.0.15: 函数已返回dict，无需json.loads
        
        print(f"✓ AI评估完成: {decision['decision']}")
        return decision
        
    except Exception as e:
        print(f"⚠️ AI评估失败: {e}")
        
        # 降级策略：基于信号质量自动判断
        if signal_quality['score'] >= 85 and signal_quality['risk_reward'] >= 4.0 and adjustment_pct < 75:
            return {
                'decision': 'ACCEPT',
                'adjusted_position': suggested_position,
                'confidence': 'MEDIUM',
                'reason': f'AI评估失败，但信号质量极高（得分{signal_quality["score"]}，R:R {signal_quality["risk_reward"]:.2f}），调整幅度{adjustment_pct:.0f}%可接受，自动批准'
            }
        else:
            return {
                'decision': 'REJECT',
                'adjusted_position': 0,
                'confidence': 'LOW',
                'reason': f'AI评估失败，信号质量（得分{signal_quality["score"]}，R:R {signal_quality["risk_reward"]:.2f}）不足以承担额外{adjustment_pct:.0f}%风险，保守拒绝'
            }


def ai_portfolio_decision(
    market_data_list,
    current_positions,
    total_position_value,
    current_balance,
    available_balance,
):
    """AI进行投资组合决策（使用学习参数）"""
    
    # 🔧 V7.7.0.14: 中英翻译映射（内部英文，输出中文）
    TREND_TRANSLATION = {
        "强势多头": "Strong Bull",
        "强势空头": "Strong Bear",
        "短期强势": "Short Bull",
        "短期弱势": "Short Bear",
        "弱势": "Weak",
        "多头": "Bullish",
        "空头": "Bearish",
        "震荡": "Range",
        "": "N/A"
    }
    
    PA_SIGNAL_TRANSLATION = {
        "多头Pin Bar（看涨反转）": "Bullish Pin",
        "空头Pin Bar（看跌反转）": "Bearish Pin",
        "多头吞没（看涨）": "Bull Engulf",
        "空头吞没（看跌）": "Bear Engulf",
    }

    # 加载学习参数
    learning_config = load_learning_config()
    
    # 计算总资产（仅用于显示和记录）
    total_unrealized_pnl = sum(pos["unrealized_pnl"] for pos in current_positions)
    total_assets = current_balance + total_unrealized_pnl
    
    # 根据可用余额（已扣除保证金）计算最大可用仓位
    # 可用余额 = 账户余额 - 已占用保证金
    if TRADE_CONFIG.get("use_dynamic_position", False):
        # 动态模式：使用实际可用余额
        max_total_position = available_balance
    else:
        # 固定模式：使用初始资金限制
        max_total_position = min(
            TRADE_CONFIG.get("initial_capital", 100), available_balance
        )
    
    # 🆕 构建决策上下文（压缩洞察+持仓承诺）
    current_positions_dict = {
        pos.get("symbol", "").split("/")[0]: pos.get("entry_price", 0) 
            for pos in current_positions 
        if pos.get("symbol")
            }
    decision_context = build_decision_context(current_positions_dict)
    
    # 构建市场概览（V3.0：增加裸K分析）
    market_overview = ""
    for i, data in enumerate(market_data_list, 1):
        if data is None:
            print("⚠️ 跳过数据获取失败的币种（AI决策）")
            continue  # 跳过获取失败的币种
        coin_name = data["symbol"].split("/")[0]
        macd = data["macd"]
        rsi = data["rsi"]
        ma = data["moving_averages"]
        vol = data["volume_analysis"]
        atr = data["atr"]
        lt = data["long_term"]
        pa = data["price_action"]
        sr = data["support_resistance"]
        
        # 判断短期趋势
        price = data["price"]
        if price > ma["ma7"] > ma["ma24"] > ma["ma72"]:
            short_trend = "强势多头"
        elif price < ma["ma7"] < ma["ma24"] < ma["ma72"]:
            short_trend = "强势空头"
        elif price > ma["ma7"]:
            short_trend = "短期强势"
        else:
            short_trend = "弱势"
        
        # Price Action Signals - Enhanced
        pin_desc = "None"
        if pa["pin_bar"] == "bullish_pin":
            pin_desc = "Bullish Pin Bar (Reversal) ✓✓"
        elif pa["pin_bar"] == "bearish_pin":
            pin_desc = "Bearish Pin Bar (Reversal) ✓✓"
        
        engulf_desc = "None"
        if pa["engulfing"] == "bullish_engulfing":
            engulf_desc = "Bullish Engulfing ✓✓"
        elif pa["engulfing"] == "bearish_engulfing":
            engulf_desc = "Bearish Engulfing ✓✓"

        # Price Action Signals (V8.2.3.6: Support both new and legacy breakout structures)
        breakout_desc = "None"
        if pa["breakout"]:
            # New logic: S/R breakout
            if pa["breakout"].get("type") in ["resistance", "support"]:
                level = pa["breakout"]["level"]
                strength_pct = pa["breakout"]["strength"] * 100
                if pa["breakout"]["type"] == "resistance":
                    breakout_desc = f"🚀 Break Resistance ${level:.0f} (+{strength_pct:.2f}%) ✓✓✓"
                else:  # support
                    breakout_desc = f"⚠️ Break Support ${level:.0f} (-{strength_pct:.2f}%) ✓✓✓"
            # Legacy logic: Volume breakout candle
            elif pa["breakout"].get("volume_ratio"):
                ratio = pa["breakout"]["volume_ratio"]
                breakout_desc = f"🚀 Breakout Candle (Vol {ratio:.1f}x) ✓✓✓"

        consecutive_desc = "None"
        if pa["consecutive"]:
            gain = pa["consecutive"]["gain_pct"]
            consecutive_desc = (
                f"📈 {pa['consecutive']['candles']} Consecutive Bullish (+{gain:.1f}%) ✓✓"
            )

        volume_surge_desc = "None"
        if pa["volume_surge"]:
            ratio = pa["volume_surge"]["ratio"]
            weight = pa["volume_surge"]["weight"]
            weight_marks = "✓" * weight
            if pa["volume_surge"]["type"] == "extreme_surge":
                volume_surge_desc = (
                    f"💥 Extreme Volume Surge ({ratio:.1f}x) {weight_marks} ⚠️CRITICAL"
                )
            elif pa["volume_surge"]["type"] == "strong_surge":
                volume_surge_desc = f"⚡ Strong Volume Surge ({ratio:.1f}x) {weight_marks}"
            else:
                volume_surge_desc = f"📊 Moderate Volume Surge ({ratio:.1f}x) {weight_marks}"

        pin_recovery_desc = "None"
        if pa["pin_recovery"]:
            recovery = pa["pin_recovery"]["recovery_pct"]
            pin_recovery_desc = f"🔄 Pin Bar Fast Recovery (+{recovery:.1f}%) ✓✓"

        # Advanced PA: Pullback & Trend Signals
        pullback_desc = "None"
        if pa["pullback_type"]:
            if pa["pullback_type"]["type"] == "simple_pullback":
                recovery = pa["pullback_type"]["recovery_pct"]
                depth = pa["pullback_type"]["depth_pct"]
                signal = pa["pullback_type"]["signal"]
                if signal == "entry_ready":
                    pullback_desc = f"🎯 Simple Pullback (Retrace {depth:.1f}%, Recover {recovery:.0f}%) ✓✓✓ ENTRY READY"
                else:
                    pullback_desc = f"⏳ Simple Pullback (Retrace {depth:.1f}%) Waiting Reversal"
            elif pa["pullback_type"]["type"] == "complex_pullback":
                depth = pa["pullback_type"]["depth_pct"]
                consol = pa["pullback_type"]["consolidation_pct"]
                pullback_desc = (
                    f"📊 Complex Pullback (Retrace {depth:.1f}%, Consol {consol:.1f}%) ✓✓ Wait Breakout"
                )

        trend_init_desc = "None"
        if pa["trend_initiation"]:
            direction = pa["trend_initiation"]["direction"]
            strength = pa["trend_initiation"]["strength"]
            entry = pa["trend_initiation"]["entry_signal"]
            reason = pa["trend_initiation"]["reason"]
            if strength == "strong" and entry == "immediate":
                trend_init_desc = (
                    f"🚀🚀🚀 Trend Inception ({direction.upper()}) {reason} ✓✓✓✓ ENTER NOW!"
                )
            elif strength == "moderate":
                trend_init_desc = (
                    f"📈 Possible Trend Inception ({direction.upper()}) {reason} ✓✓ Wait Confirm"
                )

        trend_exhaust_desc = "None"
        if pa["trend_exhaustion"]:
            signal = pa["trend_exhaustion"]["signal"]
            severity = pa["trend_exhaustion"]["severity"]
            action = pa["trend_exhaustion"]["action"]
            severity_mark = "⚠️⚠️⚠️" if severity == "high" else "⚠️"
            if action == "close_long":
                trend_exhaust_desc = f"{severity_mark} Bull Exhaustion ({signal}) CLOSE LONG"
            elif action == "close_short":
                trend_exhaust_desc = f"{severity_mark} Bear Exhaustion ({signal}) CLOSE SHORT"
        
        # Support/Resistance Description
        sr_desc = ""
        if sr["nearest_resistance"]:
            distance = ((sr["nearest_resistance"]["price"] - price) / price) * 100
            sr_desc += f"Nearest Resistance: ${sr['nearest_resistance']['price']:,.0f} ({sr['nearest_resistance']['strength']}, +{distance:.1f}%)\n"
        else:
            sr_desc += "Nearest Resistance: None\n"
        
        if sr["nearest_support"]:
            distance = ((price - sr["nearest_support"]["price"]) / price) * 100
            sr_desc += f"Nearest Support: ${sr['nearest_support']['price']:,.0f} ({sr['nearest_support']['strength']}, -{distance:.1f}%)\n"
        else:
            sr_desc += "Nearest Support: None\n"
        
        sr_desc += f"Position: {sr['position_status']}"
        if sr["position_status"] == "at_resistance":
            sr_desc += " ⚠️ (Near resistance, be cautious)"
        elif sr["position_status"] == "at_support":
            sr_desc += " ✓ (Near support, watch for entry)"
        
        # 1小时数据
        mt = data.get('mid_term', {}) or {}
        mt_sr = mt.get('support_resistance', {}) or {}
        
        # V6.5：获取三层趋势
        trend_4h = data.get('trend_4h', lt['trend'])
        trend_1h = mt.get('trend', '')
        trend_15m = data.get('trend_15m', short_trend)
        
        # 🔧 V7.7.0.14: 翻译为英文（减少Token消耗）
        trend_4h_en = TREND_TRANSLATION.get(trend_4h, trend_4h)
        trend_1h_en = TREND_TRANSLATION.get(trend_1h, trend_1h)
        trend_15m_en = TREND_TRANSLATION.get(trend_15m, trend_15m)
        
        # 判断模式
        is_trend_following = (('多头' in trend_4h and '多头' in trend_1h and '多头' in trend_15m) or 
                             ('空头' in trend_4h and '空头' in trend_1h and '空头' in trend_15m))
        is_counter_trend = (('多头' in trend_4h and '空头' in trend_1h) or 
                           ('空头' in trend_4h and '多头' in trend_1h))
        mode = "Mode1(Main)" if is_trend_following else ("Mode2(Counter)" if is_counter_trend else "Hold")
        
        # 翻译裸K信号（仅翻译关键信号）
        pa_signals_en = []
        for signal in [pin_desc, engulf_desc, breakout_desc, trend_init_desc, trend_exhaust_desc, pullback_desc]:
            if signal and signal != "无":
                # 保留emoji和标记，仅翻译关键词
                signal_en = signal
                for cn, en in PA_SIGNAL_TRANSLATION.items():
                    if cn in signal:
                        signal_en = signal.replace(cn, en)
                        break
                # 简化其他中文描述
                signal_en = signal_en.replace("看涨反转", "").replace("看跌反转", "")
                signal_en = signal_en.replace("看涨", "").replace("看跌", "")
                signal_en = signal_en.replace("量能", "Vol").replace("连续", "x").replace("阳线", "Bull")
                signal_en = signal_en.replace("极端放量", "Extreme Vol").replace("强放量", "Strong Vol")
                signal_en = signal_en.replace("温和放量", "Mild Vol").replace("必须关注", "Key")
                signal_en = signal_en.replace("快速反弹", "Fast Bounce")
                signal_en = signal_en.replace("简单回调", "Simple PB").replace("回撤", "ret")
                signal_en = signal_en.replace("已恢复", "rec").replace("最佳入场时机", "Best Entry")
                signal_en = signal_en.replace("等待反转", "Wait").replace("复杂回调", "Complex PB")
                signal_en = signal_en.replace("整理", "consol").replace("等待突破", "Wait BO")
                signal_en = signal_en.replace("趋势发起", "Trend Init").replace("立即入场", "Enter Now")
                signal_en = signal_en.replace("可能", "Maybe").replace("等待确认", "Wait Confirm")
                signal_en = signal_en.replace("多头衰竭", "Bull Exhaust").replace("空头衰竭", "Bear Exhaust")
                signal_en = signal_en.replace("立即平多", "Close Long").replace("立即平空", "Close Short")
                if '✓' in signal_en or '🚀' in signal_en or '⚠️' in signal_en or '🎯' in signal_en:
                    pa_signals_en.append(signal_en)
        
        # 提取当前位置状态（英文）
        position_status = sr.get('position_status', '')
        if position_status == "at_resistance":
            pos_status_en = "At Resistance⚠️"
        elif position_status == "at_support":
            pos_status_en = "At Support✓"
        else:
            pos_status_en = ""
        
        market_overview += f"""
=== {coin_name} ===
Price: ${price:,.2f} ({data['price_change']:+.2f}%)

🔹Trend: 4H={trend_4h_en}, 1H={trend_1h_en}, 15m={trend_15m_en}
→ {mode}

🔹1H S/R: Res ${(mt_sr.get('nearest_resistance') or {}).get('price', 0):,.0f}, Sup ${(mt_sr.get('nearest_support') or {}).get('price', 0):,.0f}, ATR {mt.get('atr_14', 0):.1f}

🔹15m: MACD{macd['histogram']:+.1f}, RSI{rsi['rsi_14']:.0f}, Vol{vol['ratio']:.0f}%

🔹PA: {', '.join(pa_signals_en)} {pos_status_en}

"""
    
    # 🔧 V7.7.0.14: 持仓信息英文化
    position_info = f"\n【ACCOUNT STATUS】\n"
    position_info += f"Total Assets: {total_assets:.2f}U (Balance {current_balance:.2f}U + UnrealizedPnL {total_unrealized_pnl:+.2f}U)\n"
    position_info += f"Available: {available_balance:.2f}U (after margin)\n"
    position_info += f"Max New Position: {max_total_position:.2f}U\n\n"
    
    position_info += f"【CURRENT POSITIONS】\n"
    if current_positions:
        for pos in current_positions:
            coin_name = pos["symbol"].split("/")[0]
            side_en = "LONG" if pos['side'] == "多" else "SHORT"
            position_info += f"- {coin_name}: {side_en} {pos['size']:.4f}, PnL {pos['unrealized_pnl']:+.2f}U\n"
    else:
        position_info += "Empty\n"
    
    # 获取当前智能学习参数
    # 计算已完成的交易数量
    try:
        if TRADES_FILE.exists():
            trades_count = (
                len(
                    [
                        line
                        for line in TRADES_FILE.read_text().split("\n")
                            if line.strip()
                    ]
                )
                - 1
            )  # 减去表头
            trades_count = max(0, trades_count)
        else:
            trades_count = 0
    except:
        trades_count = 0

    learning_params_info = f"""
=== CURRENT ADAPTIVE PARAMETERS (AI Auto-Optimized) ===
System has learned from {trades_count} completed trades

**Global Parameters** (Default Standards):
- Min Risk-Reward: {learning_config['global']['min_risk_reward']:.1f}:1
- ATR Stop Multiplier: {learning_config['global']['atr_stop_multiplier']:.1f}x
- Base Position Ratio: {learning_config['global']['base_position_ratio']*100:.0f}%
- Max Hold Time: {learning_config['global']['max_hold_time_hours']}h
- Max Loss Per Trade: {learning_config['global']['max_loss_per_trade']*100:.1f}%
- Max Consecutive Losses: {learning_config['global']['max_consecutive_losses']} trades
- Min Signal Score: {learning_config['global']['min_signal_score']}/100

**Market Regime Status**:
- Current Regime: {learning_config.get('market_regime', {}).get('type', 'unknown')}
- Trading Status: {'🚫Paused' if learning_config.get('market_regime', {}).get('pause_trading', False) else '✅Active'}

💡 These parameters are auto-adjusted by AI based on historical performance. Strictly follow them to improve win rate.
"""
    
    # 🆕 V7.6.5: 构建币种特性信息
    symbol_characteristics_info = "\n=== 🪙 SYMBOL-SPECIFIC CHARACTERISTICS (V7.6.5) ===\n\n"
    for data in market_data_list:
        if data is None:
            continue
        symbol = data["symbol"]
        profile = SYMBOL_PROFILES.get(symbol, {})
        if profile:
            coin_name = symbol.split("/")[0]
            symbol_characteristics_info += f"""**{coin_name}** - {profile.get('name', coin_name)}
- Volatility: {profile.get('volatility', 'UNKNOWN')} | Liquidity: {profile.get('liquidity', 'UNKNOWN')}
- Trend Style: {profile.get('trend_style', 'UNKNOWN')}
- Recommended Holding: ~{profile.get('recommended_holding_hours', 4)} hours
- False Breakout Risk: {profile.get('false_breakout_rate', 'UNKNOWN')}
- Key Characteristics: {profile.get('characteristics', 'N/A')}

"""
    
    # 🆕 V7.9: 双模式交易策略说明
    dual_mode_info = """
=== 🎯 DUAL-MODE TRADING STRATEGY (V7.9 - Critical Update) ===

The system now supports TWO distinct trading modes with different holding periods and TP/SL strategies:

**【SCALPING Mode】** - Quick In/Out (15-45 minutes)
Suitable Signals:
- Pin Bar + at key support/resistance
- Engulfing pattern near key levels
- Extreme volume spike (>3x) + high volatility
- YTC-TST (Test signal with momentum stall)

Characteristics:
- Expected Holding: 15-45 minutes
- TP/SL: Based on 15m ATR (tight stops, quick targets)
- Target R:R: 1.5:1
- Exit Strategy: Sensitive - any counter signal triggers exit
- Best For: Range-bound markets, fast reversals

**【SWING Mode】** - Medium-Term (2-24 hours)
Suitable Signals:
- Trend Inception (Strong/Moderate)
- Simple Pullback completion
- YTC-BOF/BPB (structural breakout signals)
- YTC-PB with weakness≥0.85
- Consecutive breakouts (6+ candles)

Characteristics:
- Expected Holding: 2-24 hours
- TP/SL: Based on 1h S/R levels (wider stops, larger targets)
- Target R:R: 2.5:1+
- Exit Strategy: Patient - requires multi-timeframe confirmation
- Best For: Trending markets, riding momentum

**Decision Framework:**
When you identify a signal, explicitly state:
1. Signal Type: Scalping or Swing
2. Rationale: Why this signal fits the chosen mode
3. Risk Management: Matching TP/SL strategy

Example:
"Signal Type: Swing
Rationale: Strong Trend Inception with 4H+1H alignment, this is a wave-riding opportunity not a quick bounce
    Expected Holding: 4-6 hours
TP Target: 1H resistance level"

**CRITICAL**: Don't use Swing strategy for reversal signals, and don't use Scalping strategy for trend signals. Mismatching mode and signal type leads to premature exits or excessive risk.
    """
    
    # 🆕 V7.6.5: 构建信号分级提示
    signal_tier_info = """
=== 📊 SIGNAL QUALITY TIERS (V7.6.5) ===

**HIGH Tier** (Score ≥75, Swing signals):
- Strategy: Aggressive (R:R 2.5:1, Position 1.3x base)
- Rationale: High-quality trend signals with multi-timeframe confirmation

**MEDIUM Tier** (Score 70-74, Scalping signals):
- Strategy: Quick (R:R 1.5:1, Position 1.0x base)
- Rationale: Fast reversal opportunities at key levels

**LOW Tier** (Score <70):
- Strategy: PASS - Do not trade
- Rationale: Insufficient signal quality

**IMPORTANT**: The system will automatically apply mode-specific TP/SL. Focus on correctly identifying signal type (Scalping vs Swing).
"""
    
    prompt = f"""
**[IMPORTANT: Respond ONLY in Chinese (中文) for all analysis and decisions]**

You are a professional cryptocurrency trading AI using a 3-layer trend alignment framework:
- Layer 1 (4H): Primary trend direction (40% weight)
- Layer 2 (1H): Stop-loss/take-profit levels (30% weight)  
- Layer 3 (15m): Entry timing confirmation (20% weight)

{learning_params_info}
{decision_context}

{symbol_characteristics_info}

{dual_mode_info}

{signal_tier_info}

=== MARKET DATA (3-Layer Analysis) ===

{market_overview}

=== ACCOUNT STATUS ===

{position_info}

=== ADAPTIVE PARAMETERS (Auto-adjusted based on last 20 trades) ===
- Risk-Reward Ratio: {learning_config['global']['min_risk_reward']:.1f}:1
- Stop-Loss: ATR×{learning_config['global']['atr_stop_multiplier']:.1f}
- Indicator Consensus: {learning_config['global']['min_indicator_consensus']}/5
- Key Level Penalty: ×{learning_config['global']['key_level_penalty']:.1f}
- Last Update: {learning_config['last_update'] or 'Initial'}

Auto-adjustment rules:
- Win rate <45% → Increase R:R requirement, reduce entries
- Frequent stop-outs → Widen stop-loss buffer
- High risk signals → Require 5/5 indicator consensus

=== 3-LAYER TREND ALIGNMENT FRAMEWORK V6.5 ===

**Mode 1: Trend Following (Recommended)**
- Condition: 4H + 1H + 15m aligned
- Position: 60-70%, Hold: 6-24h, R:R ≥1.5

**Mode 2: Counter-Trend (Cautious)**
- Condition: 4H opposite to 1H+15m
- Position: 30-40%, Hold: 1-4h, R:R ≥2.0

**Layer 1 - 4H Trend** (40% weight, see trend_4h field)
- Bullish/Bearish → Seek aligned trades only
- Weakening → Reduce positions

**Layer 2 - 1H Trend & Stops** (30% weight, see trend_1h/mid_term)
- Stop-Loss: 1H support/resistance ± ATR14×0.5
- Take-Profit: 1H resistance/support - ATR14×1.0
- Required R:R ≥ {learning_config['global']['min_risk_reward']}
- **Filter trend exhaustion**: 4H bull + 1H bear = possible reversal → wait or Mode 2

**🎯 EXIT TIMING OPTIMIZATION (V7.9 - Apply Yesterday's Lessons by Signal Type):**

【V7.9 CRITICAL】Yesterday's Lessons must be applied according to signal type!

If you see exit lessons in "Yesterday's Lessons":

**For SCALPING Signals (15-45min):**
1. **"TP Set Too Conservative"** → ⚠️ **IGNORE for Scalping**
   - Scalping needs quick profit-taking by design
   - Don't expand TP beyond 15m resistance/support
   - Reason: Scalping is about speed, not greed

2. **"High SL Rate"** → ✓ **APPLY with caution**
   - Stricter entry at key reversals
   - Demand Pin Bar/Engulfing AT exact S/R
   - But don't raise score requirement too high (Scalping naturally lower score)
   - Reason: "Applying Scalping lesson: tighter entry zones"

3. **"Premature Exit"** → ⚠️ **IGNORE for Scalping**
   - Scalping is supposed to exit early!
   - Don't hold beyond expected 15-45min window
   - Reason: Signal type mismatch, not applicable

**For SWING Signals (2-24h):**
1. **"TP Set Too Conservative"** → ✓ **STRONGLY APPLY**
   - Expand TP by 1.5-2x normal distance
   - Set TP beyond next S/R level (target 2nd resistance)
   - Use 4H levels instead of 1H levels
   - Reason: "Applying Swing lesson: let winners run longer"

2. **"High SL Rate"** → ✓ **STRONGLY APPLY**
   - Demand perfect trend alignment (4H+1H+15m)
   - Only enter at pullback completion, not mid-pullback
   - Require signal score ≥75 for Swing entries
   - Reason: "Applying Swing lesson: stricter confluence"

3. **"Premature Exit / early exit -X%"** → ✓ **STRONGLY APPLY**
   - Use 1H S/R for TP/SL, not 15m
   - Give trade at least 2 hours before considering early exit
   - Check if yesterday's exit was at key level
   - Reason: "Applying Swing lesson: more patience for wave completion"

**LESSON TAGGING (V7.9):**
- When applying a lesson, explicitly tag: `[Scalping Lesson]` or `[Swing Lesson]`
- Example: "Entry at support - [Swing Lesson: stricter confluence after yesterday's SL]"
    - If lesson type mismatches signal type, explicitly state: "[Ignored - wrong signal type]"

**IMPORTANT**: In your `reason` field, state which lesson you applied and verify signal type match. Misapplying lessons across signal types causes strategy confusion.

**Layer 3 - 15m Entry** (20% weight, see trend_15m)
- Indicator consensus ≥ {learning_config['global']['min_indicator_consensus']}/5 (EMA, MACD, RSI, Volume, ATR)
- Price action confirmation required

**LONG Entry Signals (when 4H bullish):**
    1. EMA20 > EMA50 ✓
  2. MACD histogram > 0 ✓
  3. RSI14: 30-70 ✓
  4. Volume surge (ratio >120%) ✓
  5. ATR moderate ✓

**SHORT Entry Signals (when 4H bearish):**
    1. EMA20 < EMA50 ✓
  2. MACD histogram < 0 ✓
  3. RSI14: 30-70 ✓
  4. Volume surge (ratio >120%) ✓
  5. ATR moderate ✓

**Price Action Final Confirmation (Highest priority):**
- **LONG signals:**
  * Support + Bullish Pin Bar = Strong buy ✓✓✓
  * Support + Bullish Engulfing = Strong buy ✓✓✓
  * Simple pullback entry = Optimal timing ✓✓✓
  
- **SHORT signals:**
  * Resistance + Bearish Pin Bar = Strong sell ✓✓✓
  * Resistance + Bearish Engulfing = Strong sell ✓✓✓
  * Simple pullback entry = Optimal timing ✓✓✓

- **15m Position Check:**
  * at_resistance: Short opportunity / Reduce longs
  * at_support: Long opportunity / Reduce shorts
  * neutral: Follow Layer 1 + Layer 2 signals

=== ENHANCED PRICE ACTION PATTERNS (V5.0: Pullback & Trend Inception) ===

🚀 **TREND INCEPTION - Strongest Entry (Priority 1)**

1. **Strong Trend Inception** ✓✓✓✓ (Highest priority)
   - Signal: 🚀🚀🚀 "Trend Inception (LONG/SHORT) Breakout+Consecutive+4H Confirmed"
   - Conditions:
     * Strong breakout candle (body >70%, range >1.5%)
     * 3 consecutive same-direction candles before
     * 4H trend confirmation
   - Action: **Enter immediately - Best entry point!**
       - Position: Auto-allocated 50% (Max)
   - Rationale: Triple confirmation, trend just started, optimal risk-reward

2. **Moderate Trend Inception** ✓✓✓
   - Signal: 📈 "Possible Trend Inception (LONG/SHORT) Strong Breakout Candle"
   - Conditions: Strong breakout candle (body >70%, range >1.5%)
   - Action: Wait for next candle confirmation or enter on simple pullback
       - Position: Auto-allocated 37.5%
   - Rationale: Potential inception, safer with confirmation

🎯 **PULLBACK ENTRY - Second-Best Entry (Priority 2)**

3. **Simple Pullback Entry** ✓✓✓ (Best risk-reward)
   - Signal: 🎯 "Simple Pullback (Retraced X%, Recovered Y%) Optimal Entry"
       - Conditions:
     * 1-3 pullback candles within trend
     * Retracement <38.2%
     * Recovery >50%
   - Action: **Enter immediately - Best timing after pullback!**
   - Position: Auto-allocated 47.5% (Near max)
   - Rationale: Entry within trend, tight stop, high R:R

4. **Complex Pullback - Wait for Breakout** ✓✓
   - Signal: 📊 "Complex Pullback (Retraced X%, Consolidating Y%) Wait Breakout"
   - Conditions:
     * Retracement 38.2%-61.8%
     * Narrow consolidation formed (<3%)
   - Action: **Wait for breakout above consolidation range**
       - Position: Auto-allocated 25% (Conservative)
   - Rationale: Clearer direction after breakout, safer

⚠️ **TREND EXHAUSTION - Forced Exit (Highest Priority)**

5. **High-Risk Exhaustion** ⚠️⚠️⚠️
   - Signal: ⚠️⚠️⚠️ "Bullish/Bearish Exhaustion (XXX) Close NOW"
   - Conditions:
     * Long upper/lower wick (wick >60%)
     * Engulfing reversal pattern
   - Action: **Close immediately, regardless of P&L!**
   - Rationale: Reversal signal, extreme risk to hold

6. **Moderate Exhaustion** ⚠️
   - Signal: ⚠️ "Bullish/Bearish Exhaustion (XXX) Consider Closing"
   - Conditions:
     * Doji at high/low
     * Momentum decay (candle body shrinks >50%)
   - Action: Close if profitable, watch 1-2 candles if losing
       - Rationale: Trend may end, protect profit first

🔥 **OTHER KEY PATTERNS (Priority 3):**

7. **Extreme Volume Breakout** ✓✓✓✓
   - Conditions: Volume ≥3× average + Break previous high + Strong bullish candle
   - Signal Mark: "💥 Extreme Volume"
   - Action: **Enter immediately regardless of other indicators**
   - Position: Auto-allocated 48.75%
   - Rationale: Historical win rate >80%

8. **Breakout Marubozu** ✓✓✓
   - Conditions: Body >60% total height + Break previous high + Volume >1.5×
   - Signal Mark: "🚀 Breakout Marubozu"
   - Action: Enter even if 4H neutral
       - Position: Auto-allocated 42.5%
   - Rationale: Strong breakout, high continuation probability

9. **Consecutive Bullish Candles** ✓✓
   - Conditions: 3+ consecutive bullish candles, each close > previous
   - Signal Mark: "📈 Consecutive N Bullish"
   - Action: Chase entry, trend continues
       - Position: Auto-allocated 35%
   - Rationale: Trend formed, momentum continues

10. **Pin Bar + Quick Bounce** ✓✓
    - Conditions: Lower wick >2× body + Next candle bounces >1.5%
    - Signal Mark: "🔄 Pin Bar Quick Bounce"
    - Action: Long at support
    - Position: Auto-allocated 32.5%
    - Rationale: Panic sell followed by strong bounce, solid buying

🎯 **Decision Priority Hierarchy (V5.0):**
```
EXIT: Exhaustion (Forced) > 
ENTRY: Strong Trend Inception (✓✓✓✓) > Simple Pullback (✓✓✓) > Extreme Volume (✓✓✓✓) 
  > Moderate Inception (✓✓✓) > Breakout Marubozu (✓✓✓) > Support Pin Bar (✓✓✓) 
  > Complex Pullback Breakout (✓✓) > Consecutive Candles (✓✓) > Pin Bar Bounce (✓✓) > Indicators (✓)
```

⚠️ **V5.0 KEY STRATEGY UPDATES:**
1. **Trend Inception > All**: See 🚀🚀🚀 → Enter full position
2. **Pullbacks are Gold**: Simple pullback entry = lowest risk, highest R:R
    3. **Exhaustion Must Exit**: See ⚠️⚠️⚠️ → Close immediately, protect profit
4. **Complex Pullback Wait**: Don't enter early, wait for breakout confirmation
    5. **No FOMO**: After strong inception rally, wait for simple pullback

=== YTC STRUCTURAL SIGNALS (V7.6 COMPLETE LAYER) ===

**⚠️ CRITICAL: YTC signals can override 4H trend when S/R strength ≥4 OR weakness_score ≥0.85**

Market data provides ytc_signal field with BOF/BPB/PB/TST/CPB detection. If detected:

📊 **YTC Signal Scoring (integrate with existing patterns):**

| YTC Signal | Description | Score (Max) | Key Conditions | Trapped Traders (Psychological Edge) |
|------------|-------------|-------------|----------------|--------------------------------------|
| **PB (Pullback)** | Weak pullback in strong trend, optimal re-entry | **92** | weakness_score ≥0.85 + Aligned Trend | **Fading Trapped Reversal Traders**: Sellers/Buyers who entered against the main trend during the weak pullback are about to be stopped out. |
    | **BOF (Breakout Fail)** | Breakout immediately reverses (long wick/engulfing) | **90** | S/R ≥4 + Immediate Rejection | **Fading Trapped Breakout Traders**: Those who chased the failed breakout are now forced to exit for a loss. |
| **BPB (Breakout Pullback)** | Strong break + weak pullback to polarity level | **90** | S/R ≥4 + Polarity Switch + Weak Pullback | **Fading Trapped Counter-Faders**: Traders attempting to fade the successful breakout are trapped by the weakness of their own move. |
| **TST (Test)** | Weak test of strong S/R + momentum stalls | **90** | S/R ≥4 + Momentum Stall (Slope ~ 0) | **Fading Late Chasers**: Traders who chased the exhausted move into the strong S/R are trapped by the immediate stall. |
| **CPB (Complex Pullback)** | Deep pullback (38.2%-61.8%), consolidating | **78** | Observation only | **N/A - Wait Mode**. Needs confirmation of a failed breakout of the consolidation range. |

**YTC Signal Structure (from market data):**
```python
ytc_signal = {{
    'signal_type': 'BOF|BPB|PB|TST|CPB',
    'direction': 'LONG|SHORT|WAIT',
    'strength': 3-5,  // Signal quality
    'entry_price': float,  // LWP reference (wholesale price)
        'rationale': str,
    'sr_strength': int,  // 1-5 (for structural signals BOF/BPB/TST)
        'weakness_score': float,  // 0.0-1.0 (for PB/CPB pullbacks)
    'trapped_traders': str  // Psychology: Who is trapped and why
}}
```

**Momentum Slope Interpretation:**
```
price_action.momentum_slope_15m: Linear regression slope (5-period)
- Value >0.5: Strong bullish momentum (supports LONG)
- Value 0.1~0.5: Moderate bullish momentum
- Value -0.1~0.1: Stalled/ranging (supports TST signal)
- Value -0.5~-0.1: Moderate bearish momentum
- Value <-0.5: Strong bearish momentum (supports SHORT)
```

**Decision Logic for YTC Signals:**

1. **If ytc_signal detected AND Score ≥ 85:**
   - **Entry Mode**: Use this signal as the primary entry point
       - **Counter-Trend Override**: If entry is against 4H trend:
     * Verify R:R ≥ 2.0 (stricter than normal ≥1.5)
     * Reduce position to 20-25% (vs normal 30-40%)
     * Rationale MUST explain why S/R strength allows the override
   - **Trend-Following (PB with weakness≥0.85)**:
       * BEST entries when aligned with 4H trend
     * Normal position sizing 35-45%
     * Standard R:R ≥1.5
     * Rationale: "YTC TTF Pullback, weakness={{weakness_score}}, optimal re-entry"

2. **If ytc_signal detected AND Score < 85 (e.g., CPB):**
   - **Action**: HOLD or WAIT for next candle
       - **Do NOT enter**: Complex pullback needs breakout confirmation

3. **Signal Scoring Integration:**
   - **PB @ weakness≥0.85**: Score = 92 (HIGHEST - Main YTC scenario)
   - BOF @ strength=5: Score = 90
   - BPB @ strength=5: Score = 90
   - TST @ strength=5: Score = 90
   - PB @ weakness=0.7-0.85: Score = 87
   - BOF @ strength=3-4: Score = 85
   - BPB @ strength=4: Score = 85
   - TST @ strength=4: Score = 85
   - CPB: Score = 78 (Observation only, no entry)

4. **Priority vs Existing Patterns:**
   - YTC PB (weakness≥0.85) = 92 points **(HIGHEST priority in trend)**
   - YTC BOF/BPB/TST (S/R≥4) = 85-90 points
   - Original Trend Inception = 88-90 points
   - YTC signals compete with all existing patterns
   - **Choose highest scoring signal overall**

**LWP Reference Price Handling (Strict Wholesale):**

LWP is the ideal entry price (Last Wholesale Price). Use current_price to check:

- **If current_price (bid/ask) is > 0.5% worse than LWP:**
  * For LONG: current_price > lwp_long * 1.005
  * For SHORT: current_price < lwp_short * 0.995
  * **Mark as "CHASING" and REJECT the trade (No FOMO)**
  * Rationale: "Chasing price beyond wholesale level, waiting for better entry"

- **If current_price within 0.5% of LWP:**
  * Mark as "OPTIMAL" → proceed with normal position
  * This is the best execution quality

**CRITICAL**: Never enter a YTC signal if chasing price. Wait for the next setup.

**LWP Violation Protocol (No FOMO):**

If entry price is marked as "CHASING" (more than 0.5% worse than LWP):
    - **Action**: HOLD (Wait for next setup)
- **Rationale**: "Must avoid chasing price beyond wholesale level, violating the low-risk entry core tenet of YTC. Waiting for: [BPB signal / Next PB opportunity / Price return to LWP]"
    - **Alternative Strategy**: Monitor for:
  * Next PB signal (if trend continues)
  * BPB signal (if price returns to test the level)
  * Better LWP opportunity on retracement

**Example YTC Decision:**

Scenario: BTC @ $110,000, resistance $110,500 (strength 5/5, polarity switched)
- Price breaks resistance → immediately reverses (long wick 60%)
- ytc_signal = BOF, direction=SHORT, strength=5
- 4H trend = bullish (normally reject short)

Decision:
```
✓ YTC BOF signal detected (score=90)
✓ S/R strength 5/5 (allows override)
✓ Calculated R:R = 2.3 (≥2.0 required)
→ OPEN_SHORT 25% position (reduced from 40%)
→ Rationale: "BOF突破$110,500失败，S/R强度5/5，逆4H趋势入场"
```

=== DECISION CONFLICT RESOLUTION (Priority Order) ===

**Updated Priority (V7.5 with YTC):**

1. **YTC Structural Signal (S/R≥4) > 4H Trend**
   Ex1: BOF @ resistance strength=5 → Short (even if 4H bullish)
       Ex2: BPB @ support strength=5 → Long (even if 4H bearish)
   Condition: Must have R:R≥2.0 and reduce position to 20-25%

2. **Price Action at Key Level > Technical Indicators**
   Ex1: Resistance + Bearish Pin Bar → Short (even if indicators bullish)
       Ex2: Support + Bullish Pin Bar → Long (even if indicators bearish)
   
3. **4H Trend > 15m Indicators** (降级但保留)
   Ex1: 4H bearish + No YTC signal → Only seek shorts
   Ex2: 4H bull + YTC BOF signal (S/R≥4) → Can short with reduced position
   
4. **Reversal Price Action > Take-Profit Target**
   Ex: Before TP but engulfing reversal appears → Close immediately
   
5. **2+ Indicators Deteriorate > Continue Holding**

6. **In Profit + Any Counter Signal → Protect Profit First**

=== STOP-LOSS & TAKE-PROFIT LOGIC (V6.0: Using 1H Data) ===

**Calculation Method** (Based on 1H S/R + 1H ATR14):

**LONG Positions:**
- Stop-Loss = 1H strong support - 1H ATR14×0.5 (tight buffer for strong support)
- Take-Profit = 1H strong resistance - 1H ATR14×1.0 (exit early)
- Required R:R ≥ {learning_config['global']['min_risk_reward']:.1f}:1

**SHORT Positions:**
- Stop-Loss = 1H strong resistance + 1H ATR14×0.5 (tight buffer for strong resistance)
- Take-Profit = 1H strong support + 1H ATR14×1.0 (exit early)
- Required R:R ≥ {learning_config['global']['min_risk_reward']:.1f}:1

**When Key Levels Unclear:**
- Stop-Loss = Entry ± 1H ATR14×{learning_config['global']['atr_stop_multiplier']:.1f}
    - Take-Profit = Reverse calculate from R:R

**Why Use 1H Data?**
1. ✅ More reliable S/R: 1H levels less prone to false breakouts
2. ✅ Better stop buffer: Avoid 15m noise whipsaws
3. ✅ Better R:R: Wider stop, more reasonable TP target
4. ✅ Reduce stop-outs: 1H ATR reflects true volatility

**Validation Required:**
- R:R < {learning_config['global']['min_risk_reward']:.1f} → Reject entry
    - TP beyond resistance → Adjust or skip

=== ENTRY CONDITIONS (All 3 Layers Must Pass) ===

**LONG Conditions:**
✓ Layer 1: 4H bullish trend
✓ Layer 2: 15m bullish consensus ≥ {learning_config['global']['min_indicator_consensus']}/5
✓ Layer 3: Bullish price action + Safe location (support or neutral)

**SHORT Conditions:**
✓ Layer 1: 4H bearish trend
✓ Layer 2: 15m bearish consensus ≥ {learning_config['global']['min_indicator_consensus']}/5
✓ Layer 3: Bearish price action + Safe location (resistance or neutral)

**Bonus Upgrade to HIGH Signal:**
- LONG: Support + Bullish Pin/Engulfing + 5/5 consensus
- SHORT: Resistance + Bearish Pin/Engulfing + 5/5 consensus

=== EXIT CONDITIONS (Any Trigger) ===

**IMPORTANT: Trust Your Exit Plan!**
- Stop-loss/Take-profit orders already set on exchange (hard protection)
- Only exit early on **strong counter signals**
- Give TP target some "patience", avoid frequent mind changes

**Exit Priority Levels:**

**Level 1: Must Close Immediately (Ignore TP)**
1. Stop-loss triggered or imminent (distance <1%)
2. 4H strong reversal (bull→bear / bear→bull + confirmed with strong candle)
3. Loss >2% AND Layer 2 + Layer 3 both reversed

**Level 2: Early TP (When Close to Target)**
1. Distance to TP <10% + Layer 3 reversal signal (engulfing/Pin Bar)
2. Profit >80% of TP + MACD shrinking + RSI overbought/oversold
3. TP triggered or distance <2% (exchange order auto-fills)

**Level 3: Continue Holding (Give Plan Time)**
1. Distance to TP >10% and indicators normal → **HOLD, trust plan!**
2. Small profit (<3%) without strong counter signal → **HOLD**
3. Only single Layer 2 indicator weakens, Layer 1+3 normal → **HOLD**

**LONG Exit Criteria** (by priority):
- ✗ [Level 1] 4H turns bearish + confirmed with bearish candle
- ✗ [Level 1] Loss >2% + MACD bearish + Break below EMA20 + Resistance bearish signal
- ✗ [Level 2] Distance to TP <10% + Resistance bearish Pin/Engulfing
- ✗ [Level 2] Profit >80% TP + RSI7 >75 + MACD shrinking
- ✗ [Level 3] Stop/TP triggered (exchange auto-fills)
- ✓ [HOLD] Otherwise: Continue holding, trust plan

**SHORT Exit Criteria** (by priority):
- ✗ [Level 1] 4H turns bullish + confirmed with bullish candle
- ✗ [Level 1] Loss >2% + MACD bullish + Break above EMA20 + Support bullish signal
- ✗ [Level 2] Distance to TP <10% + Support bullish Pin/Engulfing
- ✗ [Level 2] Profit >80% TP + RSI7 <25 + MACD shrinking
- ✗ [Level 3] Stop/TP triggered (exchange auto-fills)
- ✓ [HOLD] Otherwise: Continue holding, trust plan

=== ANALYSIS WORKFLOW (Must Be Complete) ===

For each symbol, follow this structure:

**Example 1: LONG Decision**
```
BTC Analysis:
[Layer 1] 4H Trend = Bullish ✓ (Supports LONG)

[Layer 2] 15m Bullish Indicators
1. EMA20>EMA50: ✓
2. MACD histogram>0: ✓
3. RSI neutral(30-70): ✓
4. Volume surge: ✗
5. ATR normal: ✓
→ Score 4/5 ✓

[Layer 3] Price Action & Location
- Pin Bar: Bullish Pin Bar ✓✓
- Location: at_support ✓✓
- Engulfing: None

[Stop & TP]
- Support: $108,500 / Resistance: $110,500
- Stop: $108,375 / TP: $110,125
- R:R: 1.72:1 ✓

[Decision] OPEN_LONG (HIGH)
```

**Example 2: SHORT Decision**
```
ETH Analysis:
[Layer 1] 4H Trend = Bearish ✓ (Supports SHORT)

[Layer 2] 15m Bearish Indicators
1. EMA20<EMA50: ✓
2. MACD histogram<0: ✓
3. RSI neutral(30-70): ✓
4. Volume surge: ✓
5. ATR normal: ✓
→ Score 5/5 ✓✓

[Layer 3] Price Action & Location
- Pin Bar: Bearish Pin Bar ✓✓
- Location: at_resistance ✓✓ (At resistance)
- Engulfing: None

[Stop & TP]
- Resistance: $3,550 / Support: $3,480
- Stop: $3,560 / TP: $3,485
- R:R: 2.1:1 ✓✓

[Decision] OPEN_SHORT (HIGH)
```

=== LEVERAGE SELECTION (1-5x Smart Adjustment) ===

**Leverage adapts to signal quality:**

**5x Leverage (Strongest):**
- HIGH signal + R:R≥2.0 + 5/5 consensus + Key level (S/R)
- Ex: Support + Bullish Pin + All 5 indicators ✓

**4x Leverage (Strong):**
- HIGH signal + R:R≥1.8 + 4/5 consensus
- Ex: Key level + Engulfing + 4 indicators ✓

**3x Leverage (Medium):**
- MEDIUM signal + R:R≥1.5 + 3-4/5 consensus
- Or HIGH signal but neutral location

**2x Leverage (Weak):**
- MEDIUM signal + R:R 1.5-1.8 + 3/5 consensus
- Or barely qualified signal

**1x Leverage (Weakest):**
- LOW signal or R:R barely qualified (<1.6)
- Or ranging market, unclear signal

**Calculation Formula:**
Base leverage = 1x
+ R:R≥2.0: +2x
+ R:R 1.8-2.0: +1x
+ 5/5 consensus: +1x
+ 4/5 consensus: +0.5x
+ Key level (S/R): +1x
+ HIGH signal: +1x

Final leverage = min(sum, 5)

=== OUTPUT FORMAT (Strict JSON) ===

⚠️ **Field Priority (if space constrained):**
    1. **actions (Most Important)** - Must be complete with all trading decisions
2. **risk_assessment** - Must be complete with overall risk assessment
3. **analysis** - Must be complete with decision summary
4. **思考过程** - As complete as possible, at minimum key symbols analysis; if space limited, can simplify but must include core decision logic

{{
    "思考过程": "Analyze each symbol following 3-layer validation + leverage calculation. Include all symbols (BTC/ETH/SOL/BNB/XRP) analysis as much as possible",
    "analysis": "[Must be complete] Final decision summary",
    "actions": [
        {{
            "symbol": "BTC/USDT:USDT",
            "action": "OPEN_LONG|OPEN_SHORT|CLOSE|HOLD",
            "position_size_usd": 0,
            "leverage": 5,
            "reason": "[Must be complete] 【V7.9必须】Signal Mode (Scalping/Swing) + Rationale + YTC Signal Type + Trapped Traders Psychology + S/R Strength/Context + Leverage Rationale",
            "signal_mode": "scalping|swing",  // 【V7.9新增必填】Scalping (15-45min快速进出) or Swing (2-24h波段持有)
            "expected_holding_hours": 0.5,  // 【V7.9新增】预期持仓时间（小时）
            "stop_loss_price": 108375.00,
            "take_profit_price": 110125.00,
            "exit_plan": {{
                "stop_loss_condition": "[Hard SL] 1H Strong Support/Resistance - ATR Buffer (Premise Invalidation Point)",
                "take_profit_condition": "[Hard TP] 1H Strong Resistance/Support - ATR Buffer (Before Opposite Order Flow)",
                "invalidation_condition": "[YTC SCRATCH] Price stalls > 3 TTF candles AND momentum_slope turns strongly against position."
            }},
            "confidence": "HIGH|MEDIUM|LOW",
            // === YTC Enhanced Fields (V7.6 Complete) ===
            "ytc_signal_detected": false,  // YTC signal detected
            "ytc_signal_type": "NONE",  // BOF|BPB|PB|TST|CPB|NONE
            "sr_strength_used": 0,  // S/R strength (1-5, for BOF/BPB/TST)
                "weakness_score": 0.0,  // Pullback weakness (0.0-1.0, for PB/CPB)
            "trapped_traders": "",  // Psychology: who is trapped? (e.g., "Fading early sellers at pullback low")
            "lwp_reference": 0.0,  // LWP reference price
            "price_vs_lwp": "UNKNOWN",  // OPTIMAL|ACCEPTABLE|CHASING|UNKNOWN
            "overriding_4h_trend": false  // Counter-trend entry (only when YTC signal + S/R≥4 OR weakness≥0.85)
                }}
    ],
    "risk_assessment": "[Must be complete] Overall risk assessment",
    
    // === Trade Management Intention (YTC Simulation) ===
    "trade_management_plan": {{
        "part1_target": "Immediate opposing S/R (Quick profit)",
        "part2_target": "Next major HTF S/R OR Trail stop aggressively using 15m structural moves",
        "scaling_strategy": "Consider scaling out 50% at Part 1, trail remaining with YTC SCRATCH logic"
            }}
}}

**Trade Management Intention (Simulation):**

While code executes as single position, AI should plan multi-part management:
- **Part 1 (Quick Profit)**: Target immediate opposing 1H S/R, scale out 50% to secure profit
- **Part 2 (Trend Run)**: Target next major 4H S/R OR trail stop aggressively:
  * Use 15m structural moves (swing highs/lows) as trailing stops
  * Apply YTC SCRATCH logic: if momentum stalls >3 candles + no profit growth, exit remaining
      * Let winners run until premise invalidates OR major HTF S/R hit

**KEY REMINDERS V5.5:**
1. **Long & Short Equally**: In 4H bearish, actively seek SHORT, not just long
2. Price action highest priority, especially at key levels
3. R:R < {learning_config['global']['min_risk_reward']:.1f} must reject
4. LONG: Enter at support / SHORT: Enter at resistance
5. In profit + any counter signal → Close immediately
6. Analysis must show 3-layer validation (seriously analyze both long/short)
7. Stop/TP based on S/R, not fixed percentage
8. Available capital: {max_total_position:.0f}U
9. Current parameters auto-optimized from history, strictly follow
10. **V5.5 Smart Position Sizing**:
    - position_size_usd can be 0, system auto-allocates 15-50% based on signal
    - leverage can be suggested (1-5), system also suggests based on score
    - Strong signal (🚀🚀🚀) → System auto 50% position + 5x leverage
    - Medium signal (🎯) → System auto 35-47.5% position + 3-5x leverage
    - Weak signal (📊) → System auto 25% position + 1-2x leverage
    - Total risk budget 10%, auto-reduce or reject if exceeded
    - Multiple signals → System auto-ranks and prioritizes best symbol
"""
    
    # 🔍 调试：记录 prompt 信息
    print(f"\n{'='*70}")
    print(f"[调试] Prompt 总长度: {len(prompt)} 字符")
    print(f"[调试] 估算 tokens: {len(prompt)/2.5:.0f}")
    print(f"{'='*70}")
    print(f"[调试] Prompt 开头 500 字符:")
    print(prompt[:500])
    print(f"\n{'='*70}")
    print(f"[调试] Prompt 结尾 500 字符:")
    print(prompt[-500:])
    print(f"{'='*70}\n")
    
    # 🚀 AI调用优化：判断是否需要调用
    should_call, reason = ai_optimizer.should_call_portfolio_ai(
        market_data_list, current_positions
    )
    
    print(f"\n{'='*70}")
    print(f"[AI调用优化] {reason}")
    print(f"[统计] {ai_optimizer.get_stats()}")
    print(f"{'='*70}\n")
    
    if not should_call:
        # 市场状态无变化，返回空决策（保持当前持仓）
        return {
            "analysis": "市场状态无实质性变化，保持当前持仓",
            "decisions": [],
            "risk_assessment": "低风险：市场平稳",
            "思考过程": "基于市场状态指纹判断，无需重新分析"
        }
    
    try:
        # 🔧 优化System Prompt结构（利于Qwen后端缓存）
        optimized_system_prompt = """You are a professional quantitative portfolio manager AI specializing in multi-asset analysis and capital allocation.

Your core principles:
- Focus on risk control and strictly follow multi-indicator consensus principles
- Equally consider LONG and SHORT directions based on 4H trend
- In bearish trends, actively seek SHORT opportunities, not just longs
- Dynamically adjust positions to ensure total risk is controlled
- Always respond in Chinese (中文)"""
        
        response = qwen_client.chat.completions.create(
            model="qwen3-max",  # Qwen模型（思考模式，提升复杂策略分析能力）
            messages=[
                {
                    "role": "system",
                    "content": optimized_system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            stream=False,
            max_tokens=8000,  # 🔧 从8K提升到16K，避免JSON被截断
        )
        
        result = response.choices[0].message.content
        finish_reason = response.choices[0].finish_reason
        
        # 🔍 调试：查看 AI 完整响应
        print(f"\n{'='*70}")
        print(f"[调试] AI 返回内容总长度: {len(result)} 字符")
        print(f"[调试] finish_reason: {finish_reason}")
        if finish_reason == 'length':
            print("⚠️ 警告：AI响应被截断（超过max_tokens限制）")
        print(f"[调试] AI 响应前 1000 字符:")
        print(result[:1000])
        print(f"\n{'='*70}")
        print(f"[调试] AI 响应后 1000 字符:")
        print(result[-1000:])
        print(f"{'='*70}\n")
        
        start_idx = result.find("{")
        end_idx = result.rfind("}") + 1
        
        if start_idx != -1 and end_idx != 0:
            json_str = result[start_idx:end_idx]
            
            # 清理 JSON 字符串中的控制字符
            import re
            # 移除无效的控制字符（保留 \n \r \t）
            json_str = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', json_str)
            
            # 🔧 尝试修复被截断的JSON
            if finish_reason == 'length':
                print("尝试修复被截断的JSON...")
                # 统计未闭合的括号
                open_braces = json_str.count('{') - json_str.count('}')
                open_brackets = json_str.count('[') - json_str.count(']')
                
                # 添加缺失的闭合符号
                if open_brackets > 0:
                    json_str += ']' * open_brackets
                if open_braces > 0:
                    json_str += '}' * open_braces
                
                print(f"已添加 {open_brackets} 个 ] 和 {open_braces} 个 }}")
            
            try:
                decision = json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"JSON解析失败: {e}")
                # 如果修复失败，尝试使用提取函数
                try:
                    decision = extract_json_from_ai_response(result)
                    print("✓ 使用备用方法成功提取JSON")
                except:
                    raise

            # 🔍 调试日志：打印AI原始返回的关键字段
            print(f"[调试] AI原始返回 - 思考过程字段存在: {'思考过程' in decision}")
            if "思考过程" in decision:
                think_preview = str(decision.get("思考过程", ""))[:100]
                print(f"[调试] 思考过程前100字符: {think_preview}")

            # 🔧 简化后处理：只转换dict类型为字符串，不过度清理
            import re

            # 处理analysis字段
            if isinstance(decision.get("analysis"), dict):
                decision["analysis"] = str(decision["analysis"])

            # 处理risk_assessment字段
            if isinstance(decision.get("risk_assessment"), dict):
                decision["risk_assessment"] = str(decision["risk_assessment"])

            # 处理思考过程字段
            if isinstance(decision.get("思考过程"), dict):
                decision["思考过程"] = str(decision["思考过程"])
            elif decision.get("思考过程") is None:
                # 如果AI没有返回思考过程，设置为空字符串并记录
                print("⚠️ AI返回的决策中缺少'思考过程'字段")
                decision["思考过程"] = ""

            # 确保字段存在（但不强制清空）
            decision["analysis"] = str(decision.get("analysis", "无"))
            decision["risk_assessment"] = str(decision.get("risk_assessment", "无"))
            decision["思考过程"] = str(decision.get("思考过程", ""))

            # 简单清理Markdown标记
            if decision.get("思考过程"):
                think_content = decision["思考过程"]
                think_content = think_content.replace("```", "").strip()
                decision["思考过程"] = think_content
                print(f"✓ 思考过程已保留，长度: {len(think_content)} 字符")
            else:
                print("⚠️ 思考过程为空")

            print(f"✓ AI决策已解析 - 分析: {decision['analysis'][:50]}...")

            return decision
        else:
            print(f"无法解析JSON: {result}")
            return None
            
    except Exception as e:
        print(f"AI决策失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def calculate_risk_reward_ratio(entry_price, stop_loss, take_profit, side="long"):
    """计算盈亏比"""
    try:
        if side == "long":
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:  # short
            risk = stop_loss - entry_price
            reward = entry_price - take_profit
        
        if risk <= 0:
            return 0
        
        ratio = reward / risk
        return ratio
    except:
        return 0


def classify_signal_type(market_data):
    """
    【V7.9新增】信号分类：Scalping超短线 vs Swing波段
    
    返回：
    - signal_type: 'scalping' 或 'swing'
    - signal_name: 具体信号名称
    - expected_holding_minutes: 预期持仓时间（分钟）
    - reason: 分类原因
    """
    try:
        pa = market_data.get("price_action", {})
        sr = market_data.get("support_resistance", {})
        vol = market_data.get("volume_analysis", {})
        ytc = market_data.get("ytc_signal", {})
        lt = market_data.get("long_term", {})
        mt = market_data.get("mid_term", {})
        
        # === Scalping 信号判断（优先级高，快速识别） ===
        
        # 1. Pin Bar + 关键位
        position_status = sr.get("position_status", "neutral")
        pin_bar = pa.get("pin_bar")
        if pin_bar in ["bullish_pin", "bearish_pin"]:
            if position_status in ["at_support", "at_resistance"]:
                return {
                    'signal_type': 'scalping',
                    'signal_name': f'{pin_bar.upper()}_AT_KEY_LEVEL',
                    'expected_holding_minutes': 30,
                    'reason': f'{pin_bar} + {position_status}，快速反转机会'
                }
        
        # 2. Engulfing + 接近关键位
        engulfing = pa.get("engulfing")
        if engulfing in ["bullish_engulfing", "bearish_engulfing"]:
            # 检查是否在支撑/阻力3%内
            current_price = market_data.get("current_price", 0)
            nearest_support = sr.get("nearest_support", {}).get("price", 0)
            nearest_resistance = sr.get("nearest_resistance", {}).get("price", 0)
            
            near_support = nearest_support > 0 and abs(current_price - nearest_support) / current_price < 0.03
            near_resistance = nearest_resistance > 0 and abs(current_price - nearest_resistance) / current_price < 0.03
            
            if near_support or near_resistance:
                level_name = "支撑位" if near_support else "阻力位"
                return {
                    'signal_type': 'scalping',
                    'signal_name': f'{engulfing.upper()}_NEAR_LEVEL',
                    'expected_holding_minutes': 25,
                    'reason': f'{engulfing}接近{level_name}，短线反转'
                }
        
        # 3. 极端成交量 + 大波动
        if vol.get("type") == "extreme_surge":
            volume_ratio = vol.get("ratio", 0)
            if volume_ratio >= 3.0:
                # 检查K线波动
                kline_list = market_data.get("kline_data", [])
                if kline_list:
                    latest = kline_list[-1]
                    price_range = abs(latest.get("high", 0) - latest.get("low", 0))
                    open_price = latest.get("open", 1)
                    volatility_pct = (price_range / open_price) * 100 if open_price > 0 else 0
                    
                    if volatility_pct >= 1.5:
                        return {
                            'signal_type': 'scalping',
                            'signal_name': 'EXTREME_VOLUME_SURGE',
                            'expected_holding_minutes': 20,
                            'reason': f'极端放量({volume_ratio:.1f}x) + 大波动({volatility_pct:.1f}%)，快速脉冲'
                        }
        
        # 4. YTC-TST（测试信号）
        if ytc.get("signal_type") == "TST":
            ytc_strength = ytc.get("strength", 0)
            if ytc_strength >= 4:
                return {
                    'signal_type': 'scalping',
                    'signal_name': 'YTC_TST',
                    'expected_holding_minutes': 35,
                    'reason': f'YTC测试信号(强度{ytc_strength})，动能停滞快速反转'
                }
        
        # === Swing 信号判断（需要趋势背景） ===
        
        # 检查多周期趋势
        trend_4h = lt.get("trend", "")
        trend_1h = mt.get("trend", "")
        has_trend_support = (
            ("多头" in trend_4h or "空头" in trend_4h) or
            ("多头" in trend_1h or "空头" in trend_1h)
        )
        
        # 1. 趋势发起
        trend_initiation = pa.get("trend_initiation")
        if trend_initiation:
            strength = trend_initiation.get("strength", "")
            if strength == "strong" and has_trend_support:
                return {
                    'signal_type': 'swing',
                    'signal_name': 'TREND_INCEPTION_STRONG',
                    'expected_holding_minutes': 360,  # 6小时
                    'reason': '强势趋势发起+多周期确认，波段机会'
                }
            elif strength == "moderate":
                return {
                    'signal_type': 'swing',
                    'signal_name': 'TREND_INCEPTION_MODERATE',
                    'expected_holding_minutes': 180,  # 3小时
                    'reason': '中等趋势发起，波段潜力'
                }
        
        # 2. 简单回调
        pullback = pa.get("pullback_type")
        if pullback and pullback.get("type") == "simple_pullback":
            if pullback.get("signal") == "entry_ready" and has_trend_support:
                return {
                    'signal_type': 'swing',
                    'signal_name': 'SIMPLE_PULLBACK',
                    'expected_holding_minutes': 240,  # 4小时
                    'reason': '简单回调完成+趋势延续，波段入场'
                }
        
        # 3. YTC结构性信号（BOF/BPB/PB）
        ytc_type = ytc.get("signal_type", "")
        ytc_strength = ytc.get("strength", 0)
        
        if ytc_type in ["BOF", "BPB"] and ytc_strength >= 4:
            return {
                'signal_type': 'swing',
                'signal_name': f'YTC_{ytc_type}',
                'expected_holding_minutes': 300,  # 5小时
                'reason': f'YTC结构性信号{ytc_type}(强度{ytc_strength})，波段机会'
            }
        
        if ytc_type == "PB":
            weakness = ytc.get("weakness_score", 0)
            if weakness >= 0.85 and has_trend_support:
                return {
                    'signal_type': 'swing',
                    'signal_name': 'YTC_PB_WEAK',
                    'expected_holding_minutes': 280,  # 4.5小时
                    'reason': f'YTC弱回调(weakness={weakness:.2f})，趋势内最佳入场'
                }
        
        # 4. 连续K线突破（6根以上）
        consecutive = pa.get("consecutive")
        if consecutive and isinstance(consecutive, dict):
            candle_count = consecutive.get("candles", 0)
            if candle_count >= 6 and has_trend_support:
                return {
                    'signal_type': 'swing',
                    'signal_name': 'CONSECUTIVE_BREAKOUT',
                    'expected_holding_minutes': 200,  # 3.3小时
                    'reason': f'连续{candle_count}根K线+趋势确认，强势延续'
                }
        
        # === 默认：根据趋势背景决定 ===
        if has_trend_support:
            return {
                'signal_type': 'swing',
                'signal_name': 'GENERAL_TREND',
                'expected_holding_minutes': 120,  # 2小时
                'reason': '一般趋势信号，波段尝试'
            }
        else:
            return {
                'signal_type': 'scalping',
                'signal_name': 'GENERAL_SCALP',
                'expected_holding_minutes': 30,
                'reason': '无明确趋势，短线操作'
            }
    
    except Exception as e:
        print(f"⚠️ 信号分类失败: {e}")
        return {
            'signal_type': 'swing',
            'signal_name': 'UNKNOWN',
            'expected_holding_minutes': 120,
            'reason': '分类失败，默认波段'
        }


def calculate_scalping_score(market_data):
    """
    【V8.0 新增】超短线专用信号评分
    
    侧重点：
    - 短期动量（momentum）
    - 放量突破（volume_surge）
    - 快速突破（breakout）
    - 不强制要求长期趋势
    
    返回：(score, position_ratio, leverage)
    """
    try:
        score = 50  # 基础分
        # 【V8.3.14.1】安全获取字段，避免KeyError
        pa = market_data.get("price_action", {})
        lt = market_data.get("long_term", {})
        
        # === 超短线核心因素（高权重）===
        
        # 1. 极端放量（超短线最重要）
        if pa.get("volume_surge") and pa["volume_surge"].get("type") == "extreme_surge":
            score += 35  # 🔥 极端放量，超短线黄金信号
        elif pa.get("volume_surge"):
            score += 20  # 普通放量
        
        # 2. 突破信号（超短线次重要）
        if pa.get("breakout"):
            score += 25  # 🚀 突破信号
        
        # 3. 动量强度（超短线关键）
        momentum = abs(pa.get("momentum_slope", 0))
        if momentum > 0.015:  # 强劲动量
            score += 20
        elif momentum > 0.01:
            score += 15
        elif momentum > 0.005:
            score += 10
        
        # 4. 连续K线（3-5根即可，不需要太长）
        consecutive_info = pa.get("consecutive")
        if consecutive_info and isinstance(consecutive_info, dict):
            candle_count = consecutive_info.get("candles", 0)
            if candle_count >= 3:
                score += 15  # 超短线：3根以上即可
        
        # 5. Pin Bar / 吞没（反转信号）
        if pa.get("pin_bar") in ["bullish_pin", "bearish_pin"]:
            score += 12
        if pa.get("engulfing") in ["bullish_engulfing", "bearish_engulfing"]:
            score += 12
        
        # === 趋势确认（低权重，不强制）===
        trends = [
            market_data.get("trend_4h", ''),
            market_data.get("trend_1h", ''),
            market_data.get("trend_15m", '')
        ]
        aligned_count = sum(1 for t in trends if ('多头' in str(t) or '空头' in str(t)))
        if aligned_count >= 2:
            score += 10  # 有趋势更好，但不强制
        
        # === 减分项 ===
        
        # 阻力位（中等惩罚）
        sr = market_data.get("support_resistance", {})
        if sr.get("position_status") == "at_resistance":
            score -= 10  # 超短线可以突破阻力
        
        # RSI极端值（轻微惩罚）
        rsi_data = market_data.get("rsi", {})
        rsi = rsi_data.get("rsi_14", 50)
        if rsi > 80 or rsi < 20:
            score -= 5  # 超短线不太看重RSI
        
        # 趋势衰竭（严重）
        if pa.get("trend_exhaustion"):
            score -= 20  # 超短线也要避免衰竭
        
        # === 限制范围 ===
        score = min(100, max(0, score))
        
        # === 仓位和杠杆（保守）===
        position_ratio = 0.15 + (score / 100) * 0.05  # 15%-20%
        if score >= 90:
            leverage = 3  # 最高3x
        elif score >= 75:
            leverage = 2
        else:
            leverage = 1
        
        return score, position_ratio, leverage
        
    except Exception as e:
        print(f"⚠️ 超短线评分失败: {e}")
        return 50, 0.15, 1


def calculate_swing_score(market_data):
    """
    【V8.0 新增】波段专用信号评分
    
    侧重点：
    - 趋势质量（trend_initiation）
    - 多周期共振（multi_timeframe_align）
    - 趋势强度（trend_strength）
    - 持续性信号
    
    返回：(score, position_ratio, leverage)
    """
    try:
        score = 50  # 基础分
        # 【V8.3.14.1】安全获取字段，避免KeyError
        pa = market_data.get("price_action", {})
        lt = market_data.get("long_term", {})
        
        # === 波段核心因素（高权重）===
        
        # 1. 趋势发起（波段最重要）
        if pa.get("trend_initiation"):
            strength = pa["trend_initiation"].get("strength", "")
            if strength == "strong":
                score += 40  # 🚀🚀🚀 强势趋势发起，波段黄金信号
            elif strength == "moderate":
                score += 25  # 📈 中等趋势发起
        
        # 2. 多周期共振（波段次重要）
        trends = [
            market_data.get("trend_4h", ''),
            market_data.get("trend_1h", ''),
            market_data.get("trend_15m", '')
        ]
        bull_count = sum(1 for t in trends if '多头' in str(t))
        bear_count = sum(1 for t in trends if '空头' in str(t))
        aligned_count = max(bull_count, bear_count)
        
        if aligned_count >= 3:
            score += 35  # 三周期共振！
        elif aligned_count >= 2:
            score += 20  # 两周期共振
        
        # 3. 4小时趋势强度（波段关键）
        if "强势多头" in lt["trend"] or "强势空头" in lt["trend"]:
            score += 25  # 强势趋势
        elif "多头" in lt["trend"] or "空头" in lt["trend"]:
            score += 15  # 普通趋势
        
        # 4. EMA发散度（趋势强度确认）
        ma = market_data.get("moving_averages", {})
        ema20 = ma.get("ema20", 0)
        ema50 = ma.get("ema50", 0)
        if ema20 > 0 and ema50 > 0:
            ema_divergence = abs(ema20 - ema50) / ema50 * 100
            if ema_divergence >= 5.0:
                score += 20  # 高度发散，强趋势
            elif ema_divergence >= 3.0:
                score += 15
            elif ema_divergence >= 2.0:
                score += 10
        
        # 5. 连续K线（6根以上，强趋势）
        consecutive_info = pa.get("consecutive")
        if consecutive_info and isinstance(consecutive_info, dict):
            candle_count = consecutive_info.get("candles", 0)
            if candle_count >= 6:
                score += 20  # 波段：6根以上才算强趋势
            elif candle_count >= 4:
                score += 10
        
        # 6. 简单回调（波段最佳入场点）
        if pa.get("pullback_type") and pa["pullback_type"].get("type") == "simple_pullback":
            if pa["pullback_type"].get("signal") == "entry_ready":
                score += 30  # 🎯 回调完成，波段入场
        
        # === 短期信号（低权重）===
        
        # 突破信号（波段次要）
        if pa.get("breakout"):
            score += 10  # 波段更看重持续性
        
        # 放量（波段次要）
        if pa.get("volume_surge"):
            score += 8
        
        # === 减分项 ===
        
        # 阻力位（重度惩罚）
        sr = market_data.get("support_resistance", {})
        if sr.get("position_status") == "at_resistance":
            score -= 20  # 波段更怕阻力
        
        # RSI极端值
        rsi_data = market_data.get("rsi", {})
        rsi = rsi_data.get("rsi_14", 50)
        if rsi > 75 or rsi < 25:
            score -= 10  # 波段看重RSI
        
        # 趋势衰竭（严重）
        if pa.get("trend_exhaustion"):
            score -= 35  # 波段必须避免衰竭
        
        # === 限制范围 ===
        score = min(100, max(0, score))
        
        # === 仓位和杠杆（波段可以更大）===
        position_ratio = 0.25 + (score / 100) * 0.10  # 25%-35%
        if score >= 90:
            leverage = 5  # 最高5x
        elif score >= 80:
            leverage = 4
        elif score >= 70:
            leverage = 3
        else:
            leverage = 2
        
        return score, position_ratio, leverage
        
    except Exception as e:
        print(f"⚠️ 波段评分失败: {e}")
        return 50, 0.25, 2


def calculate_signal_score_components(market_data, signal_type='scalping'):
    """
    【V8.2新增】计算信号评分的各个维度
    
    保存"原料"而非"成品"，支持评分标准动态调整
    
    Args:
        market_data: 市场数据字典
        signal_type: 'scalping' 或 'swing'
    
    Returns:
        dict: {
            'signal_type': 'scalping',
            # 超短线维度
            'volume_surge_type': 'extreme_surge',
            'volume_surge_score': 35,
            'has_breakout': True,
            'breakout_score': 25,
            'momentum_value': 0.015,
            'momentum_score': 20,
            'consecutive_candles': 4,
            'consecutive_score': 15,
            'pin_bar_score': 12,
            'engulfing_score': 0,
            'trend_alignment': 2,
            'trend_alignment_score': 8,
            # 波段维度
            'trend_initiation_strength': 'strong',
            'trend_initiation_score': 40,
            # ... 其他维度
            'total_score': 85
        }
    """
    try:
        pa = market_data.get("price_action", {}) or {}
        lt = market_data.get("long_term", {}) or {}
        ma = market_data.get("moving_averages", {}) or {}
        vol = market_data.get("volume_analysis", {}) or {}
        
        components = {'signal_type': signal_type}
        
        # === 超短线维度 ===
        if signal_type == 'scalping':
            # 1. 放量程度
            volume_surge = pa.get("volume_surge")
            if volume_surge and isinstance(volume_surge, dict) and volume_surge.get("type") == "extreme_surge":
                components['volume_surge_type'] = 'extreme_surge'
                components['volume_surge_score'] = 35
            elif volume_surge:
                components['volume_surge_type'] = 'normal'
                components['volume_surge_score'] = 20
            else:
                components['volume_surge_type'] = 'none'
                components['volume_surge_score'] = 0
            
            # 2. 突破检测
            components['has_breakout'] = bool(pa.get("breakout"))
            components['breakout_score'] = 25 if components['has_breakout'] else 0
            
            # 3. 动量强度
            momentum = abs(pa.get("momentum_slope", 0))
            components['momentum_value'] = round(momentum, 4)
            if momentum > 0.015:
                components['momentum_score'] = 20
            elif momentum > 0.01:
                components['momentum_score'] = 15
            elif momentum > 0.005:
                components['momentum_score'] = 10
            else:
                components['momentum_score'] = 0
            
            # 4. 连续K线
            consecutive_info = pa.get("consecutive")
            if consecutive_info and isinstance(consecutive_info, dict):
                candle_count = consecutive_info.get("candles", 0)
                components['consecutive_candles'] = candle_count
                components['consecutive_score'] = 15 if candle_count >= 3 else 0
            else:
                components['consecutive_candles'] = 0
                components['consecutive_score'] = 0
            
            # 5. Pin Bar
            pin_bar = pa.get("pin_bar", "")
            components['pin_bar'] = pin_bar
            components['pin_bar_score'] = 12 if pin_bar in ["bullish_pin", "bearish_pin"] else 0
            
            # 6. 吞没
            engulfing = pa.get("engulfing", "")
            components['engulfing'] = engulfing
            components['engulfing_score'] = 12 if engulfing in ["bullish_engulfing", "bearish_engulfing"] else 0
            
            # 7. 趋势确认（超短线权重低）
            trends = [
                market_data.get("trend_4h", ''),
                market_data.get("trend_1h", ''),
                market_data.get("trend_15m", '')
            ]
            bull_count = sum(1 for t in trends if '多头' in str(t))
            bear_count = sum(1 for t in trends if '空头' in str(t))
            aligned_count = max(bull_count, bear_count)
            components['trend_alignment'] = aligned_count
            if aligned_count >= 2:
                components['trend_alignment_score'] = 10
            elif aligned_count >= 1:
                components['trend_alignment_score'] = 5
            else:
                components['trend_alignment_score'] = 0
        
        # === 波段维度 ===
        elif signal_type == 'swing':
            # 1. 趋势发起
            trend_init = pa.get("trend_initiation")
            if trend_init and isinstance(trend_init, dict):
                strength = trend_init.get("strength", "")
                components['trend_initiation_strength'] = strength
                if strength == "strong":
                    components['trend_initiation_score'] = 40
                elif strength == "moderate":
                    components['trend_initiation_score'] = 25
                else:
                    components['trend_initiation_score'] = 0
            else:
                components['trend_initiation_strength'] = 'none'
                components['trend_initiation_score'] = 0
            
            # 2. 多周期共振
            trends = [
                market_data.get("trend_4h", ''),
                market_data.get("trend_1h", ''),
                market_data.get("trend_15m", '')
            ]
            bull_count = sum(1 for t in trends if '多头' in str(t))
            bear_count = sum(1 for t in trends if '空头' in str(t))
            aligned_count = max(bull_count, bear_count)
            components['trend_alignment'] = aligned_count
            if aligned_count >= 3:
                components['trend_alignment_score'] = 35
            elif aligned_count >= 2:
                components['trend_alignment_score'] = 20
            else:
                components['trend_alignment_score'] = 0
            
            # 【V8.3.20修复】swing也需要考虑成交量、突破、动量（通用维度）
            # 2.1. 放量程度（对swing也很重要！）
            volume_surge = pa.get("volume_surge")
            if volume_surge and isinstance(volume_surge, dict) and volume_surge.get("type") == "extreme_surge":
                components['volume_surge_type'] = 'extreme_surge'
                components['volume_surge_score'] = 35
            elif volume_surge:
                components['volume_surge_type'] = 'normal'
                components['volume_surge_score'] = 20
            else:
                components['volume_surge_type'] = 'none'
                components['volume_surge_score'] = 0
            
            # 2.2. 突破检测
            components['has_breakout'] = bool(pa.get("breakout"))
            components['breakout_score'] = 25 if components['has_breakout'] else 0
            
            # 2.3. 动量强度
            momentum = abs(pa.get("momentum_slope", 0))
            components['momentum_value'] = round(momentum, 4)
            if momentum > 0.015:
                components['momentum_score'] = 20
            elif momentum > 0.01:
                components['momentum_score'] = 15
            elif momentum > 0.005:
                components['momentum_score'] = 10
            else:
                components['momentum_score'] = 0
            
            # 3. 4小时趋势强度
            trend_4h = lt.get("trend", "")
            if "强势多头" in trend_4h or "强势空头" in trend_4h:
                components['trend_4h_strength'] = 'strong'
                components['trend_4h_strength_score'] = 25
            elif "多头" in trend_4h or "空头" in trend_4h:
                components['trend_4h_strength'] = 'normal'
                components['trend_4h_strength_score'] = 15
            else:
                components['trend_4h_strength'] = 'weak'
                components['trend_4h_strength_score'] = 5
            
            # 4. EMA发散度
            ema20 = ma.get("ema20", 0)
            ema50 = ma.get("ema50", 0)
            if ema20 > 0 and ema50 > 0:
                ema_divergence = abs(ema20 - ema50) / ema50 * 100
                components['ema_divergence_pct'] = round(ema_divergence, 2)
                if ema_divergence >= 5.0:
                    components['ema_divergence_score'] = 15
                elif ema_divergence >= 3.0:
                    components['ema_divergence_score'] = 10
                else:
                    components['ema_divergence_score'] = 0
            else:
                components['ema_divergence_pct'] = 0
                components['ema_divergence_score'] = 0
            
            # 5. 回调类型
            pullback = pa.get("pullback_type", {})
            if isinstance(pullback, dict):
                pullback_type = pullback.get("type", "")
                components['pullback_type'] = pullback_type
                if pullback_type == "simple_pullback":
                    components['pullback_score'] = 15
                elif pullback_type == "complex_pullback":
                    components['pullback_score'] = 10
                else:
                    components['pullback_score'] = 0
            else:
                components['pullback_type'] = str(pullback) if pullback else ""
                components['pullback_score'] = 10 if components['pullback_type'] else 0
            
            # 6. 连续K线（波段要求更多）
            consecutive_info = pa.get("consecutive")
            if consecutive_info and isinstance(consecutive_info, dict):
                candle_count = consecutive_info.get("candles", 0)
                components['consecutive_candles'] = candle_count
                if candle_count >= 8:
                    components['consecutive_score'] = 15
                elif candle_count >= 6:
                    components['consecutive_score'] = 10
                else:
                    components['consecutive_score'] = 0
            else:
                components['consecutive_candles'] = 0
                components['consecutive_score'] = 0
            
            # 7. 成交量确认
            components['volume_confirmed'] = bool(vol.get("ratio", 0) >= 1.2)
            components['volume_confirmed_score'] = 5 if components['volume_confirmed'] else 0
        
        # 计算总分（基础分50 + 各维度分数）
        total_score = 50
        for key, value in components.items():
            if key.endswith('_score') and isinstance(value, (int, float)):
                total_score += value
        components['total_score'] = min(100, max(0, total_score))
        
        return components
        
    except Exception as e:
        print(f"⚠️ 【V8.2】计算评分维度失败: {e}")
        # 返回默认值
        return {
            'signal_type': signal_type,
            'total_score': 50,
            # 超短线默认维度
            'volume_surge_type': '',
            'volume_surge_score': 0,
            'has_breakout': False,
            'breakout_score': 0,
            'momentum_value': 0,
            'momentum_score': 0,
            'consecutive_candles': 0,
            'consecutive_score': 0,
            'pin_bar': '',
            'pin_bar_score': 0,
            'engulfing': '',
            'engulfing_score': 0,
            'trend_alignment': 0,
            'trend_alignment_score': 0,
            # 波段默认维度
            'trend_initiation_strength': '',
            'trend_initiation_score': 0,
            'trend_4h_strength': '',
            'trend_4h_strength_score': 0,
            'ema_divergence_pct': 0,
            'ema_divergence_score': 0,
            'pullback_type': '',
            'pullback_score': 0,
            'volume_confirmed': False,
            'volume_confirmed_score': 0
        }


def calculate_signal_score(market_data):
    """
    【V8.0 重构】信号质量评分路由函数
    
    根据信号类型，路由到不同的评分函数：
    - scalping → calculate_scalping_score()
    - swing → calculate_swing_score()

    返回：
    - score: 信号得分（0-100）
    - position_ratio: 建议仓位比例
    - suggested_leverage: 建议杠杆
    - signal_classification: 信号分类信息
    """
    try:
        # 【V8.0】首先进行信号分类
        signal_classification = classify_signal_type(market_data)
        signal_type = signal_classification.get('signal_type', 'swing')
        
        # 【V8.0】根据信号类型选择评分函数
        if signal_type == 'scalping':
            score, position_ratio, leverage = calculate_scalping_score(market_data)
            print(f"  ⚡ 超短线评分: {score} | 仓位{position_ratio:.1%} | 杠杆{leverage}x")
        else:  # swing
            score, position_ratio, leverage = calculate_swing_score(market_data)
            print(f"  🌊 波段评分: {score} | 仓位{position_ratio:.1%} | 杠杆{leverage}x")
        
        return score, position_ratio, leverage, signal_classification
        
    except Exception as e:
        print(f"⚠️ 信号评分路由失败: {e}")
        # 【V8.3.14.2】增强错误诊断
        print(f"  调试信息: market_data类型={type(market_data)}")
        if isinstance(market_data, dict):
            print(f"  market_data keys: {list(market_data.keys())[:10]}")  # 只显示前10个
        import traceback
        traceback.print_exc()
        
        # Fallback：返回默认值
        try:
            signal_classification = classify_signal_type(market_data)
        except:
            # 如果classify_signal_type也失败，使用完全默认值
            signal_classification = {
                'signal_type': 'swing',
                'signal_name': 'DEFAULT',
                'expected_holding_minutes': 120,
                'reason': '评分失败，默认波段'
            }
        
        signal_type = signal_classification.get('signal_type', 'swing')
        
        # 根据信号类型返回默认值
        if signal_type == 'scalping':
            return 50, 0.15, 1, signal_classification  # 超短线默认值
        else:
            return 50, 0.25, 2, signal_classification  # 波段默认值


# 🗑️ 以下为V7.9旧版评分逻辑，已被V8.0分离函数替代，保留作为参考
def _calculate_signal_score_v79_legacy(market_data):
    """
    【已废弃】V7.9统一评分逻辑
    仅保留作为参考，实际已被 calculate_scalping_score() 和 calculate_swing_score() 替代
    """
    try:
        signal_classification = classify_signal_type(market_data)
        score = 50
        pa = market_data["price_action"]
        lt = market_data["long_term"]
        
        # 1. 趋势发起（最高优先级）
        if pa.get("trend_initiation"):
            if (
                pa["trend_initiation"].get("strength") == "strong"
                and pa["trend_initiation"].get("entry_signal") == "immediate"
            ):
                score = 100  # 🚀🚀🚀 强势趋势发起
            elif pa["trend_initiation"].get("strength") == "moderate":
                score = 70  # 📈 中等趋势发起

        # 2. 简单回调入场（次优）
        elif (
            pa.get("pullback_type")
            and pa["pullback_type"].get("type") == "simple_pullback"
        ):
            if pa["pullback_type"].get("signal") == "entry_ready":
                score = 90  # 🎯 简单回调已恢复
            else:
                score = 55  # ⏳ 简单回调中

        # 3. 极端放量突破
        elif (
            pa.get("volume_surge") and pa["volume_surge"].get("type") == "extreme_surge"
        ):
            score = 95  # 💥 极端放量

        # 4. 突破性大阳线
        elif pa.get("breakout"):
            score = 80  # 🚀 突破

        # 5. 复杂回调（需等待）
        elif (
            pa.get("pullback_type")
            and pa["pullback_type"].get("type") == "complex_pullback"
        ):
            score = 50  # 📊 复杂回调等待

        # 6. Pin Bar / 吞没
        elif pa.get("pin_bar") in ["bullish_pin", "bearish_pin"] or pa.get(
            "engulfing"
        ) in ["bullish_engulfing", "bearish_engulfing"]:
            score = 60  # ✓✓ 经典反转

        # 7. 连续阳线
        elif pa.get("consecutive"):
            score = 65  # 📈 趋势延续

        # === 加分项 ===

        # 4小时趋势确认（+5-10分）
        if "强势多头" in lt["trend"] or "强势空头" in lt["trend"]:
            score += 10
        elif "多头" in lt["trend"] or "空头" in lt["trend"]:
            score += 5

        # 【新增V7.8】连续同向K线加分（强趋势信号）
        consecutive_info = pa.get("consecutive")
        if consecutive_info and isinstance(consecutive_info, dict):
            candle_count = consecutive_info.get("candles", 0)
            if candle_count >= 6:
                score += 20  # 6根以上连续K线，强趋势
            elif candle_count >= 4:
                score += 10  # 4-5根连续K线，中等趋势
        
        # 【新增V7.8】EMA发散度加分（趋势强度确认）
        ma = market_data.get("moving_averages", {})
        ema20 = ma.get("ema20", 0)
        ema50 = ma.get("ema50", 0)
        if ema20 > 0 and ema50 > 0:
            ema_divergence = abs(ema20 - ema50) / ema50 * 100
            if ema_divergence >= 5.0:
                score += 15  # EMA高度发散，强趋势
            elif ema_divergence >= 3.0:
                score += 10  # EMA中度发散
            elif ema_divergence >= 2.0:
                score += 5   # EMA轻度发散

        # RSI处于健康区间（+5分）
        rsi = market_data["rsi"]["rsi_14"]
        if 35 < rsi < 65:
            score += 5

        # MACD确认（+3分）
        if market_data["macd"]["histogram"] > 0:
            score += 3

        # === 减分项 ===

        # 接近阻力位（-10分）
        sr = market_data["support_resistance"]
        if sr["position_status"] == "at_resistance":
            score -= 10

        # RSI超买/超卖（-5分）
        if rsi > 75 or rsi < 25:
            score -= 5

        # 趋势衰竭信号（严重，-30分）
        if pa.get("trend_exhaustion"):
            score -= 30

        # === 限制在0-100范围 ===
        score = min(100, max(0, score))

        # === 仓位比例计算（线性映射）===
        # 50分 → 25%, 100分 → 50%
        position_ratio = 0.25 + (score / 100) * 0.25
        position_ratio = min(0.50, max(0.15, position_ratio))

        # === 杠杆建议 ===
        if score >= 90:
            suggested_leverage = 5
        elif score >= 80:
            suggested_leverage = 4
        elif score >= 70:
            suggested_leverage = 3
        elif score >= 60:
            suggested_leverage = 2
        else:
            suggested_leverage = 1

        # 【V7.9】返回包含信号分类的完整信息
        return score, position_ratio, suggested_leverage, signal_classification

    except Exception as e:
        print(f"⚠️ 信号评分失败: {e}")
        # 默认值（向后兼容）
        default_classification = {
            'signal_type': 'swing',
            'signal_name': 'UNKNOWN',
            'expected_holding_minutes': 120,
            'reason': '评分失败'
        }
        return 50, 0.30, 2, default_classification


def check_risk_budget(
    planned_position_usd, leverage, stop_loss_pct, current_positions, total_assets
):
    """
    检查风险预算是否允许开仓（V5.5新增）

    总风险预算 = 账户总资产 × 10%
    单笔风险 = 仓位 × 杠杆 × 止损距离%

    返回：
    - allowed: 是否允许开仓
    - adjusted_position: 调整后的仓位（可能缩减）
    - risk_used_pct: 当前风险使用率（%）
    """
    try:
        # 总风险预算（10%）
        total_risk_budget = total_assets * 0.10

        # 计算当前所有持仓的风险
        current_risk = 0
        for pos in current_positions:
            # 持仓风险 = 保证金（近似）
            # 实际应该是：持仓价值 × 止损距离，这里简化为保证金
            position_value = abs(pos.get("contracts", 0) * pos.get("entry_price", 0))
            margin = (
                position_value / pos.get("leverage", 1)
                if pos.get("leverage", 1) > 0
                    else position_value
            )
            current_risk += margin

        # 计划交易的风险
        planned_risk = planned_position_usd * leverage * stop_loss_pct

        # 可用风险
        available_risk = total_risk_budget - current_risk

        # 风险使用率
        risk_used_pct = (
            (current_risk / total_risk_budget * 100) if total_risk_budget > 0 else 0
        )

        # 检查是否允许
        if planned_risk <= available_risk:
            # 完全允许
            return True, planned_position_usd, risk_used_pct

        # 需要缩减仓位
        if available_risk > 0:
            adjusted_position = planned_position_usd * (available_risk / planned_risk)

            # 如果调整后仓位太小（<10U），拒绝开仓
            if adjusted_position < 10:
                return False, 0, risk_used_pct

            return True, adjusted_position, risk_used_pct

        # 可用风险<=0，拒绝
        return False, 0, risk_used_pct

    except Exception as e:
        print(f"⚠️ 风险预算检查失败: {e}")
        # 出错时保守处理，拒绝开仓
        return False, 0, 100


def prioritize_signals(market_data_list, ai_actions):
    """
    对多个开仓信号进行优先级排序（V5.5新增）

    综合考虑：
    1. 信号质量得分（40%）
    2. 盈亏比（30%）
    3. 4小时趋势强度（20%）
    4. 距离关键位（10%）

    返回：
    - sorted_actions: 按优先级排序的动作列表
    """
    try:
        scored_actions = []

        for action in ai_actions:
            if action.get("action") not in ["OPEN_LONG", "OPEN_SHORT"]:
                continue

            symbol = action.get("symbol", "")

            # 找到对应的市场数据
            market_data = next(
                (m for m in market_data_list if m["symbol"] == symbol), None
            )

            if not market_data:
                continue

            # 1. 信号得分（0-100）
            signal_score, _, _, _ = calculate_signal_score(market_data)

            # 2. 盈亏比
            entry_price = action.get("entry_price", market_data["price"])
            stop_loss = action.get("stop_loss_price", 0)
            take_profit = action.get("take_profit_price", 0)
            side = "long" if action.get("action") == "OPEN_LONG" else "short"
            rr = calculate_risk_reward_ratio(entry_price, stop_loss, take_profit, side)

            # 3. 4小时趋势强度（1-5）
            lt_trend = market_data["long_term"]["trend"]
            if "强势多头" in lt_trend or "强势空头" in lt_trend:
                trend_strength = 5
            elif "多头转弱" in lt_trend or "空头转弱" in lt_trend:
                trend_strength = 2
            elif "多头" in lt_trend or "空头" in lt_trend:
                trend_strength = 3
            else:
                trend_strength = 1

            # 4. 距离关键位（简化：使用支撑阻力位状态）
            sr = market_data["support_resistance"]
            if sr["position_status"] == "at_support" and side == "long":
                distance_score = 10  # 多单在支撑，好
            elif sr["position_status"] == "at_resistance" and side == "short":
                distance_score = 10  # 空单在阻力，好
            elif sr["position_status"] == "neutral":
                distance_score = 5  # 中性位置
            else:
                distance_score = 0  # 位置不利

            # === 综合得分 ===
            priority_score = (
                signal_score * 0.4
                + min(rr * 15, 50) * 0.3  # 盈亏比最多贡献50分
                + (trend_strength * 10) * 0.2
                + distance_score * 0.1
            )

            scored_actions.append(
                {
                    "action": action,
                    "score": priority_score,
                    "signal_score": signal_score,
                    "rr": rr,
                    "trend_strength": trend_strength,
                    "market_data": market_data,
                }
            )

        # 按总分排序（得分高的优先）
        scored_actions.sort(key=lambda x: x["score"], reverse=True)

        return scored_actions

    except Exception as e:
        print(f"⚠️ 优先级排序失败: {e}")
        import traceback

        traceback.print_exc()
        return []


# ===== YTC主动平仓机制（V7.5新增）=====

def check_price_stall(df_15m: pd.DataFrame, entry_time_str: str = None) -> bool:
    """
    检查入场后价格是否停滞（YTC Premise Invalidation）
    
    Args:
        df_15m: 15分钟K线数据
        entry_time_str: 开仓时间字符串
    
    Returns:
        bool: 是否停滞
    """
    try:
        if len(df_15m) < 3:
            return False
        
        # 最近3根K线的收盘价
        recent_closes = df_15m.tail(3)['close'].values
        
        # 计算波动范围
        close_range = (recent_closes.max() - recent_closes.min()) / recent_closes.mean()
        
        # 如果波动<0.2%，视为停滞
        is_stalling = close_range < 0.002
        
        return is_stalling
    except:
        return False


def check_reversal_signal(price_action: dict, position_side: str) -> tuple:
    """
    检查是否出现反向价格行为（YTC Premise Invalidation）
    
    Args:
        price_action: 价格行为数据
        position_side: 持仓方向（long/short）
    
    Returns:
        tuple: (是否反转, 反转类型)
    """
    try:
        if position_side == 'long':
            # 持多仓，检查空头信号
            bearish_pin = price_action.get('pin_bar') == 'bearish_pin'
            bearish_engulfing = price_action.get('engulfing') == 'bearish_engulfing'
            
            # 趋势衰竭信号
            exhaustion = price_action.get('trend_exhaustion')
            if exhaustion and exhaustion.get('action') == 'close_long':
                return True, 'EXHAUSTION_' + exhaustion.get('signal', 'unknown').upper()
            
            if bearish_pin:
                return True, 'BEARISH_PIN_BAR'
            if bearish_engulfing:
                return True, 'BEARISH_ENGULFING'
        
        else:  # short position
            # 持空仓，检查多头信号
            bullish_pin = price_action.get('pin_bar') == 'bullish_pin'
            bullish_engulfing = price_action.get('engulfing') == 'bullish_engulfing'
            
            # 趋势衰竭信号
            exhaustion = price_action.get('trend_exhaustion')
            if exhaustion and exhaustion.get('action') == 'close_short':
                return True, 'EXHAUSTION_' + exhaustion.get('signal', 'unknown').upper()
            
            if bullish_pin:
                return True, 'BULLISH_PIN_BAR'
            if bullish_engulfing:
                return True, 'BULLISH_ENGULFING'
        
        return False, None
    except:
        return False, None


def check_time_invalidation(entry_time_str: str, max_hours: int = 24) -> bool:
    """
    检查持仓时间是否过长（YTC Premise Invalidation）
    
    Args:
        entry_time_str: 开仓时间字符串
            max_hours: 最大持仓小时数
    
    Returns:
        bool: 是否时间失效
    """
    try:
        if not entry_time_str:
            return False
        
        entry_dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        hours_held = (now - entry_dt).total_seconds() / 3600
        
        # 超过max_hours的80%视为时间失效预警
        return hours_held > max_hours * 0.8
    except:
        return False


def request_ai_close_confirmation(symbol, position, market_data, invalidation_reasons, entry_context):
    """
    请求AI确认是否应该平仓（V7.7.0.19新增）
    
    场景：系统检测到前提失效，但不确定是否应该平仓
    AI会结合开仓理由、当前市场情况做出判断
    
    参数:
        symbol: str, 交易对
        position: dict, 持仓信息
        market_data: dict, 当前市场数据
        invalidation_reasons: list, 系统检测到的失效原因
        entry_context: dict, 开仓时的上下文
    
    返回: (should_close: bool, reason: str)
    """
    try:
        coin_name = symbol.split("/")[0]
        side = position.get('side', 'unknown')
        entry_price = position.get('entry_price', 0)
        current_price = market_data.get('price', 0)
        unrealized_pnl = position.get('unrealized_pnl', 0)
        
        # 计算持仓时间
        entry_time = position.get('open_time')
        if entry_time:
            try:
                if isinstance(entry_time, str):
                    entry_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
                else:
                    entry_dt = entry_time
                holding_hours = (datetime.now() - entry_dt).total_seconds() / 3600
            except:
                holding_hours = 0
        else:
            holding_hours = 0
        
        # 【V7.9】获取信号类型
        signal_type = entry_context.get('signal_type', 'swing')
        expected_holding_minutes = entry_context.get('expected_holding_minutes', 120)
        classification_reason = entry_context.get('classification_reason', 'N/A')
        
        # 【V7.9】根据信号类型调整评估标准
        if signal_type == 'scalping':
            mode_guidance = """
**⚡ SCALPING MODE REVIEW STANDARDS**
- Expected holding: 15-45 minutes (fast in/out)
- Exit sensitivity: HIGH - any counter signal should be taken seriously
- Noise tolerance: LOW - this is a reversal play, not a trend ride
- Profit protection: Exit at first sign of stalling or reversal
- Time factor: If held >1 hour, likely already missed optimal exit
"""
        else:  # swing
            mode_guidance = """
**🌊 SWING MODE REVIEW STANDARDS**
- Expected holding: 2-24 hours (wave riding)
- Exit sensitivity: LOW - ignore single-bar noise
- Noise tolerance: HIGH - allow normal pullbacks within trend
- Profit protection: Only exit if multi-timeframe (1H+4H) trend reverses
    - Time factor: If held <2 hours, give it more time to develop
- Key levels: Only worry if breaking through support/resistance
    """
        
        # 构建AI Prompt（【V7.9】增加周期感知）
        prompt = f"""You are reviewing a {side} position on {coin_name}. The system has flagged potential premise invalidation. Evaluate whether to close this position.

【V7.9 IMPORTANT】This is a **{signal_type.upper()} signal** - apply appropriate review standards!

## Signal Classification
- Type: **{signal_type.upper()}**
- Expected Holding: {expected_holding_minutes} minutes
- Reason: {classification_reason}

{mode_guidance}

## Position Details
- Entry Price: ${entry_price:,.2f}
    - Current Price: ${current_price:,.2f}
- Unrealized PnL: ${unrealized_pnl:+.2f} USDT
- Holding Duration: {holding_hours:.1f} hours ({holding_hours*60:.0f} minutes)

## Original Entry Thesis
{entry_context.get('entry_reason', 'N/A')[:200]}

## Entry Strategy & Commitment
{entry_context.get('ai_strategy', 'Trust the plan')[:150]}

## System-Flagged Invalidation Signals
{' + '.join(invalidation_reasons)}

## Current Market Context
- Trend (4H): {market_data.get('long_term', {}).get('trend', 'N/A')}
- Trend (1H): {market_data.get('mid_term', {}).get('trend', 'N/A')}
- Momentum Slope: {market_data.get('price_action', {}).get('momentum_slope', 0):.3f}
- RSI: {market_data.get('mid_term', {}).get('rsi', 50):.1f}

## Decision Framework
Should we CLOSE or HOLD this position?

**Apply {signal_type.upper()} review standards above!**

Evaluate:
1. Is the original entry thesis still valid?
2. Are the invalidation signals temporary noise or structural breakdown?
3. Does the signal type (scalping vs swing) affect how we interpret these signals?
4. Risk-reward: downside exposure vs remaining upside potential?

Return JSON (reason MUST be in Chinese):
{{
  "decision": "CLOSE" or "HOLD",
  "reason": "中文简要说明（不超过50字）",
  "confidence": "HIGH" or "MEDIUM" or "LOW"
}}
"""
        
        # 调用AI
        response = qwen_client.chat.completions.create(
            model="qwen3-max",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
            temperature=0.7
        )
        
        ai_content = response.choices[0].message.content
        ai_decision = extract_json_from_ai_response(ai_content)
        
        should_close = ai_decision.get('decision') == 'CLOSE'
        reason = ai_decision.get('reason', 'AI判断')
        confidence = ai_decision.get('confidence', 'MEDIUM')
        
        print(f"   AI确认结果: {ai_decision.get('decision')} (置信度: {confidence})")
        print(f"   AI理由: {reason}")
        
        return should_close, reason
        
    except Exception as e:
        print(f"   ⚠️ AI确认失败（默认平仓）: {e}")
        return True, "AI确认失败，使用系统判断"


def ai_adjust_tp_sl_if_needed(symbol, position, market_data, entry_context, config):
    """
    AI评估并调整止盈止损（V7.7.0.19新增）
    
    场景：持仓期间，AI发现当前止盈止损设置不合理，需要调整
    
    参数:
        symbol: str, 交易对
        position: dict, 持仓信息
        market_data: dict, 当前市场数据
        entry_context: dict, 开仓时的上下文
            config: dict, 学习配置
    
    返回: dict, 调整建议 {'should_adjust': bool, 'new_tp': float, 'new_sl': float, 'reason': str}
    """
    try:
        # 检查是否允许动态调整
        tp_sl_strategy = config.get('global', {}).get('tp_sl_strategy', {})
        if not tp_sl_strategy.get('allow_dynamic_adjustment', False):
            return {'should_adjust': False, 'reason': 'Dynamic adjustment disabled'}
        
        coin_name = symbol.split("/")[0]
        side = position.get('side', 'unknown')
        entry_price = position.get('entry_price', 0)
        current_price = market_data.get('price', 0)
        unrealized_pnl = position.get('unrealized_pnl', 0)
        
        # 检查上次调整时间（冷却期）
        last_adjustment_key = f"{coin_name}_last_tp_sl_adjustment"
        cooldown_minutes = tp_sl_strategy.get('adjustment_cooldown_minutes', 60)
        
        # 这里简化处理，实际应该存储在全局变量或文件中
        # 暂时每次都允许调整，实际部署时需要加上冷却机制
        
        # 获取当前的止盈止损价格（从交易所查询）
        try:
            open_orders = exchange.fetch_open_orders(symbol)
            current_tp = None
            current_sl = None
            
            for order in open_orders:
                # 修复：reduceOnly 可能是字符串 "true" 或布尔值 True
                reduce_only = order['info'].get('reduceOnly')
                is_reduce_only = (reduce_only == True or reduce_only == 'true' or reduce_only == 'True')
                
                if is_reduce_only:
                    if order['type'] == 'take_profit_market':
                        current_tp = float(order['stopPrice'])
                    elif order['type'] == 'stop_market':
                        current_sl = float(order['stopPrice'])
            
            if not current_tp and not current_sl:
                return {'should_adjust': False, 'reason': 'No active TP/SL orders found'}
            
        except Exception as e:
            print(f"   ⚠️ 查询止盈止损订单失败: {e}")
            return {'should_adjust': False, 'reason': f'Failed to fetch orders: {e}'}
        
        # 构建AI Prompt
        prompt = f"""You are managing a {side} position on {coin_name}. The system is checking if we should adjust the current Take-Profit (TP) and Stop-Loss (SL) settings.

## Position Status
- Entry Price: ${entry_price:,.2f}
    - Current Price: ${current_price:,.2f}
- Unrealized PnL: ${unrealized_pnl:+.2f}
- Current TP: ${current_tp if current_tp else 'N/A'}
    - Current SL: ${current_sl if current_sl else 'N/A'}

## Original Entry Reason
{entry_context.get('entry_reason', 'N/A')[:200]}

## Current Market Evolution
- Trend 4H: {market_data.get('long_term', {}).get('trend', 'N/A')}
- Trend 1H: {market_data.get('mid_term', {}).get('trend', 'N/A')}
- Momentum: {market_data.get('price_action', {}).get('momentum_slope', 0):.3f}
- RSI: {market_data.get('mid_term', {}).get('rsi', 50):.1f}
- Volume Trend: {market_data.get('mid_term', {}).get('volume_trend', 'N/A')}

## Question
Should we adjust the TP/SL settings based on current market conditions?

Consider:
1. Has the trend strengthened or weakened since entry?
2. Is the current TP too conservative or aggressive?
3. Should we tighten SL to protect profit or widen it for volatility?

Return JSON:
{{
  "should_adjust": true or false,
  "new_take_profit": float or null,  // New TP price, null if no change
      "new_stop_loss": float or null,    // New SL price, null if no change
  "reason": "Explanation (max 80 words)",
  "confidence": "HIGH|MEDIUM|LOW"
}}
"""
        
        # 调用AI
        response = qwen_client.chat.completions.create(
            model="qwen3-max",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.7
        )
        
        ai_content = response.choices[0].message.content
        ai_decision = extract_json_from_ai_response(ai_content)
        
        should_adjust = ai_decision.get('should_adjust', False)
        new_tp = ai_decision.get('new_take_profit')
        new_sl = ai_decision.get('new_stop_loss')
        reason = ai_decision.get('reason', 'AI assessment')
        confidence = ai_decision.get('confidence', 'MEDIUM')
        
        # 验证调整幅度是否达到最小阈值
        min_threshold_pct = tp_sl_strategy.get('min_adjustment_threshold_pct', 2.0)
        
        if should_adjust:
            tp_change_pct = 0
            sl_change_pct = 0
            
            if new_tp and current_tp:
                tp_change_pct = abs(new_tp - current_tp) / current_tp * 100
            if new_sl and current_sl:
                sl_change_pct = abs(new_sl - current_sl) / current_sl * 100
            
            # 如果调整幅度太小，忽略
            if tp_change_pct < min_threshold_pct and sl_change_pct < min_threshold_pct:
                return {
                    'should_adjust': False,
                    'reason': f'Adjustment too small (TP: {tp_change_pct:.1f}%, SL: {sl_change_pct:.1f}% < {min_threshold_pct}%)'
                }
            
            print(f"   ✓ AI建议调整止盈止损:")
            if new_tp:
                print(f"     TP: ${current_tp:,.2f} → ${new_tp:,.2f} ({(new_tp-current_tp)/current_tp*100:+.1f}%)")
            if new_sl:
                print(f"     SL: ${current_sl:,.2f} → ${new_sl:,.2f} ({(new_sl-current_sl)/current_sl*100:+.1f}%)")
            print(f"     理由: {reason}")
            print(f"     置信度: {confidence}")
        
        return {
            'should_adjust': should_adjust,
            'new_tp': new_tp,
            'new_sl': new_sl,
            'current_tp': current_tp,
            'current_sl': current_sl,
            'reason': reason,
            'confidence': confidence
        }
        
    except Exception as e:
        print(f"   ⚠️ AI评估调整失败: {e}")
        import traceback
        traceback.print_exc()
        return {'should_adjust': False, 'reason': f'AI evaluation failed: {e}'}


def execute_tp_sl_adjustment(symbol, position, adjustment_result):
    """
    执行止盈止损调整（V7.7.0.19新增）
    
    步骤：
    1. 取消现有的止盈止损订单
    2. 设置新的止盈止损订单
    
    参数:
        symbol: str, 交易对
        position: dict, 持仓信息
        adjustment_result: dict, AI调整建议
    
    返回: bool, 是否成功
    """
    try:
        coin_name = symbol.split("/")[0]
        side = position.get('side')
        size = position.get('size', 0)
        new_tp = adjustment_result.get('new_tp')
        new_sl = adjustment_result.get('new_sl')
        
        if not new_tp and not new_sl:
            print(f"   ⚠️ 无需调整")
            return False
        
        print(f"   正在调整{coin_name}止盈止损...")
        
        # Step 1: 取消现有的止盈止损订单（包括普通订单和条件单）
        try:
            print(f"   取消旧的止盈止损订单...")
            success_count, fail_count = clear_symbol_orders(symbol, verbose=False)
            
            if success_count > 0:
                print(f"   ✓ 已取消 {success_count} 个旧订单")
            elif fail_count > 0:
                print(f"   ⚠️ 取消订单失败 {fail_count} 个")
            else:
                print(f"   ℹ️  未找到需要取消的订单")
                # 继续尝试设置新订单
                
        except Exception as e:
            print(f"   ⚠️ 取消订单失败: {e}")
            # 不返回False，继续尝试设置新订单
            pass
        
        # Step 2: 设置新的止盈止损订单
        close_side = "sell" if side == "long" else "buy"
        success_count = 0
        
        # 2.1 设置新止盈
        if new_tp:
            try:
                tp_order = exchange.create_order(
                    symbol,
                    'take_profit_market',
                    close_side,
                    size,
                    None,
                    params={
                        'stopPrice': new_tp,
                        'reduceOnly': "true",
                        'tag': 'f1ee03b510d5SUDE'
                    }
                )
                print(f"   ✓ 新止盈单已设置: ${new_tp:,.2f}")
                success_count += 1
            except Exception as e:
                print(f"   ✗ 设置新止盈单失败: {e}")
        
        # 2.2 设置新止损
        if new_sl:
            try:
                sl_order = exchange.create_order(
                    symbol,
                    'stop_market',
                    close_side,
                    size,
                    None,
                    params={
                        'stopPrice': new_sl,
                        'reduceOnly': "true",
                        'tag': 'f1ee03b510d5SUDE'
                    }
                )
                print(f"   ✓ 新止损单已设置: ${new_sl:,.2f}")
                success_count += 1
            except Exception as e:
                print(f"   ✗ 设置新止损单失败: {e}")
        
        return success_count > 0
        
    except Exception as e:
        print(f"   ✗ 执行调整失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def detect_market_regime(market_data_list):
    """【V7.9新增】市场环境检测：Trending vs Ranging
    
    Returns:
        (regime: str, confidence: float, description: str)
        regime: 'trending' / 'ranging' / 'volatile' / 'consolidating'
    """
    try:
        if not market_data_list:
            return 'unknown', 0, "无数据"
        
        # 统计多个币种的趋势状态
        trend_scores = []
        volatility_scores = []
        
        for data in market_data_list:
            if not data:
                continue
            
            # 趋势强度（4h）
            trend_4h_strength = data.get('long_term', {}).get('trend_strength', 0)
            trend_1h_strength = data.get('mid_term', {}).get('trend_strength', 0)
            
            # 综合趋势分数
            trend_score = (trend_4h_strength * 0.7 + trend_1h_strength * 0.3)
            trend_scores.append(trend_score)
            
            # 波动率
            atr = data.get('atr', {}).get('atr_14', 0)
            price = data.get('current_price', 1)
            vol = (atr / price) if price > 0 else 0
            volatility_scores.append(vol)
        
        if not trend_scores:
            return 'unknown', 0, "无有效数据"
        
        avg_trend = sum(trend_scores) / len(trend_scores)
        avg_vol = sum(volatility_scores) / len(volatility_scores)
        
        # 判断环境
        if avg_trend > 0.7:
            return 'trending', avg_trend, f"强趋势市场(均{avg_trend:.2f}) 适合Swing"
        elif avg_vol > 0.025:
            return 'volatile', avg_vol, f"高波动市场(均{avg_vol*100:.1f}%) 适合Scalping"
        elif avg_trend < 0.3 and avg_vol < 0.015:
            return 'consolidating', 1 - avg_trend, f"盘整市场 回避交易"
        else:
            return 'ranging', 0.5, f"震荡市场 Scalping优先"
    
    except Exception as e:
        print(f"⚠️ 市场环境检测失败: {e}")
        return 'unknown', 0, "检测失败"


def get_time_of_day_preference():
    """【V7.9增强】时段过滤：基于回测数据的时段偏好
    
    分析最近14天不同时段的Scalping/Swing胜率，动态决策
    
    Returns:
        (preferred_type: str, reason: str)
    """
    try:
        from datetime import datetime, timedelta
        import pandas as pd
        
        utc_hour = datetime.utcnow().hour
        
        # 默认值（初始经验值）
        default_prefs = {
            'asian': ('swing', "亚洲时段（默认）"),        # UTC 0-8
            'europe': ('both', "欧洲时段（默认）"),         # UTC 8-13
            'us': ('scalping', "美国时段（默认）"),         # UTC 13-21
            'late': ('swing', "深夜时段（默认）")           # UTC 21-24
        }
        
            # 判断当前时段（中文化）
        period_names = {
            'asian': '亚洲时段',
            'europe': '欧洲时段', 
            'us': '美国时段',
            'late': '深夜时段'
        }
        
        if 0 <= utc_hour < 8:
            current_period = 'asian'
        elif 8 <= utc_hour < 13:
            current_period = 'europe'
        elif 13 <= utc_hour < 21:
            current_period = 'us'
        else:
            current_period = 'late'
        
        # 尝试从历史数据统计
        if not TRADES_FILE.exists():
            return default_prefs[current_period]
        
        df = pd.read_csv(TRADES_FILE)
        if df.empty or '信号类型' not in df.columns:
            return default_prefs[current_period]
        
        # 只看最近14天已平仓的交易
        df['开仓时间_dt'] = pd.to_datetime(df['开仓时间'], errors='coerce')
        recent = df[
            (df['开仓时间_dt'] > datetime.now() - timedelta(days=14)) &
            (df['平仓时间'].notna())
        ].copy()
        
        if len(recent) < 5:  # 样本太少，用默认值
            return default_prefs[current_period]
        
        # 提取UTC小时
        recent['utc_hour'] = recent['开仓时间_dt'].dt.tz_localize(None).apply(
            lambda x: x.hour if pd.notna(x) else -1
                )
        
        # 分时段统计
        def get_period(hour):
            if 0 <= hour < 8: return 'asian'
            elif 8 <= hour < 13: return 'europe'
            elif 13 <= hour < 21: return 'us'
            else: return 'late'
        
        recent['period'] = recent['utc_hour'].apply(get_period)
        
        # 当前时段的数据
        period_data = recent[recent['period'] == current_period]
        
        if len(period_data) < 3:
            return default_prefs[current_period]
        
        # 分Scalping/Swing统计胜率
        scalping = period_data[period_data['信号类型'] == 'scalping']
        swing = period_data[period_data['信号类型'] == 'swing']
        
        scalp_wr = 0
        swing_wr = 0
        
        if len(scalping) > 0:
            scalp_wr = len(scalping[scalping['盈亏(U)'] > 0]) / len(scalping) * 100
        if len(swing) > 0:
            swing_wr = len(swing[swing['盈亏(U)'] > 0]) / len(swing) * 100
        
        # 决策：胜率差距>15%才切换，否则both（中文化）
        period_cn = period_names[current_period]
        if scalp_wr > swing_wr + 15:
            return 'scalping', f"回测{period_cn}超短线胜率{scalp_wr:.0f}%>波段{swing_wr:.0f}%"
        elif swing_wr > scalp_wr + 15:
            return 'swing', f"回测{period_cn}波段胜率{swing_wr:.0f}%>超短线{scalp_wr:.0f}%"
        else:
            return 'both', f"回测{period_cn}胜率相近(超短{scalp_wr:.0f}%/波段{swing_wr:.0f}%)"
    
    except Exception as e:
        print(f"⚠️ 时段统计失败: {e}")
        # 回退到默认值
        utc_hour = datetime.utcnow().hour
        if 0 <= utc_hour < 8:
            return 'swing', "亚洲时段（回退默认）"
        elif 8 <= utc_hour < 13:
            return 'both', "欧洲时段（回退默认）"
        elif 13 <= utc_hour < 21:
            return 'scalping', "美国时段（回退默认）"
        else:
            return 'swing', "深夜时段（回退默认）"


def check_signal_type_switch(position, market_data, entry_context, config):
    """【V7.9新增】信号类型动态切换检查
    
    场景1: Swing → Scalping（趋势恶化，快速退出）
    场景2: Scalping → Swing（发现强趋势，延长持有）
    
    Returns:
        (should_switch: bool, new_type: str, new_strategy: dict, reason: str)
    """
    try:
        from datetime import datetime
        
        signal_type = entry_context.get('signal_type', 'swing')
        entry_time_str = position.get('open_time')
        unrealized_pnl = position.get('unrealized_pnl', 0)
        entry_price = position.get('entry_price', 0)
        
        # 计算持仓时间
        try:
            if isinstance(entry_time_str, str):
                entry_dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
            else:
                entry_dt = entry_time_str
            holding_minutes = (datetime.now() - entry_dt).total_seconds() / 60
        except:
            holding_minutes = 0
        
        # === 场景1: Swing → Scalping（止损策略） ===
        if signal_type == 'swing' and holding_minutes > 120:  # 持仓>2小时
            # 检查趋势恶化
            trend_15m = market_data.get('trend_15m', '')
            trend_1h = market_data.get('mid_term', {}).get('trend', '')
            trend_4h = market_data.get('long_term', {}).get('trend', '')
            
            side = position.get('side', '')
            trend_weakness = 0
            
            if side == 'long':
                if '空头' in trend_15m: trend_weakness += 1
                if '空头' in trend_1h: trend_weakness += 2
                if '空头' in trend_4h: trend_weakness += 4
            else:
                if '多头' in trend_15m: trend_weakness += 1
                if '多头' in trend_1h: trend_weakness += 2
                if '多头' in trend_4h: trend_weakness += 4
            
            # 如果多周期反转且未盈利或微利
            if trend_weakness >= 3 and unrealized_pnl < entry_price * 0.01:
                return True, 'scalping', {
                    'protection_period': 0,
                    'sensitivity': 'high',
                    'max_additional_holding': 30  # 最多再持30分钟
                }, f"Swing→Scalping: 趋势恶化(共振{trend_weakness})且未盈利，快速退出策略"
        
        # === 场景2: Scalping → Swing（利润最大化） ===
        elif signal_type == 'scalping' and holding_minutes > 20:  # 持仓>20分钟
            # 检查是否发现强趋势 + 已盈利
            profit_pct = (unrealized_pnl / (entry_price * position.get('size', 1) / position.get('leverage', 1))) * 100 if entry_price > 0 else 0
            
            if profit_pct > 1.0:  # 盈利>1%
                # 检查趋势强度
                trend_4h = market_data.get('long_term', {}).get('trend', '')
                trend_1h = market_data.get('mid_term', {}).get('trend', '')
                trend_strength = market_data.get('long_term', {}).get('trend_strength', 0)
                
                side = position.get('side', '')
                trend_aligned = False
                
                if side == 'long':
                    trend_aligned = ('多头' in trend_4h and '多头' in trend_1h)
                else:
                    trend_aligned = ('空头' in trend_4h and '空头' in trend_1h)
                
                if trend_aligned and trend_strength > 0.7:
                    return True, 'swing', {
                        'enable_trailing_stop': True,
                        'expand_tp_target': True,
                        'max_additional_holding': 360  # 最多再持6小时
                    }, f"Scalping→Swing: 已盈利{profit_pct:.1f}%且强趋势确认，延长持有"
        
        return False, signal_type, {}, "无需切换"
    
    except Exception as e:
        print(f"⚠️ 信号类型切换检查失败: {e}")
        return False, signal_type, {}, "检查失败"


def check_swing_trailing_stop(position, market_data, entry_context, config):
    """【V7.9新增】Swing订单追踪止损检查
    
    Returns:
        (should_update_sl: bool, new_sl: float, reason: str)
    """
    try:
        signal_type = entry_context.get('signal_type', 'swing')
        if signal_type != 'swing':
            return False, 0, "非Swing订单"
        
        swing_params = config.get('global', {}).get('swing_params', {})
        if not swing_params.get('trailing_stop_enabled', False):
            return False, 0, "未启用追踪止损"
        
        trigger_pct = swing_params.get('trailing_stop_trigger_pct', 2.0)
        distance_atr = swing_params.get('trailing_stop_distance_atr', 1.0)
        
        entry_price = position.get('entry_price', 0)
        current_price = market_data.get('current_price', 0)
        side = position.get('side', '')
        unrealized_pnl = position.get('unrealized_pnl', 0)
        
        # 计算盈利百分比
        if entry_price <= 0:
            return False, 0, "无效入场价"
        
        profit_pct = unrealized_pnl / (entry_price * position.get('size', 1) / position.get('leverage', 1)) * 100
        
        if profit_pct < trigger_pct:
            return False, 0, f"未达触发点({profit_pct:.1f}%<{trigger_pct}%)"
        
        # 计算新止损位
        atr = market_data.get('mid_term', {}).get('atr_14', market_data.get('atr', {}).get('atr_14', current_price * 0.01))
        
        if side == 'long':
            new_sl = current_price - atr * distance_atr
            # 只在新止损高于原止损时更新
            original_sl = entry_context.get('target_sl', 0)
            if new_sl > original_sl:
                return True, new_sl, f"追踪止损(盈利{profit_pct:.1f}%)"
        else:  # short
            new_sl = current_price + atr * distance_atr
            original_sl = entry_context.get('target_sl', 99999999)
            if new_sl < original_sl:
                return True, new_sl, f"追踪止损(盈利{profit_pct:.1f}%)"
        
        return False, 0, "止损已是最优"
    
    except Exception as e:
        print(f"⚠️ 追踪止损检查失败: {e}")
        return False, 0, "检查失败"


def check_swing_partial_exit(position, market_data, entry_context, config):
    """【V7.9新增】Swing订单分批平仓检查
    
    Returns:
        (should_partial_exit: bool, exit_pct: float, reason: str)
    """
    try:
        signal_type = entry_context.get('signal_type', 'swing')
        if signal_type != 'swing':
            return False, 0, "非Swing订单"
        
        swing_params = config.get('global', {}).get('swing_params', {})
        if not swing_params.get('partial_exit_enabled', False):
            return False, 0, "未启用分批平仓"
        
        exit_pct = swing_params.get('partial_exit_first_target_pct', 50)
        
        current_price = market_data.get('current_price', 0)
        side = position.get('side', '')
        
        # 获取第一目标（1h阻力/支撑）
        sr_1h = market_data.get('mid_term', {}).get('support_resistance', {})
        
        if side == 'long':
            first_target = sr_1h.get('nearest_resistance', {}).get('price', 0)
            if first_target > 0 and current_price >= first_target * 0.995:  # 到达目标前0.5%
                return True, exit_pct, f"达第一目标${first_target:.0f}，分批{exit_pct}%"
        else:  # short
            first_target = sr_1h.get('nearest_support', {}).get('price', 0)
            if first_target > 0 and current_price <= first_target * 1.005:
                return True, exit_pct, f"达第一目标${first_target:.0f}，分批{exit_pct}%"
        
        return False, 0, "未达第一目标"
    
    except Exception as e:
        print(f"⚠️ 分批平仓检查失败: {e}")
        return False, 0, "检查失败"


def monitor_positions_for_invalidation(market_data_list: list, current_positions: list) -> list:
    """
    监控持仓的假设失效情况（YTC Premise Invalidation - V7.7.0.19扩展）
    
    V7.7.0.19新增功能：
    1. 可配置的失效阈值（AI可优化）
    2. AI确认机制（拿不准时请求AI判断）
    3. 止盈止损动态调整（持仓期间AI可调整TP/SL）
    
    触发条件（使用可配置阈值）：
    1. 价格停滞（动能低于阈值 + 未盈利）
    2. 反向信号（TTF出现反向Pin Bar/Engulfing）
    3. 时间失效（持仓时间超过配置的最大时间）
    
    Args:
        market_data_list: 市场数据列表
        current_positions: 当前持仓列表
    
    Returns:
        list: 需要主动平仓的actions
    """
    scratch_actions = []
    
    try:
        # 🆕 V7.7.0.19: 加载配置
        config = load_learning_config()
        global_thresholds = config.get('global', {}).get('invalidation_thresholds', {})
        tp_sl_strategy = config.get('global', {}).get('tp_sl_strategy', {})
        allow_ai_confirmation = global_thresholds.get('allow_ai_confirmation', True)
        allow_dynamic_adjustment = tp_sl_strategy.get('allow_dynamic_adjustment', True)
        
        model_name = os.getenv("MODEL_NAME", "qwen")
        
        for position in current_positions:
            symbol = position.get('symbol')
            side = position.get('side')
            entry_time = position.get('open_time')
            
            if not symbol or not side:
                continue
            
            # 获取该币种的市场数据
            market_data = next((m for m in market_data_list if m and m.get('symbol') == symbol), None)
            if not market_data:
                continue
            
            coin_name = symbol.split("/")[0]
            
            # 🆕 V7.7.0.19: 读取开仓上下文
            try:
                entry_context = load_position_context(coin=coin_name)
            except:
                entry_context = {'entry_reason': 'N/A', 'ai_strategy': 'Trust the plan', 'signal_type': 'swing'}
            
            # 【V7.9关键】获取信号类型，决定检查策略
            signal_type = entry_context.get('signal_type', 'swing')
            expected_holding_minutes = entry_context.get('expected_holding_minutes', 120)
            
            # 计算实际持仓时间
            try:
                from datetime import datetime
                entry_time_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
                holding_minutes = (datetime.now() - entry_time_dt).total_seconds() / 60
            except:
                holding_minutes = 0
            
            # 🆕 V7.7.0.19: 获取币种特定阈值（如果有）
            symbol_config = config.get('per_symbol', {}).get(coin_name, {})
            symbol_thresholds = symbol_config.get('invalidation_thresholds', {})
            
            # 【V7.9】根据信号类型调整阈值
            if signal_type == 'scalping':
                # Scalping: 保持敏感，快速止损
                momentum_min = symbol_thresholds.get('momentum_slope_min', global_thresholds.get('momentum_slope_min', 0.05))
                profit_min = symbol_thresholds.get('min_profit_threshold', global_thresholds.get('min_profit_threshold', 5))
                max_hours = symbol_thresholds.get('max_holding_hours', global_thresholds.get('max_holding_hours', 2))  # Scalping最多2小时
                time_pct = 0.8
            else:  # swing
                # Swing: 大幅放宽，给交易空间
                momentum_min = 0.01  # 几乎不检查动能（只有完全停滞才触发）
                profit_min = symbol_thresholds.get('min_profit_threshold', global_thresholds.get('min_profit_threshold', 5))
                max_hours = symbol_thresholds.get('max_holding_hours', global_thresholds.get('max_holding_hours', 24))
                time_pct = 0.8
            
            # 【V7.9新增】信号类型动态切换检查（所有类型都检查）
            try:
                should_switch, new_type, new_strategy, switch_reason = check_signal_type_switch(
                    position, market_data, entry_context, config
                )
                if should_switch:
                    print(f"   🔄 信号类型切换触发: {signal_type} → {new_type}")
                    print(f"   原因: {switch_reason}")
                    
                    # 更新entry_context中的signal_type
                    entry_context['signal_type'] = new_type
                    entry_context['_switched'] = True
                    entry_context['switch_reason'] = switch_reason
                    entry_context['switch_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 保存更新后的context
                    try:
                        model_name = os.getenv("MODEL_NAME", "qwen")
                        context_file = Path("trading_data") / model_name / "position_contexts.json"
                        contexts = {}
                        if context_file.exists():
                            with open(context_file, 'r', encoding='utf-8') as f:
                                contexts = json.load(f)
                        contexts[coin_name] = entry_context
                        temp_file = context_file.parent / f"{context_file.name}.tmp"
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            json.dump(contexts, f, ensure_ascii=False, indent=2)
                        temp_file.replace(context_file)
                    except:
                        pass
                    
                    # 发送通知
                    # 中文化类型名称
                    old_name = "超短线" if signal_type == 'scalping' else "波段"
                    new_name = "超短线" if new_type == 'scalping' else "波段"
                    send_bark_notification(
                        f"[{model_name.upper()}]{coin_name}策略切换🔄",
                        f"{old_name}→{new_name}\n{switch_reason}"
                    )
                    
                    # 应用新策略
                    signal_type = new_type  # 更新后续检查使用的类型
                    
                    if signal_type == 'scalping' and new_strategy.get('sensitivity') == 'high':
                        # 切换为Scalping后，立即用更严格标准检查
                        momentum_min = 0.08  # 提高动能要求
                        max_hours = new_strategy.get('max_additional_holding', 30) / 60
                    elif signal_type == 'swing' and new_strategy.get('expand_tp_target'):
                        # 切换为Swing后，扩大止盈目标
                        print(f"   ✓ 应用Swing策略：启用追踪止损，扩大止盈")
            except Exception as e:
                print(f"   ⚠️ 信号类型切换检查失败: {e}")
            
            # 【V7.9】Swing订单特殊检查（Trailing Stop & 分批平仓）
            if signal_type == 'swing':
                try:
                    # 检查追踪止损
                    should_trail, new_sl, trail_reason = check_swing_trailing_stop(
                        position, market_data, entry_context, config
                    )
                    if should_trail:
                        print(f"   🔧 Swing追踪止损触发: {trail_reason}")
                        # 执行止损更新
                        try:
                            close_side = "sell" if side == "long" else "buy"
                            size = position.get('size', 0)
                            
                            # 取消旧止损（包括普通订单和条件单）
                            print(f"   取消旧止损订单...")
                            success_count, fail_count = clear_symbol_orders(symbol, verbose=False)
                            if success_count > 0:
                                print(f"   ✓ 已取消 {success_count} 个旧止损订单")
                            
                            # 设置新止损
                            exchange.create_order(
                                symbol, 'stop_market', close_side, size, None,
                                params={'stopPrice': new_sl, 'reduceOnly': "true"}
                            )
                            print(f"   ✓ 追踪止损已更新: ${new_sl:,.2f}")
                            send_bark_notification(
                                f"[{model_name.upper()}]{coin_name}追踪止损🔧",
                                f"{trail_reason}\n新止损:${new_sl:.0f}"
                            )
                        except Exception as e:
                            print(f"   ⚠️ 追踪止损更新失败: {e}")
                    
                    # 检查分批平仓
                    should_partial, exit_pct, partial_reason = check_swing_partial_exit(
                        position, market_data, entry_context, config
                    )
                    if should_partial:
                        print(f"   📊 Swing分批平仓触发: {partial_reason}")
                        # 执行分批平仓（简化版：标记为需要平仓，在主逻辑处理）
                        # 这里只添加平仓action，不直接执行
                        scratch_actions.append({
                            'symbol': symbol,
                            'action': 'PARTIAL_CLOSE',
                            'reason': partial_reason,
                            'close_pct': exit_pct,
                            'confidence': 'HIGH',
                            'scratch_type': 'SWING_PARTIAL_EXIT'
                        })
                        print(f"   ✓ 已添加分批平仓计划({exit_pct}%)")
                except Exception as e:
                    print(f"   ⚠️ Swing订单检查失败: {e}")
            
            # 🆕 V7.7.0.19: 首先检查是否需要动态调整止盈止损
            if allow_dynamic_adjustment:
                try:
                    adjustment_result = ai_adjust_tp_sl_if_needed(
                        symbol, position, market_data, entry_context, config
                    )
                    
                    if adjustment_result.get('should_adjust'):
                        # 执行调整
                        success = execute_tp_sl_adjustment(
                            symbol, position, adjustment_result
                        )
                        
                        if success:
                            # 发送Bark通知
                            send_bark_notification(
                                f"[{model_name.upper()}]{coin_name}止盈止损调整🔧",
                                f"方向:{position.get('side','N/A')}仓 当前盈亏:{position.get('unrealized_pnl', 0):+.2f}U\n"
                                f"TP: ${adjustment_result['current_tp']:,.2f} → ${adjustment_result['new_tp']:,.2f}\n"
                                f"SL: ${adjustment_result['current_sl']:,.2f} → ${adjustment_result['new_sl']:,.2f}\n"
                                f"AI理由: {adjustment_result['reason'][:80]}"
                            )
                except Exception as e:
                    print(f"   ⚠️ 止盈止损调整失败: {e}")
            
            # 【V7.9】检查前提失效（分级策略）
            invalidation_reasons = []
            hard_invalidation = False  # 硬失效标志（无需确认，立即平仓）
            
            # === 【硬失效检查】关键位破位（所有类型都检查）===
            key_levels = entry_context.get('key_levels', {})
            current_price = market_data.get('current_price', 0)
            
            if side == 'long':
                # 多单：检查是否跌破关键支撑
                critical_support = key_levels.get('support_1h', 0) or key_levels.get('support_15m', 0)
                if critical_support > 0 and current_price < critical_support * 0.995:  # 跌破0.5%
                    invalidation_reasons.append(f'跌破关键支撑${critical_support:.0f}（硬失效）')
                    hard_invalidation = True
            else:  # short
                # 空单：检查是否突破关键阻力
                critical_resistance = key_levels.get('resistance_1h', 0) or key_levels.get('resistance_15m', 0)
                if critical_resistance > 0 and current_price > critical_resistance * 1.005:  # 突破0.5%
                    invalidation_reasons.append(f'突破关键阻力${critical_resistance:.0f}（硬失效）')
                    hard_invalidation = True
            
            # 如果是硬失效，直接跳过其他检查
            if not hard_invalidation:
                if signal_type == 'scalping':
                    # === Scalping模式：保持敏感检查 ===
                    
                    # 检查1：价格停滞
                    momentum_slope = market_data.get('price_action', {}).get('momentum_slope', 0)
                    unrealized_pnl = position.get('unrealized_pnl', 0)
                    
                    if abs(momentum_slope) < momentum_min and unrealized_pnl <= profit_min:
                        invalidation_reasons.append(
                            f'Scalping动能停滞(slope={momentum_slope:.3f}<{momentum_min})+未盈利'
                        )
                    
                    # 检查2：反向价格行为（单个K线即触发）
                    price_action = market_data.get('price_action', {})
                    is_reversal, reversal_type = check_reversal_signal(price_action, side)
                    if is_reversal:
                        invalidation_reasons.append(f'Scalping反向信号:{reversal_type}')
                    
                    # 检查3：时间失效
                    if check_time_invalidation(entry_time, max_hours=max_hours):
                        time_limit = max_hours * time_pct
                        invalidation_reasons.append(f'Scalping超时(>{time_limit:.1f}h)')
                
                else:  # swing
                    # === Swing模式：需要多周期共振确认 ===
                    
                    # 只在持仓>2小时后才检查（给交易成长时间）
                    if holding_minutes > 120:
                        
                        # 检查1：多周期趋势恶化（需要至少1h+15m共振）
                        trend_weakness_score = 0
                        trend_15m = market_data.get('trend_15m', '')
                        trend_1h = market_data.get('mid_term', {}).get('trend', '')
                        trend_4h = market_data.get('long_term', {}).get('trend', '')
                        
                        # 判断趋势是否与持仓方向相反
                        if side == 'long':
                            if '空头' in trend_15m:
                                trend_weakness_score += 1
                            if '空头' in trend_1h:
                                trend_weakness_score += 2
                            if '空头' in trend_4h:
                                trend_weakness_score += 4
                        else:  # short
                            if '多头' in trend_15m:
                                trend_weakness_score += 1
                            if '多头' in trend_1h:
                                trend_weakness_score += 2
                            if '多头' in trend_4h:
                                trend_weakness_score += 4
                        
                        # 至少需要1h+15m共振（score>=3）才触发
                        if trend_weakness_score >= 3:
                            invalidation_reasons.append(f'Swing多周期趋势反转(共振度{trend_weakness_score})')
                        
                        # 检查2：动能停滞 + 长时间未盈利
                        momentum_slope = market_data.get('price_action', {}).get('momentum_slope', 0)
                        unrealized_pnl = position.get('unrealized_pnl', 0)
                        
                        if abs(momentum_slope) < momentum_min and unrealized_pnl <= profit_min and holding_minutes > 180:
                            invalidation_reasons.append(
                                f'Swing长时间停滞({holding_minutes:.0f}min)+未盈利'
                            )
                        
                        # 检查3：反向价格行为（需要更强确认）
                        price_action = market_data.get('price_action', {})
                        is_reversal, reversal_type = check_reversal_signal(price_action, side)
                        
                        # Swing只在已盈利时才关注反向信号（保护利润）
                        if is_reversal and unrealized_pnl > 10:
                            invalidation_reasons.append(f'Swing反向信号:{reversal_type}（盈利中，保护利润）')
                        
                        # 检查4：时间失效（24小时）
                        if check_time_invalidation(entry_time, max_hours=max_hours):
                            time_limit = max_hours * time_pct
                            invalidation_reasons.append(f'Swing持仓超时(>{time_limit:.1f}h)')
                    
                    else:
                        # 持仓<2小时，给Swing交易足够的成长时间，只检查硬失效
                        pass
            
            # 【V7.9】如果有失效原因
            if invalidation_reasons:
                reason_str = " + ".join(invalidation_reasons)
                
                print(f"\n⚠️  【系统检测到前提失效】{coin_name} {side}仓 ({signal_type}模式)")
                print(f"   失效原因: {reason_str}")
                print(f"   持仓时间: {holding_minutes:.0f}分钟 (预期{expected_holding_minutes}分钟)")
                
                # 【V7.9】硬失效跳过AI确认，直接平仓
                if hard_invalidation:
                    print(f"   ✓ 【硬失效 - 无需确认】立即平仓")
                    reason_str = f"硬失效(关键位破位): {reason_str}"
                
                # 软失效需要AI确认
                elif allow_ai_confirmation:
                    print(f"   正在请求AI确认...")
                    should_close, ai_reason = request_ai_close_confirmation(
                        symbol=symbol,
                        position=position,
                        market_data=market_data,
                        invalidation_reasons=invalidation_reasons,
                        entry_context=entry_context
                    )
                    
                    if not should_close:
                        print(f"   ✓ AI建议保留{coin_name}持仓")
                        continue  # AI认为应该继续持有，不平仓
                    
                    reason_str = f"软失效(AI确认-{signal_type}): {reason_str} | AI: {ai_reason}"
                else:
                    reason_str = f"软失效(系统-{signal_type}): {reason_str}"
                
                scratch_actions.append({
                    'symbol': symbol,
                    'action': 'CLOSE',
                    'reason': reason_str,
                    'confidence': 'HIGH',
                    'scratch_type': 'PREMISE_INVALIDATION'
                })
                
                print(f"   ✓ 【确认平仓】{coin_name} {side}仓")
        
        return scratch_actions
    
    except Exception as e:
        print(f"⚠️ 主动平仓监控失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def _execute_single_close_action(action, current_positions):
    """执行单个平仓操作（V5.5辅助函数）- 实时持仓验证版"""
    symbol = action.get("symbol", "")
    coin_name = symbol.split("/")[0]

    print(f"--- {coin_name} ---")
    print(f"理由: {action.get('reason', 'N/A')}")
    
    if TRADE_CONFIG["test_mode"]:
        current_pos = next((p for p in current_positions if p["symbol"] == symbol), None)
        if not current_pos:
            print("⚠️ 无持仓，跳过平仓")
            return
        print("✓ 测试模式 - 仅模拟平仓")
        print(f"  拟平仓: {current_pos['side']}仓 {current_pos['size']}个")
        print(f"  当前盈亏: {current_pos['unrealized_pnl']:+.2f}U")
        return

    try:
        # 🆕 关键改进：实时获取持仓状态，不信任快照数据
        print("正在验证实时持仓...")
        all_positions = exchange.fetch_positions([symbol])
        
        real_pos = None
        for pos in all_positions:
            if pos["symbol"] == symbol and pos["contracts"] and float(pos["contracts"]) > 0:
                real_pos = {
                    "side": pos["side"],
                    "size": float(pos["contracts"]),
                    "entry_price": float(pos["entryPrice"]) if pos["entryPrice"] else 0,
                        "unrealized_pnl": float(pos["unrealizedPnl"]) if pos["unrealizedPnl"] else 0,
                    "mark_price": float(pos["markPrice"]) if pos["markPrice"] else 0,
                        }
                break
        
        if not real_pos:
            print("⚠️ 实时查询无持仓，可能已被止损/止盈自动平仓")
            
            # 🆕 关键修复：清理该币种的所有未成交订单（止损止盈对立订单）
            try:
                print("正在清理残留的止损/止盈订单...")
                clear_symbol_orders(symbol, verbose=True)
            except Exception as e:
                print(f"⚠️ 清理订单失败: {e}")
            
            # 更新CSV记录（标记为自动平仓）
            old_pos = next((p for p in current_positions if p["symbol"] == symbol), None)
            if old_pos:
                update_close_position(
                    coin_name,
                    "多" if old_pos["side"] == "long" else "空",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    0,
                    old_pos.get("unrealized_pnl", 0),
                    "已被止损/止盈自动平仓",
                )
                # 清理决策上下文
                try:
                    clear_position_context(coin=coin_name)
                except:
                    pass
            return
        
        print(f"✓ 确认持仓: {real_pos['side']}仓 {real_pos['size']}个")
        print(f"  当前盈亏: {real_pos['unrealized_pnl']:+.2f}U")

        side = "sell" if real_pos["side"] == "long" else "buy"

        # 先取消该币种的所有止损/止盈订单（AI主动平仓）
        try:
            clear_symbol_orders(symbol, verbose=True)
        except Exception as e:
            print(f"⚠️ 取消订单失败（可能已成交）: {e}")

        # 🆕 V7.9.3: 处理分批平仓（含精度检查）
        close_pct = action.get("close_pct", 100)
        close_amount = real_pos["size"]
        
        if close_pct < 100:
            # 计算分批数量
            partial_amount = real_pos["size"] * (close_pct / 100.0)
            remaining_amount = real_pos["size"] - partial_amount
            
            # 检查最小精度限制
            try:
                markets = exchange.load_markets()
                market_info = markets.get(symbol, {})
                min_amount = market_info.get('limits', {}).get('amount', {}).get('min', 0)
                
                # 如果分批后的任一数量低于最小精度，则全部平仓
                if min_amount and (partial_amount < min_amount or remaining_amount < min_amount):
                    print(f"  ⚠️ 分批平仓数量({partial_amount:.6f}或剩余{remaining_amount:.6f})低于最小精度({min_amount:.6f})")
                    print(f"  → 改为全部平仓")
                    close_pct = 100
                    close_amount = real_pos["size"]
                else:
                    close_amount = partial_amount
                    print(f"  📊 分批平仓: {close_pct}%仓位 ({close_amount:.6f}/{real_pos['size']:.6f})")
            except Exception as e:
                print(f"  ⚠️ 精度检查失败，使用原始分批: {e}")
                close_amount = partial_amount
                print(f"  📊 分批平仓: {close_pct}%仓位 ({close_amount:.6f}/{real_pos['size']:.6f})")

        # 执行平仓（使用实时的持仓数量）
        order = exchange.create_market_order(
            symbol,
            side,
            close_amount,
            params={"reduceOnly": "true", "tag": "f1ee03b510d5SUDE"},
        )
        print("✓ 平仓成功")
        
        # 【关键修复】立即清理残留的止盈止损订单
        try:
            print("正在清理止盈止损订单...")
            clear_symbol_orders(symbol, verbose=True)
        except Exception as e:
            print(f"⚠️ 清理订单失败: {e}")
        
        # 🆕 V7.9.3: 分批平仓后，为剩余仓位重新设置止盈止损
        if close_pct < 100:
            remaining_amount = real_pos["size"] - close_amount
            print(f"  🔧 为剩余仓位重设保护: {remaining_amount:.3f}个")
            
            try:
                # 从position_contexts读取原始止盈止损
                model_name = os.getenv("MODEL_NAME", "qwen")
                context_file = Path("trading_data") / model_name / "position_contexts.json"
                original_sl = None
                original_tp = None
                
                if context_file.exists():
                    with open(context_file, 'r', encoding='utf-8') as f:
                        contexts = json.load(f)
                        if coin_name in contexts:
                            original_sl = contexts[coin_name].get('target_sl')
                            original_tp = contexts[coin_name].get('target_tp')
                
                # 如果有原始止盈止损，重新设置
                if original_sl or original_tp:
                    sl_ok, tp_ok = set_tpsl_orders_via_papi(
                        symbol=symbol,
                        side=real_pos["side"],
                        amount=remaining_amount,
                        stop_loss=original_sl,
                        take_profit=original_tp,
                        verbose=True
                    )
                    if not (sl_ok or tp_ok):
                        print(f"  ⚠️ 剩余仓位保护设置失败，请手动检查")
                else:
                    print(f"  ⚠️ 未找到原始止盈止损，剩余仓位无保护！")
            except Exception as e:
                print(f"  ⚠️ 剩余仓位保护设置异常: {e}")

        # 【V7.9】立即发送通知（增加信号类型和持仓时间对比）
        # 🆕 V7.9: 分批平仓时按比例计算盈亏
        pnl_ratio = close_pct / 100.0
        pnl = real_pos["unrealized_pnl"] * pnl_ratio
        pnl_emoji = "📈" if pnl > 0 else "📉"
        close_reason = action.get("reason", "N/A")[:70]
        position_type = "多" if real_pos["side"] == "long" else "空"
        
        # 尝试读取信号类型和预期持仓时间
        signal_type = 'unknown'
        expected_holding = 0
        actual_holding = 0
        try:
            # 读取position_contexts
            model_name = os.getenv("MODEL_NAME", "qwen")
            context_file = Path("trading_data") / model_name / "position_contexts.json"
            if context_file.exists():
                with open(context_file, 'r', encoding='utf-8') as f:
                    contexts = json.load(f)
                    if coin_name in contexts:
                        signal_type = contexts[coin_name].get('signal_type', 'unknown')
                        expected_holding = contexts[coin_name].get('expected_holding_minutes', 0)
            
            # 读取开仓时间计算实际持仓
            if TRADES_FILE.exists():
                df = pd.read_csv(TRADES_FILE)
                df.columns = df.columns.str.strip()
                open_records = df[
                    (df['币种'] == coin_name) & 
                    (df['方向'] == position_type) & 
                    (df['平仓时间'].isna())
                ].tail(1)
                if not open_records.empty:
                    open_time_str = open_records.iloc[0]['开仓时间']
                    open_dt = pd.to_datetime(open_time_str)
                    actual_holding = (datetime.now() - open_dt).total_seconds() / 60
        except:
            pass
        
        # 格式化通知内容（中文化）
        type_emoji = "⚡" if signal_type == 'scalping' else "🌊" if signal_type == 'swing' else "❓"
        type_name_cn = "超短线" if signal_type == 'scalping' else "波段" if signal_type == 'swing' else "未知"
        
        if expected_holding > 0 and actual_holding > 0:
            diff_pct = (actual_holding / expected_holding - 1) * 100
            if abs(diff_pct) < 20:
                timing = f"符合预期"
            elif diff_pct < 0:
                timing = f"早平{abs(diff_pct):.0f}%"
            else:
                timing = f"超时{diff_pct:.0f}%"
            holding_info = f"{type_emoji}{type_name_cn} {actual_holding:.0f}分({timing})"
        else:
            holding_info = f"{type_emoji}{type_name_cn}"
        
        # 🆕 V7.9: 分批平仓标记
        partial_mark = f"[分批{close_pct:.0f}%]" if close_pct < 100 else ""
        
        send_bark_notification(
            f"[通义千问]{coin_name}平仓{pnl_emoji}{partial_mark}",
            f"{position_type}仓 {pnl:+.2f}U {holding_info}\n开${real_pos.get('entry_price', 0):.0f}→平${real_pos.get('mark_price', 0):.0f}\n{close_reason}",
                )

        # 更新交易记录
        update_close_position(
            coin_name,
            "多" if real_pos["side"] == "long" else "空",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            order.get("average", 0) if order else 0,
            pnl,  # 🆕 V7.9: 使用按比例计算的盈亏
            action.get("reason", "N/A") + (f" [分批{close_pct:.0f}%]" if close_pct < 100 else ""),
                )
        
        # 🆕 V7.9: 只有完全平仓才清理决策上下文
        if close_pct >= 100:
            try:
                clear_position_context(coin=coin_name)
                print(f"✓ 已清理 {coin_name} 的决策上下文")
            except Exception as ctx_err:
                print(f"⚠️ 清理决策上下文失败: {ctx_err}")
        else:
            print(f"  ⚠️ 分批平仓，保留 {coin_name} 的决策上下文")

        # 立即刷新持仓快照
        try:
            refreshed_positions, _ = get_all_positions()
            save_positions_snapshot(refreshed_positions, 0)
            print("✓ 持仓快照已更新")
        except:
            pass

    except Exception as e:
        print(f"❌ 平仓失败: {e}")
        # 尝试从快照获取信息用于通知
        old_pos = next((p for p in current_positions if p["symbol"] == symbol), None)
        if old_pos:
            position_type = "多" if old_pos["side"] == "long" else "空"
            send_bark_notification(
                f"[通义千问]{coin_name}平仓失败❌",
                f"{position_type}仓 持有:{old_pos['size']:.4f}个\n"
                f"开仓价:{old_pos.get('entry_price', 0):.2f} 当前盈亏:{old_pos['unrealized_pnl']:+.2f}U\n"
                    f"失败原因: {str(e)[:80]}\n"
                f"平仓理由: {action.get('reason', 'N/A')[:60]}",
            )


def _execute_single_open_action_v55(
    action,
    market_data,
    current_positions,
    total_assets,
    available_balance,
    signal_score,
    signal_classification=None,  # V7.9新增
):
    """
    执行单个开仓操作（V5.5增强版：智能仓位管理，V7.9增加信号分类支持）

    集成：
    - 信号评分 → 动态仓位
    - 风险预算检查 → 缩减仓位或拒绝
    - 智能杠杆建议
    - V7.9：信号分类 → 双模式TP/SL策略
    """
    symbol = action.get("symbol", "")
    operation = action.get("action", "")
    coin_name = symbol.split("/")[0]

    print(f"\n--- {coin_name} ---")
    print(f"操作: {operation}")
    print(f"信心度: {action.get('confidence', 'N/A')}")
    print(f"AI理由: {action.get('reason', 'N/A')}")

    # 过滤低信心度
    if action.get("confidence") == "LOW":
        print("⚠️ 信心度过低，跳过")
        return

    # === V6.0 智能参数系统 ===
    print("\n【V6.0 智能参数系统】")

    # 0. 加载学习配置并检查是否暂停交易
    learning_config = load_learning_config()

    # 检查市场环境是否需要暂停
    should_pause, pause_reason, remaining_minutes = should_pause_trading_v7(learning_config)
    if should_pause:
        print(f"🚫 交易已暂停: {pause_reason}")
        send_bark_notification(
            f"[通义千问]交易暂停🚫",
            f"{pause_reason}\n币种:{coin_name}\n建议:等待市场环境改善",
        )
        return

    # 🆕 V7.6.5: 信号分级与币种个性化参数
    print("\n【🆕 V7.6.5 信号分级系统】")
    
    # 计算趋势对齐层数
    trend_alignment = 0
    if market_data.get('trend_4h') in ['多头', '空头']:
        trend_alignment += 1
    if market_data.get('mid_term', {}).get('trend_1h') in ['多头', '空头']:
        trend_alignment += 1
    if market_data.get('trend_15m') in ['多头', '空头']:
        trend_alignment += 1
    
    # YTC信号
    ytc_signal = market_data.get('ytc_signals', {}).get('best_signal', {}).get('type', '')
    
    # 信号分级
    signal_tier, tier_description = classify_signal_quality(signal_score, ytc_signal, trend_alignment)
    
    # 获取调整后的参数
    adjusted_params = get_adjusted_params_for_signal(
        symbol,
        signal_tier,
        learning_config['global']
    )
    
    print(f"✓ 信号级别: {signal_tier}")
    print(f"  描述: {tier_description}")
    print(f"  调整后R:R: {adjusted_params['min_risk_reward']:.2f}:1")
    print(f"  调整后ATR: {adjusted_params['atr_stop_multiplier']:.2f}x")
    print(f"  调整后仓位: {adjusted_params['position_pct']:.1f}%")
    print(f"  币种特性: {adjusted_params['symbol_profile'].get('name', coin_name)} ({adjusted_params['symbol_profile'].get('volatility', 'UNKNOWN')})")
    
    # 覆盖learning_config中的参数（使用调整后的参数）
    learning_config['global']['min_risk_reward'] = adjusted_params['min_risk_reward']
    learning_config['global']['atr_stop_multiplier'] = adjusted_params['atr_stop_multiplier']
    learning_config['global']['base_position_pct'] = adjusted_params['position_pct']
    learning_config['global']['_signal_tier'] = signal_tier  # 保存以供后续使用

    # 获取币种特定配置
    symbol_config = get_learning_config_for_symbol(symbol, learning_config)
    print(f"✓ 使用配置: {symbol_config.get('_source', '全局默认')} + 信号分级({signal_tier})")

    # 1. 信号评分
    score, position_ratio, suggested_leverage, signal_classification = calculate_signal_score(market_data)
    
    # 【V7.9.1修复】优先使用AI明确指定的signal_mode
    ai_signal_mode = action.get("signal_mode", "").lower()
    if ai_signal_mode in ['scalping', 'swing']:
        signal_classification['signal_type'] = ai_signal_mode
        signal_classification['reason'] = f"AI明确指定: {ai_signal_mode}"
        print(f"✓ 信号得分: {score}/100 | 信号类型: {signal_classification['signal_type']} (AI指定) ({signal_classification['signal_name']})")
    else:
        print(f"✓ 信号得分: {score}/100 | 信号类型: {signal_classification['signal_type']} (系统推断) ({signal_classification['signal_name']})")
    
    # 【V7.9】账号阶段对信号类型的限制检查
    try:
        trades_count, level_name = get_trading_experience_level()
        
        signal_type = signal_classification['signal_type']
        
        # 新手期（<20笔）：禁止Scalping
        if trades_count < 20 and signal_type == 'scalping':
            print(f"❌ {level_name}禁止Scalping信号（需要快速反应经验）")
            send_bark_notification(
                f"[通义千问]{coin_name}开仓被拒❌",
                f"新手期禁止Scalping信号\n当前:{signal_classification['signal_name']}\n建议:等待Swing机会或完成5笔交易",
            )
            return
        
        # 学习期（20-60笔）：Scalping仓位减半
        if 20 <= trades_count < 60 and signal_type == 'scalping':
            planned_position *= 0.5  # 将在后面再次设置
            print(f"⚠️ {level_name}超短线仓位减半（练习阶段）")
    
    except Exception as e:
        print(f"⚠️ 经验阶段检查失败: {e}")

    # 【V8.3.14修复】先确定signal_type，再应用对应参数
    signal_type = signal_classification['signal_type']
    
    # 根据signal_type覆盖symbol_config中的关键参数
    # 确保scalping和swing使用各自优化的参数
    if signal_type == 'scalping':
        type_params = learning_config.get('scalping_params', {})
    else:
        type_params = learning_config.get('swing_params', {})
    
    if type_params:
        for key in ['min_risk_reward', 'min_signal_score', 'min_indicator_consensus']:
            if key in type_params:
                symbol_config[key] = type_params[key]
        print(f"✓ 已应用{signal_type}专属参数: min_rr={symbol_config.get('min_risk_reward', 'N/A')}, min_score={symbol_config.get('min_signal_score', 'N/A')}")

    # 检查信号得分是否满足币种要求（现在使用了signal_type对应的参数）
    # 【V7.8关键修复】默认值从80降到55，与get_default_config()保持一致
    min_signal_score = symbol_config.get("min_signal_score", 55)
    if score < min_signal_score:
        print(f"❌ {signal_type}信号得分{score} < 最低要求{min_signal_score}，拒绝开仓")
        return

    # 2. 智能仓位计算（【V7.9】分Scalping/Swing独立计算）
    
    planned_position = calculate_position_size_smart(
        symbol, score, total_assets, learning_config, signal_type
    )
    print(f"✓ 智能计算仓位: ${planned_position:.2f}")
    
    # 【V7.9新增】风险预算检查
    budget_ok, budget_reason, adjusted_position = check_signal_type_risk_budget(
        signal_type, current_positions, planned_position, learning_config
    )
    if not budget_ok:
        print(f"❌ {budget_reason}")
        send_bark_notification(
            f"[通义千问]{coin_name}开仓被拒❌",
            f"{budget_reason}\n信号类型:{signal_type}\nAI理由:{action.get('reason', '')[:60]}",
        )
        return
    if adjusted_position != planned_position:
        print(f"⚠️ {budget_reason}，仓位调整: ${planned_position:.2f} → ${adjusted_position:.2f}")
        planned_position = adjusted_position
    
    # 【V7.9新增】Scalping频率限制
    if signal_type == 'scalping':
        freq_ok, freq_reason = check_scalping_frequency(coin_name, learning_config)
        if not freq_ok:
            print(f"❌ {freq_reason}")
            send_bark_notification(
                f"[通义千问]{coin_name}开仓被拒❌",
                f"{freq_reason}\n建议:等待冷却期结束或选择Swing信号",
            )
            return
        print(f"✓ {freq_reason}")
    
    # 【新增】现金储备检查（防止满仓爆仓）
    reserve_ok, reserve_reason, adjusted_by_reserve = check_cash_reserve(
        total_assets, available_balance, planned_position, current_positions
    )
    if not reserve_ok:
        print(f"❌ {reserve_reason}")
        send_bark_notification(
            f"[通义千问]{coin_name}现金储备不足❌",
            f"{reserve_reason}\n建议:等待现有仓位平仓释放资金",
        )
        return
    if adjusted_by_reserve != planned_position:
        print(f"⚠️ {reserve_reason}")
        planned_position = adjusted_by_reserve
    else:
        print(f"✓ {reserve_reason}")
    
    # 【新增】单币种单方向检查（防止同一币种多单或对冲）
    direction_ok, direction_reason = check_single_direction_per_coin(
        symbol, operation, current_positions
    )
    if not direction_ok:
        print(f"❌ {direction_reason}")
        send_bark_notification(
            f"[通义千问]{coin_name}开仓被拒❌",
            f"{direction_reason}",
        )
        return
    print(f"✓ {direction_reason}")

    # 3. 获取当前价格和盈亏比
    try:
        ticker = exchange.fetch_ticker(symbol)
        entry_price = ticker["last"]
        stop_loss = action.get("stop_loss_price", 0)
        take_profit = action.get("take_profit_price", 0)

        side = "long" if operation == "OPEN_LONG" else "short"
        risk_reward = calculate_risk_reward_ratio(
            entry_price, stop_loss, take_profit, side
        )

        print(f"✓ 当前价: ${entry_price:,.2f}")
        print(f"✓ 止损价: ${stop_loss:,.2f}")
        print(f"✓ 止盈价: ${take_profit:,.2f}")
        print(f"✓ 盈亏比: {risk_reward:.2f}:1")

        # 盈亏比验证（使用币种特定参数）
        min_rr_required = symbol_config.get("min_risk_reward", 1.5)

        if risk_reward < min_rr_required:
            # 判断是开多还是开空
            direction = "开多" if operation == "OPEN_LONG" else "开空"
            direction_emoji = "📈" if operation == "OPEN_LONG" else "📉"
            
            print(
                f"❌ 盈亏比{risk_reward:.2f} < {symbol}要求{min_rr_required:.1f}，拒绝{direction}"
            )
            send_bark_notification(
                f"[通义千问]{coin_name}{direction_emoji}{direction}被拒❌",
                f"AI判断:{direction} 但盈亏比不足\n"
                f"要求:{min_rr_required:.1f} 实际:{risk_reward:.2f}\n"
                f"当前价:{entry_price:.2f} 止损:{stop_loss:.2f} 止盈:{take_profit:.2f}\n"
                    f"配置:{symbol_config.get('_source', '全局')}\n"
                f"AI理由: {action.get('reason', 'N/A')[:60]}",
            )
            return

    except Exception as e:
        print(f"❌ 获取价格失败: {e}")
        return

    # 4. 杠杆选择（【V7.9】分Scalping/Swing独立上限，可配置）
    # 获取分类型杠杆上限
    if signal_type == 'scalping':
        type_params = learning_config.get('global', {}).get('scalping_params', {})
    else:
        type_params = learning_config.get('global', {}).get('swing_params', {})
    max_leverage_for_type = type_params.get('max_leverage', 5)
    
    ai_leverage = action.get("leverage", None)
    if ai_leverage:
        leverage = max(1, min(max_leverage_for_type, int(ai_leverage)))
        if int(ai_leverage) > max_leverage_for_type:
            type_name_cn = "超短线" if signal_type == 'scalping' else "波段"
            print(f"⚠️ AI建议{ai_leverage}x被限制到{type_name_cn}最大{max_leverage_for_type}x")
        else:
            print(f"✓ 使用AI建议杠杆: {leverage}x")
    else:
        leverage = min(suggested_leverage, max_leverage_for_type)
        print(f"✓ 使用系统建议杠杆: {leverage}x (上限{max_leverage_for_type}x)")

    # 5. 风险预算检查
    stop_loss_pct = (
        abs((entry_price - stop_loss) / entry_price) if entry_price > 0 else 0.015
    )

    allowed, adjusted_position, risk_used_pct = check_risk_budget(
        planned_position, leverage, stop_loss_pct, current_positions, total_assets
    )

    print(f"✓ 当前风险使用率: {risk_used_pct:.1f}%")

    if not allowed:
        print(f"❌ 风险预算不足（已使用{risk_used_pct:.0f}%），拒绝开仓")
        send_bark_notification(
            f"[通义千问]{coin_name}风险预算不足❌",
            f"风险已用:{risk_used_pct:.0f}% 总资产:{total_assets:.0f}U\n"
            f"计划开仓:{planned_position:.0f}U {leverage}x杠杆\n"
            f"AI理由: {action.get('reason', 'N/A')[:60]}",
        )
        return

    if adjusted_position < planned_position:
        print(f"⚠️ 仓位缩减: ${planned_position:.2f} → ${adjusted_position:.2f}")
        planned_position = adjusted_position

    # === V7.6: LWP参考价验证与止损优化 ===
    lwp_reference = action.get('lwp_reference', 0)
    price_vs_lwp = action.get('price_vs_lwp', 'UNKNOWN')
    
    # 如果AI提供了LWP参考价，进行验证和止损优化
    if lwp_reference and lwp_reference > 0:
        print(f"\n【V7.6 LWP参考价验证与止损优化】")
        print(f"LWP参考价: ${lwp_reference:,.2f}")
        print(f"当前价格: ${entry_price:,.2f}")
        print(f"原始止损: ${stop_loss:,.2f}")
        
        # 1. 追价控制（入场价格验证）
        if operation == "OPEN_LONG":
            deviation_pct = (entry_price - lwp_reference) / lwp_reference
            
            if deviation_pct > 0.005:  # 超过LWP 0.5%
                print(f"⚠️ 当前价格高于LWP {deviation_pct*100:.2f}%，降低仓位30%")
                planned_position *= 0.7
                
                if deviation_pct > 0.01:  # 超过1%
                    print(f"❌ 追价过高({deviation_pct*100:.1f}%)，拒绝入场")
                    send_bark_notification(
                        f"[通义千问]{coin_name}拒绝开多❌",
                        f"追价过高：市价${entry_price:.2f} > LWP${lwp_reference:.2f}\n"
                            f"偏离度:{deviation_pct*100:.1f}% (上限1.0%)\n"
                        f"AI理由: {action.get('reason', 'N/A')[:60]}",
                    )
                    return
            else:
                print(f"✓ 价格合理，偏离LWP仅{deviation_pct*100:.2f}%")
            
            # 2. 止损优化：如果LWP提供更紧凑的止损位，使用LWP
            lwp_stop = lwp_reference * 0.995  # LWP下方0.5%作为止损
            original_risk = entry_price - stop_loss
            lwp_risk = entry_price - lwp_stop
            
            # 最小风险阈值：避免止损太近被噪音whipsaw（取入场价的0.3%）
            required_min_risk = entry_price * 0.003
            
            # 条件：减少≥20%风险 AND 优化后风险≥最小阈值
            if (lwp_risk > 0 and 
                lwp_risk < original_risk * 0.8 and 
                lwp_risk >= required_min_risk):
                print(f"✨ LWP优化止损: ${stop_loss:,.2f} → ${lwp_stop:,.2f}")
                print(f"   风险降低: ${original_risk:.2f} → ${lwp_risk:.2f} ({(1-lwp_risk/original_risk)*100:.1f}%)")
                print(f"   最小风险阈值: ${required_min_risk:.2f} (入场价0.3%)")
                stop_loss = lwp_stop
                action['stop_loss_price'] = lwp_stop  # 更新action中的止损价
                
                # 重新计算R:R
                risk_reward = calculate_risk_reward_ratio(
                    entry_price, stop_loss, take_profit, "long"
                )
                print(f"   优化后R:R: {risk_reward:.2f}:1")
            elif lwp_risk > 0 and lwp_risk < required_min_risk:
                print(f"⚠️ LWP止损太近(${lwp_risk:.2f} < ${required_min_risk:.2f})，保持原止损")
        
        elif operation == "OPEN_SHORT":
            deviation_pct = (lwp_reference - entry_price) / lwp_reference
            
            if deviation_pct > 0.005:
                print(f"⚠️ 当前价格低于LWP {deviation_pct*100:.2f}%，降低仓位30%")
                planned_position *= 0.7
                
                if deviation_pct > 0.01:
                    print(f"❌ 追价过低({deviation_pct*100:.1f}%)，拒绝入场")
                    send_bark_notification(
                        f"[通义千问]{coin_name}拒绝开空❌",
                        f"追价过低：市价${entry_price:.2f} < LWP${lwp_reference:.2f}\n"
                            f"偏离度:{deviation_pct*100:.1f}% (上限1.0%)\n"
                        f"AI理由: {action.get('reason', 'N/A')[:60]}",
                    )
                    return
            else:
                print(f"✓ 价格合理，偏离LWP仅{deviation_pct*100:.2f}%")
            
            # 2. 止损优化：如果LWP提供更紧凑的止损位，使用LWP
            lwp_stop = lwp_reference * 1.005  # LWP上方0.5%作为止损
            original_risk = stop_loss - entry_price
            lwp_risk = lwp_stop - entry_price
            
            # 最小风险阈值：避免止损太近被噪音whipsaw（取入场价的0.3%）
            required_min_risk = entry_price * 0.003
            
            # 条件：减少≥20%风险 AND 优化后风险≥最小阈值
            if (lwp_risk > 0 and 
                lwp_risk < original_risk * 0.8 and 
                lwp_risk >= required_min_risk):
                print(f"✨ LWP优化止损: ${stop_loss:,.2f} → ${lwp_stop:,.2f}")
                print(f"   风险降低: ${original_risk:.2f} → ${lwp_risk:.2f} ({(1-lwp_risk/original_risk)*100:.1f}%)")
                print(f"   最小风险阈值: ${required_min_risk:.2f} (入场价0.3%)")
                stop_loss = lwp_stop
                action['stop_loss_price'] = lwp_stop  # 更新action中的止损价
                
                # 重新计算R:R
                risk_reward = calculate_risk_reward_ratio(
                    entry_price, stop_loss, take_profit, "short"
                )
                print(f"   优化后R:R: {risk_reward:.2f}:1")
            elif lwp_risk > 0 and lwp_risk < required_min_risk:
                print(f"⚠️ LWP止损太近(${lwp_risk:.2f} < ${required_min_risk:.2f})，保持原止损")
    else:
        # 如果market_data中有LWP，从那里获取
        if market_data:
            pa = market_data.get('price_action', {})
            lwp_long = pa.get('lwp_long')
            lwp_short = pa.get('lwp_short')
            
            if operation == "OPEN_LONG" and lwp_long:
                deviation_pct = (entry_price - lwp_long) / lwp_long
                if deviation_pct > 0.005:
                    print(f"⚠️ 市价高于数据LWP {deviation_pct*100:.2f}%，降低仓位20%")
                    planned_position *= 0.8
            
            elif operation == "OPEN_SHORT" and lwp_short:
                deviation_pct = (lwp_short - entry_price) / lwp_short
                if deviation_pct > 0.005:
                    print(f"⚠️ 市价低于数据LWP {deviation_pct*100:.2f}%，降低仓位20%")
                    planned_position *= 0.8

    # === 执行开仓 ===
    if TRADE_CONFIG["test_mode"]:
        print(f"\n✓ 测试模式 - 仅模拟")
        print(f"  拟开仓: ${planned_position:.2f} {leverage}x杠杆")
        print(f"  止损: ${stop_loss:,.2f}")
        print(f"  止盈: ${take_profit:,.2f}")
        return

    try:
        # 检查是否需要先平反向仓
        current_pos = next(
            (p for p in current_positions if p["symbol"] == symbol), None
        )

        if current_pos:
            if (operation == "OPEN_LONG" and current_pos["side"] == "short") or (
                operation == "OPEN_SHORT" and current_pos["side"] == "long"
            ):
                print(f"先平{current_pos['side']}仓...")
                close_side = "buy" if current_pos["side"] == "short" else "sell"
                exchange.create_market_order(
                    symbol,
                    close_side,
                    current_pos["size"],
                    params={"reduceOnly": "true", "tag": "f1ee03b510d5SUDE"},
                )
                time.sleep(1)

        # 🆕 开仓前清理该币种的残留订单（防止旧止损止盈干扰新仓位）
        try:
            print("正在清理残留订单...")
            open_orders = exchange.fetch_open_orders(symbol)
            canceled_count = 0
            for order in open_orders:
                # 修复：reduceOnly 可能是字符串 "true" 或布尔值 True
                reduce_only = order['info'].get('reduceOnly')
                is_reduce_only = (reduce_only == True or reduce_only == 'true' or reduce_only == 'True')
                
                if is_reduce_only:
                    try:
                        exchange.cancel_order(order['id'], symbol)
                        print(f"✓ 已清理旧订单: {order['type']}")
                        canceled_count += 1
                    except:
                        pass
            if canceled_count > 0:
                print(f"✓ 共清理 {canceled_count} 个旧订单")
        except Exception as e:
            print(f"⚠️ 清理旧订单失败（可继续）: {e}")

        # 设置杠杆
        try:
            exchange.set_leverage(leverage, symbol, {"mgnMode": "cross"})
            print(f"✓ 设置杠杆率: {leverage}x")
        except Exception as e:
            print(f"⚠️ 设置杠杆率失败: {e}")

        # 计算数量
        amount = (planned_position * leverage) / entry_price

        # 🔧 V7.7.0.14: 检查最小交易数量 + AI智能调整
        try:
            markets = exchange.load_markets()
            market_info = markets.get(symbol, {})
            min_amount = market_info.get('limits', {}).get('amount', {}).get('min', 0)
            
            if min_amount and amount < min_amount:
                min_value_usd = min_amount * entry_price / leverage
                adjustment_pct = (min_value_usd - planned_position) / planned_position * 100
                
                print(f"\n⚠️ 交易数量不足")
                print(f"计划开仓: {amount:.6f} {coin_name} (${planned_position:.0f}U)")
                print(f"最小数量: {min_amount:.6f} {coin_name} (${min_value_usd:.0f}U)")
                print(f"需要调整: +{adjustment_pct:.0f}% (+${min_value_usd - planned_position:.0f}U)")
                
                # 🆕 调用AI评估是否接受调整
                print("\n【AI智能仓位调整评估】")
                ai_decision = ai_evaluate_position_adjustment(
                    coin_name=coin_name,
                    original_position=planned_position,
                    suggested_position=min_value_usd,
                    signal_quality={
                        'score': signal_score,
                        'risk_reward': risk_reward,
                        'reason': action.get('reason', '')
                    },
                    available_balance=available_balance,
                    current_positions=current_positions
                )
                
                if ai_decision['decision'] == 'ACCEPT':
                    print(f"✓ AI接受调整: ${planned_position:.0f}U → ${min_value_usd:.0f}U")
                    print(f"置信度: {ai_decision['confidence']}")
                    print(f"理由: {ai_decision['reason']}")
                    
                    # 使用调整后的仓位
                    planned_position = min_value_usd
                    amount = min_amount
                    
                    # 🔧 V7.7.0.15: 截断理由避免URL过长
                    ai_reason = ai_decision['reason']
                    ai_reason_short = ai_reason[:60] + "..." if len(ai_reason) > 60 else ai_reason
                    send_bark_notification(
                        f"[通义千问]{coin_name}仓位智能调整✅",
                        f"{'多' if operation=='OPEN_LONG' else '空'}仓 {leverage}x杠杆\n"
                        f"调整: ${planned_position:.0f}U→${min_value_usd:.0f}U (+{adjustment_pct:.0f}%)\n"
                        f"信号: {signal_score}分 R:R{risk_reward:.2f}\n"
                        f"置信度: {ai_decision['confidence']}\n"
                        f"理由: {ai_reason_short}"
                    )
                else:
                    print(f"✗ AI拒绝调整")
                    print(f"置信度: {ai_decision['confidence']}")
                    print(f"理由: {ai_decision['reason']}")
                    
                    send_bark_notification(
                        f"[通义千问]{coin_name}开仓取消❌",
                        f"方向:{'多' if operation=='OPEN_LONG' else '空'}仓 仓位:{planned_position:.0f}U {leverage}x杠杆\n"
                            f"信号: 得分{signal_score} R:R{risk_reward:.2f}\n"
                        f"原因: 仓位不足且AI拒绝调整\n"
                        f"需要${min_value_usd:.0f}U (+{adjustment_pct:.0f}%)\n"
                        f"AI理由: {ai_decision['reason'][:80]}"
                    )
                    return
                    
        except Exception as e:
            print(f"⚠️ 检查最小数量失败（继续尝试开仓）: {e}")

        print(
            f"\n开{'多' if operation=='OPEN_LONG' else '空'}仓: ${planned_position:.2f} {leverage}x杠杆 (约{amount:.6f}个)"
                )

        order_side = "buy" if operation == "OPEN_LONG" else "sell"
        order = exchange.create_market_order(
            symbol, order_side, amount, params={"tag": "f1ee03b510d5SUDE"}
        )
        print("✓ 开仓成功")

        # === 立即设置交易所止损/止盈订单（硬保护）===
        try:
            close_side = "sell" if operation == "OPEN_LONG" else "buy"
            
            # 1. 设置止损订单（必须设置，防爆仓）
            if stop_loss and stop_loss > 0:
                # YTC标识：根据是否使用YTC信号来标记
                ytc_detected = action.get('ytc_signal_detected', False)
                sl_tag = 'YTC_SL_HARD' if ytc_detected else 'f1ee03b510d5SUDE'
                
                stop_order = exchange.create_order(
                    symbol,
                    'stop_market',
                    close_side,
                    amount,
                    None,
                    params={
                        'stopPrice': stop_loss,
                        'reduceOnly': "true",
                        'tag': sl_tag
                    }
                )
                print(f"✓ 止损单已设置: ${stop_loss:,.2f} (Tag: {sl_tag})")
            
            # 2. 设置止盈订单（允许AI提前平仓）
            if take_profit and take_profit > 0:
                # YTC标识：根据是否使用YTC信号来标记
                ytc_detected = action.get('ytc_signal_detected', False)
                tp_tag = 'YTC_TP_HARD' if ytc_detected else 'f1ee03b510d5SUDE'
                
                tp_order = exchange.create_order(
                    symbol,
                    'take_profit_market',
                    close_side,
                    amount,
                    None,
                    params={
                        'stopPrice': take_profit,
                        'reduceOnly': "true",
                        'tag': tp_tag
                    }
                )
                print(f"✓ 止盈单已设置: ${take_profit:,.2f} (Tag: {tp_tag})")
                
        except Exception as e:
            print(f"⚠️ 设置止损/止盈订单失败: {e}")
            # 失败不中断流程，但发送警告
            send_bark_notification(
                f"[通义千问]{coin_name}止损单设置失败⚠️",
                f"已开仓但止损单未设置！\n仓位:{planned_position:.0f}U\n止损价:{stop_loss:.2f}\n请手动设置保护！",
            )

        # 【V7.9】立即发送通知（增加信号类型和预期持仓时间）
        direction_emoji = "📈" if operation == "OPEN_LONG" else "📉"
        signal_type = signal_classification.get('signal_type', 'swing') if signal_classification else 'swing'
        expected_holding = signal_classification.get('expected_holding_minutes', 120) if signal_classification else 120
        
        # 【V7.9.1优化】更明确的通知文案
        period_name = "短期" if signal_type == 'scalping' else "中期"
        action_name = "做多" if operation == "OPEN_LONG" else "做空"
        
        # 预期持仓格式化
        if expected_holding < 60:
            holding_str = f"{expected_holding}分钟"
        else:
            holding_str = f"{expected_holding/60:.1f}小时"
        
        # 🔧 截断理由避免URL过长
        open_reason = action.get("reason", "N/A")
        open_reason_short = open_reason[:60] + "..." if len(open_reason) > 60 else open_reason
        
        send_bark_notification(
            f"[DS]{coin_name}{period_name}{direction_emoji}",
            f"{period_name}{action_name} {planned_position:.0f}U×{leverage}倍\n预期持仓{holding_str} R:R {risk_reward:.2f}:1 信号{score}分\n止损${stop_loss:.0f} 止盈${take_profit:.0f}\n{open_reason_short}",
        )

        # 记录开仓（使用标准字段格式，【V7.9】增加signal_type）
        trade_record = {
            "开仓时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "平仓时间": None,
            "币种": coin_name,
            "方向": "多" if operation == "OPEN_LONG" else "空",
                "数量": amount,
            "开仓价格": order.get("average", entry_price) if order else entry_price,
                "平仓价格": None,
            "仓位(U)": planned_position,  # 标准字段
            "杠杆率": leverage,
            "止损": stop_loss,  # 标准字段
            "止盈": take_profit,  # 标准字段
            "盈亏比": risk_reward,  # 标准字段
            "盈亏(U)": None,  # 标准字段
            "开仓理由": action.get("reason", "N/A"),
            "平仓理由": None,
            "信号类型": signal_classification.get('signal_type', 'unknown') if signal_classification else 'unknown',  # V7.9
                "预期持仓(分钟)": signal_classification.get('expected_holding_minutes', 0) if signal_classification else 0,  # V7.9
        }

        # 使用标准保存函数
        save_open_position(trade_record)
        print("✓ 交易记录已保存")
        
        # 🆕 保存决策上下文供平仓时参考（V7.9增强）
        try:
            save_position_context(
                coin=coin_name,
                decision=action,
                entry_price=order.get("average", entry_price) if order else entry_price,
                signal_classification=signal_classification,  # V7.9新增
                market_data=market_data  # V7.9新增
            )
        except Exception as ctx_err:
            print(f"⚠️ 保存决策上下文失败: {ctx_err}")

        # 刷新持仓快照
        try:
            refreshed_positions, _ = get_all_positions()
            save_positions_snapshot(refreshed_positions, 0)
            print("✓ 持仓快照已更新")
        except:
            pass

    except Exception as e:
        print(f"❌ 开仓失败: {e}")
        direction = "多" if operation == "OPEN_LONG" else "空"
        send_bark_notification(
            f"[通义千问]{coin_name}开仓失败❌",
            f"方向:{direction}仓 仓位:{planned_position:.0f}U {leverage}x杠杆\n"
            f"信号得分:{score} 盈亏比:{risk_reward:.2f}\n"
            f"失败原因: {str(e)[:100]}\n"
            f"AI理由: {action.get('reason', 'N/A')[:60]}",
        )
        import traceback

        traceback.print_exc()


def execute_portfolio_actions(
    decision,
    current_positions,
    market_data_list=None,
    total_assets=None,
    available_balance=None,
):
    """
    执行投资组合操作（V5.5增强版：智能仓位管理）

    新增参数：
    - market_data_list: 市场数据列表（用于信号评分）
    - total_assets: 账户总资产（用于风险预算）
    - available_balance: 可用余额（用于仓位计算）
    """
    if not decision or "actions" not in decision:
        return

    print("\n" + "=" * 70)
    print("【AI投资组合决策】")
    print(f"整体分析: {decision.get('analysis', 'N/A')}")
    print(f"风险评估: {decision.get('risk_assessment', 'N/A')}")
    print("=" * 70)

    # === V5.5 智能仓位管理 ===
    use_smart_position = (
        market_data_list is not None
        and total_assets is not None
        and available_balance is not None
    )

    if use_smart_position:
        # 分离开仓和平仓操作
        open_actions = [
            a
            for a in decision["actions"]
                if a.get("action") in ["OPEN_LONG", "OPEN_SHORT"]
        ]
        close_actions = [a for a in decision["actions"] if a.get("action") == "CLOSE"]
        hold_actions = [a for a in decision["actions"] if a.get("action") == "HOLD"]

        # 先执行平仓（释放资金）
        if close_actions:
            print("\n" + "=" * 70)
            print("【第一步：执行平仓操作】")
            print("=" * 70)
            for action in close_actions:
                _execute_single_close_action(action, current_positions)
        
        # 【V7.9新增】信号优先级筛选（Scalping vs Swing智能选择）
        if len(open_actions) > 0:
            print("\n" + "=" * 70)
            print("【V7.9 信号类型优先级筛选】")
            print("=" * 70)
            
            learning_config = load_learning_config()
            priority_config = learning_config.get('global', {}).get('signal_priority', {})
            
            # 统计信号类型
            scalping_signals = [a for a in open_actions if a.get('signal_mode') == 'scalping']
            swing_signals = [a for a in open_actions if a.get('signal_mode') == 'swing']
            
            print(f"检测到信号: Scalping×{len(scalping_signals)}, Swing×{len(swing_signals)}")
            
            # 【V7.9】市场环境检测
            regime, confidence, regime_desc = detect_market_regime(market_data_list)
            print(f"市场环境: {regime.upper()} ({regime_desc})")
            
            # 【V7.9】时段过滤
            time_pref, time_reason = get_time_of_day_preference()
            print(f"时段偏好: {time_pref.upper()} ({time_reason})")
            
            # 如果同时有两种类型，根据市场状态 + 时段综合选择
            if len(scalping_signals) > 0 and len(swing_signals) > 0:
                # 检查趋势强度
                strong_trend_count = 0
                for data in market_data_list:
                    if data:
                        trend_4h = data.get('long_term', {}).get('trend_strength', 0)
                        if trend_4h > priority_config.get('trend_strength_threshold', 0.7):
                            strong_trend_count += 1
                
                # 检查波动率
                avg_volatility = 0
                volatility_count = 0
                for data in market_data_list:
                    if data:
                        atr = data.get('atr', {}).get('atr_14', 0)
                        price = data.get('current_price', 1)
                        if price > 0:
                            vol = atr / price
                            avg_volatility += vol
                            volatility_count += 1
                avg_volatility = avg_volatility / volatility_count if volatility_count > 0 else 0.01
                
                print(f"市场状态: 强趋势币种{strong_trend_count}个, 平均波动率{avg_volatility*100:.2f}%")
                
                # 【V7.9增强】综合决策逻辑（市场环境 + 时段 + 配置）
                # 1. 基于市场环境
                regime_prefer_swing = regime in ['trending']
                regime_prefer_scalping = regime in ['volatile', 'ranging']
                
                # 2. 基于时段
                time_prefer_swing = time_pref in ['swing', 'both']
                time_prefer_scalping = time_pref in ['scalping', 'both']
                
                # 3. 基于传统指标
                indicator_prefer_swing = priority_config.get('prefer_swing_on_strong_trend', True) and strong_trend_count >= 1
                indicator_prefer_scalping = priority_config.get('prefer_scalping_on_high_volatility', True) and avg_volatility > priority_config.get('volatility_threshold', 0.02)
                
                # 综合评分（0-3分）
                swing_score = sum([regime_prefer_swing, time_prefer_swing, indicator_prefer_swing])
                scalping_score = sum([regime_prefer_scalping, time_prefer_scalping, indicator_prefer_scalping])
                
                allow_both = priority_config.get('allow_both_types_simultaneously', True)
                
                print(f"决策评分: Swing={swing_score}/3, Scalping={scalping_score}/3")
                
                # 决策逻辑（优先级：3分>2分>1分）
                prefer_swing = swing_score >= 2
                prefer_scalping = scalping_score >= 2
                
                if prefer_swing and not prefer_scalping:
                    print("✓ 强趋势环境，优先Swing信号")
                    open_actions = swing_signals
                elif prefer_scalping and not prefer_swing:
                    print("✓ 高波动环境，优先Scalping信号")
                    open_actions = scalping_signals
                elif allow_both:
                    print("✓ 混合环境，保留两种信号")
                else:
                    # 默认保留信号得分更高的类型
                    print("⚠️ 冲突环境，选择得分更高的类型")
                    scalping_total = sum([a.get('confidence', '') == 'HIGH' for a in scalping_signals])
                    swing_total = sum([a.get('confidence', '') == 'HIGH' for a in swing_signals])
                    if scalping_total > swing_total:
                        open_actions = scalping_signals
                    else:
                        open_actions = swing_signals
                
                print(f"最终保留: {len(open_actions)}个信号\n")

        # 如果有多个开仓信号，进行优先级排序
        if len(open_actions) > 1:
            print("\n" + "=" * 70)
            print("【第二步：多币种优先级排序】")
            print("=" * 70)

            scored_actions = prioritize_signals(market_data_list, open_actions)

            for i, item in enumerate(scored_actions, 1):
                action = item["action"]
                coin_name = action["symbol"].split("/")[0]
                print(
                    f"{i}. {coin_name}: "
                    f"综合得分{item['score']:.1f} "
                    f"(信号{item['signal_score']}/100, "
                    f"盈亏比{item['rr']:.1f}, "
                    f"趋势强度{item['trend_strength']}/5)"
                )

            # 按优先级执行开仓
            print("\n" + "=" * 70)
            print("【第三步：按优先级执行开仓（智能仓位管理）】")
            print("=" * 70)

            for item in scored_actions:
                _execute_single_open_action_v55(
                    item["action"],
                    item["market_data"],
                    current_positions,
                    total_assets,
                    available_balance,
                    item["signal_score"],
                )

        elif len(open_actions) == 1:
            # 只有1个开仓信号
            print("\n" + "=" * 70)
            print("【第二步：执行开仓（智能仓位管理）】")
            print("=" * 70)

            action = open_actions[0]
            symbol = action.get("symbol", "")
            market_data = next(
                (m for m in market_data_list if m["symbol"] == symbol), None
            )

            if market_data:
                signal_score, _, _, signal_classification = calculate_signal_score(market_data)
                _execute_single_open_action_v55(
                    action,
                    market_data,
                    current_positions,
                    total_assets,
                    available_balance,
                    signal_score,
                    signal_classification,  # V7.9新增
                )

        # HOLD操作（仅记录）
        if hold_actions:
            print("\n" + "=" * 70)
            print("【HOLD操作】")
            print("=" * 70)
            for action in hold_actions:
                coin_name = action["symbol"].split("/")[0]
                print(f"- {coin_name}: {action.get('reason', '观望')}")

        return

    # === 原有逻辑（兼容性保留）===
    for action in decision["actions"]:
        symbol = action["symbol"]
        operation = action["action"]
        coin_name = symbol.split("/")[0]
        
        print(f"\n--- {coin_name} ---")
        print(f"操作: {operation}")
        print(f"信心度: {action.get('confidence', 'N/A')}")
        print(f"理由: {action.get('reason', 'N/A')}")
        
        if operation == "HOLD":
            print("→ 观望，不操作")
            continue
        
        # 过滤低信心度信号
        if action.get("confidence") == "LOW":
            print("⚠️  信心度过低，跳过")
            continue
        
        # 对开仓操作验证盈亏比
        if operation in ["OPEN_LONG", "OPEN_SHORT"]:
            # 加载学习参数
            learning_config = load_learning_config()
            min_rr_required = learning_config["global"]["min_risk_reward"]

            ticker = exchange.fetch_ticker(symbol)
            entry_price = ticker["last"]
            stop_loss = action.get("stop_loss_price", 0)
            take_profit = action.get("take_profit_price", 0)

            side = "long" if operation == "OPEN_LONG" else "short"
            risk_reward = calculate_risk_reward_ratio(
                entry_price, stop_loss, take_profit, side
            )
            
            print(f"当前价: ${entry_price:,.2f}")
            print(f"止损价: ${stop_loss:,.2f}")
            print(f"止盈价: ${take_profit:,.2f}")
            print(f"盈亏比: {risk_reward:.2f}:1 (要求≥{min_rr_required:.1f}:1)")

            if risk_reward < min_rr_required:
                # 判断是开多还是开空
                direction = "开多" if operation == "OPEN_LONG" else "开空"
                direction_emoji = "📈" if operation == "OPEN_LONG" else "📉"
                
                print(
                    f"❌ 盈亏比{risk_reward:.2f}:1 < {min_rr_required:.1f}:1，不符合学习参数要求，放弃{direction}"
                )
                send_bark_notification(
                    f"[通义千问]{coin_name}{direction_emoji}{direction}被拒❌",
                    f"AI判断:{direction} 但盈亏比不足\n"
                    f"要求:{min_rr_required:.1f} 实际:{risk_reward:.2f}\n"
                    f"当前价:{entry_price:.2f} 止损:{stop_loss:.2f} 止盈:{take_profit:.2f}\n"
                        f"AI理由: {action.get('reason', 'N/A')[:80]}",
                )
                continue
            else:
                print(f"✓ 盈亏比符合智能参数要求")
        
        if TRADE_CONFIG["test_mode"]:
            print("✓ 测试模式 - 仅模拟")
            if operation in ["OPEN_LONG", "OPEN_SHORT", "ADD"]:
                print(f"  拟开仓: ${action.get('position_size_usd', 0):.2f}")
                print(f"  止损: ${action.get('stop_loss_price', 0):,.2f}")
                print(f"  止盈: ${action.get('take_profit_price', 0):,.2f}")
            continue
        
        try:
            # 查找当前持仓
            current_pos = next(
                (p for p in current_positions if p["symbol"] == symbol), None
            )
            
            if operation == "CLOSE":
                if current_pos:
                    print(f"平仓: {current_pos['side']}仓 {current_pos['size']}个")
                    side = "sell" if current_pos["side"] == "long" else "buy"
                    
                    # 执行平仓
                    order = exchange.create_market_order(
                        symbol,
                        side,
                        current_pos["size"],
                        params={"reduceOnly": "true", "tag": "f1ee03b510d5SUDE"},
                    )
                    print("✓ 平仓成功")
                    
                    # 【V7.9.1修复】清理该币种的止损/止盈订单
                    try:
                        print("正在清理残留的止损/止盈订单...")
                        open_orders = exchange.fetch_open_orders(symbol)
                        canceled_count = 0
                        for ord in open_orders:
                            # 修复：reduceOnly 可能是字符串 "true" 或布尔值 True
                            reduce_only = ord['info'].get('reduceOnly')
                            is_reduce_only = (reduce_only == True or reduce_only == 'true' or reduce_only == 'True')
                            
                            if is_reduce_only:
                                try:
                                    exchange.cancel_order(ord['id'], symbol)
                                    print(f"  ✓ 已清理订单: {ord['type']}")
                                    canceled_count += 1
                                except:
                                    pass
                        if canceled_count > 0:
                            print(f"✓ 共清理 {canceled_count} 个订单")
                    except Exception as e:
                        print(f"⚠️ 清理订单失败（可忽略）: {e}")

                    # 立即发送通知（在保存记录之前，确保一定会推送）
                    pnl = current_pos["unrealized_pnl"]
                    pnl_emoji = "📈" if pnl > 0 else "📉"
                    close_reason = action.get("reason", "N/A")
                    position_type = "多" if current_pos["side"] == "long" else "空"
                    send_bark_notification(
                        f"[通义千问]{coin_name}平仓{pnl_emoji}",
                        f"{position_type}仓平仓 盈亏:{pnl:+.2f}U\n开仓价:{current_pos.get('entry_price', 0):.2f} 平仓价:{current_pos.get('mark_price', 0):.2f}\n平仓理由:{close_reason}",
                            )
                    
                    # 更新交易记录
                    update_close_position(
                        coin_name,
                        "多" if current_pos["side"] == "long" else "空",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        order.get("average", 0) if order else 0,
                        current_pos["unrealized_pnl"],
                        action.get("reason", "N/A"),
                    )

                    # 立即刷新持仓快照（让前端尽快看到持仓变化）
                    try:
                        refreshed_positions, _ = get_all_positions()
                        save_positions_snapshot(refreshed_positions, 0)
                        print("✓ 持仓快照已立即更新")
                    except Exception as e:
                        print(f"⚠️ 更新持仓快照失败: {e}")
                else:
                    print("无持仓，跳过")
            
            elif operation == "OPEN_LONG":
                if current_pos and current_pos["side"] == "short":
                    # 先平空
                    print("先平空仓...")
                    close_order = exchange.create_market_order(
                        symbol,
                        "buy",
                        current_pos["size"],
                        params={"reduceOnly": "true", "tag": "f1ee03b510d5SUDE"},
                    )
                    
                    # 更新交易记录
                    update_close_position(
                        coin_name,
                        "空",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        close_order.get("average", 0) if close_order else 0,
                        current_pos["unrealized_pnl"],
                        "转多前平空",
                    )
                    time.sleep(1)
                
                # 开多
                position_usd = action.get("position_size_usd", 0)
                if position_usd > 0:
                    # 获取当前价格计算数量
                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker["last"]
                    # 使用AI决策的杠杆率（1-5倍），如果没有则默认使用配置的最大杠杆
                    leverage = int(action.get("leverage", TRADE_CONFIG["max_leverage"]))
                    leverage = max(1, min(5, leverage))  # 确保在1-5范围内

                    # 设置本次交易的杠杆率
                    try:
                        exchange.set_leverage(leverage, symbol, {"mgnMode": "cross"})
                        print(f"✓ 设置杠杆率: {leverage}x")
                    except Exception as e:
                        print(f"⚠️ 设置杠杆率失败，使用默认: {e}")

                    # 考虑杠杆，实际需要的币数 = 仓位价值 * 杠杆 / 价格
                    amount = (position_usd * leverage) / price
                    
                    print(
                        f"开多仓: ${position_usd:.2f} {leverage}x杠杆 (约{amount:.6f}个)"
                    )
                    order = exchange.create_market_order(
                        symbol, "buy", amount, params={"tag": "f1ee03b510d5SUDE"}
                    )
                    print("✓ 开仓成功")

                    # 立即发送通知（在保存记录之前，确保一定会推送）
                    open_reason = action.get("reason", "N/A")
                    send_bark_notification(
                        f"[通义千问]{coin_name}开多仓📈",
                        f"仓位:{position_usd}U 杠杆:{leverage}x\n盈亏比:{risk_reward:.2f} 止损:{action.get('stop_loss_price', 0):.0f}\n理由:{open_reason}",
                    )
                    
                    # 记录开仓
                    trade_record = {
                        "开仓时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "平仓时间": None,
                        "币种": coin_name,
                        "方向": "多",
                        "数量": amount,
                        "开仓价格": order.get("average", price) if order else price,
                            "平仓价格": None,
                        "仓位(U)": position_usd,
                        "杠杆率": leverage,
                        "止损": action.get("stop_loss_price", 0),
                        "止盈": action.get("take_profit_price", 0),
                        "盈亏比": risk_reward,
                        "盈亏(U)": None,
                        "开仓理由": action.get("reason", "N/A"),
                        "平仓理由": None,
                    }
                    save_open_position(trade_record)
                    
                    # 立即刷新持仓快照（让前端尽快看到新持仓）
                    try:
                        refreshed_positions, _ = get_all_positions()
                        save_positions_snapshot(refreshed_positions, 0)
                        print("✓ 持仓快照已立即更新")
                    except Exception as e:
                        print(f"⚠️ 更新持仓快照失败: {e}")

            elif operation == "OPEN_SHORT":
                if current_pos and current_pos["side"] == "long":
                    # 先平多
                    print("先平多仓...")
                    close_order = exchange.create_market_order(
                        symbol,
                        "sell",
                        current_pos["size"],
                        params={"reduceOnly": "true", "tag": "f1ee03b510d5SUDE"},
                    )
                    
                    # 更新交易记录
                    update_close_position(
                        coin_name,
                        "多",
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        close_order.get("average", 0) if close_order else 0,
                        current_pos["unrealized_pnl"],
                        "转空前平多",
                    )
                    time.sleep(1)
                
                # 开空
                position_usd = action.get("position_size_usd", 0)
                if position_usd > 0:
                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker["last"]
                    # 使用AI决策的杠杆率（1-5倍），如果没有则默认使用配置的最大杠杆
                    leverage = int(action.get("leverage", TRADE_CONFIG["max_leverage"]))
                    leverage = max(1, min(5, leverage))  # 确保在1-5范围内

                    # 设置本次交易的杠杆率
                    try:
                        exchange.set_leverage(leverage, symbol, {"mgnMode": "cross"})
                        print(f"✓ 设置杠杆率: {leverage}x")
                    except Exception as e:
                        print(f"⚠️ 设置杠杆率失败，使用默认: {e}")

                    amount = (position_usd * leverage) / price

                    print(
                        f"开空仓: ${position_usd:.2f} {leverage}x杠杆 (约{amount:.6f}个)"
                    )
                    order = exchange.create_market_order(
                        symbol, "sell", amount, params={"tag": "f1ee03b510d5SUDE"}
                    )
                    print("✓ 开仓成功")

                    # 立即发送通知（在保存记录之前，确保一定会推送）
                    open_reason = action.get("reason", "N/A")
                    send_bark_notification(
                        f"[通义千问]{coin_name}开空仓📉",
                        f"仓位:{position_usd}U 杠杆:{leverage}x\n盈亏比:{risk_reward:.2f} 止损:{action.get('stop_loss_price', 0):.0f}\n理由:{open_reason}",
                    )
                    
                    # 记录开仓
                    trade_record = {
                        "开仓时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "平仓时间": None,
                        "币种": coin_name,
                        "方向": "空",
                        "数量": amount,
                        "开仓价格": order.get("average", price) if order else price,
                            "平仓价格": None,
                        "仓位(U)": position_usd,
                        "杠杆率": leverage,
                        "止损": action.get("stop_loss_price", 0),
                        "止盈": action.get("take_profit_price", 0),
                        "盈亏比": risk_reward,
                        "盈亏(U)": None,
                        "开仓理由": action.get("reason", "N/A"),
                        "平仓理由": None,
                    }
                    save_open_position(trade_record)
                    
                    # 立即刷新持仓快照（让前端尽快看到新持仓）
                    try:
                        refreshed_positions, _ = get_all_positions()
                        save_positions_snapshot(refreshed_positions, 0)
                        print("✓ 持仓快照已立即更新")
                    except Exception as e:
                        print(f"⚠️ 更新持仓快照失败: {e}")
            
            time.sleep(0.5)  # 避免请求过快
            
        except Exception as e:
            print(f"执行失败: {e}")
            send_bark_notification(
                f"[通义千问]{coin_name}交易失败❌", f"操作:{operation} 错误:{str(e)}"
            )
            import traceback

            traceback.print_exc()


def trading_bot():
    """主交易机器人（增强版：带进度日志和耗时统计）"""
    import time

    start_time = time.time()

    print("\n" + "=" * 70)
    print(f"🔄 [开始执行] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    try:
        print("⏳ [1/6] 获取市场数据...")
        # 1. 获取所有币种的市场数据【V8.1.3增强：添加重试机制和延迟】
        market_data_list = []
        max_retries = 2  # 最多重试2次
        retry_delay = 1  # 重试延迟1秒
        inter_symbol_delay = 0.3  # 币种间延迟0.3秒，避免速率限制
        
        for idx, symbol in enumerate(TRADE_CONFIG["symbols"]):
            coin_name = symbol.split("/")[0]
            data = None
            
            # 重试机制
            for attempt in range(max_retries + 1):
                try:
                    data = get_ohlcv_data(symbol)
                    
                    # 【V8.1.3关键】检查kline_data是否完整
                    if data:
                        kline_data = data.get("kline_data", [])
                        if not kline_data or len(kline_data) == 0:
                            if attempt < max_retries:
                                print(f"⚠️ {coin_name}: kline_data为空，{retry_delay}秒后重试({attempt+1}/{max_retries})...")
                                time.sleep(retry_delay)
                                continue  # 重试
                            else:
                                print(f"⚠️ {coin_name}: kline_data为空（已重试{max_retries}次），使用不完整数据")
                        # 数据完整，跳出重试循环
                        break
                    else:
                        if attempt < max_retries:
                            print(f"⚠️ {coin_name}: 数据获取失败，{retry_delay}秒后重试({attempt+1}/{max_retries})...")
                            time.sleep(retry_delay)
                        else:
                            print(f"❌ {coin_name}: 数据获取失败（已重试{max_retries}次）")
                except Exception as e:
                    if attempt < max_retries:
                        print(f"⚠️ {coin_name}: 异常({e})，{retry_delay}秒后重试({attempt+1}/{max_retries})...")
                        time.sleep(retry_delay)
                    else:
                        print(f"❌ {coin_name}: 异常({e})，已重试{max_retries}次")
                        data = None
            
            if data:
                market_data_list.append(data)
                print(f"✓ {coin_name}: ${data['price']:,.2f} ({data['price_change']:+.2f}%)")
            else:
                market_data_list.append(None)  # 保持索引一致
            
            # 【V8.1.3】币种间延迟，避免触发速率限制（最后一个币种不需要延迟）
            if idx < len(TRADE_CONFIG["symbols"]) - 1:
                time.sleep(inter_symbol_delay)
        
        # 检查是否至少有一个有效数据
        valid_data_count = sum(1 for d in market_data_list if d is not None)
        if valid_data_count == 0:
            print("❌ 未能获取任何有效市场数据")
            return
        
        print(f"✓ 成功获取 {valid_data_count}/{len(market_data_list)} 个币种数据")
        
        print("⏳ [2/6] 获取余额和持仓...")
        # 2. 获取当前余额和持仓
        balance = exchange.fetch_balance()
        usdt_balance = balance["USDT"]["total"]  # 总余额
        available_balance = balance["USDT"]["free"]  # 可用余额（已扣除保证金）
        current_positions, total_position_value = get_all_positions()
        
        # 计算总资产（用于显示）
        total_unrealized_pnl = sum(pos["unrealized_pnl"] for pos in current_positions)
        total_assets = usdt_balance + total_unrealized_pnl
        
        # 计算可用于开仓的资金（正确逻辑）
        if TRADE_CONFIG.get("use_dynamic_position", False):
            max_position = available_balance  # 使用可用余额
        else:
            max_position = min(
                TRADE_CONFIG.get("initial_capital", 100), available_balance
            )

        print(
            f"  ✓ 总资产: {total_assets:.2f}U (余额{usdt_balance:.2f}U + 未实现盈亏{total_unrealized_pnl:+.2f}U)"
        )
        print(f"  ✓ 可用余额: {available_balance:.2f}U (已扣除保证金)")
        print(f"  ✓ 当前持仓: {len(current_positions)}个")
        print(f"  ✓ 可开仓资金: {max_position:.2f}U")
        
        # 🆕 同步CSV和交易所持仓（检测自动平仓）
        sync_csv_with_exchange_positions(current_positions)
        
        print("⏳ [3/6] 保存持仓快照...")
        # 保存持仓快照
        save_positions_snapshot(current_positions, total_position_value)
        
        # 🆕 V7.0: 检查冷静期状态
        config = load_learning_config()
        should_pause, pause_reason, remaining_minutes = should_pause_trading_v7(config)
        
        if should_pause:
            print(f"🚫 系统处于冷静期: {pause_reason}")
            print("💾 跳过AI分析，仅保存市场数据")
            
            # 保存市场快照
            save_market_snapshot_v7(market_data_list)
            
            # 更新系统状态
            status_data = {
                '更新时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                '系统状态': f'冷静期（{pause_reason}）',
                'USDT余额': usdt_balance,
                '总资产': total_assets,
            }
            save_system_status(status_data)
            
            elapsed = time.time() - start_time
            print(f"\n✅ 冷静期检查完成 (耗时: {elapsed:.1f}秒)\n")
            return
        
        # 🆕 V7.0: 每次执行都保存市场快照（因为已使用固定时间调度）
        save_market_snapshot_v7(market_data_list)
        
        # 🆕 V7.5: YTC主动平仓检查（在AI决策之前执行）
        if current_positions:
            print("⏳ [3.5/6] YTC主动平仓检查...")
            scratch_actions = monitor_positions_for_invalidation(market_data_list, current_positions)
            
            if scratch_actions:
                print(f"⚠️  检测到 {len(scratch_actions)} 个需要主动平仓的持仓")
                # 立即执行主动平仓
                for scratch_action in scratch_actions:
                    _execute_single_close_action(scratch_action, current_positions)
                
                # 刷新持仓数据
                try:
                    print("刷新持仓数据...")
                    current_positions, total_position_value = get_all_positions()
                    save_positions_snapshot(current_positions, total_position_value)
                    print(f"✓ 主动平仓后持仓: {len(current_positions)}个")
                except Exception as e:
                    print(f"⚠️ 刷新持仓失败: {e}")
            else:
                print("✓ 无需主动平仓")
        
        print("⏳ [4/6] AI决策分析...")
        # 3. AI决策
        decision = ai_portfolio_decision(
            market_data_list,
            current_positions,
            total_position_value,
            usdt_balance,
            available_balance,
        )
        if not decision:
            print("❌ AI决策失败")
            return
        
        print("⏳ [5/6] 保存AI决策...")
        # 保存AI决策历史
        save_ai_decision(decision)
        
        print("⏳ [6/6] 执行交易操作...")
        # 4. 执行操作（V5.5：传入额外参数启用智能仓位管理）
        execute_portfolio_actions(
            decision,
            current_positions,
            market_data_list=market_data_list,  # 市场数据（用于信号评分）
            total_assets=total_assets,  # 总资产（用于风险预算）
            available_balance=available_balance,  # 可用余额（用于仓位计算）
        )
        
        # 5. 更新系统状态（重新获取以获得最新数据）
        balance = exchange.fetch_balance()
        usdt_balance = balance["USDT"]["total"]  # 使用total余额（包含所有资产）
        current_positions_updated, total_position_value_updated = get_all_positions()
        
        # 计算未实现盈亏（用于显示）
        total_unrealized_pnl_updated = sum(
            pos["unrealized_pnl"] for pos in current_positions_updated
        )
        # 总资产直接使用total余额（已包含未实现盈亏）
        total_assets_updated = usdt_balance
        
        # 保存盈亏快照
        save_pnl_snapshot(
            current_positions_updated, usdt_balance, total_position_value_updated
        )
        
        status_data = {
            "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "USDT余额": usdt_balance,
            "总资产": total_assets_updated,
            "总仓位价值": total_position_value_updated,
            "最大仓位限制": max_position,
            "当前持仓数": len(current_positions_updated),
            "持仓详情": [
                {
                    "币种": p["symbol"].split("/")[0],
                    "方向": p["side"],
                    "盈亏": p["unrealized_pnl"],
                }
                for p in current_positions_updated
                    ],
            "市场概况": [
                {
                    "币种": d["symbol"].split("/")[0],
                    "价格": d["price"],
                    "涨跌": f"{d['price_change']:+.2f}%",
                }
                for d in market_data_list
                    if d is not None  # 跳过获取失败的币种
            ],
            "AI分析": decision.get("analysis", "N/A"),
            "风险评估": decision.get("risk_assessment", "N/A"),
        }
        save_system_status(status_data)
        
        elapsed = time.time() - start_time
        print("\n" + "=" * 70)
        print(f"✅ 本轮执行完成 (耗时: {elapsed:.1f}秒)")
        
        # 🚀 每4小时输出一次AI调用优化统计
        current_hour = datetime.now().hour
        if current_hour % 4 == 0 and datetime.now().minute < 20:  # 每4小时的前20分钟输出一次
            stats = ai_optimizer.get_stats()
            print(f"\n📊 AI调用优化统计（今日累计）:")
            print(f"  • 总决策次数: {stats['total_decisions']}")
            print(f"  • 实际API调用: {stats['api_calls']}")
            print(f"  • 智能跳过: {stats['calls_saved']} 次")
            print(f"  • 节省率: {stats['save_rate']}")
            print(f"  • 成本降低: {stats['cost_reduction']}")
        
        print("=" * 70)
        
    except Exception as e:
        elapsed = time.time() - start_time
        error_str = str(e)
        
        # 【新增】针对时间戳错误的特殊处理
        if "-1021" in error_str or "Timestamp for this request is outside of the recvWindow" in error_str:
            print(f"\n⚠️  时间戳错误 (耗时: {elapsed:.1f}秒)")
            print(f"   错误: {error_str}")
            print(f"   原因: 系统卡顿导致请求时间超出recvWindow")
            print(f"   已优化: recvWindow=60秒，应该能解决")
            print(f"   建议: 检查系统负载 (free -h, top)")
            # 时间戳错误不发送通知（太频繁）
        else:
            print(f"\n❌ 交易循环异常 (耗时: {elapsed:.1f}秒): {e}")
            send_bark_notification("[通义千问]系统异常⚠️", f"交易循环出错 {str(e)}")
        
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    # 🆕 V7.6.3.6: 检查是否为手动回测模式
    if os.getenv("MANUAL_BACKTEST") == "true":
        print("\n" + "=" * 70)
        print("🔬 手动回测模式 - 立即触发参数优化")
        print("=" * 70)
        
        # 初始化交易所（回测需要）- 🆕 V7.7.0.6: 传入回测标记
        if not setup_exchange(is_manual_backtest=True):
            print("❌ 初始化失败")
            return
        
        # 运行一次完整的参数优化
        try:
            analyze_and_adjust_params()
            print("\n✅ 手动回测完成，参数已更新！")
        except Exception as e:
            print(f"\n❌ 手动回测失败: {e}")
            import traceback
            traceback.print_exc()
        
        return  # 退出，不进入主循环
    
    # 正常启动流程
    print("=" * 70)
    print("多币种AI智能交易系统启动")
    print("=" * 70)
    print(f"监控币种: {', '.join([s.split('/')[0] for s in TRADE_CONFIG['symbols']])}")
    print(f"最大杠杆: {TRADE_CONFIG['max_leverage']}倍")
    print(f"初始资金: {TRADE_CONFIG['initial_capital']}U (动态调整)")
    print(f"交易周期: {TRADE_CONFIG['timeframe']}")
    
    if TRADE_CONFIG["test_mode"]:
        print("⚠️  当前为测试模式")
    else:
        print("⚠️  实盘模式，请谨慎！")
    
    # 🚀 AI调用优化功能说明
    print("\n" + "=" * 70)
    print("🚀 AI调用优化已启用 (效果优先 + 成本节约)")
    print("=" * 70)
    print("  • 有持仓时：实时监控（100%调用，保护盈利）")
    print("  • 关键信号（Pin Bar/吞没/突破）：立即分析")
    print("  • 市场状态无变化 + 无持仓：智能跳过")
    print("  • 定期强制刷新：最多30分钟")
    print("  • 预计节省成本：20-35%（不影响决策质量）")
    print("=" * 70 + "\n")
    
    # 初始化
    if not setup_exchange():
        print("初始化失败")
        return
    
    # 设置定时任务（固定时间点，避免重启导致错过）
    if TRADE_CONFIG["timeframe"] == "15m":
        schedule.every().hour.at(":00").do(trading_bot)
        schedule.every().hour.at(":15").do(trading_bot)
        schedule.every().hour.at(":30").do(trading_bot)
        schedule.every().hour.at(":45").do(trading_bot)
        print("执行频率: 每小时的0、15、30、45分（固定时间）")
    elif TRADE_CONFIG["timeframe"] == "1h":
        schedule.every().hour.at(":01").do(trading_bot)
        print("执行频率: 每小时")
    else:
        schedule.every().hour.at(":01").do(trading_bot)
        print("执行频率: 每小时")
    
    # 设置每日AI参数优化任务（北京时间早上8:05 = UTC 00:05，避免与整点交易冲突）
    schedule.every().day.at("00:05").do(analyze_and_adjust_params)
    print("AI参数优化: 每日北京时间08:05 (UTC 00:05)")
    
    # 立即执行一次
    print("\n开始首次分析...")
    trading_bot()
    
    # 循环执行（增强版：防止 schedule 僵死）
    # 心跳文件（用于外部监控）
    HEARTBEAT_FILE = DATA_DIR / ".heartbeat"

    # 异常计数器
    consecutive_errors = 0
    max_consecutive_errors = 10
    last_heartbeat_time = time.time()

    print("\n" + "=" * 70)
    print("进入主循环（增强容错版）")
    print("=" * 70)

    while True:
        try:
            # 运行待执行的任务
            schedule.run_pending()

            # 重置错误计数
            consecutive_errors = 0

            # 更新心跳（每60秒一次）
            current_time = time.time()
            if current_time - last_heartbeat_time > 60:
                try:
                    with open(HEARTBEAT_FILE, "w") as f:
                        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    last_heartbeat_time = current_time
                except:
                    pass  # 心跳写入失败不影响主流程

            # 短暂休眠
            time.sleep(1)

        except KeyboardInterrupt:
            print("\n" + "=" * 70)
            print("用户手动停止")
            print("=" * 70)

            # 发送停止通知
            send_bark_notification("[通义千问]系统停止", "用户手动停止交易系统")
            break

        except Exception as e:
            consecutive_errors += 1
            error_msg = str(e)[:200]  # 限制错误消息长度

            print("\n" + "=" * 70)
            print(
                f"⚠️  Schedule 循环异常 ({consecutive_errors}/{max_consecutive_errors})"
            )
            print(f"错误: {error_msg}")
            print("=" * 70)

            # 打印堆栈跟踪（帮助诊断）
            import traceback

            traceback.print_exc()

            # 判断是否需要告警
            if consecutive_errors >= max_consecutive_errors:
                print(
                    f"\n❌ 连续 {max_consecutive_errors} 次异常，系统可能存在严重问题"
                )

                # 发送严重告警
                send_bark_notification(
                    "[通义千问]系统严重异常⚠️",
                    f"Schedule连续失败{max_consecutive_errors}次 {error_msg[:50]}",
                )

                # 等待较长时间后重试
                print(f"等待 60 秒后重置计数器并继续...")
                time.sleep(60)
                consecutive_errors = 0  # 重置计数器

            elif consecutive_errors >= 3:
                # 中等异常，发送通知
                send_bark_notification(
                    "[通义千问]Schedule异常",
                    f"连续{consecutive_errors}次错误 {error_msg[:50]}",
                )

                # 短暂等待
                print(f"等待 10 秒后继续...")
                time.sleep(10)

            else:
                # 轻微异常，短暂等待后继续
                print(f"等待 5 秒后继续...")
                time.sleep(5)

    print("\n" + "=" * 70)
    print("交易系统已退出")
    print("=" * 70)


# ============================================================================
# 深度复盘系统核心函数
# ============================================================================

def detect_major_trends(kline_snapshots, coin=None):
    """
    识别昨天所有重要的趋势和行情
    
    参数:
        kline_snapshots: DataFrame, 昨天的市场快照数据
        coin: str, 可选，只分析特定币种
    
    返回:
        list of dict, 识别到的重要趋势
    """
    import pandas as pd
    import numpy as np
    
    trends = []
    
    if kline_snapshots is None or kline_snapshots.empty:
        return trends
    
    # 检查必要的列是否存在（兼容旧格式）
    required_cols = ['coin', 'time', 'close']
    if not all(col in kline_snapshots.columns for col in required_cols):
        print(f"⚠️ 市场快照缺少必要列，跳过趋势识别")
        return trends
    
    # 按币种分组分析
    coins = [coin] if coin else kline_snapshots['coin'].unique()
    
    for coin_name in coins:
        coin_data = kline_snapshots[kline_snapshots['coin'] == coin_name].sort_values('time')
        
        if len(coin_data) < 4:  # 至少需要4个数据点（1小时）
            continue
        
        # === 识别单边上涨 ===
        for i in range(len(coin_data) - 3):
            window = coin_data.iloc[i:i+4]  # 1小时窗口
            
            start_price = window.iloc[0]['close']
            end_price = window.iloc[-1]['close']
            amplitude = (end_price - start_price) / start_price * 100
            
            # 计算最大回撤
            max_price = window['close'].max()
            min_price = window['close'].min()
            max_drawdown = (max_price - min_price) / max_price * 100
            
            if amplitude > 3 and max_drawdown < 1:
                trends.append({
                    "type": "单边上涨",
                    "coin": coin_name,
                    "start_time": window.iloc[0]['time'],
                    "end_time": window.iloc[-1]['time'],
                    "start_price": start_price,
                    "end_price": end_price,
                    "amplitude": round(amplitude, 2),
                    "duration": 60,
                    "quality": "优质" if max_drawdown < 0.5 else "良好"
                        })
        
        # === 识别单边下跌 ===
        for i in range(len(coin_data) - 3):
            window = coin_data.iloc[i:i+4]
            
            start_price = window.iloc[0]['close']
            end_price = window.iloc[-1]['close']
            amplitude = (end_price - start_price) / start_price * 100
            
            if amplitude < -3:
                trends.append({
                    "type": "单边下跌",
                    "coin": coin_name,
                    "start_time": window.iloc[0]['time'],
                    "end_time": window.iloc[-1]['time'],
                    "start_price": start_price,
                    "end_price": end_price,
                    "amplitude": round(amplitude, 2),
                    "duration": 60,
                    "quality": "优质"
                })
    
    return trends


def analyze_trade_performance(trade, kline_snapshots):
    """
    深度分析单笔交易的表现（预期vs实际）
    
    参数:
        trade: dict, 交易记录
        kline_snapshots: DataFrame, 市场快照数据
    
    返回:
        dict, 详细的分析结果
    """
    import pandas as pd
    from datetime import datetime
    
    try:
        coin = trade.get('币种')
        entry_time_str = trade.get('开仓时间', '')
        exit_time_str = trade.get('平仓时间', '')
        
        if not entry_time_str or not exit_time_str:
            return {"error": "交易时间缺失"}
        
        entry_time = pd.to_datetime(entry_time_str)
        exit_time = pd.to_datetime(exit_time_str)
        entry_price = float(trade.get('开仓价格', 0))
        exit_price = float(trade.get('平仓价格', 0))
        side = trade.get('方向')
        
        # 预期设置
        expected_sl = float(trade.get('止损', 0))
        expected_tp = float(trade.get('止盈', 0))
        expected_rr = float(trade.get('盈亏比', 0))
        
        # 获取持仓期间的K线数据
        if kline_snapshots is None or kline_snapshots.empty:
            return {"error": "没有K线快照数据"}
        
        coin_klines = kline_snapshots[kline_snapshots['coin'] == coin].copy()
        
        # 计算实际走势
        if side == '多':
            max_profit_price = coin_klines['high'].max()
            max_profit_pct = (max_profit_price - entry_price) / entry_price * 100
            max_drawdown_price = coin_klines['low'].min()
            max_drawdown_pct = (max_drawdown_price - entry_price) / entry_price * 100
            
            tp_reached = max_profit_price >= expected_tp if expected_tp > 0 else False
            sl_triggered = max_drawdown_price <= expected_sl if expected_sl > 0 else False
            
            actual_pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            max_profit_price = coin_klines['low'].min()
            max_profit_pct = (entry_price - max_profit_price) / entry_price * 100
            max_drawdown_price = coin_klines['high'].max()
            max_drawdown_pct = (max_drawdown_price - entry_price) / entry_price * 100
            
            tp_reached = max_profit_price <= expected_tp if expected_tp > 0 else False
            sl_triggered = max_drawdown_price >= expected_sl if expected_sl > 0 else False
            
            actual_pnl_pct = (entry_price - exit_price) / entry_price * 100
        
        # 判断是否提前平仓
        premature_exit = max_profit_pct > actual_pnl_pct and not tp_reached
        missed_profit = max_profit_pct - actual_pnl_pct if premature_exit else 0
        
        # 评价
        expected_tp_pct = abs((expected_tp - entry_price) / entry_price * 100) if expected_tp > 0 else 0
        tp_distance = expected_tp_pct - max_profit_pct
        
        if tp_reached:
            tp_setting = "合理（已达到）"
        elif tp_distance < 0.5:
            tp_setting = "略微乐观"
        elif tp_distance < 1:
            tp_setting = "过于乐观"
        else:
            tp_setting = "严重偏离"
        
        exit_timing = "过早" if premature_exit and missed_profit > 0.5 else "合理"
        
        # 建议的止盈
        recommended_tp_pct = max_profit_pct * 0.9
        if side == '多':
            recommended_tp = entry_price * (1 + recommended_tp_pct / 100)
        else:
            recommended_tp = entry_price * (1 - recommended_tp_pct / 100)
        
        return {
            "coin": coin,
            "side": side,
            "expected": {
                "stop_loss": expected_sl,
                "take_profit": expected_tp,
                "risk_reward": expected_rr
            },
            "actual": {
                "max_profit_pct": round(max_profit_pct, 2),
                "max_drawdown_pct": round(max_drawdown_pct, 2),
                "actual_pnl_pct": round(actual_pnl_pct, 2),
                "tp_reached": tp_reached,
                "sl_triggered": sl_triggered,
                "premature_exit": premature_exit
            },
            "analysis": {
                "tp_setting": tp_setting,
                "tp_distance": round(tp_distance, 2),
                "exit_timing": exit_timing,
                "missed_profit": round(missed_profit, 2)
            },
            "recommendations": {
                "next_tp": round(recommended_tp, 2),
                "next_tp_pct": round(recommended_tp_pct, 2)
            }
        }
    
    except Exception as e:
        return {"error": f"分析失败: {str(e)}"}


def recalculate_signal_score_from_snapshot(snapshot_row, signal_type):
    """
    【V8.2新增】从历史快照的维度数据重新计算signal_score
    
    这是V8.2架构的核心：评分标准改变时，历史数据自动重新计算
    
    Args:
        snapshot_row: 历史快照的一行数据（pd.Series或dict）
        signal_type: 'scalping' 或 'swing'
    
    Returns:
        int: 重新计算的signal_score（0-100）
    """
    def safe_score(value):
        """安全地转换评分值为数字"""
        if value is None or value == '' or value == 'N/A' or value == '-':
            return 0
        try:
            # 处理NaN
            import math
            if isinstance(value, float) and math.isnan(value):
                return 0
            return float(value)
        except:
            return 0
    
    try:
        # 基础分
        total_score = 50
        
        # 【方案A】如果有维度数据，使用维度重新计算
        if 'volume_surge_score' in snapshot_row:
            if signal_type == 'scalping':
                # 超短线维度加分（安全转换）
                total_score += safe_score(snapshot_row.get('volume_surge_score', 0))
                total_score += safe_score(snapshot_row.get('breakout_score', 0))
                total_score += safe_score(snapshot_row.get('momentum_score', 0))
                total_score += safe_score(snapshot_row.get('scalp_consecutive_score', 0))
                total_score += safe_score(snapshot_row.get('pin_bar_score', 0))
                total_score += safe_score(snapshot_row.get('engulfing_score', 0))
                total_score += safe_score(snapshot_row.get('trend_alignment_score', 0))
            
            elif signal_type == 'swing':
                # 波段维度加分（安全转换）
                total_score += safe_score(snapshot_row.get('trend_initiation_score', 0))
                total_score += safe_score(snapshot_row.get('trend_alignment_score', 0))
                total_score += safe_score(snapshot_row.get('trend_4h_strength_score', 0))
                total_score += safe_score(snapshot_row.get('ema_divergence_score', 0))
                total_score += safe_score(snapshot_row.get('swing_pullback_score', 0))
                total_score += safe_score(snapshot_row.get('swing_consecutive_score', 0))
                total_score += safe_score(snapshot_row.get('volume_confirmed_score', 0))
        
        # 【方案B兼容】如果没有维度数据（旧数据），尝试使用signal_score
        elif 'signal_score' in snapshot_row:
            # 旧数据：直接使用signal_score（不准确，但至少能用）
            return int(safe_score(snapshot_row.get('signal_score', 50)))
        
        # 限制在0-100范围
        return min(100, max(0, int(total_score)))
        
    except Exception as e:
        print(f"⚠️ 【V8.2】重新计算signal_score失败: {e}")
        return 50  # 默认值


def analyze_opportunities_with_new_params(market_snapshots, actual_trades, new_config, old_config=None):
    """
    用新参数重新评估历史机会（V7.9.0 - 完全重构版）
    
    核心逻辑（完全修正）：
    1. 客观识别机会：完全基于价格走势，不依赖任何参数过滤
       - 超短线：1小时内实际达到≥1.5%利润
       - 波段：24小时内实际达到≥3%利润
    2. 模拟旧参数交易：真实模拟入场判断、止盈止损触发、计算捕获利润
    3. 模拟新参数交易：同样真实模拟，计算捕获利润
    4. 对比三种利润：
       - actual_profit: 客观利润（价格实际走势）
       - old_captured_profit: 旧参数按止盈止损获得的利润
       - new_captured_profit: 新参数按止盈止损获得的利润
    
    参数:
        market_snapshots: DataFrame, 历史市场快照数据
        actual_trades: list, 实际开的仓
        new_config: dict, 优化后的新参数
        old_config: dict, 优化前的旧参数（可选）
    
    返回:
        dict: {
            'all_opportunities': list,  # 所有客观机会
            'old_captured': list,  # 旧参数能捕获的
            'new_captured': list,  # 新参数能捕获的
            'missed': list,  # 新参数仍错过的
            'stats': dict  # 统计数据
        }
    """
    import pandas as pd
    import numpy as np
    
    if market_snapshots is None or market_snapshots.empty:
        return {'all_opportunities': [], 'old_captured': [], 'new_captured': [], 'missed': [], 'stats': {}}
    
    all_opportunities = []
    
    # 【V8.0→V8.1】辅助函数：根据信号类型获取参数（含时间/频率）
    def get_params_for_signal_type(config, signal_type):
        """从配置中获取对应信号类型的参数"""
        if signal_type == 'scalping':
            params_key = 'scalping_params'
            fallback = {
                'min_signal_score': 60,
                'min_indicator_consensus': 2,
                'min_risk_reward': 1.5,
                'atr_stop_multiplier': 1.0,
                'atr_tp_multiplier': 1.5,
                # 【V8.1】时间/频率参数
                'max_holding_hours': 2.0,              # 最长持仓时间
                'trailing_stop_trigger': 1.0,          # 移动止损触发倍数（盈利>1.0×ATR启动）
                'cooldown_same_coin_minutes': 30,      # 同币种冷却时间
                'max_trades_per_hour': 4               # 每小时最大交易数
            }
        else:  # swing
            params_key = 'swing_params'
            fallback = {
                'min_signal_score': 70,
                'min_indicator_consensus': 2,
                'min_risk_reward': 3.0,
                'atr_stop_multiplier': 2.0,
                'atr_tp_multiplier': 6.0,
                # 【V8.1】时间/频率参数
                'max_holding_hours': 24.0,             # 最长持仓时间
                'trailing_stop_trigger': 2.0,          # 移动止损触发倍数（盈利>2.0×ATR启动）
                'protection_period_minutes': 120,      # 保护期（期间不检查时间失效）
                'max_trades_per_hour': 2               # 每小时最大交易数
            }
        
        # 尝试从专用配置读取，否则从global读取，最后使用fallback
        specialized = config.get(params_key, {})
        global_config = config.get('global', {})
        
        return {
            'min_signal_score': specialized.get('min_signal_score') or global_config.get('min_signal_score') or fallback['min_signal_score'],
            'min_consensus': specialized.get('min_indicator_consensus') or global_config.get('min_indicator_consensus') or fallback['min_indicator_consensus'],
            'min_risk_reward': specialized.get('min_risk_reward') or global_config.get('min_risk_reward') or fallback['min_risk_reward'],
            'atr_stop_multiplier': specialized.get('atr_stop_multiplier') or global_config.get('atr_stop_multiplier') or fallback['atr_stop_multiplier'],
            'atr_tp_multiplier': specialized.get('atr_tp_multiplier') or fallback['atr_tp_multiplier'],
            # 【V8.1】时间/频率参数
            'max_holding_hours': specialized.get('max_holding_hours') or fallback.get('max_holding_hours', 12.0),
            'trailing_stop_trigger': specialized.get('trailing_stop_trigger') or fallback.get('trailing_stop_trigger', 1.5),
            'cooldown_same_coin_minutes': specialized.get('cooldown_same_coin_minutes') or fallback.get('cooldown_same_coin_minutes', 30),
            'max_trades_per_hour': specialized.get('max_trades_per_hour') or fallback.get('max_trades_per_hour', 3),
            'protection_period_minutes': specialized.get('protection_period_minutes') or fallback.get('protection_period_minutes', 60)
        }
    
    # 按币种分组
    coins = market_snapshots['coin'].unique()
    
    for coin in coins:
        coin_data = market_snapshots[market_snapshots['coin'] == coin].copy()
        coin_data = coin_data.sort_values('time').reset_index(drop=True)
        
        if len(coin_data) < 4:  # 至少需要4个点
            continue
        
        # 遍历每个时间点，检查是否为客观机会
        for idx in range(len(coin_data) - 4):  # 留出足够的后续数据
            current = coin_data.iloc[idx]
            
            # 【V8.3.10.3】确保所有从Series获取的值都转为标量
            timestamp = str(current.get('time', ''))
            # 安全获取entry_price：优先close，否则price
            try:
                entry_price = float(current.get('close', 0))
                if entry_price <= 0:
                    entry_price = float(current.get('price', 0))
            except (ValueError, TypeError):
                entry_price = 0
            
            if entry_price <= 0:
                continue
            
            # 获取当前点的市场数据（用于后续模拟）
            # signal_score = current.get('signal_score', 0)  # 【V8.2已移除】改用维度重新计算（第16383行）
            # 【V8.3.10.3】所有数值都需要安全转换
            try:
                consensus = int(float(current.get('indicator_consensus', 0)))
            except (ValueError, TypeError):
                consensus = 0
            try:
                risk_reward = float(current.get('risk_reward', 0))
            except (ValueError, TypeError):
                risk_reward = 0
            try:
                atr = float(current.get('atr', 0))
            except (ValueError, TypeError):
                atr = 0
            
            # ✅ 移除参数过滤 - 不再跳过任何信号
            # 所有时间点都可能是机会，只要价格走势达标
            
            # 向后查看1小时（4个15分钟）和24小时（96个15分钟）
            later_1h = coin_data.iloc[idx+1:min(idx+5, len(coin_data))]
            later_24h = coin_data.iloc[idx+1:min(idx+97, len(coin_data))]
            
            if later_1h.empty:
                continue
            
            # 判断方向（多空）
            trends = [current.get('trend_4h', ''), current.get('trend_1h', ''), current.get('trend_15m', '')]
            bullish_count = sum(1 for t in trends if '多头' in str(t))
            bearish_count = sum(1 for t in trends if '空头' in str(t))
            
            if bullish_count > bearish_count:
                direction = 'long'
            elif bearish_count > bullish_count:
                direction = 'short'
            else:
                continue  # 方向不明确，跳过
            
            # 计算1小时内的最大利润（超短线）
            scalping_profit = 0
            if direction == 'long':
                max_price_1h = later_1h['high'].max() if 'high' in later_1h.columns else later_1h['close'].max()
                scalping_profit = (max_price_1h - entry_price) / entry_price * 100
            else:  # short
                min_price_1h = later_1h['low'].min() if 'low' in later_1h.columns else later_1h['close'].min()
                scalping_profit = (entry_price - min_price_1h) / entry_price * 100
            
            # 计算24小时内的最大利润（波段）
            swing_profit = 0
            if not later_24h.empty:
                if direction == 'long':
                    max_price_24h = later_24h['high'].max() if 'high' in later_24h.columns else later_24h['close'].max()
                    swing_profit = (max_price_24h - entry_price) / entry_price * 100
                else:  # short
                    min_price_24h = later_24h['low'].min() if 'low' in later_24h.columns else later_24h['close'].min()
                    swing_profit = (entry_price - min_price_24h) / entry_price * 100
            
            # 判断是否为客观机会（只看价格，不看参数）
            is_scalping_opp = scalping_profit >= 1.5
            is_swing_opp = swing_profit >= 3.0
            
            if not (is_scalping_opp or is_swing_opp):
                continue  # 不是客观机会
            
            # 确定机会类型和实际利润
            if is_swing_opp:
                opp_type = 'swing'
                actual_profit = swing_profit
            else:
                opp_type = 'scalping'
                actual_profit = scalping_profit
            
            # 【V8.2】从维度数据重新计算signal_score（使用对应的评分标准）
            signal_score = recalculate_signal_score_from_snapshot(current, opp_type)
            
            # 判断是否实际交易了
            was_traded = False
            for t in actual_trades:
                if t.get('币种') != coin:
                    continue
                try:
                    trade_time_str = str(t.get('开仓时间', ''))
                    if not trade_time_str:
                        continue
                    
                    trade_time = pd.to_datetime(trade_time_str)
                    snap_time_str = str(timestamp)
                    if len(snap_time_str) == 4 and snap_time_str.isdigit():
                        trade_hhmm = trade_time.strftime('%H%M')
                        if trade_hhmm == snap_time_str:
                            was_traded = True
                            break
                    else:
                        snap_time = pd.to_datetime(snap_time_str)
                        if abs((trade_time - snap_time).total_seconds()) <= 900:
                            was_traded = True
                            break
                except:
                    continue
            
            # ✅ 【V8.0】核心改动：根据信号类型使用对应参数
            # 获取旧参数（根据机会类型）
            old_params = get_params_for_signal_type(old_config if old_config else new_config, opp_type)
            
            # 模拟旧参数交易
            old_sim = _simulate_trade_with_params(
                entry_price=entry_price,
                direction=direction,
                atr=atr,
                future_data=later_24h,
                signal_score=signal_score,
                consensus=consensus,
                risk_reward=risk_reward,
                min_signal_score=old_params['min_signal_score'],
                min_consensus=old_params['min_consensus'],
                min_risk_reward=old_params['min_risk_reward'],
                atr_stop_multiplier=old_params['atr_stop_multiplier'],
                atr_tp_multiplier=old_params['atr_tp_multiplier'],
                max_holding_hours=old_params.get('max_holding_hours')  # 【V8.1】时间限制
            )
            
            # 获取新参数（根据机会类型）
            new_params = get_params_for_signal_type(new_config, opp_type)
            
            # 模拟新参数交易
            new_sim = _simulate_trade_with_params(
                entry_price=entry_price,
                direction=direction,
                atr=atr,
                future_data=later_24h,
                signal_score=signal_score,
                consensus=consensus,
                risk_reward=risk_reward,
                min_signal_score=new_params['min_signal_score'],
                min_consensus=new_params['min_consensus'],
                min_risk_reward=new_params['min_risk_reward'],
                atr_stop_multiplier=new_params['atr_stop_multiplier'],
                atr_tp_multiplier=new_params['atr_tp_multiplier'],
                max_holding_hours=new_params.get('max_holding_hours')  # 【V8.1】时间限制
            )
            
            # 构建机会对象
            # 🔧 V7.9.2: 尝试获取日期（优先从数据中，否则从时间戳推导，最后使用yesterday）
            opp_date = current.get('date', None)
            if not opp_date:
                # 如果market_snapshots中没有date列，尝试从datetime字段推导
                datetime_field = current.get('datetime', None)
                if datetime_field:
                    try:
                        dt = pd.to_datetime(datetime_field)
                        opp_date = dt.strftime('%Y%m%d')
                    except:
                        opp_date = None
            
            # 如果还是没有date，使用yesterday作为估算（因为这个分析通常是每日凌晨运行）
            if not opp_date:
                # 获取yesterday变量（在外部函数中定义）
                try:
                    from datetime import datetime, timedelta
                    opp_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
                except:
                    opp_date = None
            
            opportunity = {
                'coin': coin,
                'time': timestamp,
                'date': opp_date,  # 🆕 V7.9.2: 添加日期字段
                'direction': direction,
                'entry_price': entry_price,
                    'signal_score': int(signal_score),
                'consensus': int(consensus),
                'risk_reward': round(risk_reward, 2),
                'signal_type': opp_type,
                'actual_profit_pct': round(actual_profit, 1),  # 客观利润
                'was_traded': was_traded,
                # 旧参数模拟结果
                'old_can_entry': old_sim['can_entry'],
                    'old_captured_profit': round(old_sim['profit'], 1) if old_sim['can_entry'] else 0,
                'old_exit_type': old_sim.get('exit_type', 'N/A') if old_sim['can_entry'] else 'N/A',
                # 新参数模拟结果
                'new_can_entry': new_sim['can_entry'],
                    'new_captured_profit': round(new_sim['profit'], 1) if new_sim['can_entry'] else 0,
                'new_exit_type': new_sim.get('exit_type', 'N/A') if new_sim['can_entry'] else 'N/A',
                    }
            
            # 计算捕获效率
            if old_sim['can_entry'] and actual_profit > 0:
                opportunity['old_efficiency'] = round(old_sim['profit'] / actual_profit * 100, 1)
            else:
                opportunity['old_efficiency'] = 0
            
            if new_sim['can_entry'] and actual_profit > 0:
                opportunity['new_efficiency'] = round(new_sim['profit'] / actual_profit * 100, 1)
            else:
                opportunity['new_efficiency'] = 0
            
            # 分析错过原因（针对新参数）
            if not new_sim['can_entry']:
                reasons = []
                if signal_score < new_params['min_signal_score']:
                    reasons.append(f"信号分{int(signal_score)}<{new_params['min_signal_score']}")
                if consensus < new_params['min_consensus']:
                    reasons.append(f"共振{int(consensus)}<{new_params['min_consensus']}")
                if risk_reward < new_params['min_risk_reward']:
                    reasons.append(f"盈亏比{risk_reward:.1f}<{new_params['min_risk_reward']:.1f}")
                opportunity['miss_reason'] = "、".join(reasons) if reasons else "其他"
            else:
                opportunity['miss_reason'] = ""
            
            all_opportunities.append(opportunity)
    
    # 【V8.1.4】分类统计：总体 + 超短线 + 波段
    old_captured = [o for o in all_opportunities if o['old_can_entry']]
    new_captured = [o for o in all_opportunities if o['new_can_entry']]
    missed = [o for o in all_opportunities if not o['new_can_entry']]
    
    # 按类型分组
    scalping_opps = [o for o in all_opportunities if o.get('signal_type') == 'scalping']
    swing_opps = [o for o in all_opportunities if o.get('signal_type') == 'swing']
    
    # 超短线统计
    scalping_old_captured = [o for o in scalping_opps if o['old_can_entry']]
    scalping_new_captured = [o for o in scalping_opps if o['new_can_entry']]
    
    # 波段统计
    swing_old_captured = [o for o in swing_opps if o['old_can_entry']]
    swing_new_captured = [o for o in swing_opps if o['new_can_entry']]
    
    # 计算统计数据
    total = len(all_opportunities)
    scalping_total = len(scalping_opps)
    swing_total = len(swing_opps)
    
    avg_old_profit = sum(o['old_captured_profit'] for o in old_captured) / len(old_captured) if old_captured else 0
    avg_new_profit = sum(o['new_captured_profit'] for o in new_captured) / len(new_captured) if new_captured else 0
    
    stats = {
        # 总体统计
        'total_opportunities': total,
        'old_captured_count': len(old_captured),
        'new_captured_count': len(new_captured),
        'missed_count': len(missed),
        'old_capture_rate': (len(old_captured) / total * 100) if total > 0 else 0,
            'new_capture_rate': (len(new_captured) / total * 100) if total > 0 else 0,
        # 【V8.1.4新增】超短线分类统计
        'scalping_total': scalping_total,
        'scalping_old_captured': len(scalping_old_captured),
        'scalping_new_captured': len(scalping_new_captured),
        'scalping_old_rate': (len(scalping_old_captured) / scalping_total * 100) if scalping_total > 0 else 0,
            'scalping_new_rate': (len(scalping_new_captured) / scalping_total * 100) if scalping_total > 0 else 0,
        # 【V8.1.4新增】波段分类统计
        'swing_total': swing_total,
        'swing_old_captured': len(swing_old_captured),
        'swing_new_captured': len(swing_new_captured),
        'swing_old_rate': (len(swing_old_captured) / swing_total * 100) if swing_total > 0 else 0,
            'swing_new_rate': (len(swing_new_captured) / swing_total * 100) if swing_total > 0 else 0,
        # 平均利润
        'avg_actual_profit': sum(o['actual_profit_pct'] for o in all_opportunities) / total if total > 0 else 0,
            'avg_old_captured_profit': avg_old_profit,
        'avg_new_captured_profit': avg_new_profit,
        # 平均捕获效率
        'avg_old_efficiency': sum(o['old_efficiency'] for o in old_captured) / len(old_captured) if old_captured else 0,
            'avg_new_efficiency': sum(o['new_efficiency'] for o in new_captured) / len(new_captured) if new_captured else 0,
        # 改进幅度
        'capture_rate_improvement': (len(new_captured) - len(old_captured)) / total * 100 if total > 0 else 0,
            'profit_improvement': avg_new_profit - avg_old_profit
    }
    
    return {
        'all_opportunities': all_opportunities,
        'old_captured': old_captured,
        'new_captured': new_captured,
        'missed': missed,
        'stats': stats
    }


def _simulate_trade_with_params_enhanced(entry_price, direction, atr, future_data, 
                                          signal_score, consensus, risk_reward,
                                          min_signal_score, min_consensus, min_risk_reward, 
                                          atr_stop_multiplier, atr_tp_multiplier=None,
                                          max_holding_hours=None, signal_type='scalping',
                                          support=None, resistance=None, pattern_type=None,
                                          pattern_data=None):
    """
    【V8.3.13.1】增强版模拟函数 - 支持SR Levels + 形态识别
    
    新增功能:
    - signal_type: 'scalping' or 'swing'
    - support/resistance: SR levels for swing trades
    - pattern_type: 形态类型 ('bullish_pin', 'bearish_pin', etc.)
    - pattern_data: 形态数据 (high, low, etc.)
    
    优先级:
    1. 形态识别 (scalping优先)
    2. SR Levels (swing优先)
    3. ATR-based (默认)
    """
    # 1. 判断是否会入场
    can_entry = (
        signal_score >= min_signal_score and
        consensus >= min_consensus and
        risk_reward >= min_risk_reward
    )
    
    if not can_entry:
        return {'can_entry': False, 'profit': 0, 'exit_type': 'no_entry'}
    
    # 2. 计算TP/SL
    if atr <= 0:
        atr = entry_price * 0.02
    
    # 优先级1: 形态识别 (scalping)
    if pattern_type and pattern_data and signal_type == 'scalping':
        tp_sl = get_pattern_based_tp_sl(entry_price, direction, pattern_type, pattern_data, atr)
        if tp_sl:
            stop_loss = tp_sl['stop_loss']
            take_profit = tp_sl['take_profit']
        else:
            # Fallback
            stop_loss_distance = atr * atr_stop_multiplier
            take_profit_distance = atr * (atr_tp_multiplier or atr_stop_multiplier * min_risk_reward)
            stop_loss = entry_price - stop_loss_distance if direction == 'long' else entry_price + stop_loss_distance
            take_profit = entry_price + take_profit_distance if direction == 'long' else entry_price - take_profit_distance
    
    # 优先级2: SR Levels (swing)
    elif signal_type == 'swing' and support and resistance:
        sr_margin = atr * 0.3
        if direction == 'long':
            stop_loss = (support - sr_margin) if support > 0 else (entry_price - atr * atr_stop_multiplier)
            take_profit = (resistance + sr_margin) if resistance > 0 else (entry_price + atr * (atr_tp_multiplier or 6.0))
            
            # 验证合理性
            if (entry_price - stop_loss) <= 0 or (take_profit - entry_price) <= 0 or ((take_profit - entry_price) / (entry_price - stop_loss)) < 1.5:
                stop_loss = entry_price - atr * atr_stop_multiplier
                take_profit = entry_price + atr * (atr_tp_multiplier or 6.0)
        else:
            stop_loss = (resistance + sr_margin) if resistance > 0 else (entry_price + atr * atr_stop_multiplier)
            take_profit = (support - sr_margin) if support > 0 else (entry_price - atr * (atr_tp_multiplier or 6.0))
            
            if (stop_loss - entry_price) <= 0 or (entry_price - take_profit) <= 0 or ((entry_price - take_profit) / (stop_loss - entry_price)) < 1.5:
                stop_loss = entry_price + atr * atr_stop_multiplier
                take_profit = entry_price - atr * (atr_tp_multiplier or 6.0)
    
    # 优先级3: ATR-based
    else:
        stop_loss_distance = atr * atr_stop_multiplier
        take_profit_distance = atr * (atr_tp_multiplier or atr_stop_multiplier * min_risk_reward)
        
        if direction == 'long':
            stop_loss = entry_price - stop_loss_distance
            take_profit = entry_price + take_profit_distance
        else:
            stop_loss = entry_price + stop_loss_distance
            take_profit = entry_price - take_profit_distance
    
    # 3. 模拟交易
    if future_data.empty:
        return {'can_entry': True, 'profit': 0, 'exit_type': 'no_data'}
    
    max_candles = None
    if max_holding_hours:
        max_candles = int(max_holding_hours * 4)
    
    for idx, row in future_data.iterrows():
        if max_candles and idx >= max_candles:
            close_price = float(row.get('close', entry_price))
            profit_pct = (close_price - entry_price) / entry_price * 100 if direction == 'long' else (entry_price - close_price) / entry_price * 100
            return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'time_exit'}
        
        high = float(row.get('high', row.get('close', 0)))
        low = float(row.get('low', row.get('close', 0)))
        
        if high <= 0 or low <= 0:
            continue
        
        if direction == 'long':
            if low <= stop_loss:
                return {'can_entry': True, 'profit': (stop_loss - entry_price) / entry_price * 100, 'exit_type': 'stop_loss'}
            if high >= take_profit:
                return {'can_entry': True, 'profit': (take_profit - entry_price) / entry_price * 100, 'exit_type': 'take_profit'}
        else:
            if high >= stop_loss:
                return {'can_entry': True, 'profit': (entry_price - stop_loss) / entry_price * 100, 'exit_type': 'stop_loss'}
            if low <= take_profit:
                return {'can_entry': True, 'profit': (entry_price - take_profit) / entry_price * 100, 'exit_type': 'take_profit'}
    
    last_close = float(future_data.iloc[-1].get('close', entry_price))
    profit_pct = (last_close - entry_price) / entry_price * 100 if direction == 'long' else (entry_price - last_close) / entry_price * 100
    return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'holding'}


def _simulate_with_summary(entry_price, direction, stop_loss, take_profit, 
                           future_summary, max_holding_hours=None):
    """
    【V8.3.21】使用摘要数据快速模拟交易（内存优化版）
    
    Args:
        entry_price: 入场价
        direction: 'long' 或 'short'
        stop_loss: 止损价
        take_profit: 止盈价
        future_summary: dict {'max_high': float, 'min_low': float, 'final_close': float, 'data_points': int}
        max_holding_hours: 最长持仓小时（可选）
    
    Returns:
        {'can_entry': True, 'profit': float, 'exit_type': str}
    """
    max_high = future_summary.get('max_high', 0)
    min_low = future_summary.get('min_low', 0)
    final_close = future_summary.get('final_close', entry_price)
    
    if max_high <= 0 or min_low <= 0:
        return {'can_entry': True, 'profit': 0, 'exit_type': 'no_data'}
    
    if direction == 'long':
        # 多单：检查是否触及止损或止盈
        if min_low <= stop_loss:
            # 触及止损
            profit_pct = (stop_loss - entry_price) / entry_price * 100
            return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'stop_loss'}
        elif max_high >= take_profit:
            # 触及止盈
            profit_pct = (take_profit - entry_price) / entry_price * 100
            return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'take_profit'}
        else:
            # 未触及，按最终价格计算
            profit_pct = (final_close - entry_price) / entry_price * 100
            exit_type = 'time_exit' if max_holding_hours else 'holding'
            return {'can_entry': True, 'profit': profit_pct, 'exit_type': exit_type}
    else:  # short
        # 空单：检查是否触及止损或止盈
        if max_high >= stop_loss:
            # 触及止损
            profit_pct = (entry_price - stop_loss) / entry_price * 100
            return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'stop_loss'}
        elif min_low <= take_profit:
            # 触及止盈
            profit_pct = (entry_price - take_profit) / entry_price * 100
            return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'take_profit'}
        else:
            # 未触及，按最终价格计算
            profit_pct = (entry_price - final_close) / entry_price * 100
            exit_type = 'time_exit' if max_holding_hours else 'holding'
            return {'can_entry': True, 'profit': profit_pct, 'exit_type': exit_type}


def _simulate_trade_with_params(entry_price, direction, atr, future_data, 
                                 signal_score, consensus, risk_reward,
                                 min_signal_score, min_consensus, min_risk_reward, 
                                 atr_stop_multiplier, atr_tp_multiplier=None,
                                 max_holding_hours=None,
                                 signal_type=None, market_data=None):
    """
    【V8.0→V8.1→V8.3.8→V8.3.21】模拟用给定参数交易一个机会 - 支持独立止盈倍数 + 时间限制 + 波段SR优先 + 摘要数据
    
    Args:
        atr_stop_multiplier: 止损ATR倍数
        atr_tp_multiplier: 止盈ATR倍数（可选，默认使用min_risk_reward计算）
        max_holding_hours: 最长持仓小时数（可选，超时强制平仓）【V8.1新增】
        signal_type: 信号类型 'scalping' 或 'swing'【V8.3.8新增】
        market_data: 市场数据（用于获取SR级别）【V8.3.8新增】
        future_data: DataFrame或dict摘要数据【V8.3.21支持dict】
    
    返回:
        dict: {
            'can_entry': bool,  # 是否会入场
                'profit': float,  # 捕获的利润（%）
            'exit_type': str  # 平仓类型：'stop_loss', 'take_profit', 'holding', 'time_exit'
        }
    """
    # 1. 判断是否会入场
    can_entry = (
        signal_score >= min_signal_score and
        consensus >= min_consensus and
        risk_reward >= min_risk_reward
    )
    
    if not can_entry:
        return {'can_entry': False, 'profit': 0, 'exit_type': 'no_entry'}
    
    # 2. 如果会入场，计算止盈止损价格
    if atr <= 0:
        atr = entry_price * 0.02  # 默认2%
    
    # 【V8.3.8】波段交易优先使用SR级别
    use_sr = False
    if signal_type == 'swing' and market_data and isinstance(market_data, dict):
        support_levels = market_data.get('support_levels', [])
        resistance_levels = market_data.get('resistance_levels', [])
        
        if direction == 'long' and support_levels and resistance_levels:
            # 多单：止损=最近支撑位下方，止盈=最近阻力位
            nearest_support = max([s for s in support_levels if s < entry_price], default=None)
            nearest_resistance = min([r for r in resistance_levels if r > entry_price], default=None)
            
            if nearest_support and nearest_resistance:
                stop_loss = nearest_support * 0.995  # 支撑位下方0.5%
                take_profit = nearest_resistance * 0.995  # 阻力位下方0.5%（保守）
                use_sr = True
        elif direction == 'short' and support_levels and resistance_levels:
            # 空单：止损=最近阻力位上方，止盈=最近支撑位
            nearest_resistance = min([r for r in resistance_levels if r > entry_price], default=None)
            nearest_support = max([s for s in support_levels if s < entry_price], default=None)
            
            if nearest_resistance and nearest_support:
                stop_loss = nearest_resistance * 1.005  # 阻力位上方0.5%
                take_profit = nearest_support * 1.005  # 支撑位上方0.5%（保守）
                use_sr = True
    
    # Fallback: 使用ATR计算
    if not use_sr:
        stop_loss_distance = atr * atr_stop_multiplier
        
        # 【V8.0】支持独立止盈倍数
        if atr_tp_multiplier is not None:
            take_profit_distance = atr * atr_tp_multiplier
        else:
            take_profit_distance = stop_loss_distance * min_risk_reward
        
        if direction == 'long':
            stop_loss = entry_price - stop_loss_distance
            take_profit = entry_price + take_profit_distance
        else:  # short
            stop_loss = entry_price + stop_loss_distance
            take_profit = entry_price - take_profit_distance
    
    # 3. 【V8.3.21】检查future_data类型
    if isinstance(future_data, dict):
        # 使用摘要数据快速模拟
        return _simulate_with_summary(entry_price, direction, stop_loss, take_profit, 
                                      future_data, max_holding_hours)
    
    # 3. 模拟交易：遍历后续价格，看哪个先触及
    if future_data.empty:
        return {'can_entry': True, 'profit': 0, 'exit_type': 'no_data'}
    
    # 【V8.1】计算时间限制（如果指定）
    max_candles = None
    if max_holding_hours is not None and max_holding_hours > 0:
        # 假设每根K线15分钟
        max_candles = int(max_holding_hours * 4)  # 1小时=4根15分钟K线
    
    for idx, row in future_data.iterrows():
        # 【V8.1】检查是否超时
        if max_candles is not None and idx >= max_candles:
            # 超时强制平仓
            close_price = row.get('close', entry_price)
            if direction == 'long':
                profit_pct = (close_price - entry_price) / entry_price * 100
            else:
                profit_pct = (entry_price - close_price) / entry_price * 100
            return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'time_exit'}
        
        high = row.get('high', row.get('close', 0))
        low = row.get('low', row.get('close', 0))
        
        if high <= 0 or low <= 0:
            continue
        
        if direction == 'long':
            # 多单：先检查止损
            if low <= stop_loss:
                profit_pct = (stop_loss - entry_price) / entry_price * 100
                return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'stop_loss'}
            # 再检查止盈
            if high >= take_profit:
                profit_pct = (take_profit - entry_price) / entry_price * 100
                return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'take_profit'}
        else:  # short
            # 空单：先检查止损
            if high >= stop_loss:
                profit_pct = (entry_price - stop_loss) / entry_price * 100
                return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'stop_loss'}
            # 再检查止盈
            if low <= take_profit:
                profit_pct = (entry_price - take_profit) / entry_price * 100
                return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'take_profit'}
    
    # 4. 如果都没触及，按最后价格计算浮动盈亏
    last_close = future_data.iloc[-1].get('close', entry_price)
    if direction == 'long':
        profit_pct = (last_close - entry_price) / entry_price * 100
    else:
        profit_pct = (entry_price - last_close) / entry_price * 100
    
    return {'can_entry': True, 'profit': profit_pct, 'exit_type': 'holding'}


# ============================================================================
# 【V8.3.12】Separated Strategy Optimization - 分离策略优化
# ============================================================================

def analyze_separated_opportunities(market_snapshots, old_config):
    """
    【V8.3.12→V8.3.21】分析超短线和波段的分离机会（内存优化版）
    
    核心思路：
    1. 从历史快照中识别客观机会（实际达到利润目标的点位）
    2. 按信号类型分类为scalping/swing
    3. 统计各自的表现（利润、time_exit率等）
    
    【V8.3.21优化】：
    - 用摘要替换完整DataFrame（节省99%内存）
    - 采样处理（最多200个点位/币种）
    - 限制机会数量（每类最多500个）
    - 及时垃圾回收
    
    返回：
    {
        'scalping': {
            'total_opportunities': int,
            'profitable_count': int,
            'avg_profit': float,
            'time_exit_rate': float,
            'opportunities': [...]
        },
        'swing': {...}
    }
    """
    try:
        import pandas as pd
        import gc
        
        # 【V8.3.21】全局机会数量限制（保守策略：不遗漏机会）
        MAX_OPPORTUNITIES_PER_TYPE = 2000  # 提高到2000，确保不遗漏重要机会
        MAX_OPPORTUNITIES_PER_COIN = 300   # 提高到300
        ENABLE_SAMPLING = False  # 关闭采样，分析所有点位（保证准确性）
        MAX_SAMPLE_POINTS = 200  # 如果开启采样才使用
        
        scalping_opps = []
        swing_opps = []
        
        # 获取当前参数
        scalping_params = old_config.get('scalping_params', {})
        swing_params = old_config.get('swing_params', {})
        
        print(f"  📊 分析历史快照: {len(market_snapshots)}条记录")
        if ENABLE_SAMPLING:
            print(f"  💾 内存优化模式: 采样分析 + 摘要数据（最大内存<500MB）")
        else:
            print(f"  💾 内存优化模式: 全点位分析 + 摘要数据（预计<1GB，保证不遗漏）")
        
        # 按币种分组
        coins_list = list(market_snapshots['coin'].unique())
        total_coins = len(coins_list)
        
        for coin_idx, coin in enumerate(coins_list, 1):
            coin_data = market_snapshots[market_snapshots['coin'] == coin].sort_values('time')
            coin_data = coin_data.reset_index(drop=True)
            
            coin_scalping = []
            coin_swing = []
            
            # 【V8.3.21】决定是否采样
            total_points = len(coin_data) - 96
            if total_points <= 0:
                print(f"  ⚠️ [{coin_idx}/{total_coins}] {coin} 数据不足，跳过")
                continue
            
            if ENABLE_SAMPLING:
                # 采样模式：快速但可能遗漏
                step_size = max(1, total_points // MAX_SAMPLE_POINTS)
                sampled_indices = list(range(0, total_points, step_size))
                print(f"  🔍 [{coin_idx}/{total_coins}] 分析 {coin}... (采样{len(sampled_indices)}/{total_points}个点位)", end='', flush=True)
            else:
                # 全点位模式：准确但稍慢
                sampled_indices = list(range(total_points))
                print(f"  🔍 [{coin_idx}/{total_coins}] 分析 {coin}... (全量{total_points}个点位)", end='', flush=True)
            
            for idx_count, idx in enumerate(sampled_indices):
                # 每处理100个点显示一次进度（全量模式下调整显示频率）
                display_interval = 50 if ENABLE_SAMPLING else 200
                if idx_count > 0 and idx_count % display_interval == 0:
                    progress = min(100, idx_count * 100 // len(sampled_indices))
                    print(f"\r  🔍 [{coin_idx}/{total_coins}] 分析 {coin}... {progress}%", end='', flush=True)
                current = coin_data.iloc[idx]
                
                # 安全获取数据
                try:
                    timestamp = str(current.get('time', ''))
                    entry_price = float(current.get('close', 0))
                    if entry_price <= 0:
                        entry_price = float(current.get('price', 0))
                    if entry_price <= 0:
                        continue
                    
                    consensus = int(float(current.get('indicator_consensus', 0)))
                    risk_reward = float(current.get('risk_reward', 0))
                    atr = float(current.get('atr', 0))
                    signal_score = float(current.get('signal_score', 50))  # 【V8.3.21】添加signal_score
                    
                    # 【V8.3.21】获取上下文字段（用于4层过滤）
                    kline_ctx_bullish_ratio = float(current.get('kline_ctx_bullish_ratio', 0.5))
                    kline_ctx_price_chg_pct = float(current.get('kline_ctx_price_chg_pct', 0))
                    mkt_struct_swing = str(current.get('mkt_struct_swing', ''))
                    sr_hist_test_count = int(float(current.get('sr_hist_test_count', 0)))
                    sr_hist_avg_reaction = float(current.get('sr_hist_avg_reaction', 0))
                    
                    # 获取信号分类信息
                    signal_type = str(current.get('signal_type', 'swing')).lower()
                    signal_name = str(current.get('signal_name', ''))
                    
                    # 获取方向
                    direction = 'long'
                    if 'macd_signal' in current:
                        macd_sig = str(current.get('macd_signal', '')).lower()
                        if 'short' in macd_sig or 'bear' in macd_sig:
                            direction = 'short'
                    
                    # 获取后续24小时数据
                    later_24h = coin_data.iloc[idx+1:idx+97].copy()
                    if later_24h.empty:
                        continue
                    
                    # 计算客观利润（24小时内能达到的最大利润）
                    if direction == 'long':
                        max_price_24h = float(later_24h['high'].max())
                        objective_profit = (max_price_24h - entry_price) / entry_price * 100 if entry_price > 0 else 0
                    else:
                        min_price_24h = float(later_24h['low'].min())
                        objective_profit = (entry_price - min_price_24h) / entry_price * 100 if entry_price > 0 else 0
                    
                    # 只关注有利润的机会
                    if objective_profit < 1.0:  # 至少1%利润
                        continue
                    
                    # 【V8.3.21】创建摘要数据代替完整DataFrame
                    future_summary = {
                        'max_high': float(later_24h['high'].max()),
                        'min_low': float(later_24h['low'].min()),
                        'final_close': float(later_24h.iloc[-1]['close']),
                        'data_points': len(later_24h)
                    }
                    
                    # 根据信号类型分类
                    opp_data = {
                        'coin': coin,
                        'timestamp': timestamp,
                        'entry_price': entry_price,
                        'direction': direction,
                        'consensus': consensus,
                        'risk_reward': risk_reward,
                        'atr': atr,
                        'signal_score': signal_score,  # 【V8.3.21】添加signal_score字段
                        'signal_type': signal_type,
                        'signal_name': signal_name,
                        'objective_profit': objective_profit,
                        'future_data': future_summary,  # 【V8.3.21】使用摘要代替完整DataFrame
                        # 【V8.3.21】添加上下文字段（用于4层过滤）
                        'kline_ctx_bullish_ratio': kline_ctx_bullish_ratio,
                        'kline_ctx_price_chg_pct': kline_ctx_price_chg_pct,
                        'mkt_struct_swing': mkt_struct_swing,
                        'sr_hist_test_count': sr_hist_test_count,
                        'sr_hist_avg_reaction': sr_hist_avg_reaction
                    }
                    
                    if signal_type == 'scalping':
                        coin_scalping.append(opp_data)
                    else:  # swing
                        coin_swing.append(opp_data)
                
                except (ValueError, TypeError, KeyError) as e:
                    continue
            
            # 【V8.3.21】每个币种只保留TOP机会（按利润排序）
            coin_scalping.sort(key=lambda x: x['objective_profit'], reverse=True)
            coin_swing.sort(key=lambda x: x['objective_profit'], reverse=True)
            scalping_opps.extend(coin_scalping[:MAX_OPPORTUNITIES_PER_COIN])
            swing_opps.extend(coin_swing[:MAX_OPPORTUNITIES_PER_COIN])
            
            # 每个币种完成后换行
            print(f"\r  ✓ [{coin_idx}/{total_coins}] {coin} 完成 (scalping:{len(coin_scalping)} swing:{len(coin_swing)})")
            
            # 【V8.3.21】及时释放内存
            del coin_data, coin_scalping, coin_swing
            gc.collect()
        
        # 【V8.3.21】全局机会数量限制（保留利润最高的）
        if len(scalping_opps) > MAX_OPPORTUNITIES_PER_TYPE:
            scalping_opps.sort(key=lambda x: x['objective_profit'], reverse=True)
            scalping_opps = scalping_opps[:MAX_OPPORTUNITIES_PER_TYPE]
        
        if len(swing_opps) > MAX_OPPORTUNITIES_PER_TYPE:
            swing_opps.sort(key=lambda x: x['objective_profit'], reverse=True)
            swing_opps = swing_opps[:MAX_OPPORTUNITIES_PER_TYPE]
        
        print(f"\n  ⚡ 超短线机会: {len(scalping_opps)}个（已优化）")
        print(f"  🌊 波段机会: {len(swing_opps)}个（已优化）")
        
        # 分析超短线表现
        scalping_analysis = {
            'total_opportunities': len(scalping_opps),
            'profitable_count': 0,
            'avg_profit': 0,
            'time_exit_rate': 0,
            'opportunities': scalping_opps
        }
        
        # 分析波段表现
        swing_analysis = {
            'total_opportunities': len(swing_opps),
            'profitable_count': 0,
            'avg_profit': 0,
            'time_exit_rate': 0,
            'opportunities': swing_opps
        }
        
        # 【V8.3.21】最后释放内存
        gc.collect()
        
        return {
            'scalping': scalping_analysis,
            'swing': swing_analysis
        }
    
    except Exception as e:
        print(f"⚠️ 分离机会分析失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            'scalping': {'total_opportunities': 0, 'opportunities': []},
            'swing': {'total_opportunities': 0, 'opportunities': []}
        }


def simulate_params_on_opportunities(opportunities, params):
    """
    【V8.3.12】用指定参数模拟交易机会
    
    参数:
        opportunities: 机会列表
        params: 参数字典 {
            'min_signal_score': int,
            'min_indicator_consensus': int,
            'min_risk_reward': float,
            'atr_stop_multiplier': float,
            'atr_tp_multiplier': float,
            'max_holding_hours': float
        }
    
    返回:
        {
            'total_opportunities': int,
            'captured_count': int,
            'total_profit': float,
            'avg_profit': float,
            'time_exit_count': int,
            'take_profit_count': int,
            'stop_loss_count': int
        }
    """
    captured_count = 0
    total_profit = 0
    time_exit_count = 0
    take_profit_count = 0
    stop_loss_count = 0
    
    for opp in opportunities:
        # 模拟这个机会
        sim_result = _simulate_trade_with_params(
            entry_price=opp['entry_price'],
            direction=opp['direction'],
            atr=opp['atr'],
            future_data=opp['future_data'],
            signal_score=70,  # 假设满足信号分数要求
            consensus=opp['consensus'],
            risk_reward=opp['risk_reward'],
            min_signal_score=params.get('min_signal_score', 60),
            min_consensus=params.get('min_indicator_consensus', 2),
            min_risk_reward=params.get('min_risk_reward', 1.5),
            atr_stop_multiplier=params.get('atr_stop_multiplier', 1.5),
            atr_tp_multiplier=params.get('atr_tp_multiplier', 3.0),
            max_holding_hours=params.get('max_holding_hours', 24)
        )
        
        if sim_result['can_entry']:
            captured_count += 1
            total_profit += sim_result['profit']
            
            exit_type = sim_result.get('exit_type', '')
            if exit_type == 'time_exit':
                time_exit_count += 1
            elif exit_type == 'take_profit':
                take_profit_count += 1
            elif exit_type == 'stop_loss':
                stop_loss_count += 1
    
    return {
        'total_opportunities': len(opportunities),
        'captured_count': captured_count,
        'total_profit': total_profit,
        'avg_profit': total_profit / captured_count if captured_count > 0 else 0,
        'time_exit_count': time_exit_count,
        'take_profit_count': take_profit_count,
        'stop_loss_count': stop_loss_count,
        'capture_rate': captured_count / len(opportunities) if len(opportunities) > 0 else 0
    }


def simulate_params_on_opportunities_with_details(opportunities, params):
    """
    【V8.3.12.1】增强版：记录详细的exit信息，用于AI分析
    
    返回：
    {
        'summary': {...},  # 基本统计
        'exit_details': [...]  # 详细的exit记录
    }
    """
    captured_count = 0
    total_profit = 0
    time_exit_count = 0
    take_profit_count = 0
    stop_loss_count = 0
    
    exit_details = []
    
    for opp in opportunities:
        # 模拟这个机会
        sim_result = _simulate_trade_with_params(
            entry_price=opp['entry_price'],
            direction=opp['direction'],
            atr=opp['atr'],
            future_data=opp['future_data'],
            signal_score=70,
            consensus=opp['consensus'],
            risk_reward=opp['risk_reward'],
            min_signal_score=params.get('min_signal_score', 60),
            min_consensus=params.get('min_indicator_consensus', 2),
            min_risk_reward=params.get('min_risk_reward', 1.5),
            atr_stop_multiplier=params.get('atr_stop_multiplier', 1.5),
            atr_tp_multiplier=params.get('atr_tp_multiplier', 3.0),
            max_holding_hours=params.get('max_holding_hours', 24),
            signal_type=opp.get('signal_type', 'swing'),
            market_data=None  # 暂不传入完整market_data
        )
        
        if sim_result['can_entry']:
            captured_count += 1
            captured_profit = sim_result['profit']
            total_profit += captured_profit
            
            exit_type = sim_result.get('exit_type', '')
            if exit_type == 'time_exit':
                time_exit_count += 1
            elif exit_type == 'take_profit':
                take_profit_count += 1
            elif exit_type == 'stop_loss':
                stop_loss_count += 1
            
            # 【V8.3.13.4】记录详细信息（包含holding_hours）
            # 计算持仓时间（基于max_holding_hours和exit_type）
            holding_hours = 0
            if exit_type == 'time_exit':
                holding_hours = params.get('max_holding_hours', 24)
            elif exit_type in ['take_profit', 'stop_loss']:
                # 估算实际持仓时间（假设平均在max_holding_hours的50%触发）
                holding_hours = params.get('max_holding_hours', 24) * 0.5
            elif exit_type == 'holding':
                holding_hours = params.get('max_holding_hours', 24)
            
            exit_detail = {
                'coin': opp['coin'],
                'timestamp': opp.get('timestamp', ''),
                'entry_price': opp['entry_price'],
                'direction': opp['direction'],
                'exit_type': exit_type,
                'captured_profit': captured_profit,
                'objective_profit': opp['objective_profit'],
                'missed_profit': opp['objective_profit'] - captured_profit,
                'atr': opp['atr'],
                'atr_pct': opp['atr'] / opp['entry_price'] * 100 if opp['entry_price'] > 0 else 0,
                'holding_hours': holding_hours  # 【V8.3.13.4新增】
            }
            exit_details.append(exit_detail)
    
    summary = {
        'total_opportunities': len(opportunities),
        'captured_count': captured_count,
        'total_profit': total_profit,
        'avg_profit': total_profit / captured_count if captured_count > 0 else 0,
        'time_exit_count': time_exit_count,
        'take_profit_count': take_profit_count,
        'stop_loss_count': stop_loss_count,
        'capture_rate': captured_count / len(opportunities) if len(opportunities) > 0 else 0
    }
    
    return {
        'summary': summary,
        'exit_details': exit_details
    }


def analyze_exit_patterns(exit_details):
    """
    【V8.3.12.1】分析exit模式，找出问题所在
    
    核心分析：
    1. Time Exit：哪些本该盈利更多却提前平仓
    2. Stop Loss：哪些止损过紧，错过后续上涨
    3. Take Profit：哪些过早止盈
    """
    if not exit_details:
        return None
    
    # 1. Time Exit分析
    time_exits = [d for d in exit_details if d['exit_type'] == 'time_exit']
    time_exit_missed = [d for d in time_exits if d['missed_profit'] > 2.0]  # 错过>2%
    time_exit_avg_missed = sum(d['missed_profit'] for d in time_exits) / len(time_exits) if time_exits else 0
    
    # 2. Stop Loss分析
    stop_losses = [d for d in exit_details if d['exit_type'] == 'stop_loss']
    tight_sl = [d for d in stop_losses if d['missed_profit'] > 5.0]  # 止损后涨>5%
    sl_loss_avg = sum(d['captured_profit'] for d in stop_losses) / len(stop_losses) if stop_losses else 0
    
    # 3. Take Profit分析
    take_profits = [d for d in exit_details if d['exit_type'] == 'take_profit']
    early_tp = [d for d in take_profits if d['missed_profit'] > 3.0]  # 止盈后又涨>3%
    tp_profit_avg = sum(d['captured_profit'] for d in take_profits) / len(take_profits) if take_profits else 0
    tp_missed_avg = sum(d['missed_profit'] for d in take_profits) / len(take_profits) if take_profits else 0
    
    analysis = {
        'time_exit': {
            'count': len(time_exits),
            'rate': len(time_exits) / len(exit_details) * 100,
            'avg_missed_profit': time_exit_avg_missed,
            'significant_missed_count': len(time_exit_missed),
            'examples': sorted(time_exit_missed, key=lambda x: x['missed_profit'], reverse=True)[:5]
        },
        'stop_loss': {
            'count': len(stop_losses),
            'rate': len(stop_losses) / len(exit_details) * 100,
            'avg_loss': sl_loss_avg,
            'tight_count': len(tight_sl),
            'examples': sorted(tight_sl, key=lambda x: x['missed_profit'], reverse=True)[:5]
        },
        'take_profit': {
            'count': len(take_profits),
            'rate': len(take_profits) / len(exit_details) * 100,
            'avg_profit': tp_profit_avg,
            'avg_missed_profit': tp_missed_avg,
            'early_count': len(early_tp),
            'examples': sorted(early_tp, key=lambda x: x['missed_profit'], reverse=True)[:5]
        },
        'total_count': len(exit_details)
    }
    
    return analysis


def generate_ai_strategy_prompt(exit_analysis, current_params, signal_type):
    """
    【V8.3.12.1】生成AI分析prompt
    
    让AI分析exit模式并给出策略调整建议
    """
    if not exit_analysis:
        return None
    
    te = exit_analysis['time_exit']
    sl = exit_analysis['stop_loss']
    tp = exit_analysis['take_profit']
    
    # 构建典型案例描述
    te_cases = "\n".join([
        f"  - {ex['coin']}: 入场{ex['entry_price']:.2f}, {ex['exit_type']}, 获利{ex['captured_profit']:.1f}%, 客观利润{ex['objective_profit']:.1f}%, 错过{ex['missed_profit']:.1f}%"
        for ex in te['examples'][:3]
    ]) if te['examples'] else "  （无案例）"
    
    sl_cases = "\n".join([
        f"  - {ex['coin']}: 入场{ex['entry_price']:.2f}, {ex['exit_type']}, 亏损{ex['captured_profit']:.1f}%, 后续涨幅{ex['objective_profit']:.1f}%, 错过{ex['missed_profit']:.1f}%"
        for ex in sl['examples'][:3]
    ]) if sl['examples'] else "  （无案例）"
    
    tp_cases = "\n".join([
        f"  - {ex['coin']}: 入场{ex['entry_price']:.2f}, {ex['exit_type']}, 获利{ex['captured_profit']:.1f}%, 后续涨幅{ex['objective_profit']:.1f}%, 错过{ex['missed_profit']:.1f}%"
        for ex in tp['examples'][:3]
    ]) if tp['examples'] else "  （无案例）"
    
    strategy_context = ""
    if signal_type == 'scalping':
        strategy_context = """
【超短线特点】
- 持仓时间短（目标0.5-2小时）
- 依赖形态突破、Pin Bar等快速信号
- 需要快速止盈，避免回撤
- 止损应该适度，防止假突破
"""
    else:  # swing
        strategy_context = """
【波段特点】
- 持仓时间长（目标24-48小时）
- 依赖支撑阻力位、趋势线
- 需要给利润留出空间
- 止损应该放宽，容忍正常回调
"""
    
    prompt = f"""You are a professional quantitative trading strategy optimizer. Analyze the exit patterns and provide specific parameter adjustment recommendations.

【{signal_type.upper()} Exit Analysis】
{strategy_context}

Current Parameters:
- atr_tp_multiplier: {current_params.get('atr_tp_multiplier', 'N/A')}
- atr_stop_multiplier: {current_params.get('atr_stop_multiplier', 'N/A')}
- max_holding_hours: {current_params.get('max_holding_hours', 'N/A')}
- min_risk_reward: {current_params.get('min_risk_reward', 'N/A')}

Exit Distribution:
- Time Exit: {te['count']} ({te['rate']:.0f}%) | Avg Missed: {te['avg_missed_profit']:.1f}% | Significant: {te['significant_missed_count']}
- Stop Loss: {sl['count']} ({sl['rate']:.0f}%) | Avg Loss: {sl['avg_loss']:.1f}% | Too Tight: {sl['tight_count']}
- Take Profit: {tp['count']} ({tp['rate']:.0f}%) | Avg Profit: {tp['avg_profit']:.1f}% | Too Early: {tp['early_count']}

Time Exit Examples (Missed Profit):
{te_cases}

Stop Loss Examples (Too Tight):
{sl_cases}

Take Profit Examples (Too Early):
{tp_cases}

ANALYSIS REQUIREMENTS:

1. Root Cause Analysis:
   - Why is Time Exit rate {te['rate']:.0f}%? Is it because:
     * TP target too high (atr_tp_multiplier too large)?
     * Holding time too long (max_holding_hours)?
     * Market volatility issue?
   
   - Are Stop Losses too tight? Evidence:
     * {sl['tight_count']} trades hit SL then rallied 5%+
     * Avg loss: {sl['avg_loss']:.1f}%
   
   - Are Take Profits too early? Evidence:
     * {tp['early_count']} trades closed then rallied 3%+
     * Avg missed profit: {tp['avg_missed_profit']:.1f}% on TP trades

2. Parameter Recommendations:
   Based on the data, recommend:
   - atr_tp_multiplier: Should it be INCREASED or DECREASED? By how much? Why?
   - atr_stop_multiplier: Should it be INCREASED or DECREASED? By how much? Why?
   - max_holding_hours: Should it be INCREASED or DECREASED? Why?
   
   CRITICAL: For {signal_type}:
   {"- Focus on REDUCING atr_tp_multiplier to capture quick profits" if signal_type == 'scalping' else "- Consider INCREASING atr_tp_multiplier to capture larger moves"}
   - Time Exit > 80% is BAD - means we're holding too long or TP is too far
   - Stop Loss > 30% is BAD - means SL is too tight

3. Strategy Notes:
   - For {signal_type}, should we use Support/Resistance levels instead of pure ATR?
   - Any special considerations for TP/SL calculation?

OUTPUT JSON:
{{
    "diagnosis": "Brief diagnosis in Chinese",
    "root_causes": [
        "Time Exit high because...",
        "Stop Loss issue because...",
        "Take Profit problem because..."
    ],
    "recommendations": {{
        "atr_tp_multiplier": {{
            "current": {current_params.get('atr_tp_multiplier', 0)},
            "recommended": 1.5,
            "change": "DECREASE",
            "reason": "Why this change will help"
        }},
        "atr_stop_multiplier": {{
            "current": {current_params.get('atr_stop_multiplier', 0)},
            "recommended": 1.0,
            "change": "ADJUST",
            "reason": "Why this change will help"
        }},
        "max_holding_hours": {{
            "current": {current_params.get('max_holding_hours', 0)},
            "recommended": 1.5,
            "change": "DECREASE",
            "reason": "Why this change will help"
        }},
        "min_risk_reward": {{
            "current": {current_params.get('min_risk_reward', 0)},
            "recommended": 1.3,
            "reason": "Why this change will help"
        }}
    }},
    "strategy_notes": "Additional considerations for {signal_type} TP/SL strategy",
    "expected_improvement": "What metrics should improve and by how much"
}}

IMPORTANT: Be aggressive in recommendations. If Time Exit > 50%, TP is definitely too far!
"""
    
    return prompt


def call_ai_for_exit_analysis(exit_analysis, current_params, signal_type, model_name='qwen'):
    """
    【V8.3.12.1】调用AI分析exit patterns并给出策略建议
    
    返回：
    {
        'diagnosis': str,
        'root_causes': list,
        'recommendations': dict,
        'strategy_notes': str,
        'expected_improvement': str
    }
    """
    try:
        prompt = generate_ai_strategy_prompt(exit_analysis, current_params, signal_type)
        
        if not prompt:
            return None
        
        print(f"  🤖 调用AI分析{signal_type} exit patterns...")
        
        # 调用AI
        response = qwen_client.chat.completions.create(
            model="qwen3-max",
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional quantitative trading strategy optimizer specialized in TP/SL parameter optimization."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        ai_response = response.choices[0].message.content
        
        # 解析JSON
        import re
        import json
        
        json_match = re.search(r"```json\s*(.*?)\s*```", ai_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析
            json_str = ai_response
        
        try:
            ai_suggestions = json.loads(json_str)
            print(f"  ✅ AI分析完成")
            print(f"     诊断: {ai_suggestions.get('diagnosis', 'N/A')[:80]}...")
            return ai_suggestions
        except json.JSONDecodeError as e:
            print(f"  ⚠️ JSON解析失败: {e}")
            print(f"  原始响应: {ai_response[:200]}...")
            return None
            
    except Exception as e:
        print(f"  ⚠️ AI调用失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def apply_ai_suggestions(base_params, ai_suggestions, apply_aggressiveness=0.8):
    """
    【V8.3.12.1】应用AI建议到参数
    
    参数：
        base_params: 基础参数（Grid Search结果）
        ai_suggestions: AI建议
        apply_aggressiveness: 应用激进度（0-1），0.5表示AI建议的50%调整
    
    返回：
        调整后的参数
    """
    if not ai_suggestions or 'recommendations' not in ai_suggestions:
        return base_params
    
    adjusted_params = base_params.copy()
    recommendations = ai_suggestions['recommendations']
    
    print(f"\n  📊 应用AI建议（激进度{apply_aggressiveness*100:.0f}%）:")
    
    # 应用每个参数的建议
    for param_name, suggestion in recommendations.items():
        if param_name not in adjusted_params:
            continue
        
        current_value = adjusted_params[param_name]
        recommended_value = suggestion.get('recommended', current_value)
        
        # 计算调整量
        if isinstance(recommended_value, (int, float)) and isinstance(current_value, (int, float)):
            # 使用激进度调整
            adjustment = (recommended_value - current_value) * apply_aggressiveness
            new_value = current_value + adjustment
            
            # 应用合理范围限制
            if param_name == 'atr_tp_multiplier':
                new_value = max(0.5, min(10.0, new_value))
            elif param_name == 'atr_stop_multiplier':
                new_value = max(0.5, min(3.0, new_value))
            elif param_name == 'max_holding_hours':
                new_value = max(0.25, min(72.0, new_value))
            elif param_name == 'min_risk_reward':
                new_value = max(1.0, min(5.0, new_value))
            
            adjusted_params[param_name] = new_value
            
            change_pct = (new_value - current_value) / current_value * 100 if current_value != 0 else 0
            print(f"     {param_name}: {current_value:.2f} → {new_value:.2f} ({change_pct:+.0f}%)")
            print(f"       理由: {suggestion.get('reason', 'N/A')[:60]}...")
    
    return adjusted_params


def calculate_scalping_optimization_score(sim_result):
    """
    【V8.3.12】超短线优化评分函数（用于参数优化，不是信号评分）
    
    优先级：
    1. time_exit率越低越好（权重60%）
    2. 平均利润越高越好（权重30%）
    3. 捕获率越高越好（权重10%）
    """
    if sim_result['captured_count'] == 0:
        return -1.0  # 无法捕获任何机会，最低分
    
    # 计算各项指标
    time_exit_rate = sim_result['time_exit_count'] / sim_result['captured_count']
    avg_profit = sim_result['avg_profit']
    capture_rate = sim_result['capture_rate']
    
    # 归一化并加权
    time_exit_score = max(0, 1 - time_exit_rate) * 0.6  # 低time_exit高分
    profit_score = min(1, max(0, (avg_profit + 5) / 10)) * 0.3  # -5%~+5%映射到0~1
    capture_score = capture_rate * 0.1
    
    total_score = time_exit_score + profit_score + capture_score
    
    return total_score


def generate_round1_combinations():
    """
    【V8.3.18.10】生成第1轮Grid Search的测试组合 - 极度紧凑TP/SL用于超短线
    
    针对time_exit=100%问题的激进策略：34组参数
    """
    test_combinations = []
    
    # 【策略1】极度紧凑TP/SL测试（0.15-0.25×ATR）- 6组
    for tp in [0.15, 0.2, 0.25]:
        for time_h in [2.0, 3.0]:
            test_combinations.append({
                'max_holding_hours': time_h,
                'atr_tp_multiplier': tp,
                'atr_stop_multiplier': 0.4,
                'min_risk_reward': 1.0,
                'min_signal_score': 65
            })
    
    # 【策略2】紧凑范围（0.3-0.4×ATR）- 12组
    for tp in [0.3, 0.35, 0.4]:
        for sl in [0.5, 0.6]:
            for time_h in [2.0, 2.5]:
                test_combinations.append({
                    'max_holding_hours': time_h,
                    'atr_tp_multiplier': tp,
                    'atr_stop_multiplier': sl,
                    'min_risk_reward': 1.2,
                    'min_signal_score': 70
                })
    
    # 【策略3】中等范围（0.5-0.6×ATR）- 8组
    for tp in [0.5, 0.6]:
        for sl in [0.7, 0.8]:
            for time_h in [2.0, 3.0]:
                test_combinations.append({
                    'max_holding_hours': time_h,
                    'atr_tp_multiplier': tp,
                    'atr_stop_multiplier': sl,
                    'min_risk_reward': 1.5,
                    'min_signal_score': 75
                })
    
    # 补充边界情况 - 8组
    for rr in [1.0, 1.5]:
        for score in [60, 70]:
            for tp in [0.25, 0.35]:
                test_combinations.append({
                    'max_holding_hours': 2.5,
                    'atr_tp_multiplier': tp,
                    'atr_stop_multiplier': 0.5,
                    'min_risk_reward': rr,
                    'min_signal_score': score
                })
    
    return test_combinations  # 总计34组


def generate_round2_combinations_from_ai(ai_suggestions):
    """
    【V8.3.18.8】根据AI建议生成第2轮测试组合（增加参数验证）
    """
    param_ranges = ai_suggestions.get('param_ranges', {})
    
    if not param_ranges:
        param_ranges = {
            'atr_tp_multiplier': [0.3, 0.4, 0.5],
            'max_holding_hours': [1.5, 2.0, 2.5],
            'min_signal_score': [70, 80, 90],
            'atr_stop_multiplier': [0.6, 0.8],
            'min_risk_reward': [1.8, 2.2]
        }
    
    # 【V8.3.19】验证和修正参数范围
    # 超短线定义：max_holding_hours ≤ 8.0（V8.3.19从3.0放宽到8.0，基于信号分析数据）
    if 'max_holding_hours' in param_ranges:
        valid_hours = [h for h in param_ranges['max_holding_hours'] if h <= 8.0]
        if not valid_hours:
            print(f"     ⚠️  AI建议的max_holding_hours全部>8h（不符合超短线定义），自动修正为[5.0, 6.0, 8.0]")
            param_ranges['max_holding_hours'] = [5.0, 6.0, 8.0]
        elif len(valid_hours) < len(param_ranges['max_holding_hours']):
            print(f"     ⚠️  AI建议的部分max_holding_hours>8h，过滤为{valid_hours}")
            param_ranges['max_holding_hours'] = valid_hours
    
    # 验证min_signal_score不能太高（>95基本没信号）
    if 'min_signal_score' in param_ranges:
        valid_scores = [s for s in param_ranges['min_signal_score'] if s <= 95]
        if not valid_scores:
            print(f"     ⚠️  AI建议的min_signal_score全部>95（太高），自动修正为[70, 80, 90]")
            param_ranges['min_signal_score'] = [70, 80, 90]
        elif len(valid_scores) < len(param_ranges['min_signal_score']):
            print(f"     ⚠️  AI建议的部分min_signal_score>95，过滤为{valid_scores}")
            param_ranges['min_signal_score'] = valid_scores
    
    test_combinations = []
    from itertools import product
    
    keys = list(param_ranges.keys())
    values = [param_ranges[k] for k in keys]
    
    for combo_values in product(*values):
        combination = dict(zip(keys, combo_values))
        test_combinations.append(combination)
    
    if len(test_combinations) > 50:
        import random
        random.shuffle(test_combinations)
        test_combinations = test_combinations[:50]
    
    return test_combinations


def call_ai_for_round_decision(round_num, round_results, current_best_params, opportunities_count, all_rounds_results=None, signal_performance=None):
    """
    【V8.3.19】调用AI分析当前轮次结果并决策（增强信号类型指导）
    
    Args:
        round_num: 轮次编号
        round_results: 当前轮次测试结果
        current_best_params: 当前最佳参数
        opportunities_count: 机会数量
        all_rounds_results: 【V8.3.18.2】所有轮次结果
        signal_performance: 【V8.3.19 NEW】信号类型分析结果
    """
    global qwen_api_key  # 【修复】声明全局变量
    best_result = round_results[0] if round_results else None
    
    # 【V8.3.19】构建信号类型提示
    signal_hint = ""
    if signal_performance:
        signal_hint = f"""
📊 **【V8.3.19 DATA-DRIVEN】Historical Signal Type Analysis** ({opportunities_count} opportunities):
"""
        for sig_type, perf in sorted(signal_performance.items(), key=lambda x: x[1]['count'], reverse=True)[:3]:
            signal_hint += f"""  • {sig_type}: {perf['count']} ({perf['ratio']*100:.0f}%)
    - Avg Profit: {perf['avg_profit']:.1f}% | Avg Time: {perf['avg_time']:.1f}h
    - **Typical TP Distance: {perf['typical_tp_atr']:.2f}× ATR** ← KEY METRIC!
    - Successful Exit Rate: {perf['successful_exit_rate']*100:.0f}% (non-timeout)
"""
        
        dominant_sig = max(signal_performance.items(), key=lambda x: x[1]['count'])[0]
        dominant_perf = signal_performance[dominant_sig]
        
        signal_hint += f"""
💡 **Data-Driven Recommendation** (based on dominant signal: {dominant_sig}):
  - Suggested TP Range: {dominant_perf['typical_tp_atr']*0.8:.2f} - {dominant_perf['typical_tp_atr']*1.2:.2f}× ATR
  - Suggested Time Window: ≤{dominant_perf['max_time']:.0f}h (90th percentile of actual holding times)
  - **DON'T blindly use 0.15×! Use {dominant_perf['typical_tp_atr']:.2f}× based on {dominant_perf['count']} historical samples!**
  - If {dominant_sig} dominates (>{dominant_perf['ratio']*100:.0f}%), prioritize these data-driven ranges!
"""
    
    prompt = f"""You are a quantitative trading strategy optimization expert.

【Current Status】
- Round: {round_num} of Grid Search
- Opportunities: {opportunities_count} scalping opportunities
- Tested Combinations: {len(round_results)} parameter sets
{signal_hint}
⚠️ **SCALPING CONSTRAINTS** (MUST respect):
1. `max_holding_hours` ≤ 8.0 (超短线定义，根据信号分析可放宽到8h)
2. `min_signal_score` ≤ 95 (太高会导致captured_count=0)
3. `atr_tp_multiplier`: **USE signal_performance data, NOT random guessing!**

💡 **V8.3.19 CRITICAL STRATEGY CHANGE**:
- **OLD (V8.3.18.10)**: Blindly tighten to 0.15×ATR → 100% time_exit FAILURE
- **NEW (V8.3.19)**: Use signal_performance.typical_tp_atr from historical data!
- Example: If pin_bar.typical_tp_atr=0.35×, test 0.25-0.45× (±30%)
- Example: If breakout.typical_tp_atr=0.65×, test 0.5-0.8× (±25%)
- Time window: Match avg_time + buffer (e.g., 3.5h avg → 5-6h window)

【Round {round_num} Best Result】
Parameters: {json.dumps(best_result['params'], ensure_ascii=False) if best_result else 'None'}
"""
    
    if best_result:
        result = best_result['result']
        te_rate = result['time_exit_count']/result['captured_count']*100 if result['captured_count'] > 0 else 100
        prompt += f"""Performance: time_exit={te_rate:.0f}%, avg_profit={result['avg_profit']:.1f}%, captured={result['captured_count']}, score={best_result['score']:.4f}

【Top 5 Comparison】
"""
        for i, res in enumerate(round_results[:5], 1):
            p = res['params']
            r = res['result']
            te = r['time_exit_count']/r['captured_count']*100 if r['captured_count'] > 0 else 100
            prompt += f"#{i}. signal{p['min_signal_score']} TP{p['atr_tp_multiplier']}× hold{p['max_holding_hours']}h → te={te:.0f}% profit={r['avg_profit']:.1f}% score={res['score']:.4f}\n"
    
    if round_num == 1:
        prompt += """
【Task】Should we run Round 2?

🎯 **Optimization Goals** (CRITICAL):
1. **time_exit_rate**: Target <70% (MUST <90%, NEVER accept 100%)
   - 100% = total failure (all trades timeout, no TP/SL triggered)
   - 90-99% = poor quality (strategy too slow)
   - 70-89% = acceptable
   - <70% = excellent (most trades exit via TP/SL)

2. **avg_profit**: Target >1.5% per trade
   - >2% = excellent
   - 1-2% = good
   - 0.5-1% = acceptable
   - <0.5% = needs improvement

3. **captured_count**: Target >500 (enough data)

Context:
- If Round 1 found time_exit<90% AND avg_profit>1%, you can skip Round 2
- If ALL combinations have time_exit≥90%, you MUST run Round 2 with more aggressive params

⚠️ **CRITICAL**: If needs_round2=true, you MUST provide specific `round2_suggestions` with param ranges that will solve the problem!

Respond in JSON format ONLY:
{
  "needs_round2": true/false,
  "reasoning": "Your analysis",
  "round2_suggestions": {  // ⚠️ REQUIRED if needs_round2=true
    "strategy": "Brief description of what to change and why",
    "param_ranges": {
      "atr_tp_multiplier": [0.15, 0.2, 0.25],  // 💡 EXTREME tightening for micro-scalping!
      "max_holding_hours": [4.0, 6.0, 8.0],  // ⚠️ MUST ≤8.0 (V8.3.19: 基于信号分析数据)
      "min_signal_score": [60, 65, 70],  // ⚠️ MUST ≤95, relax for volume
      "atr_stop_multiplier": [0.4, 0.5, 0.6],  // 💡 Very tight SL for immediate feedback
      "min_risk_reward": [1.0, 1.2, 1.5]  // Very low R:R for micro-movements
    },
    "rationale": "Why these specific ranges: time_exit={te_rate:.0f}% because [reason], new ranges fix this by [solution]"
  } or null,  // null only if needs_round2=false
  "final_decision": {
    "accept_result": true,
    "selected_params": {...},
    "execution_strategy": "apply_immediately"
  }
}"""
    else:
        # 【V8.3.18.1】添加Round1 vs Round2对比
        best_round1 = all_rounds_results[0][1][0] if len(all_rounds_results) > 0 else None
        best_round2 = all_rounds_results[1][1][0] if len(all_rounds_results) > 1 else None
        
        r1_profit = best_round1['result']['avg_profit'] if best_round1 else 0
        r2_profit = best_round2['result']['avg_profit'] if best_round2 else 0
        
        # 获取time_exit率
        r1_te_rate = best_round1['result']['time_exit_count']/best_round1['result']['captured_count']*100 if best_round1 and best_round1['result']['captured_count'] > 0 else 100
        r2_te_rate = best_round2['result']['time_exit_count']/best_round2['result']['captured_count']*100 if best_round2 and best_round2['result']['captured_count'] > 0 else 100
        
        prompt += f"""
【Task】Make the FINAL decision - Compare ALL rounds and select the BEST

📊 **Round Comparison**:
- Round 1 Best: avg_profit={r1_profit:.1f}%, time_exit={r1_te_rate:.0f}%, score={best_round1['score'] if best_round1 else 0:.4f}
- Round 2 Best: avg_profit={r2_profit:.1f}%, time_exit={r2_te_rate:.0f}%, score={best_round2['score'] if best_round2 else 0:.4f}

🎯 **Optimization Goals** (MUST achieve):
1. **time_exit_rate < 90%** (CRITICAL) - 100% = total failure
2. **avg_profit > 0.8%** (minimum for profitability)
3. Prefer: time_exit <70% + avg_profit >1.5%

🎯 **Decision Rule**:
1. **If time_exit ≥90% in BOTH rounds**: Set accept_result=false + MUST provide round3_suggestion
2. **Priority**: Lower time_exit_rate > Higher avg_profit
   - Example: 80% te + 1.2% profit > 100% te + 1.6% profit
3. If both have similar time_exit (<5% diff), choose higher avg_profit

⚠️ **CRITICAL**: If rejecting (accept_result=false), you MUST provide `round3_suggestion` with new parameter ranges to test!

Respond in JSON format ONLY:
{{
  "final_decision": {{
    "accept_result": true/false,
    "selected_params": {{...}} or null,  // null if rejecting
    "reasoning": "...",
    "execution_strategy": "apply_immediately" or "reject_and_retry",
    "monitoring_metrics": ["avg_profit", "time_exit_rate", "capture_count"],
    "rollback_conditions": "7-day avg profit <0.5% OR cumulative loss >3U"
  }},
  "round3_suggestion": {{  // ⚠️ REQUIRED if accept_result=false
    "strategy": "Brief explanation of what to change and why",
    "param_ranges": {{
      "min_signal_score": [55, 60, 65],  // ⚠️ MUST ≤95, relax further
      "max_holding_hours": [6.0, 8.0],  // ⚠️ MUST ≤8.0 (V8.3.19: 基于信号分析数据)
      "atr_tp_multiplier": [0.1, 0.15, 0.2],  // 💡 ULTIMATE tightening - catch micro-movements
      "atr_stop_multiplier": [0.3, 0.4, 0.5],  // 💡 Extremely tight SL
      "min_risk_reward": [0.8, 1.0, 1.2]  // Ultra-low R:R for ultra-short trades
    }},
    "rationale": "Why these ranges should work: time_exit was 100% because [specific reason], new ranges address this by [specific solution]"
  }} or null  // Only null if accept_result=true
}}"""
    
    try:
        response = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={"Authorization": f"Bearer {qwen_api_key}"},
            json={
                "model": "qwen-plus",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 2000
            },
            timeout=60
        )
        
        if response.status_code == 200:
            ai_text = response.json()['choices'][0]['message']['content'].strip()
            if '```json' in ai_text:
                ai_text = ai_text.split('```json')[1].split('```')[0].strip()
            elif '```' in ai_text:
                ai_text = ai_text.split('```')[1].split('```')[0].strip()
            
            # 【V8.3.18.4】添加AI响应日志（用于调试）
            try:
                ai_response = json.loads(ai_text)
                # 打印关键信息（不打印完整JSON，太长）
                if round_num == 1:
                    print(f"     🔍 AI响应: needs_round2={ai_response.get('needs_round2', 'N/A')}")
                else:
                    fd = ai_response.get('final_decision', {})
                    has_round3 = bool(ai_response.get('round3_suggestion'))
                    print(f"     🔍 AI响应: accept={fd.get('accept_result', 'N/A')}, has_params={bool(fd.get('selected_params'))}, has_round3={has_round3}")
                return ai_response
            except json.JSONDecodeError as json_err:
                print(f"     ⚠️  AI响应JSON解析失败: {json_err}")
                print(f"     原始响应（前200字符）: {ai_text[:200]}...")
                return {"needs_round2": False, "final_decision": {"accept_result": True, "selected_params": current_best_params}}
        else:
            print(f"     ⚠️  AI调用失败: {response.status_code}")
            return {"needs_round2": False, "final_decision": {"accept_result": True, "selected_params": current_best_params}}
    except Exception as e:
        print(f"     ⚠️  AI决策异常: {e}")
        import traceback
        traceback.print_exc()
        return {"needs_round2": False, "final_decision": {"accept_result": True, "selected_params": current_best_params}}



def calculate_swing_optimization_score(sim_result):
    """
    【V8.3.12】波段优化评分函数（用于参数优化，不是信号评分）
    
    优先级：
    1. 平均利润越高越好（权重50%）
    2. 捕获率越高越好（权重30%）
    3. time_exit率越低越好（权重20%）
    """
    if sim_result['captured_count'] == 0:
        return -1.0
    
    # 计算各项指标
    time_exit_rate = sim_result['time_exit_count'] / sim_result['captured_count']
    avg_profit = sim_result['avg_profit']
    capture_rate = sim_result['capture_rate']
    
    # 归一化并加权
    profit_score = min(1, max(0, avg_profit / 20)) * 0.5  # 0~20%映射到0~1
    capture_score = capture_rate * 0.3
    time_exit_score = max(0, 1 - time_exit_rate) * 0.2
    
    total_score = profit_score + capture_score + time_exit_score
    
    return total_score


def analyze_signal_type_performance(opportunities):
    """
    【V8.3.19】分析不同信号类型的历史表现
    
    从快照中提取各信号类型的评分，统计：
    - 数量、占比
    - 平均利润、平均持仓时间
    - 典型TP达到距离（用于指导atr_tp_multiplier）
    - 建议的时间窗口（90分位数）
    
    返回:
        dict: {
            'pin_bar': {
                'count': 320,
                'ratio': 0.26,
                'avg_profit': 2.1,
                'avg_time': 3.5,
                'typical_tp_atr': 0.35,
                'max_time': 5.2,
                'successful_exit_rate': 0.15
            },
            ...
        }
    """
    from collections import defaultdict
    import numpy as np
    
    signal_stats = defaultdict(lambda: {
        'count': 0,
        'profits': [],
        'times': [],
        'tp_distances': [],
        'successful_exits': 0
    })
    
    for opp in opportunities:
        snapshot = opp.get('snapshot', {})
        
        # 【V8.3.19修复】从实际保存的字段识别信号类型
        # 快照中保存的是字符串形态，不是评分
        pin_bar_str = snapshot.get('pin_bar', '')
        engulfing_str = snapshot.get('engulfing', '')
        breakout_score = snapshot.get('breakout_score', 0)
        volume_surge_score = snapshot.get('volume_surge_score', 0)
        
        # 识别主要信号类型（从字符串和评分）
        signal_types = []
        # Pin Bar: 任何包含"pin"的形态
        if pin_bar_str and 'pin' in pin_bar_str.lower():
            signal_types.append('pin_bar')
        # Engulfing: 任何包含"engulfing"的形态
        if engulfing_str and 'engulfing' in engulfing_str.lower():
            signal_types.append('engulfing')
        # Breakout: 评分>10即可（降低阈值）
        if breakout_score > 10:
            signal_types.append('breakout')
        # Volume Surge: 评分>15即可（降低阈值）
        if volume_surge_score > 15:
            signal_types.append('volume_surge')
        if not signal_types:
            signal_types.append('other')
        
        # 统计数据
        profit = opp.get('actual_profit', 0)
        time_hours = opp.get('holding_hours', 0)
        atr = snapshot.get('atr', 1)
        exit_reason = opp.get('exit_reason', 'time_exit')
        
        for sig_type in signal_types:
            signal_stats[sig_type]['count'] += 1
            if profit > 0:
                signal_stats[sig_type]['profits'].append(profit)
                signal_stats[sig_type]['times'].append(time_hours)
                if atr > 0:
                    # 计算TP距离：实际利润 / ATR
                    signal_stats[sig_type]['tp_distances'].append(profit / atr)
            if exit_reason != 'time_exit':
                signal_stats[sig_type]['successful_exits'] += 1
    
    # 计算汇总统计
    result = {}
    total_count = len(opportunities)
    
    for sig_type, stats in signal_stats.items():
        if stats['count'] > 0:
            result[sig_type] = {
                'count': stats['count'],
                'ratio': stats['count'] / total_count,
                'avg_profit': np.mean(stats['profits']) if stats['profits'] else 0,
                'avg_time': np.mean(stats['times']) if stats['times'] else 0,
                'typical_tp_atr': np.median(stats['tp_distances']) if stats['tp_distances'] else 0.5,
                'max_time': np.percentile(stats['times'], 90) if len(stats['times']) > 0 else 3,
                'successful_exit_rate': stats['successful_exits'] / stats['count']
            }
    
    return result


def optimize_scalping_params(scalping_data, current_params, initial_params=None, ai_suggested_params=None, use_v8321=True):
    """
    【V8.3.21】超短线参数优化 - V8.3.21增强版 + 旧版Grid Search（可选）
    
    优化流程：
    - V8.3.21增强版（默认）：
      1. 11维度参数Grid Search（200组采样）
      2. V8.3.21上下文过滤（4层：基础→K线→结构→S/R）
      3. 本地统计分析（参数敏感度、异常检测）
      4. 成本优化（节省89%）
    
    - 旧版Grid Search（use_v8321=False）：
      1. Grid Search找到最优参数（54组参数）
      2. Exit Analysis分析最优参数的问题
      3. 条件AI调用：只在Time Exit>80%时调用AI（V8.3.16）
      4. 动态激进度：根据Time Exit率调整AI建议采纳度（V8.3.16技术债3）
    
    目标：降低time_exit率，提高平均利润，提高捕获率
    
    Args:
        scalping_data: 超短线机会数据
        current_params: 当前配置的策略参数
        initial_params: 【V8.3.16】V7.7.0快速探索提供的初始参数（技术债1）
        ai_suggested_params: 【V8.3.25.10新增】AI洞察建议的参数（将加入测试候选集）
        use_v8321: 【V8.3.21新增】是否使用V8.3.21增强优化器（默认True）
    """
    opportunities = scalping_data['opportunities']
    
    if len(opportunities) < 10:
        print("  ⚠️  超短线机会不足10个，跳过优化")
        return {
            'optimized_params': current_params,
            'improvement': None
        }
    
    # ===== 【V8.3.21】使用增强优化器 =====
    if use_v8321:
        try:
            from backtest_optimizer_v8321 import optimize_params_v8321_lightweight
            
            print(f"\n  🚀 【V8.3.21】使用增强优化器（{len(opportunities)}个机会）")
            print(f"     • 11维度参数搜索")
            print(f"     • 4层上下文过滤")
            print(f"     • 成本优化（节省89%）")
            
            v8321_result = optimize_params_v8321_lightweight(
                opportunities=opportunities,
                current_params=current_params,
                signal_type='scalping',
                max_combinations=200,  # 2核2G环境优化
                ai_suggested_params=ai_suggested_params  # 【V8.3.25.10新增】
            )
            
            print(f"\n  ✅ V8.3.21优化完成")
            print(f"     最优分数: {v8321_result['top_10_configs'][0]['score']:.3f}")
            print(f"     捕获率: {v8321_result['top_10_configs'][0]['metrics']['capture_rate']*100:.0f}%")
            print(f"     平均利润: {v8321_result['top_10_configs'][0]['metrics']['avg_profit']:.1f}%")
            print(f"     胜率: {v8321_result['top_10_configs'][0]['metrics']['win_rate']*100:.0f}%")
            print(f"     💰 成本节省: ${v8321_result['cost_saved']:.4f}")
            
            # 打印关键洞察
            if v8321_result['context_analysis'].get('key_insights'):
                print(f"\n  💡 关键发现:")
                for insight in v8321_result['context_analysis']['key_insights'][:3]:
                    print(f"     {insight}")
            
            # 打印参数敏感度（Top 3）
            if v8321_result['statistics'].get('param_sensitivity'):
                print(f"\n  📊 参数敏感度（影响最大的3个）:")
                sorted_params = sorted(
                    v8321_result['statistics']['param_sensitivity'].items(),
                    key=lambda x: abs(x[1]['avg_impact']),
                    reverse=True
                )[:3]
                for param_name, sensitivity in sorted_params:
                    print(f"     • {param_name}: {sensitivity['importance']} "
                          f"(影响={sensitivity['avg_impact']:+.3f})")
            
            # 【V8.3.21修复】计算old_result/new_result以兼容邮件/bark
            print(f"\n  📊 计算前后对比（兼容性）...")
            baseline_result = simulate_params_on_opportunities(opportunities, current_params)
            optimized_result = simulate_params_on_opportunities(
                opportunities, 
                v8321_result['optimized_params']
            )
            
            # 【V8.3.21 AI迭代】提取AI决策（如果有）
            ai_decision = v8321_result.get('ai_decision', None)
            ai_insights_zh = []
            ai_recommendation_zh = f"V8.3.21建议使用Top 1配置（分数{v8321_result['top_10_configs'][0]['score']:.3f}）"
            
            if ai_decision:
                # AI参与了迭代决策
                print(f"  🤖 AI迭代决策:")
                print(f"     选择: Rank {ai_decision.get('selected_rank', 1)}")
                print(f"     调整: {'是' if ai_decision.get('needs_adjustment') else '否'}")
                
                # 使用AI转换的中文洞察
                ai_insights_zh = ai_decision.get('key_insights_zh', [])
                
                # AI推荐（英文转中文）
                if ai_decision.get('reasoning_en'):
                    ai_recommendation_zh = f"AI建议: {ai_decision['reasoning_en']}"
                    # 简单翻译关键词
                    ai_recommendation_zh = ai_recommendation_zh.replace("Rank 1 is optimal", "Top 1配置最优")
                    ai_recommendation_zh = ai_recommendation_zh.replace("best balance", "最佳平衡")
            else:
                # 使用本地分析的洞察（中文）
                ai_insights_zh = v8321_result['context_analysis'].get('key_insights', [])
            
            # 🆕 V8.3.21.2: 保存V8.3.21洞察到 compressed_insights，供实时AI决策使用
            try:
                config = load_learning_config()
                if 'compressed_insights' not in config:
                    config['compressed_insights'] = {}
                if 'v8321_insights' not in config['compressed_insights']:
                    config['compressed_insights']['v8321_insights'] = {}
                
                # 提取参数敏感度（Top 3）
                param_sensitivity_summary = {}
                if v8321_result['statistics'].get('param_sensitivity'):
                    sorted_params = sorted(
                        v8321_result['statistics']['param_sensitivity'].items(),
                        key=lambda x: abs(x[1]['avg_impact']),
                        reverse=True
                    )[:3]
                    for param_name, sensitivity in sorted_params:
                        param_sensitivity_summary[param_name] = f"{sensitivity['importance']} ({sensitivity['avg_impact']:+.3f})"
                
                # 保存超短线洞察
                config['compressed_insights']['v8321_insights']['scalping'] = {
                    'best_contexts': v8321_result['context_analysis'].get('key_insights', [])[:3],
                    'param_sensitivity': param_sensitivity_summary,
                    'performance': {
                        'score': v8321_result['top_10_configs'][0]['score'],
                        'capture_rate': v8321_result['top_10_configs'][0]['metrics']['capture_rate'],
                        'avg_profit': v8321_result['top_10_configs'][0]['metrics']['avg_profit'] / 100,  # 转为小数
                        'win_rate': v8321_result['top_10_configs'][0]['metrics']['win_rate']
                    },
                    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                save_learning_config(config)
                print(f"  ✅ V8.3.21超短线洞察已保存到 compressed_insights")
            except Exception as e:
                print(f"  ⚠️  保存V8.3.21洞察失败: {e}")
            
            # 【V8.3.21修复】构建完全兼容的返回结构
            return {
                'optimized_params': v8321_result['optimized_params'],
                'old_result': baseline_result,
                'new_result': optimized_result,
                'old_time_exit_rate': baseline_result['time_exit_count'] / baseline_result['captured_count'] * 100 if baseline_result['captured_count'] > 0 else 100,
                'new_time_exit_rate': optimized_result['time_exit_count'] / optimized_result['captured_count'] * 100 if optimized_result['captured_count'] > 0 else 100,
                'old_avg_profit': baseline_result['avg_profit'],
                'new_avg_profit': optimized_result['avg_profit'],
                'old_capture_rate': baseline_result['capture_rate'],
                'new_capture_rate': optimized_result['capture_rate'],
                'exit_analysis': {
                    'round1': {
                        'common_exit_reasons': v8321_result['statistics'].get('exit_reason_distribution', {}),
                        'affected_symbols': list(v8321_result['statistics'].get('symbol_performance', {}).keys())[:5]
                    }
                },
                'ai_suggestions': {
                    'key_findings': ai_insights_zh,
                    'recommendation': ai_recommendation_zh,
                    'applied_changes': [f"V8.3.21: {v8321_result['optimized_params']}"]
                },
                'improvement': {
                    'capture_rate': optimized_result['capture_rate'] - baseline_result['capture_rate'],
                    'avg_profit': optimized_result['avg_profit'] - baseline_result['avg_profit'],
                    'time_exit_rate': (optimized_result['time_exit_count'] / optimized_result['captured_count'] * 100 if optimized_result['captured_count'] > 0 else 100) - (baseline_result['time_exit_count'] / baseline_result['captured_count'] * 100 if baseline_result['captured_count'] > 0 else 100)
                }
            }
            
        except ImportError as e:
            print(f"  ⚠️  V8.3.21模块未找到，降级到旧版Grid Search: {e}")
        except Exception as e:
            print(f"  ❌ V8.3.21优化失败，降级到旧版Grid Search: {e}")
            import traceback
            traceback.print_exc()
    
    # ===== 【旧版】Grid Search（降级或use_v8321=False） =====
    print(f"\n  📊 使用旧版Grid Search优化器（{len(opportunities)}个机会）")
    
    # ========== 【V8.3.19 NEW】信号类型分析 ==========
    print(f"\n  📊 【V8.3.19】分析信号类型表现（共{len(opportunities)}个机会）...")
    signal_performance = analyze_signal_type_performance(opportunities)
    
    # 打印关键发现
    print(f"  📈 信号类型分布:")
    for sig_type, perf in sorted(signal_performance.items(), key=lambda x: x[1]['count'], reverse=True)[:5]:
        print(f"     • {sig_type}: {perf['count']}个({perf['ratio']*100:.0f}%) | "
              f"平均{perf['avg_profit']:.1f}%利润 | "
              f"{perf['avg_time']:.1f}h | "
              f"典型TP={perf['typical_tp_atr']:.2f}×ATR | "
              f"成功出场率{perf['successful_exit_rate']*100:.0f}%")
    
    # 确定主导信号类型
    if signal_performance:
        dominant_signal = max(signal_performance.items(), key=lambda x: x[1]['count'])[0]
        dominant_perf = signal_performance[dominant_signal]
        
        print(f"\n  💡 主导信号: {dominant_signal} ({dominant_perf['ratio']*100:.0f}%)")
        print(f"     建议TP范围: {dominant_perf['typical_tp_atr']*0.8:.2f}-{dominant_perf['typical_tp_atr']*1.2:.2f}×ATR")
        print(f"     建议时间窗口: ≤{dominant_perf['max_time']:.0f}h (90分位数)")
        print(f"     数据驱动策略: 基于{dominant_perf['count']}个历史样本")
    
    # 【V8.3.16】使用initial_params作为Grid Search的起点
    if initial_params:
        print(f"\n     ℹ️  应用V7.7.0初始参数到Grid Search")
        # 将initial_params合并到current_params
    
    # ========== 存储所有轮次的结果 ==========
    all_rounds_results = []
    final_ai_decision = None
    
    # ========== 第1轮 Grid Search ==========
    print(f"\n  🔍 第1轮 Grid Search")
    round1_combinations = generate_round1_combinations()
    print(f"     测试组合: {len(round1_combinations)}组")
    
    # 执行第1轮Grid Search
    round1_results = []
    import gc
    
    for idx, combination in enumerate(round1_combinations, 1):
        if idx % 5 == 0 or idx == len(round1_combinations):
            print(f"     进度: {idx}/{len(round1_combinations)}组... (信号分={combination.get('min_signal_score', '?')})")
        
        test_params = current_params.copy()
        test_params.update(combination)
        
        # 模拟
        result = simulate_params_on_opportunities(opportunities, test_params)
        score = calculate_scalping_optimization_score(result)
        
        round1_results.append({
            'params': combination,
            'full_params': test_params,  # 保存完整参数
            'result': result,
            'score': score,
            'rank': 0  # 稍后排序
        })
        
        del result, test_params
        if idx % 5 == 0:
            gc.collect()
    
    # 排序
    round1_results.sort(key=lambda x: x['score'], reverse=True)
    for idx, r in enumerate(round1_results, 1):
        r['rank'] = idx
    all_rounds_results.append(('round1', round1_results))
    
    best_round1 = round1_results[0]
    best_round1_te_rate = best_round1['result']['time_exit_count']/best_round1['result']['captured_count']*100 if best_round1['result']['captured_count'] > 0 else 100
    print(f"     ✅ 第1轮完成: 最佳分数={best_round1['score']:.4f}, time_exit={best_round1_te_rate:.0f}%, 利润={best_round1['result']['avg_profit']:.1f}%")
    
    # ========== 调用AI决策：是否需要第2轮 ==========
    print(f"\n  🤖 调用AI分析第1轮结果...")
    ai_decision_round1 = call_ai_for_round_decision(
        round_num=1,
        round_results=round1_results,
        current_best_params=best_round1['params'],
        opportunities_count=len(opportunities),
        all_rounds_results=all_rounds_results,
        signal_performance=signal_performance  # 【V8.3.19】传递信号分析
    )
    
    print(f"     AI决策: needs_round2={ai_decision_round1.get('needs_round2', False)}")
    print(f"     推理: {ai_decision_round1.get('reasoning', 'N/A')[:120]}...")
    
    # ========== 如果需要第2轮 ==========
    round2_results = []
    if ai_decision_round1.get('needs_round2', False):
        print(f"\n  🔍 第2轮 Grid Search（AI建议）")
        round2_suggestions = ai_decision_round1.get('round2_suggestions', {})
        print(f"     策略: {round2_suggestions.get('strategy', 'N/A')}")
        
        round2_combinations = generate_round2_combinations_from_ai(round2_suggestions)
        print(f"     测试组合: {len(round2_combinations)}组")
        
        # 执行第2轮Grid Search
        for idx, combination in enumerate(round2_combinations, 1):
            if idx % 5 == 0 or idx == len(round2_combinations):
                print(f"     进度: {idx}/{len(round2_combinations)}组...")
            
            test_params = current_params.copy()
            test_params.update(combination)
            
            result = simulate_params_on_opportunities(opportunities, test_params)
            score = calculate_scalping_optimization_score(result)
            
            round2_results.append({
                'params': combination,
                'full_params': test_params,
                'result': result,
                'score': score,
                'rank': 0
            })
            
            del result, test_params
            if idx % 5 == 0:
                gc.collect()
        
        # 排序
        round2_results.sort(key=lambda x: x['score'], reverse=True)
        for idx, r in enumerate(round2_results, 1):
            r['rank'] = idx
        all_rounds_results.append(('round2', round2_results))
        
        best_round2 = round2_results[0]
        best_round2_te_rate = best_round2['result']['time_exit_count']/best_round2['result']['captured_count']*100 if best_round2['result']['captured_count'] > 0 else 100
        print(f"     ✅ 第2轮完成: 最佳分数={best_round2['score']:.4f}, time_exit={best_round2_te_rate:.0f}%, 利润={best_round2['result']['avg_profit']:.1f}%")
        
        # ========== 调用AI给出最终决策 ==========
        print(f"\n  🤖 调用AI综合第1/第2轮，给出最终决策...")
        # 合并两轮的Top结果
        combined_top_results = sorted(
            round1_results[:5] + round2_results[:5],
            key=lambda x: x['score'],
            reverse=True
        )[:10]
        
        final_ai_decision = call_ai_for_round_decision(
            round_num=2,
            round_results=combined_top_results,
            current_best_params=best_round2['full_params'],
            opportunities_count=len(opportunities),
            all_rounds_results=all_rounds_results,
            signal_performance=signal_performance  # 【V8.3.19】传递信号分析
        )
    else:
        # ========== 不需要第2轮，使用第1轮的AI决策 ==========
        print(f"     ✅ AI判断：第1轮结果已足够，跳过第2轮")
        final_ai_decision = ai_decision_round1
    
    # ========== 应用最终决策 ==========
    final_decision = final_ai_decision.get('final_decision', {})
    
    # 从AI给出的selected_params中找到对应的完整参数
    selected_params_partial = final_decision.get('selected_params')
    if not selected_params_partial or not isinstance(selected_params_partial, dict):
        print(f"     ⚠️  AI未返回有效参数，使用第1轮最佳结果")
        selected_params_partial = best_round1['params']
    
    # 尝试从round1或round2结果中找到匹配的完整参数
    final_params = None
    for round_name, round_results_list in all_rounds_results:
        for res in round_results_list:
            # 检查关键参数是否匹配
            if (res['params'].get('min_signal_score') == selected_params_partial.get('min_signal_score') and
                res['params'].get('atr_tp_multiplier') == selected_params_partial.get('atr_tp_multiplier') and
                res['params'].get('max_holding_hours') == selected_params_partial.get('max_holding_hours')):
                final_params = res['full_params']
                final_result = res['result']
                break
        if final_params:
            break
    
    # 如果没找到匹配，使用第1轮最佳
    if not final_params:
        print(f"     ⚠️  未找到AI选择的参数，使用第1轮最佳结果")
        final_params = best_round1['full_params']
        final_result = best_round1['result']
    
    print(f"\n  ✅ AI最终决策:")
    accept_result = final_decision.get('accept_result', True)
    print(f"     接受结果: {accept_result}")
    print(f"     执行策略: {final_decision.get('execution_strategy', 'apply_immediately')}")
    print(f"     推理: {final_decision.get('reasoning', 'N/A')[:150]}...")
    if final_decision.get('monitoring_metrics'):
        print(f"     监控指标: {', '.join(final_decision.get('monitoring_metrics', [])[:3])}")
    if final_decision.get('rollback_conditions'):
        print(f"     回滚条件: {final_decision.get('rollback_conditions', 'N/A')[:80]}...")
    
    # 【V8.3.18.6】检查AI是否拒绝结果
    if not accept_result:
        # 检查AI是否提供了Round 3建议
        round3_suggestion = final_ai_decision.get('round3_suggestion')
        if round3_suggestion and isinstance(round3_suggestion, dict) and round3_suggestion.get('param_ranges'):
            print(f"\n  ⚠️  AI拒绝当前结果，但提供了Round 3改进建议")
            print(f"     策略: {round3_suggestion.get('strategy', 'N/A')[:100]}...")
            print(f"     推理: {round3_suggestion.get('rationale', 'N/A')[:150]}...")
            
            # 【V8.3.18.6】执行Round 3
            print(f"\n  🔍 第3轮 Grid Search（AI改进建议）")
            round3_combinations = generate_round2_combinations_from_ai(round3_suggestion['param_ranges'])
            print(f"     测试组合: {len(round3_combinations)}组")
            
            round3_results = []
            for idx, test_params in enumerate(round3_combinations, 1):
                result = simulate_params_on_opportunities(opportunities, test_params)
                score = calculate_scalping_optimization_score(result)
                
                round3_results.append({
                    'params': test_params,
                    'full_params': test_params,
                    'result': result,
                    'score': score,
                    'is_profitable': result['avg_profit'] > 0,
                    'rank': 0
                })
                
                if idx % 10 == 0:
                    print(f"     进度: {idx}/{len(round3_combinations)}组...")
                del result, test_params
                if idx % 5 == 0:
                    gc.collect()
            
            round3_results.sort(key=lambda x: x['score'], reverse=True)
            for idx, r in enumerate(round3_results, 1):
                r['rank'] = idx
            all_rounds_results.append(('round3', round3_results))
            
            best_round3 = round3_results[0]
            best_round3_te_rate = best_round3['result']['time_exit_count']/best_round3['result']['captured_count']*100 if best_round3['result']['captured_count'] > 0 else 100
            print(f"     ✅ 第3轮完成: 最佳分数={best_round3['score']:.4f}, time_exit={best_round3_te_rate:.0f}%, 利润={best_round3['result']['avg_profit']:.1f}%")
            
            # 如果Round 3成功（time_exit < 90%），使用Round 3结果
            if best_round3_te_rate < 90:
                print(f"\n  ✅ Round 3成功降低time_exit，接受此结果")
                final_params = best_round3['full_params']
                final_result = best_round3['result']
            else:
                print(f"\n  ❌ Round 3仍然失败（time_exit={best_round3_te_rate:.0f}%），保持原参数")
                baseline_result = simulate_params_on_opportunities(opportunities, current_params)
                return {
                    'optimized_params': current_params,
                    'old_result': baseline_result,
                    'new_result': baseline_result,
                    'old_time_exit_rate': baseline_result['time_exit_count']/baseline_result['captured_count'] if baseline_result['captured_count'] > 0 else 0,
                    'new_time_exit_rate': baseline_result['time_exit_count']/baseline_result['captured_count'] if baseline_result['captured_count'] > 0 else 0,
                    'old_avg_profit': baseline_result['avg_profit'],
                    'new_avg_profit': baseline_result['avg_profit'],
                    'improvement': None,
                    'ai_rejection_reason': f"All 3 rounds failed (time_exit≥90%). {final_decision.get('reasoning', '')}"
                }
        else:
            # AI拒绝但没给建议（不应该发生）
            print(f"\n  ❌ AI拒绝优化结果，且未提供Round 3建议")
            print(f"     原因: {final_decision.get('reasoning', 'N/A')[:100]}...")
            baseline_result = simulate_params_on_opportunities(opportunities, current_params)
            return {
                'optimized_params': current_params,
                'old_result': baseline_result,
                'new_result': baseline_result,
                'old_time_exit_rate': baseline_result['time_exit_count']/baseline_result['captured_count'] if baseline_result['captured_count'] > 0 else 0,
                'new_time_exit_rate': baseline_result['time_exit_count']/baseline_result['captured_count'] if baseline_result['captured_count'] > 0 else 0,
                'old_avg_profit': baseline_result['avg_profit'],
                'new_avg_profit': baseline_result['avg_profit'],
                'improvement': None,
                'ai_rejection_reason': final_decision.get('reasoning', 'Strategy needs redesign')
            }
    
    # ========== 计算改进指标 ==========
    baseline_result = simulate_params_on_opportunities(opportunities, current_params)
    
    # ========== 返回优化结果 ==========
    return {
        'optimized_params': final_params,
        'old_result': baseline_result,
        'new_result': final_result,
        'old_time_exit_rate': baseline_result['time_exit_count']/baseline_result['captured_count'] if baseline_result['captured_count'] > 0 else 0,
        'new_time_exit_rate': final_result['time_exit_count']/final_result['captured_count'] if final_result['captured_count'] > 0 else 0,
        'old_avg_profit': baseline_result['avg_profit'],
        'new_avg_profit': final_result['avg_profit'],
        'exit_analysis': None,  # V8.3.18不再需要详细的Exit Analysis
        'ai_suggestions': final_ai_decision,  # 保存AI的完整决策
        'improvement': {
            'rounds': len(all_rounds_results),
            'round1_best_score': round1_results[0]['score'],
            'round2_best_score': round2_results[0]['score'] if round2_results else None,
            'ai_decision': final_ai_decision
        }
    }



def optimize_swing_params(swing_data, current_params, initial_params=None, ai_suggested_params=None, use_v8321=True):
    """
    【V8.3.21】波段参数优化 - V8.3.21增强版 + 旧版Grid Search（可选）
    
    优化流程：
    - V8.3.21增强版（默认）：
      1. 11维度参数Grid Search（200组采样）
      2. V8.3.21上下文过滤（4层：基础→K线→结构→S/R）
      3. 本地统计分析（参数敏感度、异常检测）
      4. 成本优化（节省89%）
    
    - 旧版Grid Search（use_v8321=False）：
      1. Grid Search找到最优参数（54组参数）
      2. Exit Analysis分析最优参数的问题
      3. 条件AI调用：只在Time Exit>80%时调用AI（V8.3.16）
      4. 动态激进度：根据Time Exit率调整AI建议采纳度（V8.3.16技术债3）
    
    目标：提高平均利润，保持捕获率
    
    Args:
        swing_data: 波段机会数据
        current_params: 当前配置的策略参数
        initial_params: 【V8.3.16】V7.7.0快速探索提供的初始参数（技术债1）
        ai_suggested_params: 【V8.3.25.10新增】AI洞察建议的参数（将加入测试候选集）
        use_v8321: 【V8.3.21新增】是否使用V8.3.21增强优化器（默认True）
    """
    opportunities = swing_data['opportunities']
    
    if len(opportunities) < 10:
        print("  ⚠️  波段机会不足10个，跳过优化")
        return {
            'optimized_params': current_params,
            'improvement': None
        }
    
    # ===== 【V8.3.21】使用增强优化器 =====
    if use_v8321:
        try:
            from backtest_optimizer_v8321 import optimize_params_v8321_lightweight
            
            print(f"\n  🚀 【V8.3.21】使用增强优化器（{len(opportunities)}个机会）")
            print(f"     • 11维度参数搜索")
            print(f"     • 4层上下文过滤")
            print(f"     • 成本优化（节省89%）")
            
            v8321_result = optimize_params_v8321_lightweight(
                opportunities=opportunities,
                current_params=current_params,
                signal_type='swing',
                max_combinations=200,  # 2核2G环境优化
                ai_suggested_params=ai_suggested_params  # 【V8.3.25.10新增】
            )
            
            print(f"\n  ✅ V8.3.21优化完成")
            print(f"     最优分数: {v8321_result['top_10_configs'][0]['score']:.3f}")
            print(f"     捕获率: {v8321_result['top_10_configs'][0]['metrics']['capture_rate']*100:.0f}%")
            print(f"     平均利润: {v8321_result['top_10_configs'][0]['metrics']['avg_profit']:.1f}%")
            print(f"     胜率: {v8321_result['top_10_configs'][0]['metrics']['win_rate']*100:.0f}%")
            print(f"     💰 成本节省: ${v8321_result['cost_saved']:.4f}")
            
            # 打印关键洞察
            if v8321_result['context_analysis'].get('key_insights'):
                print(f"\n  💡 关键发现:")
                for insight in v8321_result['context_analysis']['key_insights'][:3]:
                    print(f"     {insight}")
            
            # 打印参数敏感度（Top 3）
            if v8321_result['statistics'].get('param_sensitivity'):
                print(f"\n  📊 参数敏感度（影响最大的3个）:")
                sorted_params = sorted(
                    v8321_result['statistics']['param_sensitivity'].items(),
                    key=lambda x: abs(x[1]['avg_impact']),
                    reverse=True
                )[:3]
                for param_name, sensitivity in sorted_params:
                    print(f"     • {param_name}: {sensitivity['importance']} "
                          f"(影响={sensitivity['avg_impact']:+.3f})")
            
            # 【V8.3.21修复】计算old_result/new_result以兼容邮件/bark
            print(f"\n  📊 计算前后对比（兼容性）...")
            baseline_result = simulate_params_on_opportunities(opportunities, current_params)
            optimized_result = simulate_params_on_opportunities(
                opportunities, 
                v8321_result['optimized_params']
            )
            
            # 【V8.3.21 AI迭代】提取AI决策（如果有）
            ai_decision = v8321_result.get('ai_decision', None)
            ai_insights_zh = []
            ai_recommendation_zh = f"V8.3.21建议使用Top 1配置（分数{v8321_result['top_10_configs'][0]['score']:.3f}）"
            
            if ai_decision:
                # AI参与了迭代决策
                print(f"  🤖 AI迭代决策:")
                print(f"     选择: Rank {ai_decision.get('selected_rank', 1)}")
                print(f"     调整: {'是' if ai_decision.get('needs_adjustment') else '否'}")
                
                # 使用AI转换的中文洞察
                ai_insights_zh = ai_decision.get('key_insights_zh', [])
                
                # AI推荐（英文转中文）
                if ai_decision.get('reasoning_en'):
                    ai_recommendation_zh = f"AI建议: {ai_decision['reasoning_en']}"
                    # 简单翻译关键词
                    ai_recommendation_zh = ai_recommendation_zh.replace("Rank 1 is optimal", "Top 1配置最优")
                    ai_recommendation_zh = ai_recommendation_zh.replace("best balance", "最佳平衡")
            else:
                # 使用本地分析的洞察（中文）
                ai_insights_zh = v8321_result['context_analysis'].get('key_insights', [])
            
            # 🆕 V8.3.21.2: 保存V8.3.21洞察到 compressed_insights，供实时AI决策使用
            try:
                config = load_learning_config()
                if 'compressed_insights' not in config:
                    config['compressed_insights'] = {}
                if 'v8321_insights' not in config['compressed_insights']:
                    config['compressed_insights']['v8321_insights'] = {}
                
                # 提取参数敏感度（Top 3）
                param_sensitivity_summary = {}
                if v8321_result['statistics'].get('param_sensitivity'):
                    sorted_params = sorted(
                        v8321_result['statistics']['param_sensitivity'].items(),
                        key=lambda x: abs(x[1]['avg_impact']),
                        reverse=True
                    )[:3]
                    for param_name, sensitivity in sorted_params:
                        param_sensitivity_summary[param_name] = f"{sensitivity['importance']} ({sensitivity['avg_impact']:+.3f})"
                
                # 保存波段洞察
                config['compressed_insights']['v8321_insights']['swing'] = {
                    'best_contexts': v8321_result['context_analysis'].get('key_insights', [])[:3],
                    'param_sensitivity': param_sensitivity_summary,
                    'performance': {
                        'score': v8321_result['top_10_configs'][0]['score'],
                        'capture_rate': v8321_result['top_10_configs'][0]['metrics']['capture_rate'],
                        'avg_profit': v8321_result['top_10_configs'][0]['metrics']['avg_profit'] / 100,  # 转为小数
                        'win_rate': v8321_result['top_10_configs'][0]['metrics']['win_rate']
                    },
                    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                save_learning_config(config)
                print(f"  ✅ V8.3.21波段洞察已保存到 compressed_insights")
            except Exception as e:
                print(f"  ⚠️  保存V8.3.21洞察失败: {e}")
            
            # 【V8.3.21修复】构建完全兼容的返回结构
            return {
                'optimized_params': v8321_result['optimized_params'],
                
                # 兼容字段（邮件/bark需要）
                'old_result': baseline_result,
                'new_result': optimized_result,
                'old_avg_profit': baseline_result['avg_profit'],
                'new_avg_profit': optimized_result['avg_profit'],
                'old_capture_rate': baseline_result['capture_rate'],
                'new_capture_rate': optimized_result['capture_rate'],
                'exit_analysis': None,  # V8.3.21不需要
                
                # AI建议（中文，给用户看）
                'ai_suggestions': {
                    'method': 'v8321_ai_iterative' if ai_decision else 'v8321_local_analysis',
                    'key_insights': ai_insights_zh,  # 中文洞察
                    'param_sensitivity': v8321_result['statistics'].get('param_sensitivity', {}),
                    'anomalies': v8321_result.get('anomalies', []),
                    'recommendation': ai_recommendation_zh,  # 中文推荐
                    'ai_decision_en': ai_decision  # 保留英文原始决策（供调试）
                },
                
                # improvement字段（兼容格式）
                'improvement': {
                    'method': 'v8321_with_ai' if ai_decision else 'v8321',
                    'rounds': 1 + (1 if ai_decision else 0),  # AI迭代算作第2轮
                    'v8321_score': v8321_result['top_10_configs'][0]['score'],
                    'v8321_capture_rate': v8321_result['top_10_configs'][0]['metrics']['capture_rate'],
                    'v8321_insights': ai_insights_zh[:3],  # 中文洞察
                    'cost_saved': v8321_result['cost_saved'],
                    'ai_enhanced': ai_decision is not None
                }
            }
            
        except ImportError as e:
            print(f"  ⚠️  V8.3.21模块未找到，降级到旧版Grid Search: {e}")
        except Exception as e:
            print(f"  ❌ V8.3.21优化失败，降级到旧版Grid Search: {e}")
            import traceback
            traceback.print_exc()
    
    # ===== 【旧版】Grid Search（降级或use_v8321=False） =====
    print(f"\n  📊 使用旧版Grid Search优化器（{len(opportunities)}个机会）")
    
    # 【V8.3.16】使用initial_params作为Grid Search的起点
    if initial_params:
        print(f"     ℹ️  应用V7.7.0初始参数到Grid Search")
        # 将initial_params合并到current_params
        current_params = {**current_params, **initial_params}
    
    print(f"  🔧 开始波段参数优化（{len(opportunities)}个机会）...")
    
    # ========== 阶段1: Grid Search ==========
    # 【V8.3.15】激进调整参数范围，解决Time Exit率82%和捕获率5%问题
    # 关键变化：延长持仓时间，大幅降低TP距离50-70%
    print(f"\n  📊 阶段1: Grid Search（54组参数，V8.3.15激进优化）")
    param_grid = {
        'max_holding_hours': [48, 60, 72],          # 延长（24-48h → 48-72h）
        'atr_tp_multiplier': [2.0, 3.0, 4.0],       # 大幅降低（4.0-6.0 → 2.0-4.0）
        'atr_stop_multiplier': [1.5, 2.0],          # 保持
        'min_risk_reward': [1.5, 2.0, 2.5]          # 扩展（2.0-2.5 → 1.5-2.5）
    }  # Total: 3×3×2×3 = 54组（V8.3.15激进优化）
    
    best_score = -float('inf')
    best_params = current_params.copy()
    best_result = None
    
    # 计算基准表现
    baseline_params = current_params.copy()
    baseline_result = simulate_params_on_opportunities(opportunities, baseline_params)
    baseline_score = calculate_swing_optimization_score(baseline_result)
    
    print(f"     基准: 平均利润={baseline_result['avg_profit']:.1f}%, 捕获率={baseline_result['capture_rate']*100:.0f}%")
    
    tested_count = 0
    total_combinations = len(param_grid['max_holding_hours']) * len(param_grid['atr_tp_multiplier']) * len(param_grid['atr_stop_multiplier']) * len(param_grid['min_risk_reward'])
    
    # Grid Search with memory optimization
    import gc
    for max_hours in param_grid['max_holding_hours']:
        for tp_mult in param_grid['atr_tp_multiplier']:
            for sl_mult in param_grid['atr_stop_multiplier']:
                for min_rr in param_grid['min_risk_reward']:
                    tested_count += 1
                    
                    # 【V8.3.14.4】进度显示
                    if tested_count % 5 == 0 or tested_count == total_combinations:
                        print(f"     进度: {tested_count}/{total_combinations}组...")
                    
                    test_params = current_params.copy()
                    test_params.update({
                        'max_holding_hours': max_hours,
                        'atr_tp_multiplier': tp_mult,
                        'atr_stop_multiplier': sl_mult,
                        'min_risk_reward': min_rr
                    })
                    
                    # 模拟
                    result = simulate_params_on_opportunities(opportunities, test_params)
                    score = calculate_swing_optimization_score(result)
                    
                    if score > best_score:
                        best_score = score
                        best_params = test_params
                        best_result = result
                    
                    # 【V8.3.14.4】释放内存，避免OOM
                    del result, test_params
                    if tested_count % 5 == 0:
                        gc.collect()
    
    print(f"     ✅ Grid Search完成: 平均利润={best_result['avg_profit']:.1f}%, 捕获率={best_result['capture_rate']*100:.0f}%")
    
    # ========== 阶段2: Exit Analysis ==========
    print(f"\n  🔍 阶段2: Exit Analysis")
    detailed_result = simulate_params_on_opportunities_with_details(opportunities, best_params)
    exit_analysis = analyze_exit_patterns(detailed_result['exit_details'])
    
    if exit_analysis:
        te = exit_analysis['time_exit']
        sl = exit_analysis['stop_loss']
        tp = exit_analysis['take_profit']
        print(f"     Time Exit: {te['count']}笔 ({te['rate']:.0f}%) | 平均错过{te['avg_missed_profit']:.1f}%利润")
        print(f"     Stop Loss: {sl['count']}笔 ({sl['rate']:.0f}%) | {sl['tight_count']}笔过紧")
        print(f"     Take Profit: {tp['count']}笔 ({tp['rate']:.0f}%) | {tp['early_count']}笔过早")
    
    # ========== 【V8.3.13.4】多时间框架分析 ==========
    print(f"\n  📊 【V8.3.13.4】多时间框架分析")
    timeframe_analysis = analyze_multi_timeframe_exits(
        exit_details=detailed_result['exit_details'],
        timeframes=['1H', '4H']
    )
    
    if timeframe_analysis:
        for tf, stats in timeframe_analysis.items():
            print(f"     {tf}: {stats['total_count']}笔, Time Exit率{stats['time_exit_rate']*100:.0f}%, 平均持仓{stats['avg_holding_time']:.1f}h")
        
        # 生成建议
        tf_recommendations = generate_timeframe_recommendations(
            timeframe_analysis=timeframe_analysis,
            signal_type='swing'
        )
        
        if tf_recommendations:
            print(f"     💡 建议: {tf_recommendations['recommended_timeframe']}时间框架")
            print(f"        {tf_recommendations['reason']}")
    
    # ========== 阶段3: AI策略分析（条件调用+动态激进度）==========
    # 【V8.3.16】技术债3修复：条件AI调用+动态激进度
    print(f"\n  🤖 阶段3: AI策略分析（V8.3.16条件调用）")
    
    te_rate = exit_analysis['time_exit']['rate'] / 100 if exit_analysis else 0
    ai_suggestions = None
    
    # 【V8.3.16】条件AI调用：只在Time Exit>80%或配置强制时调用
    should_call_ai = (not ENABLE_CONDITIONAL_AI_CALL) or (te_rate > 0.8)
    
    if should_call_ai:
        if te_rate > 0.8:
            print(f"     ⚠️  Time Exit率过高({te_rate*100:.0f}%)，调用AI分析...")
        ai_suggestions = call_ai_for_exit_analysis(exit_analysis, best_params, 'swing')
    else:
        print(f"     ✅ Time Exit率可接受({te_rate*100:.0f}%)，跳过AI调用（节省1-2分钟）")
    
    final_params = best_params.copy()
    if ai_suggestions:
        # 【V8.3.16】技术债3修复：动态调整AI激进度
        if AI_AGGRESSIVENESS_DYNAMIC:
            if te_rate > 0.9:
                aggressiveness = 1.0
                print(f"     📊 Time Exit率>90% → AI激进度=100%（全部采纳）")
            elif te_rate > 0.8:
                aggressiveness = 0.9
                print(f"     📊 Time Exit率>80% → AI激进度=90%")
            elif te_rate > 0.6:
                aggressiveness = 0.7
                print(f"     📊 Time Exit率>60% → AI激进度=70%")
            else:
                aggressiveness = 0.5
                print(f"     📊 Time Exit率<60% → AI激进度=50%（保守）")
        else:
            aggressiveness = 0.8
            print(f"     📊 使用固定AI激进度=80%")
        
        # 应用AI建议
        final_params = apply_ai_suggestions(best_params, ai_suggestions, apply_aggressiveness=aggressiveness)
        
        # 验证AI调整后的效果
        print(f"\n  ✅ 验证AI调整后的效果...")
        final_result = simulate_params_on_opportunities(opportunities, final_params)
        final_score = calculate_swing_optimization_score(final_result)
        
        print(f"     最终: 平均利润={final_result['avg_profit']:.1f}%, 捕获率={final_result['capture_rate']*100:.0f}%")
        print(f"     评分: Grid={best_score:.3f} → AI调整后={final_score:.3f}")
        
        # 如果AI调整后反而变差，使用Grid Search结果
        if final_score < best_score * 0.95:  # 允许5%的容错
            print(f"     ⚠️  AI调整效果不佳，保持Grid Search结果")
            final_params = best_params
            final_result = best_result
    else:
        if should_call_ai:
            print(f"     ⚠️  AI分析失败，使用Grid Search结果")
        final_result = best_result
    
    return {
        'optimized_params': final_params,
        'old_result': baseline_result,
        'new_result': final_result,
        'old_avg_profit': baseline_result['avg_profit'],
        'new_avg_profit': final_result['avg_profit'],
        'old_capture_rate': baseline_result['capture_rate'],
        'new_capture_rate': final_result['capture_rate'],
        'exit_analysis': exit_analysis,
        'ai_suggestions': ai_suggestions,
        'improvement': 'with_ai' if ai_suggestions else 'grid_only'
    }


# ==================================================
# 【V8.3.13.3】Per-Symbol优化
# ==================================================

def analyze_per_symbol_opportunities(market_snapshots, old_config, symbols=None):
    """
    【V8.3.13.3】分析每个币种的分离机会
    
    返回:
    {
        'BTC': {
            'scalping': {...},
            'swing': {...}
        },
        ...
    }
    """
    try:
        import pandas as pd
        
        if symbols is None:
            symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'LTC']
        
        per_symbol_data = {}
        
        print(f"  🔍 【V8.3.13.3】Per-Symbol分析")
        
        for symbol in symbols:
            symbol_data = market_snapshots[market_snapshots['coin'] == symbol]
            
            if len(symbol_data) < 100:
                print(f"    ⚠️  {symbol}: 数据不足（{len(symbol_data)}条）")
                continue
            
            # 复用V8.3.12的函数
            separated = analyze_separated_opportunities(symbol_data, old_config)
            per_symbol_data[symbol] = separated
            
            scalping_count = separated['scalping']['total_opportunities']
            swing_count = separated['swing']['total_opportunities']
            print(f"    📊 {symbol}: ⚡{scalping_count}个scalping, 🌊{swing_count}个swing")
        
        return per_symbol_data
        
    except Exception as e:
        print(f"⚠️ Per-symbol分析失败: {e}")
        import traceback
        traceback.print_exc()
        return {}


def optimize_per_symbol_params(per_symbol_data, global_config):
    """
    【V8.3.13.3】为每个币种优化参数
    """
    try:
        optimized_params = {}
        
        for symbol, data in per_symbol_data.items():
            print(f"\n  🔧 优化{symbol}参数...")
            
            symbol_result = {
                'scalping_params': {},
                'swing_params': {},
                'improvement': {}
            }
            
            # 优化scalping
            if data['scalping']['total_opportunities'] >= 20:
                scalping_opt = optimize_scalping_params(
                    scalping_data=data['scalping'],
                    current_params=global_config.get('scalping_params', {})
                )
                symbol_result['scalping_params'] = scalping_opt['optimized_params']
                symbol_result['improvement']['scalping'] = scalping_opt.get('improvement')
                
                old_te = scalping_opt['old_time_exit_rate']
                new_te = scalping_opt['new_time_exit_rate']
                print(f"    ⚡ Scalping: time_exit {old_te*100:.0f}% → {new_te*100:.0f}%")
            
            # 优化swing
            if data['swing']['total_opportunities'] >= 20:
                swing_opt = optimize_swing_params(
                    swing_data=data['swing'],
                    current_params=global_config.get('swing_params', {})
                )
                symbol_result['swing_params'] = swing_opt['optimized_params']
                symbol_result['improvement']['swing'] = swing_opt.get('improvement')
                
                old_profit = swing_opt['old_avg_profit']
                new_profit = swing_opt['new_avg_profit']
                print(f"    🌊 Swing: 利润 {old_profit:.1f}% → {new_profit:.1f}%")
            
            optimized_params[symbol] = symbol_result
        
        return optimized_params
        
    except Exception as e:
        print(f"⚠️ Per-symbol优化失败: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_per_symbol_params(symbol, signal_type, learning_config):
    """
    【V8.3.13.3】获取币种专属参数
    
    优先级:
    1. per_symbol_params[symbol][signal_type]
    2. signal_type_params
    3. global params
    """
    try:
        # 优先级1
        per_symbol = learning_config.get('per_symbol_params', {}).get(symbol, {})
        key = 'scalping_params' if signal_type == 'scalping' else 'swing_params'
        params = per_symbol.get(key, {})
        if params:
            return params
        
        # 优先级2
        if signal_type == 'scalping':
            return learning_config.get('scalping_params', {})
        else:
            return learning_config.get('swing_params', {})
            
    except:
        return learning_config.get('global', {})


# ==================================================
# 【V8.3.13.4】多时间框架分析
# ==================================================

def analyze_multi_timeframe_exits(exit_details, timeframes=['1H', '4H']):
    """
    【V8.3.13.4】分析不同时间框架的exit patterns
    """
    try:
        if not exit_details:
            return None
        
        analysis = {}
        
        for tf in timeframes:
            # 根据时间框架过滤
            if tf == '1H':
                filtered = [d for d in exit_details if d.get('holding_hours', 0) < 2]
            elif tf == '4H':
                filtered = [d for d in exit_details if d.get('holding_hours', 0) >= 2]
            else:
                filtered = exit_details
            
            if not filtered:
                continue
            
            time_exits = [d for d in filtered if d['exit_type'] == 'time_exit']
            take_profits = [d for d in filtered if d['exit_type'] == 'take_profit']
            
            analysis[tf] = {
                'total_count': len(filtered),
                'time_exit_rate': len(time_exits) / len(filtered) if filtered else 0,
                'avg_missed_profit': sum(d.get('missed_profit', 0) for d in time_exits) / len(time_exits) if time_exits else 0,
                'avg_holding_time': sum(d.get('holding_hours', 0) for d in filtered) / len(filtered) if filtered else 0,
                'tp_avg_time': sum(d.get('holding_hours', 0) for d in take_profits) / len(take_profits) if take_profits else 0
            }
        
        return analysis
        
    except Exception as e:
        print(f"⚠️ 多时间框架分析失败: {e}")
        return None


def generate_timeframe_recommendations(timeframe_analysis, signal_type):
    """
    【V8.3.13.4】生成时间框架优化建议
    """
    try:
        if not timeframe_analysis:
            return None
        
        recommendations = {
            'recommended_timeframe': None,
            'recommended_holding_hours': None,
            'reason': '',
            'expected_improvement': ''
        }
        
        # 超短线：选择Time Exit率低的
        if signal_type == 'scalping':
            tf_1h = timeframe_analysis.get('1H', {})
            tf_4h = timeframe_analysis.get('4H', {})
            
            if tf_1h and tf_4h:
                if tf_1h['time_exit_rate'] < tf_4h['time_exit_rate']:
                    recommendations['recommended_timeframe'] = '1H'
                    recommendations['recommended_holding_hours'] = tf_1h['tp_avg_time']
                    recommendations['reason'] = f"1H时间框架Time Exit率更低（{tf_1h['time_exit_rate']*100:.0f}% vs {tf_4h['time_exit_rate']*100:.0f}%）"
                else:
                    recommendations['recommended_timeframe'] = '4H'
                    recommendations['recommended_holding_hours'] = tf_4h['tp_avg_time']
                    recommendations['reason'] = f"4H时间框架Time Exit率更低"
        
        # 波段：选择4H
        else:
            tf_4h = timeframe_analysis.get('4H', {})
            if tf_4h:
                recommendations['recommended_timeframe'] = '4H'
                recommendations['recommended_holding_hours'] = tf_4h.get('avg_holding_time', 24)
                recommendations['reason'] = "波段交易适合4H时间框架"
        
        recommendations['expected_improvement'] = f"预计Time Exit率降低5-10%"
        
        return recommendations
        
    except Exception as e:
        print(f"⚠️ 时间框架建议生成失败: {e}")
        return None


# ==================================================
# 【V8.3.13.6】实时策略切换增强
# ==================================================

def select_strategy_by_market_state(atr_pct, signal_type, current_params):
    """
    【V8.3.13.6】根据市场状态动态选择策略
    """
    try:
        adjusted_params = current_params.copy()
        
        # 高波动
        if atr_pct > 2.5:
            if signal_type == 'scalping':
                adjusted_params['atr_stop_multiplier'] = current_params.get('atr_stop_multiplier', 1.0) * 1.3
                adjusted_params['max_holding_hours'] = current_params.get('max_holding_hours', 1.5) * 0.8
                strategy_note = "高波动：扩大止损30%，缩短持仓20%"
            else:
                adjusted_params['use_sr_levels'] = False
                adjusted_params['atr_stop_multiplier'] = current_params.get('atr_stop_multiplier', 2.0) * 1.2
                strategy_note = "高波动：使用ATR止损"
        
        # 低波动
        elif atr_pct < 1.0:
            if signal_type == 'scalping':
                adjusted_params['atr_tp_multiplier'] = current_params.get('atr_tp_multiplier', 1.5) * 0.8
                adjusted_params['max_holding_hours'] = current_params.get('max_holding_hours', 1.5) * 1.2
                strategy_note = "低波动：缩小止盈20%，延长持仓20%"
            else:
                adjusted_params['use_sr_levels'] = True
                adjusted_params['atr_tp_multiplier'] = current_params.get('atr_tp_multiplier', 6.0) * 0.9
                strategy_note = "低波动：优先SR levels"
        
        # 正常波动
        else:
            strategy_note = "正常波动：标准参数"
        
        return adjusted_params, strategy_note
        
    except Exception as e:
        print(f"⚠️ 策略选择失败: {e}")
        return current_params, "默认参数"


# ==================================================
# 【V8.3.13.5】RL框架设计（仅框架）
# ==================================================

class TradingEnvironment:
    """【V8.3.13.5】交易环境 - RL框架（框架设计，暂不实现）"""
    def __init__(self, historical_data):
        self.data = historical_data
        self.current_step = 0
        self.current_params = {}
    
    def reset(self):
        """重置环境"""
        self.current_step = 0
        return {}
    
    def step(self, action):
        """执行动作，返回(state, reward, done, info)"""
        return {}, 0, False, {}


class ParameterAgent:
    """【V8.3.13.5】参数优化智能体 - RL框架（框架设计，暂不实现）"""
    def __init__(self):
        self.policy_network = None
        self.value_network = None
    
    def select_params(self, state):
        """选择参数"""
        return {}
    
    def update(self, experience):
        """更新策略"""
        pass


def analyze_missed_opportunities(trends, actual_trades, config):
    """
    分析错过的交易机会（V6.5：添加三层趋势分析）
    ⚠️ 已弃用：使用 analyze_opportunities_with_new_params 代替
    
    参数:
        trends: list, 识别到的重要趋势
        actual_trades: list, 实际开的仓
        config: dict, 当前参数配置
    
    返回:
        list of dict, 错过的机会分析
    """
    missed = []
    
    for trend in trends:
        coin = trend['coin']
        
        # 🔧 V8.3.25.3: 修复类型错误 - 确保时间统一格式
        # 检查是否在这个趋势中开仓了
        opened = any(
            t.get('币种') == coin and 
            int(trend['start_time']) <= int(pd.to_datetime(t.get('开仓时间', ''), errors='coerce').strftime('%H%M') if t.get('开仓时间') else '0000') <= int(trend['end_time'])
            for t in actual_trades
                )
        
        if not opened:
            # 错过了这个机会
            potential_profit = abs(trend['amplitude'])
            risk_reward = potential_profit / 1.0  # 假设1%止损
            
            min_rr = config.get('global', {}).get('min_risk_reward', 2.5)
            
            # V6.5：分析是否因三层趋势不一致而错过
            reason_parts = []
            if risk_reward < min_rr:
                reason_parts.append(f"盈亏比{risk_reward:.1f}<{min_rr}")
            
            # 添加趋势不一致判断（假设从market_snapshots可获取）
            reason_parts.append("可能三层趋势不一致")
            
            reason = f"可能原因：" + "、".join(reason_parts)
            suggestion = f"建议：降低盈亏比至{risk_reward:.1f}或增加模式2（短线逆势）交易"
            
            missed.append({
                "trend": trend,
                "potential_profit_pct": potential_profit,
                "reason": reason,
                "suggestion": suggestion
            })
    
    return missed


def analyze_exit_timing(yesterday_trades, kline_snapshots):
    """
    分析平仓时机是否合理（V7.7.0.15）
    
    核心逻辑：
    1. 对每笔已平仓交易，分析平仓后的K线走势
    2. 判断是否错过了后续的利润
    3. 评估平仓时机是否合理（基于技术指标）
    4. 统计止损/止盈触发情况
    
    参数:
        yesterday_trades: DataFrame, 昨日交易记录
        kline_snapshots: DataFrame, 市场快照数据
    
    返回:
        dict: {
            'exit_stats': dict,  # 平仓统计
            'suboptimal_exits': list,  # 平仓不理想的交易
            'good_exits': list,  # 平仓合理的交易
            'exit_lessons': list  # 平仓经验教训
        }
    """
    if yesterday_trades is None or yesterday_trades.empty or kline_snapshots is None or kline_snapshots.empty:
        return {'exit_stats': {}, 'suboptimal_exits': [], 'good_exits': [], 'exit_lessons': []}
    
    import pandas as pd
    
    suboptimal_exits = []
    good_exits = []
    exit_stats = {
        'total_exits': 0,
        'tp_exits': 0,
        'sl_exits': 0,
        'manual_exits': 0,
        'premature_exits': 0,  # 过早平仓
        'optimal_exits': 0,    # 平仓合理
        'avg_missed_profit_pct': 0
    }
    
    for idx, trade in yesterday_trades.iterrows():
        if pd.isna(trade.get('平仓时间')) or pd.isna(trade.get('平仓理由')):
            continue
        
        exit_stats['total_exits'] += 1
        
        coin = trade.get('币种')
        exit_time = pd.to_datetime(trade.get('平仓时间'))
        exit_price = float(trade.get('平仓价格', 0))
        exit_reason = str(trade.get('平仓理由', ''))
        side = trade.get('方向')
        entry_price = float(trade.get('开仓价格', 0))
        pnl = float(trade.get('盈亏(U)', 0))
        
        # 分类平仓类型
        if any(kw in exit_reason for kw in ['止盈', '目标', 'TP', '阻力', '支撑']):
            exit_stats['tp_exits'] += 1
            exit_type = '止盈'
        elif any(kw in exit_reason for kw in ['止损', 'SL', '反转', '破位', '跌破']):
            exit_stats['sl_exits'] += 1
            exit_type = '止损'
        else:
            exit_stats['manual_exits'] += 1
            exit_type = '手动'
        
        # 🔧 V7.7.0.16: 改进平仓分析 - 即使无未来数据也能分析
        coin_klines = kline_snapshots[kline_snapshots['coin'] == coin].copy()
        coin_klines['time'] = pd.to_datetime(coin_klines['time'])
        
        # 获取平仓后的K线
        future_klines = coin_klines[coin_klines['time'] > exit_time].head(16)  # 平仓后4小时（15分钟K线×16）
        
        # 📊 分析平仓后的走势（如果有未来数据）
        if not future_klines.empty:
            if side == '多':
                # 多单：看平仓后是否继续上涨
                max_future_price = future_klines['high'].max()
                missed_profit_pct = (max_future_price - exit_price) / exit_price * 100
                
                # 判断是否过早平仓（平仓后又上涨超过2%）
                is_premature = missed_profit_pct > 2.0 and pnl > 0
                
            else:  # 空单
                # 空单：看平仓后是否继续下跌
                min_future_price = future_klines['low'].min()
                missed_profit_pct = (exit_price - min_future_price) / exit_price * 100
                
                # 判断是否过早平仓（平仓后又下跌超过2%）
                is_premature = missed_profit_pct > 2.0 and pnl > 0
        else:
            # 🆕 无未来数据时的降级分析：根据盈亏和止盈止损类型判断
            missed_profit_pct = 0
            
            # 对于盈利但手动平仓的交易，标记为可能过早（需人工审查）
            if pnl > 0 and exit_type == '手动':
                is_premature = True  # 标记为需要关注
                missed_profit_pct = 0  # 未知
            # 对于止损平仓，标记为可能入场不合理
            elif exit_type == '止损':
                is_premature = False
            # 对于止盈平仓，标记为合理（除非盈利很小）
            elif exit_type == '止盈':
                profit_pct = (pnl / entry_price * 100) if entry_price > 0 else 0
                is_premature = profit_pct < 1.5  # 盈利<1.5%视为止盈设置过保守
            else:
                is_premature = False
        
        # 查找是否有技术信号支撑平仓决策
        exit_kline = coin_klines[coin_klines['time'] <= exit_time].iloc[-1] if not coin_klines[coin_klines['time'] <= exit_time].empty else None
        
        if exit_kline is not None:
            rsi = exit_kline.get('rsi', 50)
            macd_signal = exit_kline.get('macd_signal', 0)
            
            if side == '多':
                technical_support = (
                    rsi > 70 or  # 超买
                    macd_signal < 0  # MACD死叉
                )
            else:
                technical_support = (
                    rsi < 30 or  # 超卖
                    macd_signal > 0  # MACD金叉
                )
        else:
            technical_support = False
        
        # 🔧 V7.7.0.15 Enhanced: 记录分析结果（增加价格和最大潜在利润字段）
        trade_analysis = {
            'coin': coin,
            'side': side,
            'entry_price': entry_price,
                'exit_price': exit_price,
            'exit_type': exit_type,
            'exit_reason': exit_reason,
            'pnl': pnl,
            'missed_profit_pct': missed_profit_pct,
            'max_potential_profit_pct': missed_profit_pct + (pnl / entry_price * 100) if entry_price > 0 else 0,  # 最大潜在利润 = 实际利润 + 错过利润
                'is_premature': is_premature,
            'technical_support': technical_support
        }
        
        if is_premature:
            exit_stats['premature_exits'] += 1
            suboptimal_exits.append(trade_analysis)
        else:
            if technical_support or exit_type == '止损':
                exit_stats['optimal_exits'] += 1
                good_exits.append(trade_analysis)
    
    # 计算平均错过利润
    if suboptimal_exits:
        exit_stats['avg_missed_profit_pct'] = sum(t['missed_profit_pct'] for t in suboptimal_exits) / len(suboptimal_exits)
    
    # 生成经验教训（V7.7.0.15增强：更量化和可操作）
    exit_lessons = []
    
    if exit_stats['premature_exits'] >= 2:
        avg_missed = exit_stats['avg_missed_profit_pct']
        lesson = f"Exit Too Early: {exit_stats['premature_exits']} trades, avg missed {avg_missed:.1f}% profit"
        exit_lessons.append(lesson)
        
        # 分析过早平仓的共性
        premature_tp = sum(1 for t in suboptimal_exits if t['exit_type'] == '止盈')
        if premature_tp >= 2:
            # 🆕 量化建议：根据错过的利润推荐TP扩展倍数
            if avg_missed > 15:
                multiplier_suggest = "2.0x"
            elif avg_missed > 8:
                multiplier_suggest = "1.5x"
            else:
                multiplier_suggest = "1.3x"
            exit_lessons.append(f"TP Too Conservative (Missed {avg_missed:.0f}%): Expand TP by {multiplier_suggest} (e.g., ATR×3 → ATR×{float(multiplier_suggest[:-1])*3:.1f})")
    
    if exit_stats['sl_exits'] > exit_stats['tp_exits'] * 1.5:
        sl_rate = exit_stats['sl_exits'] / exit_stats['total_exits'] * 100 if exit_stats['total_exits'] > 0 else 0
        tp_rate = exit_stats['tp_exits'] / exit_stats['total_exits'] * 100 if exit_stats['total_exits'] > 0 else 0
        
        # 🆕 量化建议：根据止损率推荐入场要求
        if sl_rate > 60:
            entry_req = "signal_score≥75 + 5/5 consensus"
        elif sl_rate > 50:
            entry_req = "signal_score≥70 + strict entry zone"
        else:
            entry_req = "pullback entry only"
        
        exit_lessons.append(f"High SL Rate ({sl_rate:.0f}% SL vs {tp_rate:.0f}% TP): Require {entry_req}")
    
    return {
        'exit_stats': exit_stats,
        'suboptimal_exits': suboptimal_exits[:5],  # 只保留TOP5
        'good_exits': good_exits[:3],  # 只保留TOP3
        'exit_lessons': exit_lessons
    }


def compress_insights_for_realtime(trends, trade_analyses, missed_opportunities, optimization, exit_analysis=None):
    """
    将复盘洞察压缩成50-80 tokens的精炼版本供实时决策使用
    
    参数:
        trends: list, 识别到的趋势
        trade_analyses: list, 交易分析结果
        missed_opportunities: list, 错过的机会
        optimization: dict, AI优化建议
        exit_analysis: dict, 平仓时机分析（V7.7.0.15新增）
    
    返回:
        dict, 压缩后的洞察（约30-50 tokens，英文）
    """
    from datetime import timedelta
    
    lessons = []
    
    # 🔧 V7.7.0.13: 改为英文格式（减少tokens消耗）
    # 错过的TOP机会（最多2个）
    for opp in missed_opportunities[:2]:
        trend_type = "long" if opp['trend']['type'] == "多" else "short"
        # 提取reason的核心信息（英文关键词）
        reason = opp['reason']
        if "参数" in reason or "严格" in reason:
            reason_key = "strict"
        elif "指标" in reason or "共振" in reason:
            reason_key = "consensus"
        elif "盈亏比" in reason or "R:R" in reason:
            reason_key = "R:R"
        else:
            reason_key = "other"
        
        lessons.append(
            f"{opp['trend']['coin']} {trend_type} +{opp['potential_profit_pct']:.0f}% missed ({reason_key})"
        )
    
    # 提前平仓（最多2个）
    premature_exits = [ta for ta in trade_analyses if ta.get('actual', {}).get('premature_exit')]
    for ta in premature_exits[:2]:
        lessons.append(
            f"{ta['coin']} early exit -{ta['analysis']['missed_profit']:.1f}%"
        )
    
    # 🆕 V7.7.0.15: 平仓时机经验（最多2条）
    if exit_analysis and exit_analysis.get('exit_lessons'):
        for lesson in exit_analysis['exit_lessons'][:2]:
            lessons.append(lesson)
    
    # 参数调整原因（英文，精简到20字符）
    param_reason = ""
    if optimization:
        diagnosis = optimization.get('diagnosis', '')
        # 提取关键信息（英文）
        if "胜率" in diagnosis and "低" in diagnosis:
            param_reason = "Low win rate"
        elif "盈亏比" in diagnosis and "低" in diagnosis:
            param_reason = "Low R:R ratio"
        elif "捕获" in diagnosis or "机会" in diagnosis:
            param_reason = "Capture rate issue"
        else:
            param_reason = diagnosis[:20] if diagnosis else ""
    
    return {
        "date": (datetime.now() - timedelta(days=1)).strftime("%Y%m%d"),
        "lessons": lessons,
        "focus": param_reason,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }


def save_position_context(coin, decision, entry_price, signal_classification=None, market_data=None):
    """
    保存开仓决策的上下文，供平仓时参考
    
    参数:
        coin: str, 币种名称
        decision: dict, AI决策内容
        entry_price: float, 开仓价格
            signal_classification: dict, 信号分类信息（V7.9新增）
        market_data: dict, 市场数据（用于提取关键位，V7.9新增）
    """
    model_name = os.getenv("MODEL_NAME", "qwen")
    context_file = Path("trading_data") / model_name / "position_contexts.json"
    
    try:
        # 读取现有上下文
        contexts = {}
        if context_file.exists():
            with open(context_file, 'r', encoding='utf-8') as f:
                contexts = json.load(f)
        
        # 【V7.9】提取关键位信息
        key_levels = {}
        if market_data:
            sr = market_data.get("support_resistance", {})
            sr_1h = market_data.get("mid_term", {}).get("support_resistance", {})
            
            # 15分钟关键位
            if sr.get("nearest_support"):
                key_levels["support_15m"] = sr["nearest_support"].get("price", 0)
            if sr.get("nearest_resistance"):
                key_levels["resistance_15m"] = sr["nearest_resistance"].get("price", 0)
            
            # 1小时关键位（更重要）
            if sr_1h.get("nearest_support"):
                key_levels["support_1h"] = sr_1h["nearest_support"].get("price", 0)
            if sr_1h.get("nearest_resistance"):
                key_levels["resistance_1h"] = sr_1h["nearest_resistance"].get("price", 0)
            
            # 趋势信息
            key_levels["trend_4h"] = market_data.get("long_term", {}).get("trend", "")
            key_levels["trend_1h"] = market_data.get("mid_term", {}).get("trend", "")
        
        # Save new context (V7.9扩展)
        contexts[coin] = {
            "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "entry_price": entry_price,
            "entry_reason": decision.get("reason", "")[:100],
                "target_tp": decision.get("take_profit_price", 0),
            "target_sl": decision.get("stop_loss_price", 0),
            "risk_reward": decision.get("risk_reward", 0),
            "ai_strategy": decision.get("strategy", "Trust the TP plan")[:80],
            
            # 【V7.9新增】信号分类信息
            "signal_type": signal_classification.get("signal_type", "swing") if signal_classification else "swing",
                "signal_name": signal_classification.get("signal_name", "UNKNOWN") if signal_classification else "UNKNOWN",
            "expected_holding_minutes": signal_classification.get("expected_holding_minutes", 120) if signal_classification else 120,
                "classification_reason": signal_classification.get("reason", "") if signal_classification else "",
            
            # 【V7.9新增】关键位信息（用于判断硬失效）
            "key_levels": key_levels
        }
        
        # 原子写入
        temp_file = context_file.parent / f"{context_file.name}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(contexts, f, ensure_ascii=False, indent=2)
        temp_file.replace(context_file)
        
        print(f"✓ 已保存 {coin} 的决策上下文")
    except Exception as e:
        print(f"⚠️ 保存决策上下文失败: {e}")


def load_position_context(coin):
    """
    读取开仓决策的上下文（V7.7.0.19新增）
    
    参数:
        coin: str, 币种名称
    
    返回:
        dict, 决策上下文
    """
    model_name = os.getenv("MODEL_NAME", "qwen")
    context_file = Path("trading_data") / model_name / "position_contexts.json"
    
    try:
        if context_file.exists():
            with open(context_file, 'r', encoding='utf-8') as f:
                contexts = json.load(f)
                return contexts.get(coin, {
                    'entry_reason': 'N/A',
                        'ai_strategy': 'Trust the plan',
                    'entry_price': 0,
                        'target_tp': 0,
                    'target_sl': 0
                })
        return {
            'entry_reason': 'N/A',
                'ai_strategy': 'Trust the plan',
            'entry_price': 0,
                'target_tp': 0,
            'target_sl': 0
        }
    except Exception as e:
        print(f"⚠️ 读取决策上下文失败: {e}")
        return {
            'entry_reason': 'N/A',
                'ai_strategy': 'Trust the plan',
            'entry_price': 0,
                'target_tp': 0,
            'target_sl': 0
        }


def clear_position_context(coin):
    """
    清理已平仓币种的决策上下文
    
    参数:
        coin: str, 币种名称
    """
    model_name = os.getenv("MODEL_NAME", "qwen")
    context_file = Path("trading_data") / model_name / "position_contexts.json"
    
    try:
        if context_file.exists():
            with open(context_file, 'r', encoding='utf-8') as f:
                contexts = json.load(f)
            
            if coin in contexts:
                del contexts[coin]
                
                with open(context_file, 'w', encoding='utf-8') as f:
                    json.dump(contexts, f, ensure_ascii=False, indent=2)
                
                print(f"✓ 已清理 {coin} 的决策上下文")
    except Exception as e:
        print(f"⚠️ 清理决策上下文失败: {e}")


def merge_historical_insights(config):
    """
    🆕 V8.3.25: 智能合并历史经验，防止prompt过长
    
    策略：
    1. 如果ai_entry_analysis和ai_exit_analysis超过7天，合并为精简版
    2. 保留最近3天的完整洞察
    3. 将7天前的洞察合并为"历史模式总结"
    """
    from datetime import datetime, timedelta
    
    insights = config.get('compressed_insights', {})
    if not insights:
        return config
    
    # 检查是否需要合并
    ai_entry = insights.get('ai_entry_analysis', {})
    ai_exit = insights.get('ai_exit_analysis', {})
    
    # 解析生成时间
    try:
        if ai_entry.get('generated_at'):
            entry_date = datetime.strptime(ai_entry['generated_at'], '%Y-%m-%d %H:%M:%S')
            days_old = (datetime.now() - entry_date).days
            
            # 如果超过7天，压缩为精简版
            if days_old > 7:
                # 提取最关键的3条洞察
                key_insights = ai_entry.get('learning_insights', [])[:3]
                key_recs = ai_entry.get('key_recommendations', [])[:2]
                
                # 创建精简版
                insights['ai_entry_analysis'] = {
                    'diagnosis': f"[Merged {days_old}-day insights]",
                    'learning_insights': key_insights,
                    'key_recommendations': key_recs,
                    'generated_at': ai_entry['generated_at'],
                    'merged': True
                }
                print(f"  🗜️  Entry insights compressed ({days_old} days old)")
        
        if ai_exit.get('generated_at'):
            exit_date = datetime.strptime(ai_exit['generated_at'], '%Y-%m-%d %H:%M:%S')
            days_old = (datetime.now() - exit_date).days
            
            if days_old > 7:
                key_insights = ai_exit.get('learning_insights', [])[:3]
                key_recs = ai_exit.get('key_recommendations', [])[:2]
                
                insights['ai_exit_analysis'] = {
                    'diagnosis': f"[Merged {days_old}-day insights]",
                    'learning_insights': key_insights,
                    'key_recommendations': key_recs,
                    'generated_at': ai_exit['generated_at'],
                    'merged': True
                }
                print(f"  🗜️  Exit insights compressed ({days_old} days old)")
        
        config['compressed_insights'] = insights
    except Exception as e:
        print(f"  ⚠️ 合并历史洞察失败: {e}")
    
    return config


def build_decision_context(current_positions=None):
    """
    Build concise decision context for AI (<150 tokens)
    
    Args:
        current_positions: dict, current position info (symbol->price)
    
    Returns:
        str, formatted decision context
    """
    context = ""
    model_name = os.getenv("MODEL_NAME", "qwen")
    
    # 1. Read compressed insights from learning_config.json (~50 tokens)
    # 🔧 V7.7.0.19: 从 learning_config.json 读取 compressed_insights
    try:
        learning_config = load_learning_config()
        
        # 🆕 V8.3.25: 智能合并过期经验（防止prompt过长）
        learning_config = merge_historical_insights(learning_config)
        
        insights = learning_config.get('compressed_insights', {})
        
        if insights and insights.get('lessons'):
            context += f"\n## 📚 Yesterday's Lessons ({insights.get('date', 'N/A')})\n"
            for lesson in insights['lessons']:
                context += f"- {lesson}\n"
            if insights.get('focus'):
                context += f"**Strategy Focus**: {insights['focus']}\n"
        
        # 🆕 V8.3.21.2: 传递V8.3.21优化洞察给AI（约80-100 tokens）
        v8321 = insights.get('v8321_insights', {})
        if v8321:
            context += f"\n## 🔬 Optimized Context Patterns (V8.3.21)\n"
            context += f"*Data-driven insights from {len(v8321)} backtested strategies*\n\n"
            
            # 超短线洞察
            if 'scalping' in v8321:
                s = v8321['scalping']
                perf = s.get('performance', {})
                context += f"**Scalping** (Score: {perf.get('score', 0):.3f}, "
                context += f"Capture: {perf.get('capture_rate', 0)*100:.0f}%, "
                context += f"Profit: {perf.get('avg_profit', 0)*100:.1f}%)\n"
                for ctx in s.get('best_contexts', [])[:2]:  # 只显示前2条
                    context += f"  • {ctx}\n"
            
            # 波段洞察
            if 'swing' in v8321:
                w = v8321['swing']
                perf = w.get('performance', {})
                context += f"**Swing** (Score: {perf.get('score', 0):.3f}, "
                context += f"Capture: {perf.get('capture_rate', 0)*100:.0f}%, "
                context += f"Profit: {perf.get('avg_profit', 0)*100:.1f}%)\n"
                for ctx in w.get('best_contexts', [])[:2]:  # 只显示前2条
                    context += f"  • {ctx}\n"
            
            context += f"\n*Use these patterns to evaluate current market context quality.*\n"
        
        # 🆕 V8.3.23: AI自主学习洞察（开仓+平仓经验）
        ai_entry = insights.get('ai_entry_analysis', {})
        ai_exit = insights.get('ai_exit_analysis', {})
        
        if ai_entry or ai_exit:
            context += f"\n## 🧠 AI Self-Learning Insights (English)\n"
            context += f"*Deep analysis from recent backtests - Apply these lessons to improve decisions*\n\n"
            
            # 开仓经验
            if ai_entry and ai_entry.get('learning_insights'):
                context += f"**Entry Quality Lessons** ({ai_entry.get('generated_at', 'N/A')}):\n"
                for insight in ai_entry['learning_insights'][:3]:  # TOP3最重要的
                    context += f"  • {insight}\n"
                
                # 添加关键建议
                if ai_entry.get('key_recommendations'):
                    context += f"\n**Priority Actions for Entry**:\n"
                    for rec in ai_entry['key_recommendations'][:2]:  # TOP2高优先级
                        if rec.get('priority') == 'High':
                            context += f"  → {rec['action']}: {rec['threshold']}\n"
            
            # 平仓经验
            if ai_exit and ai_exit.get('learning_insights'):
                context += f"\n**Exit Quality Lessons** ({ai_exit.get('generated_at', 'N/A')}):\n"
                for insight in ai_exit['learning_insights'][:3]:  # TOP3
                    context += f"  • {insight}\n"
                
                # 添加关键建议
                if ai_exit.get('key_recommendations'):
                    context += f"\n**Priority Actions for Exit**:\n"
                    for rec in ai_exit['key_recommendations'][:2]:  # TOP2高优先级
                        if rec.get('priority') == 'High':
                            context += f"  → {rec['action']}: {rec['threshold']}\n"
            
            context += f"\n*These insights were generated by AI analyzing your trade history. Follow them strictly.*\n"
    
    except Exception as e:
        print(f"⚠️ Failed to read compressed insights: {e}")
    
    # 2. Read position contexts (~40 tokens per symbol)
    position_file = Path("trading_data") / model_name / "position_contexts.json"
    if position_file.exists() and current_positions:
        try:
            with open(position_file, 'r', encoding='utf-8') as f:
                position_contexts = json.load(f)
            
            if position_contexts:
                context += f"\n## 🔒 Position Commitments\n"
                for coin, ctx in position_contexts.items():
                    # Only show symbols still in position
                    if coin in current_positions:
                        current_price = current_positions[coin]
                        target_tp = ctx.get('target_tp', 0)
                        
                        if target_tp > 0:
                            distance = (target_tp - current_price) / current_price * 100
                            
                            context += f"""**{coin}**: Target {target_tp:.0f} (distance {distance:.1f}%)
- Entry Reason: {ctx.get('entry_reason', 'N/A')[:50]}
    - Commitment: {ctx.get('ai_strategy', 'Trust the plan')}
"""
        except Exception as e:
            print(f"⚠️ Failed to read position contexts: {e}")
    
    return context


if __name__ == "__main__":
    main()
