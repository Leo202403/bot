import os
import time
import csv
import schedule
from openai import OpenAI
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
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

# 🔧 明确指定 .env 文件路径
_env_file = Path(__file__).parent / '.env'
if not _env_file.exists():
    raise FileNotFoundError(f"❌ 找不到 .env 文件: {_env_file}")
load_dotenv(_env_file, override=True)

# 🔧 V8.3.32.13: 模型显示名称（用于Bark推送）
MODEL_DISPLAY_NAME = "DS"  # DS = DeepSeek

# ==================== 【V8.3.16】优化配置开关 ====================
ENABLE_V770_FULL_OPTIMIZATION = False  # V7.7.0完整优化（7-10分钟）
ENABLE_V770_QUICK_SEARCH = True        # V7.7.0快速探索（3分钟）- 为V8.3.12提供初始参数
ENABLE_PER_SYMBOL_OPTIMIZATION = False  # Per-Symbol优化（56-91分钟）
ENABLE_CONDITIONAL_AI_CALL = True       # 条件AI调用（仅Time Exit>80%时）
AI_AGGRESSIVENESS_DYNAMIC = True        # 动态AI激进度（根据Time Exit率调整）

# ==================== 辅助函数 ====================

def extract_json_from_ai_response(ai_content: str) -> dict:
    """
    从AI响应中提取JSON对象（鲁棒版本）
    
    尝试顺序：
    1. 清理特殊标签（兼容性处理）
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
    
    # 方法0: 移除特殊标签（兼容性处理）
    # 某些模型可能返回：<think>推理过程</think>\n{JSON}
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
        cost_per_call = 0.014  # DeepSeek API平均成本（元/次，deepseek-reasoner约0.014）
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
            'cost_reduction': f"约{saved_rate * 0.8:.0f}%",  # 考虑DeepSeek自身缓存
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

# 初始化DeepSeek客户端
deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
if not deepseek_api_key:
    raise ValueError("❌ DEEPSEEK_API_KEY 环境变量未设置，请检查 .env.deepseek 文件")
# 去除可能的空格和换行符
deepseek_api_key = deepseek_api_key.strip()
deepseek_client = OpenAI(
    api_key=deepseek_api_key, base_url="https://api.deepseek.com"
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

# 数据存储路径（DeepSeek专用目录）
DATA_DIR = Path(__file__).parent / "trading_data" / "deepseek"
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
    """发送Bark推送通知（支持多个地址 + DeepSeek分组）"""
    try:
        from urllib.parse import quote

        # 🔧 V8.2.6: 限制内容长度，避免URL过长导致404
        # GET请求URL长度限制通常为2048字符
        # 中文URL编码后长度约为原字符数×3，所以限制要更小
        MAX_TITLE_LEN = 50   # 编码后~150字符
        MAX_CONTENT_LEN = 600  # 编码后~1800字符（Bark URL限制约2048字节）
        
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

                # 添加group参数，将推送归类到"DeepSeek"文件夹
                url = f"https://api.day.app/{bark_key}/{encoded_title}/{encoded_content}?group=DeepSeek"
                
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


def send_email_notification(subject, body_html, model_name="DeepSeek"):
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
        # 根据model_name添加前缀（映射：deepseek->DeepSeek）
        display_name = "DeepSeek" if "deepseek" in model_name.lower() else model_name
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
        "信号分数",
        "共振指标数",
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


def update_close_position(coin_name, side, close_time, close_price, pnl, close_reason, close_pct=100):
    """更新平仓记录（找到对应的开仓记录并更新）- 支持分批平仓"""
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
        
            # 6. 处理平仓记录
            last_idx = matching_rows.index[-1]
            original_row = df.loc[last_idx].copy()
            
            if close_pct >= 100:
                # 完全平仓：直接更新记录
                df.at[last_idx, "平仓时间"] = close_time
                df.at[last_idx, "平仓价格"] = close_price
                df.at[last_idx, "盈亏(U)"] = pnl
                df.at[last_idx, "平仓理由"] = close_reason
            else:
                # 分批平仓：创建一条已平仓记录，保留一条未平仓记录
                # 更新当前记录为已平仓（代表平掉的部分）
                df.at[last_idx, "平仓时间"] = close_time
                df.at[last_idx, "平仓价格"] = close_price
                df.at[last_idx, "盈亏(U)"] = pnl
                df.at[last_idx, "平仓理由"] = close_reason
                
                # 创建新记录代表剩余仓位（复制原记录，清空平仓信息）
                remaining_row = original_row.copy()
                remaining_row["平仓时间"] = pd.NA
                remaining_row["平仓价格"] = pd.NA
                remaining_row["盈亏(U)"] = pd.NA
                remaining_row["平仓理由"] = pd.NA
                remaining_row["开仓理由"] = original_row["开仓理由"] + f" [剩余{100-close_pct:.0f}%]"
                
                # 将新记录追加到DataFrame
                df = pd.concat([df, pd.DataFrame([remaining_row])], ignore_index=True)
                print(f"  📝 已创建剩余{100-close_pct:.0f}%仓位的新记录")

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


def _precision_to_decimal_places(precision_value):
    """
    将precision值转换为小数位数（整数）
    
    Binance API可能返回两种格式：
    - 整数：如 2 表示2位小数
    - 浮点数：如 0.01 表示2位小数，0.001 表示3位小数
    
    Args:
        precision_value: 整数或浮点数
    
    Returns:
        int: 小数位数
    """
    if isinstance(precision_value, int):
        return precision_value
    elif isinstance(precision_value, float):
        # 通过计算浮点数的小数位数来确定精度
        # 例如: 0.01 -> 2, 0.001 -> 3, 0.1 -> 1
        import math
        if precision_value <= 0:
            return 0
        return max(0, int(round(-math.log10(precision_value))))
    else:
        return 2  # 默认2位小数


def set_tpsl_orders_via_papi(symbol: str, side: str, amount: float, stop_loss: float = None, take_profit: float = None, verbose: bool = True):
    """
    V7.9.3 通过papi端点为仓位设置止盈止损订单（V8.5.1.3: 添加精度处理）
    
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
    
    # 🆕 V8.5.1.3: 获取市场精度信息
    try:
        markets = exchange.load_markets()
        market_info = markets.get(symbol, {})
        amount_precision_raw = market_info.get('precision', {}).get('amount', 3)
        price_precision_raw = market_info.get('precision', {}).get('price', 2)
        
        # 🔧 V8.5.1.4: 转换precision为整数（支持浮点数格式）
        amount_precision = _precision_to_decimal_places(amount_precision_raw)
        price_precision = _precision_to_decimal_places(price_precision_raw)
        
        # 对数量和价格进行精度舍入
        amount = round(amount, amount_precision)
        if stop_loss:
            stop_loss = round(stop_loss, price_precision)
        if take_profit:
            take_profit = round(take_profit, price_precision)
    except Exception as e:
        if verbose:
            print(f"  ⚠️ 获取市场精度失败，使用默认值: {e}")
        # 使用默认精度
        amount = round(amount, 3)
        if stop_loss:
            stop_loss = round(stop_loss, 2)
        if take_profit:
            take_profit = round(take_profit, 2)
    
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
                    model_name = os.getenv("MODEL_NAME", "deepseek")
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
                        f"[DeepSeek]{coin}自动平仓{pnl_emoji}",
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
        
        # 🔧 V8.3.32.9: 保留最近200条（覆盖约2天，每天96条）
        if len(history) > 200:
            history = history[-200:]
        
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
            config_file = Path("trading_data") / os.getenv("MODEL_NAME", "deepseek") / "learning_config.json"
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            # 发送盈利恢复通知
            send_recovery_notification_v7(
                model_name=os.getenv("MODEL_NAME", "DeepSeek"),
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
            config_file = Path("trading_data") / os.getenv("MODEL_NAME", "deepseek") / "learning_config.json"
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            # 发送恢复通知
            send_recovery_notification_v7(
                model_name=os.getenv("MODEL_NAME", "DeepSeek"),
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
        trades_file = Path("trading_data") / os.getenv("MODEL_NAME", "deepseek") / "trades_history.csv"
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
        trades_file = Path("trading_data") / os.getenv("MODEL_NAME", "deepseek") / "trades_history.csv"
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
        
        model_name = os.getenv("MODEL_NAME", "deepseek")
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
            
            # 【V8.3.21.2修复】获取并转换K线数据格式
            # kline_data是ccxt格式的列表：[[timestamp, open, high, low, close, volume], ...]
            kline_list_raw = data.get("kline_data", [])
            
            # 转换为字典格式，方便后续处理
            kline_list = []
            for kline in kline_list_raw:
                if isinstance(kline, list) and len(kline) >= 6:
                    kline_list.append({
                        'timestamp': kline[0],
                        'open': kline[1],
                        'high': kline[2],
                        'low': kline[3],
                        'close': kline[4],
                        'volume': kline[5]
                    })
            
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
            
            # 【V8.5.2.4.3完整修复】直接从data获取indicator_consensus
            # 现在在get_ohlcv_data中已经计算好了，无需重复计算
            indicator_consensus = data.get("indicator_consensus", 0)
            
            # 【V8.5.2.4.3完整修复】直接从data获取consensus_score
            # 现在在get_ohlcv_data中已经计算好了（如果需要的话）
            consensus_score = data.get("consensus_score", 0)
            
            # 【V8.2】计算信号评分的各个维度（保存"原料"而非"成品"）
            # 初始化signal_type（防止未定义错误）
            signal_type = 'swing'
            
            try:
                # 【V8.3.10.3修复】确保data不为None
                if not data or not isinstance(data, dict):
                    raise ValueError("Invalid market_data")
                
                # 【V8.5.2.4.89.25】双信号分评估：同时计算超短线和波段视角
                scalping_components = calculate_signal_score_components(data, 'scalping')
                swing_components = calculate_signal_score_components(data, 'swing')
                
                # 直接使用components中的total_score（已根据权重计算）
                scalping_score = scalping_components.get('total_score', 0)
                swing_score = swing_components.get('total_score', 0)
                
                # 保存双信号分到data中
                data['scalping_signal_score'] = scalping_score
                data['swing_signal_score'] = swing_score
                
                # 判断推荐策略：根据配置的阈值
                scalping_threshold = 80  # 超短线高阈值
                swing_threshold = 65     # 波段低阈值
                
                scalping_qualified = scalping_score >= scalping_threshold
                swing_qualified = swing_score >= swing_threshold
                
                # 兼容性：signal_type和components使用较高分数的那个
                # 但同时考虑阈值（合格性）
                if scalping_qualified and (not swing_qualified or scalping_score >= swing_score):
                    signal_type = 'scalping'
                    components = scalping_components
                    data['signal_score'] = scalping_score
                    data['recommended_strategy'] = 'scalping'
                elif swing_qualified:
                    signal_type = 'swing'
                    components = swing_components
                    data['signal_score'] = swing_score
                    data['recommended_strategy'] = 'swing'
                else:
                    # 都不合格，选分数高的
                    if scalping_score >= swing_score:
                        signal_type = 'scalping'
                        components = scalping_components
                        data['signal_score'] = scalping_score
                        data['recommended_strategy'] = 'scalping'
                    else:
                        signal_type = 'swing'
                        components = swing_components
                        data['signal_score'] = swing_score
                        data['recommended_strategy'] = 'swing'
                
            except Exception as e:
                print(f"⚠️ 计算评分维度失败: {e}")
                # 降级：使用默认值
                components = {
                    'signal_type': 'scalping',
                    'total_score': 0,
                }
                data['scalping_signal_score'] = 0
                data['swing_signal_score'] = 0
                data['scalping_signal_score_weighted'] = 0
                data['swing_signal_score_weighted'] = 0
                signal_type = 'swing'
            
            # 【V8.4】更新consensus_score的形态评分部分（使用components中的数据）
            try:
                # 获取形态评分
                pin_bar_score = components.get('pin_bar_score', 0)
                engulfing_score = components.get('engulfing_score', 0)
                breakout_score = components.get('breakout_score', 0)
                
                # 重新计算consensus_score（加上形态评分）
                # 简化方式：在原有基础上追加形态得分
                pattern_score = 0
                if pin_bar_score > 0:
                    pattern_score += min(5, pin_bar_score / 2)
                if engulfing_score > 0:
                    pattern_score += min(5, engulfing_score / 2)
                if breakout_score > 0:
                    pattern_score += min(5, breakout_score / 5)
                
                consensus_score = min(100, consensus_score + int(pattern_score))
            except Exception as e:
                pass  # 如果失败，使用之前计算的consensus_score
            
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
                "indicator_consensus": indicator_consensus,  # 【兼容性】指标共振数（0-5）
                "consensus_score": consensus_score,  # 【V8.4新增】综合确认度评分（0-100）
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
        
        # 【V8.5.2新增】去重逻辑：检查当前时间点是否已有数据
        if snapshot_file.exists():
            try:
                existing_df = pd.read_csv(snapshot_file, dtype={'time': str})
                
                # 获取当前要保存的时间点
                current_time_str = snapshot_data[0].get('time')
                
                if current_time_str:
                    # 检查这个时间点是否已存在
                    existing_times = set(existing_df['time'].values)
                    
                    if current_time_str in existing_times:
                        print(f"⏭️  跳过保存：时间点 {current_time_str} 的数据已存在")
                        return  # 跳过保存
                    else:
                        print(f"✅ 时间点 {current_time_str} 尚未保存，继续保存")
                
            except Exception as e:
                print(f"⚠️ 读取现有文件失败: {e}，将直接追加")
        
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
        
        model_name = os.getenv("MODEL_NAME", "deepseek")
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
        # 【V8.3.21.5修复】检查并修复过高的共振阈值
        fixed_consensus = False
        for strategy in ['scalping', 'swing']:
            if strategy in config:
                old_consensus = config[strategy].get('min_consensus', 2)
                if old_consensus >= 2:
                    config[strategy]['min_consensus'] = 1
                    # 提高信号质量要求作为补偿（75分以上相对安全）
                    config[strategy]['min_signal_score'] = max(75, config[strategy].get('min_signal_score', 60))
                    fixed_consensus = True
                    print(f"  🔧 自动修复{strategy} min_consensus: {old_consensus} → 1 (提高signal_score≥75)")
        
        if fixed_consensus:
            print("  💡 原因：共振≥2会错过98%的高质量机会（如BNB 82分/2共振 盈利20%）")
        
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
            model_name = os.getenv("MODEL_NAME", "deepseek")
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


def update_position_after_adding(symbol, side, new_avg_price, new_total_amount, 
                                  new_amount, new_price, add_reason, signal_score, 
                                  price_improvement_pct):
    """
    更新CSV记录，追加加仓历史（V8.5.2新增）
    
    格式：原始理由 | [加仓N] 时间 +数量@价格 理由:xxx
    
    Args:
        symbol: 交易对
        side: 方向 (long/short)
        new_avg_price: 新的平均开仓价
        new_total_amount: 新的总数量
        new_amount: 本次加仓数量
        new_price: 本次加仓价格
        add_reason: 加仓理由（简短）
        signal_score: 信号评分
        price_improvement_pct: 价格改善百分比
    """
    import fcntl
    import shutil
    
    coin_name = symbol.split('/')[0]
    side_cn = "多" if side == "long" else "空"
    
    max_retries = 3
    for attempt in range(max_retries):
        lock_file = None
        try:
            # 1. 创建文件锁
            lock_path = TRADES_FILE.parent / f"{TRADES_FILE.name}.lock"
            lock_file = open(lock_path, "w")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # 2. 创建备份
            backup_path = TRADES_FILE.parent / f"{TRADES_FILE.name}.backup"
            if TRADES_FILE.exists():
                shutil.copy2(TRADES_FILE, backup_path)
            
            # 3. 读取现有数据
            df = pd.read_csv(TRADES_FILE, encoding="utf-8")
            df.columns = df.columns.str.strip().str.replace("\ufeff", "")
            
            # 4. 找到该币种、该方向、未平仓的记录
            mask = (
                (df["币种"] == coin_name)
                & (df["方向"] == side_cn)
                & (df["平仓时间"].isna())
            )
            matching_rows = df[mask]
            
            if matching_rows.empty:
                print(f"  ⚠️ 未找到 {coin_name} {side_cn} 的未平仓记录，无法记录加仓")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                return
            
            # 5. 更新记录
            last_idx = matching_rows.index[-1]
            original_reason = str(df.at[last_idx, "开仓理由"])
            
            # 计算是第几次加仓
            add_count = original_reason.count("[加仓") + 1
            
            # 构建加仓记录
            current_time = datetime.now().strftime("%H:%M")
            add_entry = (
                f" | [加仓{add_count}] {current_time} "
                f"+{new_amount:.3f}@{new_price:.2f} "
                f"理由:{add_reason}+价格优{abs(price_improvement_pct):.1f}%+信号分{signal_score}"
            )
            
            # 更新字段
            df.at[last_idx, "开仓价"] = new_avg_price
            df.at[last_idx, "开仓理由"] = original_reason + add_entry
            
            # 6. 保存
            temp_file = TRADES_FILE.parent / f"{TRADES_FILE.name}.tmp"
            df.to_csv(temp_file, index=False, encoding="utf-8")
            temp_file.replace(TRADES_FILE)
            
            print(f"  📝 已记录加仓{add_count}: +{new_amount:.3f}@{new_price:.2f}, 新平均价{new_avg_price:.2f}")
            
            # 7. 释放锁
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
            break
            
        except Exception as e:
            print(f"  ⚠️ 更新加仓记录失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if lock_file:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()
                except:
                    pass
            
            if attempt == max_retries - 1:
                print(f"  ❌ 加仓记录更新失败")
            else:
                import time
                time.sleep(0.5)
                continue


def add_to_position(symbol, side, new_amount, new_price, leverage, existing_position, 
                    ai_signal, price_improvement_pct, available_balance, current_positions):
    """
    加仓到现有持仓（V8.5.2新增）
    
    Args:
        symbol: 交易对
        side: 方向 (long/short)
        new_amount: 新增数量
        new_price: 新增价格
        leverage: 杠杆
        existing_position: 现有持仓信息
        ai_signal: AI信号
        price_improvement_pct: 价格改善百分比
        available_balance: 可用余额
        current_positions: 当前所有持仓
    
    Returns:
        加仓是否成功
    """
    try:
        coin_name = symbol.split('/')[0]
        side_cn = "多" if side == "long" else "空"
        
        # 1. 计算原持仓成本
        old_amount = existing_position.get('size', 0)
        old_price = existing_position.get('entry_price', 0)
        old_cost = old_amount * old_price
        
        # 2. 计算新增成本
        new_cost = new_amount * new_price
        
        # 3. 计算合并后的平均价
        total_amount = old_amount + new_amount
        avg_price = (old_cost + new_cost) / total_amount
        
        print(f"\n🔼 执行加仓: {coin_name} {side_cn}")
        print(f"  原持仓: {old_amount:.3f}个 @{old_price:.2f}")
        print(f"  新增: {new_amount:.3f}个 @{new_price:.2f}")
        print(f"  合并后: {total_amount:.3f}个 @{avg_price:.2f}")
        
        # 4. 执行市价单加仓
        order_side = 'buy' if side == 'long' else 'sell'
        order = exchange.create_market_order(
            symbol,
            order_side,
            new_amount,
            params={'tag': 'f1ee03b510d5SUDE'}
        )
        print(f"  ✓ 加仓订单已执行")
        
        # 5. 更新CSV记录
        add_reason = ai_signal.get('reason', '金字塔加仓')[:20]  # 简短理由
        signal_score = ai_signal.get('signal_quality', 0)
        
        update_position_after_adding(
            symbol, side, avg_price, total_amount,
            new_amount, new_price, add_reason, signal_score,
            price_improvement_pct
        )
        
        # 6. 重新计算并设置止盈止损
        try:
            # 清理旧的止盈止损订单
            clear_symbol_orders(symbol, verbose=False)
            
            # 从AI信号获取新的止盈止损
            stop_loss = ai_signal.get('stop_loss_price', 0)
            take_profit = ai_signal.get('take_profit_price', 0)
            
            if stop_loss and take_profit:
                # 基于新平均价重新设置
                sl_ok, tp_ok = set_tpsl_orders_via_papi(
                    symbol=symbol,
                    side=side,
                    amount=total_amount,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    verbose=True
                )
                if not (sl_ok or tp_ok):
                    print(f"  ⚠️ 止盈止损设置失败")
        except Exception as e:
            print(f"  ⚠️ 重设止盈止损失败: {e}")
        
        # 7. 更新 position_contexts（记录加仓时间和次数）
        try:
            model_name = os.getenv("MODEL_NAME", "deepseek")
            context_file = Path("trading_data") / model_name / "position_contexts.json"
            
            if context_file.exists():
                with open(context_file, 'r', encoding='utf-8') as f:
                    contexts = json.load(f)
            else:
                contexts = {}
            
            if coin_name in contexts:
                contexts[coin_name]['last_add_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                contexts[coin_name]['add_count'] = contexts[coin_name].get('add_count', 0) + 1
                contexts[coin_name]['avg_entry_price'] = avg_price
                
                with open(context_file, 'w', encoding='utf-8') as f:
                    json.dump(contexts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  ⚠️ 更新position_contexts失败: {e}")
        
        # 8. 发送Bark通知
        notional_value = total_amount * new_price
        send_bark_notification(
            f"[DeepSeek]{coin_name}加仓✅",
            f"{side_cn}仓 加仓{new_amount:.3f}个 @{new_price:.2f}\n"
            f"新平均价: {avg_price:.2f}\n"
            f"总仓位: {total_amount:.3f}个 ({notional_value:.2f}U)\n"
            f"理由: {add_reason}+价格优{abs(price_improvement_pct):.1f}%+信号分{signal_score}"
        )
        
        # 9. 刷新持仓快照
        try:
            refreshed_positions, _ = get_all_positions()
            save_positions_snapshot(refreshed_positions, 0)
            print("  ✓ 持仓快照已更新")
        except:
            pass
        
        return True
        
    except Exception as e:
        print(f"❌ 加仓失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 发送失败通知
        send_bark_notification(
            f"[DeepSeek]{coin_name}加仓失败❌",
            f"{side_cn}仓 加仓{new_amount:.3f}个失败\n"
            f"错误: {str(e)[:80]}"
        )
        return False


def check_add_position_conditions(symbol, existing_position, ai_signal, available_balance, current_price=0, total_assets=0):
    """
    检查是否满足加仓条件（V8.5.2新增）
    
    Args:
        symbol: 交易对
        existing_position: 现有持仓信息
        ai_signal: AI信号信息
        available_balance: 可用余额
        current_price: 当前市场价格
        total_assets: 总资产
    
    Returns:
        (can_add: bool, reason: str, price_improvement_pct: float)
    """
    try:
        # 1. 检查现有持仓状态（浮亏不超过5%）
        unrealized_pnl = existing_position.get('unrealized_pnl', 0)
        notional = abs(existing_position.get('notional', 0))
        if notional > 0:
            pnl_pct = unrealized_pnl / notional
            if pnl_pct < -0.05:
                return False, f"现有持仓浮亏{pnl_pct*100:.1f}%>5%", 0
        
        # 2. 检查信号质量（需要≥原信号90%）
        new_score = ai_signal.get('signal_quality', 0) if ai_signal else 0
        
        # 从position_contexts读取原始信号质量
        try:
            model_name = os.getenv("MODEL_NAME", "deepseek")
            context_file = Path("trading_data") / model_name / "position_contexts.json"
            old_score = 0
            if context_file.exists():
                with open(context_file, 'r', encoding='utf-8') as f:
                    contexts = json.load(f)
                    coin_name = symbol.split('/')[0]
                    if coin_name in contexts:
                        old_score = contexts[coin_name].get('signal_quality', 0)
            
            if old_score > 0 and new_score < old_score * 0.9:
                return False, f"信号质量{new_score}<原信号{old_score}的90%", 0
        except Exception as e:
            print(f"  ⚠️ 读取原始信号质量失败: {e}")
        
        # 3. 检查价格是否更优（金字塔加仓）
        entry_price = existing_position.get('entry_price', 0)
        side = existing_position.get('side', '')
        
        if entry_price == 0 or current_price == 0:
            return False, "价格数据缺失", 0
        
        # 计算价格改善
        if side == 'short':
            price_improvement_pct = ((current_price - entry_price) / entry_price) * 100
            if price_improvement_pct <= 0.5:  # 空单需价格至少高0.5%
                return False, f"空单加仓需价格更优（当前{current_price:.2f}仅比开仓价{entry_price:.2f}高{price_improvement_pct:.2f}%<0.5%）", 0
        else:  # long
            price_improvement_pct = ((entry_price - current_price) / entry_price) * 100
            if price_improvement_pct <= 0.5:  # 多单需价格至少低0.5%
                return False, f"多单加仓需价格更优（当前{current_price:.2f}仅比开仓价{entry_price:.2f}低{price_improvement_pct:.2f}%<0.5%）", 0
        
        # 4. 检查加仓后总保证金是否超过单币种开仓上限
        # 获取新仓位的保证金
        new_position_margin = ai_signal.get('position_size_usd', 0) if ai_signal else 0
        new_leverage = ai_signal.get('leverage', 1) if ai_signal else 1
        
        # 计算现有持仓的保证金（名义价值 / 杠杆）
        existing_leverage = existing_position.get('leverage', 1)
        if existing_leverage <= 0:
            existing_leverage = 1
        existing_margin = notional / existing_leverage
        
        # 累计保证金
        total_margin_after_add = existing_margin + new_position_margin
        
        # 计算单币种允许的最大保证金（与单次开仓限制一致）
        MIN_CASH_RESERVE_RATIO = 0.20  # 保留20%现金储备
        max_single_position = available_balance - (total_assets * MIN_CASH_RESERVE_RATIO) if total_assets > 0 else available_balance * 0.8
        
        print(f"   [加仓检查] 现有保证金: {existing_margin:.2f}U, 新增保证金: {new_position_margin:.2f}U")
        print(f"   [加仓检查] 累计保证金: {total_margin_after_add:.2f}U, 单币种上限: {max_single_position:.2f}U")
        
        # 限制：累计保证金不超过单币种开仓上限
        if total_margin_after_add > max_single_position:
            return False, f"加仓后总保证金{total_margin_after_add:.2f}U>单币种上限{max_single_position:.2f}U", 0
        
        # 5. 检查加仓频率（从position_contexts读取最后加仓时间）
        try:
            if context_file.exists():
                with open(context_file, 'r', encoding='utf-8') as f:
                    contexts = json.load(f)
                    coin_name = symbol.split('/')[0]
                    if coin_name in contexts:
                        last_add_time_str = contexts[coin_name].get('last_add_time', '')
                        if last_add_time_str:
                            last_add_time = datetime.strptime(last_add_time_str, "%Y-%m-%d %H:%M:%S")
                            time_since_last_add = (datetime.now() - last_add_time).total_seconds() / 60
                            if time_since_last_add < 60:  # 1小时内不允许重复加仓
                                return False, f"距上次加仓仅{time_since_last_add:.0f}分钟<60分钟", 0
        except Exception as e:
            print(f"  ⚠️ 检查加仓频率失败: {e}")
        
        # 所有条件满足
        return True, f"价格优{abs(price_improvement_pct):.1f}%+信号强{new_score}分+仓位可控", price_improvement_pct
        
    except Exception as e:
        print(f"⚠️ 加仓条件检查失败: {e}")
        return False, f"检查失败: {str(e)[:50]}", 0


def check_single_direction_per_coin(symbol, operation, current_positions, ai_signal=None, available_balance=0, current_price=0, total_assets=0):
    """
    检查单币种单方向限制，支持智能加仓（V8.5.2更新）
    
    规则：
    - 单个币种只能持有一个方向的订单（做多或做空）
    - 不允许同一币种同时做多和做空（对冲）
    - 满足条件时允许加仓到现有订单
    
    Args:
        symbol: 交易对符号
        operation: 操作类型（OPEN_LONG/OPEN_SHORT）
        current_positions: 当前持仓列表
        ai_signal: AI信号信息（用于判断加仓条件）
        available_balance: 可用余额
        current_price: 当前市场价格
        total_assets: 总资产
    
    Returns:
        (allowed: bool, reason: str, should_add: bool, price_improvement: float)
    """
    try:
        # 检查是否已有该币种的持仓
        existing_positions = [p for p in current_positions if p.get("symbol") == symbol]
        
        if not existing_positions:
            return True, f"该币种无持仓，可以开仓", False, 0
        
        # 获取现有订单的方向
        existing_position = existing_positions[0]
        existing_side = existing_position.get("side", "").lower()
        
        # 确定新订单方向
        new_side = "long" if operation == "OPEN_LONG" else "short"
        
        # 检查是否是相反方向（对冲）
        if existing_side != new_side:
            return False, (
                f"该币种已有{existing_side}仓位，不允许开{new_side}仓（禁止对冲）。"
                f"建议：先平仓现有订单再开反向单"
            ), False, 0
        
        # 检查是否是相同方向 - 判断是否可以加仓
        if existing_side == new_side:
            # 检查是否满足加仓条件
            can_add, add_reason, price_improvement = check_add_position_conditions(
                symbol, existing_position, ai_signal, available_balance, current_price, total_assets
            )
            
            if can_add:
                # 满足加仓条件
                return True, f"✅加仓条件: {add_reason}", True, price_improvement
            else:
                # 不满足加仓条件，拒绝
                position_notional = abs(existing_position.get("notional", 0))
                
                return False, (
                    f"该币种已有{existing_side}仓位（名义价值{position_notional:.2f}U），"
                        f"不满足加仓条件：{add_reason}"
                    ), False, 0
        
        return True, f"检查通过", False, 0
    
    except Exception as e:
        print(f"⚠️ 单方向检查失败: {e}")
        return True, "检查失败，放行", False, 0


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

【V8.5.2.4.43】移动止盈止损决策指南：
- 当市场波动率高、趋势明确时，建议启用移动止损（trailing_stop_enabled=true）
- 超短线交易：适合在快速突破时使用移动止损，保护短期利润
- 波段交易：在强趋势中使用移动止损，让利润充分奔跑
- 震荡市场：建议使用静态止损（trailing_stop_enabled=false），避免频繁触发
- 根据历史回测数据和当前市场状态，自主决定是否启用移动止损
- trailing_stop_enabled参数可以在scalping_params和swing_params中独立设置

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
        response = deepseek_client.chat.completions.create(
            model="deepseek-reasoner",
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
        model_dir = os.getenv("MODEL_NAME", "deepseek")
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
        model_dir = os.getenv("MODEL_NAME", "deepseek")
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
        # 【V8.5.2.3升级】加载learning_config用于动态计算signal_score
        learning_config = None
        if 'min_signal_score' not in config_variant:
            try:
                learning_config = load_learning_config()
                config_variant['min_signal_score'] = learning_config.get('global', {}).get('min_signal_score', 55)
            except:
                config_variant['min_signal_score'] = 55  # 默认55分
        else:
            # 即使已有min_signal_score，也要加载learning_config用于动态评分
            try:
                learning_config = load_learning_config()
            except:
                pass
        
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
                    
                    # 【V8.5.2.3】动态计算signal_score（不再依赖CSV中的值）
                    # 先推断信号类型（基于趋势强度和分数）
                    strong_trend = row.get('trend_4h') or row.get('trend_1h')
                    inferred_signal_type_for_score = 'swing' if strong_trend else 'scalping'
                    
                    # 调用recalculate_signal_score_from_snapshot动态计算
                    signal_score = recalculate_signal_score_from_snapshot(row, inferred_signal_type_for_score, learning_config)
                    
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

        response = deepseek_client.chat.completions.create(
            model="deepseek-reasoner",
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
#   python3 /tmp/merge_v770_to_q wen.py
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
            
            # 调用AI（直接使用全局deepseek_client）
            try:
                response = deepseek_client.chat.completions.create(
                    model="deepseek-reasoner",
                    messages=[{"role": "user", "content": ai_prompt}],
                    temperature=0.7,
                    max_tokens=8000  # 🔧 增加到8000，避免复杂决策时JSON被截断
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
                response = deepseek_client.chat.completions.create(
                    model="deepseek-reasoner",
                    messages=[{"role": "user", "content": ai_deep_prompt}],
                    temperature=0.8,  # 更高温度鼓励创新
                    max_tokens=8000  # 🔧 增加到8000，避免复杂决策时JSON被截断
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
                response = deepseek_client.chat.completions.create(
                    model="deepseek-reasoner",
                    messages=[{"role": "user", "content": emergency_prompt}],
                    temperature=0.9,  # 最高温度，最大创新
                    max_tokens=8000  # 🔧 增加到8000，避免复杂决策时JSON被截断
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
  