from flask import Flask, jsonify, request
import logging
from datetime import datetime, timedelta
import json
import os
import csv

app = Flask(__name__)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== 时区转换辅助函数 ====================

def utc_to_beijing_time(utc_time_str):
    """
    将UTC时间字符串转换为北京时间字符串
    服务器在美国，存储的是UTC时间，需要+8小时展示给用户
    """
    if not utc_time_str or not utc_time_str.strip():
        return utc_time_str
    
    try:
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%m-%d %H:%M', '%Y-%m-%d']:
            try:
                utc_dt = datetime.strptime(utc_time_str.strip(), fmt)
                beijing_dt = utc_dt + timedelta(hours=8)
                return beijing_dt.strftime(fmt)
            except ValueError:
                continue
        return utc_time_str
    except Exception as e:
        logging.error(f"时间转换失败: {utc_time_str}, 错误: {e}")
        return utc_time_str

def beijing_to_utc_time(beijing_time_str):
    """
    将北京时间字符串转换为UTC时间字符串
    用户输入的是北京时间，需要-8小时去查询UTC数据
    """
    if not beijing_time_str or not beijing_time_str.strip():
        return beijing_time_str
    
    try:
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
            try:
                beijing_dt = datetime.strptime(beijing_time_str.strip(), fmt)
                utc_dt = beijing_dt - timedelta(hours=8)
                return utc_dt.strftime(fmt)
            except ValueError:
                continue
        return beijing_time_str
    except Exception as e:
        logging.error(f"时间转换失败: {beijing_time_str}, 错误: {e}")
        return beijing_time_str

# ==================== 交易指标计算辅助函数 ====================

def calculate_max_drawdown(trades_history):
    """计算最大回撤"""
    if not trades_history:
        return 0.0
    
    initial_capital = 100.0
    sorted_trades = sorted(trades_history, key=lambda x: x.get('开仓时间', ''))
    
    capital = initial_capital
    peak = capital
    max_dd = 0.0
    
    for trade in sorted_trades:
        if trade.get('平仓时间'):
            pnl = float(trade.get('盈亏(U)', 0) or 0)
            capital += pnl
            
            if capital > peak:
                peak = capital
            
            if peak > 0:
                drawdown = (peak - capital) / peak * 100
                if drawdown > max_dd:
                    max_dd = drawdown
    
    return max_dd

def calculate_sharpe_ratio(trades_history, pnl_history=None, initial_capital=100.0):
    """计算夏普比率（年化）"""
    if not trades_history or len(trades_history) < 2:
        return 0.0
    
    if pnl_history and len(pnl_history) > 1:
        try:
            assets = []
            for record in pnl_history:
                asset_value = float(record.get('总资产', record.get('total_assets', 0)) or 0)
                if asset_value > 0:
                    assets.append(asset_value)
            
            if len(assets) < 2:
                return 0.0
            
            returns = []
            for i in range(1, len(assets)):
                if assets[i-1] > 0:
                    ret = (assets[i] - assets[i-1]) / assets[i-1]
                    returns.append(ret)
            
            if not returns:
                return 0.0
            
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_return = variance ** 0.5
            
            if std_return == 0:
                return 0.0
            
            risk_free_rate = 0.00
            sharpe = (mean_return - risk_free_rate) / std_return
            annualization_factor = (365 * 24 * 4) ** 0.5
            annual_sharpe = sharpe * annualization_factor
            
            return annual_sharpe
        except Exception as e:
            logging.error(f"使用盈亏历史计算夏普比率失败: {e}")
    
    try:
        sorted_trades = sorted([t for t in trades_history if t.get('平仓时间')], 
            key=lambda x: x.get('平仓时间', ''))
        
        if len(sorted_trades) < 2:
            return 0.0
        
        capital = initial_capital
        returns = []
        
        for trade in sorted_trades:
            pnl = float(trade.get('盈亏(U)', 0) or 0)
            if capital > 0:
                ret = pnl / capital
                returns.append(ret)
                capital += pnl
        
        if not returns:
            return 0.0
        
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = variance ** 0.5
        
        if std_return == 0:
            return 0.0
        
        start_time = datetime.strptime(sorted_trades[0].get('开仓时间', ''), '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(sorted_trades[-1].get('平仓时间', ''), '%Y-%m-%d %H:%M:%S')
        days_elapsed = (end_time - start_time).total_seconds() / 86400
        
        if days_elapsed <= 0:
            return 0.0
        
        trades_per_year = len(sorted_trades) * (365 / days_elapsed)
        sharpe = mean_return / std_return
        annual_sharpe = sharpe * (trades_per_year ** 0.5)
        
        return annual_sharpe
    except Exception as e:
        logging.error(f"计算夏普比率失败: {e}")
        return 0.0

def filter_data_by_time_range(data_list, time_field, range_type='all', start_date='', end_date=''):
    """根据时间范围过滤数据"""
    if range_type == 'all':
        return data_list
    
    from datetime import timezone
    beijing_tz = timezone(timedelta(hours=8))
    now_beijing = datetime.now(beijing_tz).replace(tzinfo=None)
    
    if range_type == 'day':
        start_time = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif range_type == 'week':
        days_since_monday = now_beijing.weekday()
        start_time = (now_beijing - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif range_type == 'month':
        start_time = now_beijing.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif range_type == 'custom' and start_date and end_date:
        start_time = datetime.strptime(start_date, '%Y-%m-%d')
        end_time = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
    else:
        return data_list
    
    # 时区转换：服务器在美国，CSV存储的是UTC时间
    start_time = start_time - timedelta(hours=8)
    if end_time:
        end_time = end_time - timedelta(hours=8)
    
    filtered = []
    parse_errors = 0
    
    for item in data_list:
        time_str = item.get(time_field, '')
        if not time_str:
            continue
        
        item_time = None
        time_formats = [
            '%Y-%m-%d %H:%M:%S',
            '%m-%d %H:%M',
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d',
        ]
        
        for fmt in time_formats:
            try:
                item_time = datetime.strptime(time_str.strip(), fmt)
                if fmt == '%m-%d %H:%M':
                    item_time = item_time.replace(year=now_beijing.year)
                break
            except:
                continue
        
        if item_time is None:
            try:
                item_time = datetime.strptime(time_str.split('.')[0].strip(), '%Y-%m-%d %H:%M:%S')
            except:
                parse_errors += 1
                continue
        
        if end_time:
            if start_time <= item_time < end_time:
                filtered.append(item)
        else:
            if item_time >= start_time:
                filtered.append(item)
    
    if parse_errors > 0:
        logging.warning(f"[filter_data_by_time_range] 时间过滤中有 {parse_errors} 条记录时间格式解析失败")
    
    logging.info(f"[filter_data_by_time_range] 字段={time_field}, 范围={range_type}, 输入={len(data_list)}, 输出={len(filtered)}")
    
    return filtered

# ==================== AI交易系统配置 ====================

TRADING_DATA_BASE = '/home/admin/10-23-bot/ds/trading_data'
CONTROL_PASSWORD = '34801198Bai'
VISITOR_LOG_FILE = os.path.join(TRADING_DATA_BASE, 'visitor_ips.txt')

def get_trading_data_dir(model='deepseek'):
    """根据模型名称获取数据目录"""
    if model not in ['deepseek', 'qwen']:
        model = 'deepseek'
    return os.path.join(TRADING_DATA_BASE, model)

def get_pause_reason(pause_level):
    """根据暂停等级返回原因描述"""
    if pause_level == 0:
        return ''
    elif pause_level == 1:
        return '连续3笔亏损，2小时冷静期'
    elif pause_level == 2:
        return '再连续2笔亏损，4小时冷静期'
    elif pause_level == 3:
        return '再连续2笔亏损，暂停至明日'
    else:
        return f'冷静期等级{pause_level}'

def log_visitor():
    """记录访客IP"""
    try:
        if request.headers.get('X-Forwarded-For'):
            client_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
        elif request.headers.get('X-Real-IP'):
            client_ip = request.headers.get('X-Real-IP')
        else:
            client_ip = request.remote_addr
        
        existing_ips = set()
        if os.path.exists(VISITOR_LOG_FILE):
            with open(VISITOR_LOG_FILE, 'r') as f:
                existing_ips = set(line.strip() for line in f if line.strip())
        
        if client_ip not in existing_ips:
            with open(VISITOR_LOG_FILE, 'a') as f:
                f.write(f"{client_ip}\n")
            return len(existing_ips) + 1
    else:
            return len(existing_ips)
    except Exception as e:
        logging.error(f"记录访客失败: {e}")
        return 0

def get_visitor_count():
    """获取独立访客数量"""
    try:
        if os.path.exists(VISITOR_LOG_FILE):
            with open(VISITOR_LOG_FILE, 'r') as f:
                return len([line for line in f if line.strip()])
        return 0
    except:
        return 0

# ==================== API端点 ====================

@app.route('/trading-visitor-count', methods=['GET'])
def trading_visitor_count():
    """获取访客数量"""
    try:
        count = get_visitor_count()
        return jsonify({'count': count}), 200
    except Exception as e:
        logging.error(f"获取访客数失败: {e}")
        return jsonify({'count': 0}), 200

@app.route('/trading-status', methods=['GET'])
def trading_status():
    """获取交易系统状态"""
    try:
        model = request.args.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        status_file = os.path.join(data_dir, 'system_status.json')
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data), 200
        else:
            return jsonify({'error': '系统状态文件不存在'}), 404
    except Exception as e:
        logging.error(f"读取交易状态失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-positions', methods=['GET'])
def trading_positions():
    """获取当前持仓（适配中英文字段名，支持时间筛选）"""
    try:
        model = request.args.get('model', 'deepseek')
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        data_dir = get_trading_data_dir(model)
        positions_file = os.path.join(data_dir, 'current_positions.csv')
        if os.path.exists(positions_file):
            with open(positions_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                raw_positions = list(reader)
            
            filtered_positions = filter_data_by_time_range(
                raw_positions, '开仓时间', range_type, start_date, end_date
            )
            
            positions = []
            for pos in filtered_positions:
                positions.append({
                    'symbol': pos.get('币种', pos.get('symbol', '')),
                    'side': pos.get('方向', pos.get('side', '')),
                    'size': float(pos.get('数量', pos.get('size', 0)) or 0),
                    'entry_price': float(pos.get('开仓价', pos.get('entry_price', 0)) or 0),
                    'unrealized_pnl': float(pos.get('当前盈亏(U)', pos.get('unrealized_pnl', 0)) or 0)
                })
            return jsonify({'positions': positions}), 200
        else:
            return jsonify({'positions': []}), 200
    except Exception as e:
        logging.error(f"读取持仓数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-history', methods=['GET'])
def trading_history():
    """获取交易历史（支持时间筛选，以平仓时间为准）"""
    try:
        model = request.args.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        limit = int(request.args.get('limit', 20))
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        trades_file = os.path.join(data_dir, 'trades_history.csv')
        if os.path.exists(trades_file):
            with open(trades_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                all_trades = list(reader)
            
            closed_trades = [t for t in all_trades if t.get('平仓时间')]
            filtered_trades = filter_data_by_time_range(
                closed_trades, '平仓时间', range_type, start_date, end_date
            )
            
            if len(filtered_trades) > limit:
                filtered_trades = sorted(filtered_trades, key=lambda x: x.get('平仓时间', ''), reverse=True)[:limit]
            
            return jsonify({'trades': filtered_trades}), 200
        else:
            return jsonify({'trades': []}), 200
        except Exception as e:
        logging.error(f"读取交易历史失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-pnl', methods=['GET'])
def trading_pnl():
    """获取盈亏曲线数据（支持日期范围筛选）"""
    try:
        model = request.args.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        limit = int(request.args.get('limit', 100))
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        pnl_file = os.path.join(data_dir, 'pnl_history.csv')
        if os.path.exists(pnl_file):
            with open(pnl_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) <= 1:
                    return jsonify({'pnl_data': []}), 200
                
                reader = csv.DictReader(lines)
                all_data = list(reader)
                
                from datetime import timezone
                beijing_tz = timezone(timedelta(hours=8))
                now_beijing = datetime.now(beijing_tz).replace(tzinfo=None)
                filtered_data = []
                
                if range_type == 'day':
                    start_time = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0)
                elif range_type == 'week':
                    days_since_monday = now_beijing.weekday()
                    start_time = (now_beijing - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
                elif range_type == 'month':
                    start_time = now_beijing.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                elif start_date and end_date:
                    start_time = datetime.strptime(start_date, '%Y-%m-%d')
                    end_time = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                else:
                    start_time = None
                
                for row in all_data:
                    timestamp = row.get('时间') or row.get('timestamp', '')
                    if not timestamp:
                        continue
                    
                    try:
                        row_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                    except:
                        continue
                    
                    if range_type in ['day', 'week', 'month']:
                        if row_time >= start_time:
                            filtered_data.append(row)
                    elif start_date and end_date:
                        if start_time <= row_time < end_time:
                            filtered_data.append(row)
                    else:
                        filtered_data.append(row)
                
                if range_type != 'all' and len(filtered_data) > limit:
                    filtered_data = filtered_data[-limit:]
                
                return jsonify({'pnl_data': filtered_data}), 200
    else:
            return jsonify({'pnl_data': []}), 200
    except Exception as e:
        logging.error(f"读取盈亏数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-ai-decisions', methods=['GET'])
def trading_ai_decisions():
    """获取AI决策历史（最近N条）"""
    try:
        model = request.args.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        limit = int(request.args.get('limit', 9999))  # 默认返回所有，支持无限滚动
        decisions_file = os.path.join(data_dir, 'ai_decisions.json')
        if os.path.exists(decisions_file):
            with open(decisions_file, 'r', encoding='utf-8') as f:
                decisions = json.load(f)
                if isinstance(decisions, list):
                    decisions = decisions[-limit:]
                    # 为每条决策添加model字段
                    for decision in decisions:
                        if isinstance(decision, dict) and 'model' not in decision:
                            decision['model'] = model
                return jsonify({'decisions': decisions}), 200
        else:
            return jsonify({'decisions': []}), 200
    except Exception as e:
        logging.error(f"读取AI决策失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-summary', methods=['GET'])
def trading_summary():
    """获取交易摘要（一次性返回所有关键信息）"""
    try:
        model = request.args.get('model', 'deepseek')
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        data_dir = get_trading_data_dir(model)
        summary = {}
        
        status_file = os.path.join(data_dir, 'system_status.json')
        trades_file = os.path.join(data_dir, 'trades_history.csv')
        
        all_trades = []
        
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                raw_status = json.load(f)
                
                all_trades = []
                if os.path.exists(trades_file):
                    try:
                        with open(trades_file, 'r', encoding='utf-8') as tf:
                            trades_reader = csv.DictReader(tf)
                            trades_reader.fieldnames = [name.strip() if name else name for name in trades_reader.fieldnames]
                            for trade in trades_reader:
                                trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
                                all_trades.append(trade_cleaned)
                            logging.info(f"[{model}] 读取到 {len(all_trades)} 笔交易记录")
                    except Exception as e:
                        logging.error(f"读取交易历史失败: {e}")
                
                closed_trades = [t for t in all_trades if t.get('平仓时间') and t.get('平仓时间').strip()]
                logging.info(f"[{model}] 已平仓交易数: {len(closed_trades)}, 时间范围: {range_type}")
                
                filtered_closed_trades = filter_data_by_time_range(
                    closed_trades, '平仓时间', range_type, start_date, end_date
                )
                logging.info(f"[{model}] 筛选后已平仓交易数: {len(filtered_closed_trades)}")
                
                total_realized_pnl = 0
                win_count = 0
                total_count = len(filtered_closed_trades)
                
                for trade in filtered_closed_trades:
                    pnl_str = trade.get('盈亏(U)', '0') or '0'
                    try:
                        pnl = float(pnl_str)
                        total_realized_pnl += pnl
                        if pnl > 0:
                            win_count += 1
        except (ValueError, TypeError):
                        continue
                
                win_rate = (win_count / total_count * 100) if total_count > 0 else 0
                logging.info(f"[{model}] 胜率: {win_rate:.1f}% ({win_count}/{total_count})")
                
                pnl_history = []
                pnl_file = os.path.join(data_dir, 'pnl_history.csv')
                if os.path.exists(pnl_file):
                    try:
                        with open(pnl_file, 'r', encoding='utf-8') as pf:
                            pnl_reader = csv.DictReader(pf)
                            pnl_history = list(pnl_reader)
                            pnl_history = filter_data_by_time_range(
                                pnl_history, '时间', range_type, start_date, end_date
                            )
                    except Exception as e:
                        logging.error(f"读取盈亏历史失败: {e}")
                
                unrealized_pnl = 0
                initial_capital = 100.0
                total_assets = raw_status.get('总资产', raw_status.get('total_assets', 0))
                
                if range_type == 'all':
                    profit_rate = ((total_assets - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0
            else:
                    profit_rate = (total_realized_pnl / initial_capital * 100) if initial_capital > 0 else 0
                
                annualized_return = 0
                if filtered_closed_trades:
                    try:
                        sorted_trades = sorted(filtered_closed_trades, key=lambda x: x.get('开仓时间', ''))
                        first_trade = sorted_trades[0]
                        start_time = datetime.strptime(first_trade.get('开仓时间', ''), '%Y-%m-%d %H:%M:%S')
                        days_elapsed = (datetime.now() - start_time).total_seconds() / 86400
                        if days_elapsed > 0:
                            annualized_return = ((profit_rate / 100 + 1) ** (365 / days_elapsed) - 1) * 100
                    except Exception as e:
                        logging.error(f"计算年化收益失败: {e}")
                
                max_drawdown = calculate_max_drawdown(filtered_closed_trades)
                sharpe_ratio = calculate_sharpe_ratio(
                    filtered_closed_trades,
                    pnl_history if pnl_history else None,
                    initial_capital
                )
                
                total_margin = 0
                
                summary['status'] = {
                    'timestamp': utc_to_beijing_time(raw_status.get('更新时间', raw_status.get('timestamp', ''))),
                    'usdt_balance': 0,
                    'total_assets': total_assets,
                    'total_position_value': raw_status.get('总仓位价值', raw_status.get('total_position_value', 0)),
                    'unrealized_pnl': unrealized_pnl,
                    'total_realized_pnl': total_realized_pnl,
                    'profit_rate': profit_rate,
                    'annualized_return': annualized_return,
                    'max_drawdown': max_drawdown,
                    'sharpe_ratio': sharpe_ratio,
                    'win_rate': win_rate,
                    'win_count': win_count,
                    'total_trades': total_count,
                    'max_position': raw_status.get('最大仓位限制', 100),
                    'position_count': raw_status.get('当前持仓数', 0),
                    'positions_detail': raw_status.get('持仓详情', []),
                    'market_overview': raw_status.get('市场概况', []),
                    'ai_analysis': raw_status.get('AI分析', ''),
                    'risk_assessment': raw_status.get('风险评估', '')
                }
        
        summary['experiment_config'] = {
            'initial_capital': 100.0,
            'trading_pairs': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT'],
            'max_leverage': '≤5x (合约)',
            'strategy': 'AI智能多空策略 + 裸K分析',
            'risk_per_trade': '单笔最大40U'
        }
        
        positions_file = os.path.join(data_dir, 'current_positions.csv')
        if os.path.exists(positions_file):
            with open(positions_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                raw_positions = list(reader)
                trade_details = {}
                if os.path.exists(trades_file):
                    with open(trades_file, 'r', encoding='utf-8') as tf:
                        trades_reader = csv.DictReader(tf)
                        for trade in trades_reader:
                            if not trade.get('平仓时间'):
                                key = f"{trade.get('币种', '')}_{trade.get('方向', '')}"
                                trade_details[key] = {
                                    'open_time': trade.get('开仓时间', ''),
                                    'stop_loss': float(trade.get('止损', 0) or 0),
                                    'take_profit': float(trade.get('止盈', 0) or 0),
                                    'risk_reward': float(trade.get('盈亏比', 0) or 0),
                                    'margin': float(trade.get('仓位(U)', 0) or 0),
                                    'leverage': int(trade.get('杠杆率', 1) or 1),
                                    'open_reason': trade.get('开仓理由', '')
                                }
                summary['positions'] = []
                for pos in raw_positions:
                    coin = pos.get('币种', pos.get('symbol', ''))
                    side = pos.get('方向', pos.get('side', ''))
                    key = f"{coin}_{side}"
                    details = trade_details.get(key, {})
                    entry_price = float(pos.get('开仓价', pos.get('entry_price', 0)) or 0)
                    size = float(pos.get('数量', pos.get('size', 0)) or 0)
                    stop_loss = details.get('stop_loss', 0)
                    take_profit = details.get('take_profit', 0)
                    
                    margin = details.get('margin', 0)
                    leverage = details.get('leverage', 1)
                    notional_value = margin * leverage
                    
                    expected_pnl = 0
                    if take_profit > 0 and entry_price > 0 and size > 0:
                        if side == '多':
                            expected_pnl = (take_profit - entry_price) * size
                        else:
                            expected_pnl = (entry_price - take_profit) * size
                    summary['positions'].append({
                        'symbol': coin,
                        'side': side,
                        'size': size,
                        'entry_price': entry_price,
                        'unrealized_pnl': float(pos.get('当前盈亏(U)', pos.get('unrealized_pnl', 0)) or 0),
                        'open_time': utc_to_beijing_time(details.get('open_time', '')),
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'risk_reward': details.get('risk_reward', 0),
                        'leverage': leverage,
                        'margin': margin,
                        'notional_value': notional_value,
                        'expected_pnl': expected_pnl,
                        'open_reason': details.get('open_reason', '')
                    })
                    total_margin += margin
        else:
            summary['positions'] = []
        
        if summary.get('positions'):
            unrealized_pnl_from_positions = sum(
                pos.get('unrealized_pnl', 0) for pos in summary['positions']
            )
            if 'status' in summary:
                summary['status']['unrealized_pnl'] = unrealized_pnl_from_positions
        
        if 'status' in summary:
            summary['status']['usdt_balance'] = summary['status']['total_assets'] - total_margin
        
        closed_trades_for_display = [t for t in all_trades if t.get('平仓时间') and t.get('平仓时间').strip()]
        closed_trades_for_display = filter_data_by_time_range(
            closed_trades_for_display, '平仓时间', range_type, start_date, end_date
        )
        
        open_trades_for_display = [t for t in all_trades if not (t.get('平仓时间') and t.get('平仓时间').strip())]
        open_trades_for_display = filter_data_by_time_range(
            open_trades_for_display, '开仓时间', range_type, start_date, end_date
        )
        
        logging.info(f"[{model}] 显示交易 - 已平仓: {len(closed_trades_for_display)}, 未平仓: {len(open_trades_for_display)}, 时间范围: {range_type}")
        
        summary['recent_trades'] = []
        for trade in closed_trades_for_display + open_trades_for_display:
            trade['model'] = model
            if trade.get('开仓时间'):
                trade['开仓时间'] = utc_to_beijing_time(trade['开仓时间'])
            if trade.get('平仓时间'):
                trade['平仓时间'] = utc_to_beijing_time(trade['平仓时间'])
            summary['recent_trades'].append(trade)
        
        pnl_file = os.path.join(data_dir, 'pnl_history.csv')
        if os.path.exists(pnl_file):
            with open(pnl_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > 96:
                    lines = [lines[0]] + lines[-96:]
                reader = csv.DictReader(lines)
                pnl_data = list(reader)
                if pnl_data:
                    start_assets = float(pnl_data[0].get('总资产', pnl_data[0].get('total_assets', 0)))
                    end_assets = float(pnl_data[-1].get('总资产', pnl_data[-1].get('total_assets', 0)))
                    change = end_assets - start_assets
                    change_pct = (change / start_assets * 100) if start_assets > 0 else 0
                    summary['pnl_24h'] = {
                        'start': start_assets,
                        'end': end_assets,
                        'change': change,
                        'change_pct': change_pct
                    }
        
        try:
            env_file = '/home/admin/10-23-bot/ds/.env' if model == 'deepseek' else '/home/admin/10-23-bot/ds/.env.qwen'
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                        summary['test_mode'] = True
                    elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                        summary['test_mode'] = False
    else:
                        summary['test_mode'] = None
        except:
            summary['test_mode'] = None
        
        try:
            learning_config_file = os.path.join(data_dir, 'learning_config.json')
            if os.path.exists(learning_config_file):
                with open(learning_config_file, 'r', encoding='utf-8') as f:
                    learning_config = json.load(f)
                    market_regime = learning_config.get('market_regime', {})
                    pause_level = market_regime.get('pause_level', 0)
                    pause_until = market_regime.get('pause_until', None)
                    
                    summary['cooldown_status'] = {
                        'is_paused': pause_level > 0,
                        'pause_level': pause_level,
                        'pause_until': pause_until,
                        'pause_reason': get_pause_reason(pause_level)
                    }
            else:
                summary['cooldown_status'] = {
                    'is_paused': False,
                    'pause_level': 0,
                    'pause_until': None,
                    'pause_reason': ''
                }
        except Exception as e:
            logging.error(f"读取冷却期状态失败: {e}")
            summary['cooldown_status'] = {
                'is_paused': False,
                'pause_level': 0,
                'pause_until': None,
                'pause_reason': ''
            }
        
        return jsonify(summary), 200
    except Exception as e:
        logging.error(f"生成交易摘要失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/trading-combined', methods=['GET'])
def trading_combined():
    """获取合并后的交易摘要（DeepSeek + 通义千问）"""
    try:
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        deepseek_summary = get_model_summary('deepseek', range_type, start_date, end_date)
        qwen_summary = get_model_summary('qwen', range_type, start_date, end_date)
        
        combined_total_assets = (deepseek_summary.get('status', {}).get('total_assets', 0) + 
                                qwen_summary.get('status', {}).get('total_assets', 0))
        
        combined_total_margin = 0
        for pos in deepseek_summary.get('positions', []):
            combined_total_margin += pos.get('margin', 0)
        for pos in qwen_summary.get('positions', []):
            combined_total_margin += pos.get('margin', 0)
        
        combined_usdt_balance = combined_total_assets - combined_total_margin
        
        combined = {
            'status': {
                'timestamp': deepseek_summary.get('status', {}).get('timestamp', ''),
                'usdt_balance': combined_usdt_balance,
                'total_position_value': (deepseek_summary.get('status', {}).get('total_position_value', 0) + 
                    qwen_summary.get('status', {}).get('total_position_value', 0)),
                'unrealized_pnl': (deepseek_summary.get('status', {}).get('unrealized_pnl', 0) + 
                    qwen_summary.get('status', {}).get('unrealized_pnl', 0)),
                'total_assets': combined_total_assets,
                'total_realized_pnl': (deepseek_summary.get('status', {}).get('total_realized_pnl', 0) + 
                    qwen_summary.get('status', {}).get('total_realized_pnl', 0)),
                'profit_rate': 0,
                'annualized_return': 0,
                'max_drawdown': 0,
                'sharpe_ratio': 0,
                'position_count': (deepseek_summary.get('status', {}).get('position_count', 0) + 
                    qwen_summary.get('status', {}).get('position_count', 0)),
                'ai_analysis': '',
                'risk_assessment': '',
                'latest_model': ''
            },
            'experiment_config': {
                'initial_capital': '200U (100U×2)',
                'trading_pairs': ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT'],
                'max_leverage': '≤5x (合约)',
                'strategy': 'AI智能多空策略 + 裸K分析 (双模型)',
                'risk_per_trade': '单模型单笔最大40U'
            },
            'positions': [],
            'recent_trades': [],
            'pnl_24h': {
                'change': (deepseek_summary.get('pnl_24h', {}).get('change', 0) + 
                    qwen_summary.get('pnl_24h', {}).get('change', 0)),
                'change_pct': 0
            },
            'test_mode': deepseek_summary.get('test_mode'),
            'models': {
                'deepseek': deepseek_summary,
                'qwen': qwen_summary
            }
        }
        
        for pos in deepseek_summary.get('positions', []):
            pos['model'] = 'deepseek'
            combined['positions'].append(pos)
        for pos in qwen_summary.get('positions', []):
            pos['model'] = 'qwen'
            combined['positions'].append(pos)
        
        all_trades = []
        for trade in deepseek_summary.get('recent_trades', []):
            trade['model'] = 'deepseek'
            all_trades.append(trade)
        for trade in qwen_summary.get('recent_trades', []):
            trade['model'] = 'qwen'
            all_trades.append(trade)
        combined['recent_trades'] = sorted(all_trades, key=lambda x: x.get('平仓时间', ''), reverse=True)
        
        ds_time = deepseek_summary.get('status', {}).get('timestamp', '') if deepseek_summary else ''
        qw_time = qwen_summary.get('status', {}).get('timestamp', '') if qwen_summary else ''
        
        if ds_time and qw_time:
            if ds_time >= qw_time:
                combined['status']['ai_analysis'] = str(deepseek_summary['status'].get('ai_analysis', ''))
                combined['status']['risk_assessment'] = str(deepseek_summary['status'].get('risk_assessment', ''))
                combined['status']['latest_model'] = 'DeepSeek'
        else:
                combined['status']['ai_analysis'] = str(qwen_summary['status'].get('ai_analysis', ''))
                combined['status']['risk_assessment'] = str(qwen_summary['status'].get('risk_assessment', ''))
                combined['status']['latest_model'] = '通义千问'
        elif ds_time:
            combined['status']['ai_analysis'] = str(deepseek_summary['status'].get('ai_analysis', ''))
            combined['status']['risk_assessment'] = str(deepseek_summary['status'].get('risk_assessment', ''))
            combined['status']['latest_model'] = 'DeepSeek'
        elif qw_time:
            combined['status']['ai_analysis'] = str(qwen_summary['status'].get('ai_analysis', ''))
            combined['status']['risk_assessment'] = str(qwen_summary['status'].get('risk_assessment', ''))
            combined['status']['latest_model'] = '通义千问'
        
        initial_capital = 200.0
        total_assets = combined['status']['total_assets']
        if initial_capital > 0:
            combined['status']['profit_rate'] = ((total_assets - initial_capital) / initial_capital * 100)
        
        earliest_time = None
        for model in ['deepseek', 'qwen']:
            model_summary = combined['models'][model]
            all_trades = model_summary.get('recent_trades', [])
            if all_trades:
                for trade in all_trades:
                    open_time_str = trade.get('开仓时间', '')
                    if open_time_str:
                        try:
                            trade_time = datetime.strptime(open_time_str, '%Y-%m-%d %H:%M:%S')
                            if earliest_time is None or trade_time < earliest_time:
                                earliest_time = trade_time
                        except:
                            pass
        
        if earliest_time:
            days_elapsed = (datetime.now() - earliest_time).total_seconds() / 86400
            if days_elapsed > 0:
                profit_rate = combined['status']['profit_rate']
                combined['status']['annualized_return'] = ((profit_rate / 100 + 1) ** (365 / days_elapsed) - 1) * 100
        else:
                combined['status']['annualized_return'] = 0
        else:
            combined['status']['annualized_return'] = 0
        
        if combined['pnl_24h'].get('change') and total_assets > 0:
            combined['pnl_24h']['change_pct'] = (combined['pnl_24h']['change'] / total_assets * 100)
        
        ds_max_dd = deepseek_summary.get('status', {}).get('max_drawdown', 0)
        qw_max_dd = qwen_summary.get('status', {}).get('max_drawdown', 0)
        combined['status']['max_drawdown'] = max(ds_max_dd, qw_max_dd)
        
        ds_sharpe = deepseek_summary.get('status', {}).get('sharpe_ratio', 0)
        qw_sharpe = qwen_summary.get('status', {}).get('sharpe_ratio', 0)
        combined['status']['sharpe_ratio'] = (ds_sharpe + qw_sharpe) / 2 if (ds_sharpe or qw_sharpe) else 0
        
        ds_win_count = deepseek_summary.get('status', {}).get('win_count', 0)
        ds_total_trades = deepseek_summary.get('status', {}).get('total_trades', 0)
        qw_win_count = qwen_summary.get('status', {}).get('win_count', 0)
        qw_total_trades = qwen_summary.get('status', {}).get('total_trades', 0)
        
        combined_win_count = ds_win_count + qw_win_count
        combined_total_trades = ds_total_trades + qw_total_trades
        combined['status']['win_rate'] = (combined_win_count / combined_total_trades * 100) if combined_total_trades > 0 else 0
        combined['status']['win_count'] = combined_win_count
        combined['status']['total_trades'] = combined_total_trades
        
        logging.info(f"[combined] 综合胜率: {combined['status']['win_rate']:.1f}% ({combined_win_count}/{combined_total_trades})")
        
        return jsonify(combined), 200
    except Exception as e:
        logging.error(f"生成合并摘要失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

def get_model_summary(model, range_type='all', start_date='', end_date=''):
    """获取单个模型的摘要数据（内部辅助函数）"""
    try:
        data_dir = get_trading_data_dir(model)
        summary = {}

        status_file = os.path.join(data_dir, 'system_status.json')
        trades_file = os.path.join(data_dir, 'trades_history.csv')
        positions_file = os.path.join(data_dir, 'current_positions.csv')
        pnl_file = os.path.join(data_dir, 'pnl_history.csv')

        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                raw_status = json.load(f)

                all_trades = []
                if os.path.exists(trades_file):
                    try:
                        with open(trades_file, 'r', encoding='utf-8') as tf:
                            trades_reader = csv.DictReader(tf)
                            trades_reader.fieldnames = [name.strip() if name else name for name in trades_reader.fieldnames]
                            for trade in trades_reader:
                                trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
                                all_trades.append(trade_cleaned)
                    except Exception as e:
                        logging.error(f"读取{model}交易历史失败: {e}")
                
                closed_trades = [t for t in all_trades if t.get('平仓时间') and t.get('平仓时间').strip()]
                filtered_closed_trades = filter_data_by_time_range(
                    closed_trades, '平仓时间', range_type, start_date, end_date
                )
                
                total_realized_pnl = 0
                win_count = 0
                total_count = len(filtered_closed_trades)
                
                for trade in filtered_closed_trades:
                    pnl_str = trade.get('盈亏(U)', '0') or '0'
                                    try:
                                        pnl = float(pnl_str)
                                        total_realized_pnl += pnl
                        if pnl > 0:
                            win_count += 1
                                    except (ValueError, TypeError):
                                        continue
                
                win_rate = (win_count / total_count * 100) if total_count > 0 else 0
                logging.info(f"[{model}][get_model_summary] 胜率: {win_rate:.1f}% ({win_count}/{total_count})")
                
                pnl_history = []
                if os.path.exists(pnl_file):
                    try:
                        with open(pnl_file, 'r', encoding='utf-8') as pf:
                            pnl_reader = csv.DictReader(pf)
                            pnl_history = list(pnl_reader)
                            pnl_history = filter_data_by_time_range(
                                pnl_history, '时间', range_type, start_date, end_date
                            )
                    except Exception as e:
                        logging.error(f"读取{model}盈亏历史失败: {e}")
                
                unrealized_pnl = 0
                if '持仓详情' in raw_status:
                    unrealized_pnl = sum(pos.get('盈亏', 0) for pos in raw_status['持仓详情'])
                
                initial_capital = 100.0
                total_assets = raw_status.get('总资产', raw_status.get('total_assets', 0))
                
                if range_type == 'all':
                    profit_rate = ((total_assets - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0
                else:
                    profit_rate = (total_realized_pnl / initial_capital * 100) if initial_capital > 0 else 0
                
                annualized_return = 0
                if filtered_closed_trades:
                    try:
                        sorted_trades = sorted(filtered_closed_trades, key=lambda x: x.get('开仓时间', ''))
                        first_trade = sorted_trades[0]
                        start_time = datetime.strptime(first_trade.get('开仓时间', ''), '%Y-%m-%d %H:%M:%S')
                        days_elapsed = (datetime.now() - start_time).total_seconds() / 86400
                                        if days_elapsed > 0:
                            annualized_return = ((profit_rate / 100 + 1) ** (365 / days_elapsed) - 1) * 100
                    except Exception as e:
                        logging.error(f"计算年化收益失败: {e}")
                
                max_drawdown = calculate_max_drawdown(filtered_closed_trades)
                sharpe_ratio = calculate_sharpe_ratio(
                    filtered_closed_trades, 
                    pnl_history if pnl_history else None, 
                    initial_capital
                )
                
                ai_analysis = raw_status.get('AI分析', raw_status.get('ai_analysis', ''))
                risk_assessment = raw_status.get('风险评估', raw_status.get('risk_assessment', ''))
                
                if isinstance(ai_analysis, dict):
                    ai_analysis = json.dumps(ai_analysis, ensure_ascii=False)
                if isinstance(risk_assessment, dict):
                    risk_assessment = json.dumps(risk_assessment, ensure_ascii=False)
                
                summary['status'] = {
                    'timestamp': utc_to_beijing_time(raw_status.get('更新时间', raw_status.get('时间', raw_status.get('timestamp', '')))),
                    'usdt_balance': 0,
                    'total_position_value': raw_status.get('持仓总价值', raw_status.get('总仓位价值', raw_status.get('total_position_value', 0))),
                    'unrealized_pnl': unrealized_pnl,
                    'total_assets': total_assets,
                    'total_realized_pnl': total_realized_pnl,
                    'profit_rate': profit_rate,
                    'annualized_return': annualized_return,
                    'max_drawdown': max_drawdown,
                    'sharpe_ratio': sharpe_ratio,
                    'win_rate': win_rate,
                    'win_count': win_count,
                    'total_trades': total_count,
                    'position_count': len(raw_status.get('持仓详情', [])),
                    'ai_analysis': str(ai_analysis) if ai_analysis else '',
                    'risk_assessment': str(risk_assessment) if risk_assessment else ''
                }
        else:
            summary['status'] = {}
        
        total_margin_model = 0
        if os.path.exists(positions_file):
            with open(positions_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                raw_positions = list(reader)
                
                trade_details = {}
                if os.path.exists(trades_file):
                    with open(trades_file, 'r', encoding='utf-8') as tf:
                        trades_reader = csv.DictReader(tf)
                        for trade in trades_reader:
                            if not trade.get('平仓时间'):
                                key = f"{trade.get('币种', '')}_{trade.get('方向', '')}"
                                trade_details[key] = {
                                    'open_time': trade.get('开仓时间', ''),
                                    'stop_loss': float(trade.get('止损', 0) or 0),
                                    'take_profit': float(trade.get('止盈', 0) or 0),
                                    'risk_reward': float(trade.get('盈亏比', 0) or 0),
                                    'margin': float(trade.get('仓位(U)', 0) or 0),
                                    'leverage': int(trade.get('杠杆率', 1) or 1),
                                    'open_reason': trade.get('开仓理由', '')
                                }
                
                summary['positions'] = []
                for pos in raw_positions:
                    coin = pos.get('币种', pos.get('symbol', ''))
                    side = pos.get('方向', pos.get('side', ''))
                    key = f"{coin}_{side}"
                    details = trade_details.get(key, {})
                    entry_price = float(pos.get('开仓价', pos.get('entry_price', 0)) or 0)
                    size = float(pos.get('数量', pos.get('size', 0)) or 0)
                    stop_loss = details.get('stop_loss', 0)
                    take_profit = details.get('take_profit', 0)
                    
                    margin = details.get('margin', 0)
                    leverage = details.get('leverage', 1)
                    notional_value = margin * leverage
                    
                    expected_pnl = 0
                    if take_profit > 0 and entry_price > 0 and size > 0:
                        if side == '多':
                            expected_pnl = (take_profit - entry_price) * size
        else:
                            expected_pnl = (entry_price - take_profit) * size
                    
                    summary['positions'].append({
                        'symbol': coin,
                        'side': side,
                        'size': size,
                        'entry_price': entry_price,
                        'unrealized_pnl': float(pos.get('当前盈亏(U)', pos.get('unrealized_pnl', 0)) or 0),
                        'open_time': utc_to_beijing_time(details.get('open_time', '')),
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'risk_reward': details.get('risk_reward', 0),
                        'leverage': leverage,
                        'margin': margin,
                        'notional_value': notional_value,
                        'expected_pnl': expected_pnl,
                        'model': model,
                        'open_reason': details.get('open_reason', '')
                    })
                    total_margin_model += margin
        else:
            summary['positions'] = []
        
        if summary.get('positions'):
            summary['positions'] = filter_data_by_time_range(
                summary['positions'], 'open_time', range_type, start_date, end_date
            )
        
        if summary.get('positions'):
            unrealized_pnl_from_positions = sum(
                pos.get('unrealized_pnl', 0) for pos in summary['positions']
            )
            if 'status' in summary:
                summary['status']['unrealized_pnl'] = unrealized_pnl_from_positions
        
        if 'status' in summary:
            summary['status']['usdt_balance'] = summary['status']['total_assets'] - total_margin_model
        
        if os.path.exists(trades_file):
            with open(trades_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                reader.fieldnames = [name.strip() if name else name for name in reader.fieldnames]
                all_trades_raw = []
                for trade in reader:
                    trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
                    trade_cleaned['model'] = model
                    all_trades_raw.append(trade_cleaned)
                
                closed_trades_for_display = [t for t in all_trades_raw if t.get('平仓时间') and t.get('平仓时间').strip()]
                closed_trades_filtered = filter_data_by_time_range(
                    closed_trades_for_display, '平仓时间', range_type, start_date, end_date
                )
                
                open_trades_for_display = [t for t in all_trades_raw if not (t.get('平仓时间') and t.get('平仓时间').strip())]
                open_trades_filtered = filter_data_by_time_range(
                    open_trades_for_display, '开仓时间', range_type, start_date, end_date
                )
                
                all_filtered_trades = closed_trades_filtered + open_trades_filtered
                for trade in all_filtered_trades:
                    if trade.get('开仓时间'):
                        trade['开仓时间'] = utc_to_beijing_time(trade['开仓时间'])
                    if trade.get('平仓时间'):
                        trade['平仓时间'] = utc_to_beijing_time(trade['平仓时间'])
                summary['recent_trades'] = all_filtered_trades
                logging.info(f"[{model}][get_model_summary] 交易记录 - 已平仓: {len(closed_trades_filtered)}, 未平仓: {len(open_trades_filtered)}")
        else:
            summary['recent_trades'] = []

        pnl_file = os.path.join(data_dir, 'pnl_history.csv')
        if os.path.exists(pnl_file):
            with open(pnl_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > 96:
                    lines = [lines[0]] + lines[-96:]
                reader = csv.DictReader(lines)
                pnl_data = list(reader)
                if pnl_data:
                    start_assets = float(pnl_data[0].get('总资产', pnl_data[0].get('total_assets', 0)))
                    end_assets = float(pnl_data[-1].get('总资产', pnl_data[-1].get('total_assets', 0)))
                    change = end_assets - start_assets
                    change_pct = (change / start_assets * 100) if start_assets > 0 else 0
                    summary['pnl_24h'] = {
                        'start': start_assets,
                        'end': end_assets,
                        'change': change,
                        'change_pct': change_pct
                    }
        
        try:
            env_file = '/home/admin/10-23-bot/ds/.env' if model == 'deepseek' else '/home/admin/10-23-bot/ds/.env.qwen'
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                        summary['test_mode'] = True
                    elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                        summary['test_mode'] = False
                    else:
                        summary['test_mode'] = None
            else:
                summary['test_mode'] = None
        except:
            summary['test_mode'] = None
        
        try:
            learning_config_file = os.path.join(data_dir, 'learning_config.json')
            if os.path.exists(learning_config_file):
                with open(learning_config_file, 'r', encoding='utf-8') as f:
                    learning_config = json.load(f)
                    market_regime = learning_config.get('market_regime', {})
                    pause_level = market_regime.get('pause_level', 0)
                    pause_until = market_regime.get('pause_until', None)
                    
                    summary['cooldown_status'] = {
                        'is_paused': pause_level > 0,
                        'pause_level': pause_level,
                        'pause_until': pause_until,
                        'pause_reason': get_pause_reason(pause_level)
                    }
            else:
                summary['cooldown_status'] = {
                    'is_paused': False,
                    'pause_level': 0,
                    'pause_until': None,
                    'pause_reason': ''
                }
    except Exception as e:
            logging.error(f"读取{model}冷却期状态失败: {e}")
            summary['cooldown_status'] = {
                'is_paused': False,
                'pause_level': 0,
                'pause_until': None,
                'pause_reason': ''
            }
        
        return summary
    except Exception as e:
        logging.error(f"获取{model}摘要失败: {e}")
        return {}

@app.route('/trading-chat', methods=['POST'])
def trading_chat():
    """与AI对话（需要密码验证）"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        password = data.get('password', '').strip()
        model = data.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        
        if password != CONTROL_PASSWORD:
            return jsonify({'success': False, 'error': '密码错误，无法与AI对话'}), 403

        if not user_message:
            return jsonify({'error': '消息不能为空'}), 400

        import requests

        status_file = os.path.join(data_dir, 'system_status.json')
        context = ""
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
                context = f"""
当前系统状态：
- 总资产: {status.get('总资产', status.get('total_assets', 0)):.2f}U
- USDT余额: {status.get('USDT余额', status.get('usdt_balance', 0)):.2f}U
- 持仓数: {status.get('当前持仓数', status.get('position_count', 0))}
- AI分析: {status.get('AI分析', status.get('ai_analysis', '无'))}
"""

        if model == 'qwen':
            api_key = os.getenv('QWEN_API_KEY', '')
            api_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
            ai_model = 'qwen-turbo'
        else:
            api_key = os.getenv('DEEPSEEK_API_KEY', 'sk-1d8568a372774640ad4daac128ede404')
            api_url = 'https://api.deepseek.com/chat/completions'
            ai_model = 'deepseek-chat'
        
        response = requests.post(
            api_url,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': ai_model,
                'messages': [
                    {'role': 'system', 'content': f'你是一个专业的加密货币交易顾问。{context}'},
                    {'role': 'user', 'content': user_message}
                ],
                'temperature': 0.7
            },
            timeout=30
        )

        if response.status_code == 200:
            ai_reply = response.json()['choices'][0]['message']['content']
            beijing_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return jsonify({
                'success': True,
                'reply': ai_reply,
                'timestamp': beijing_time
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': f'AI API错误: {response.status_code}'
            }), 500

    except Exception as e:
        logging.error(f"AI对话失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/trading-control', methods=['POST'])
def trading_control():
    """控制交易系统（切换模式/重启/停止）"""
    try:
        data = request.get_json()
        action = data.get('action')
        password = data.get('password')
        model = data.get('model', 'deepseek')

        if password != CONTROL_PASSWORD:
            return jsonify({'error': '密码错误'}), 403
        
        if model == 'qwen':
            env_file = '/home/admin/10-23-bot/ds/.env.qwen'
            bot_script = 'qwen_多币种智能版.py'
            screen_name = 'ai-qwen'
            model_name = '通义千问'
        else:
            env_file = '/home/admin/10-23-bot/ds/.env'
            bot_script = 'deepseek_多币种智能版.py'
            screen_name = 'ai-deepseek'
            model_name = 'DeepSeek'
        
        if action == 'toggle_mode':
            if not os.path.exists(env_file):
                return jsonify({'error': f'{model_name}环境变量文件不存在'}), 404
            
            with open(env_file, 'r', encoding='utf-8') as f:
                content = f.read()

            if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                new_content = content.replace('TEST_MODE=True', 'TEST_MODE=False').replace('TEST_MODE=true', 'TEST_MODE=False')
                new_mode = 'LIVE'
            elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                new_content = content.replace('TEST_MODE=False', 'TEST_MODE=True').replace('TEST_MODE=false', 'TEST_MODE=True')
                new_mode = 'TEST'
            else:
                new_content = content + '\nTEST_MODE=False\n'
                new_mode = 'LIVE'

            with open(env_file, 'w', encoding='utf-8') as f:
                f.write(new_content)

            import subprocess
            try:
                subprocess.run(['pkill', '-9', '-f', bot_script], timeout=5)
                import time
                time.sleep(2)
                
                start_cmd = f"cd /home/admin/10-23-bot/ds && set -a; source {env_file}; set +a; exec /home/admin/10-23-bot/ds/venv/bin/python -u {bot_script} 2>&1 | tee -a logs/{model}_trading.log"
                subprocess.Popen(['screen', '-dmS', screen_name, 'bash', '-c', start_cmd])
                time.sleep(3)
                
                check_result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
                is_running = bot_script in check_result.stdout
                
                return jsonify({
                    'message': f'{model_name}模式已切换为: {new_mode}',
                    'new_mode': new_mode,
                    'model': model_name,
                    'restarted': is_running,
                    'note': '已自动重启交易系统' if is_running else '切换成功但重启失败，请手动重启'
                }), 200
            except Exception as e:
                return jsonify({
                    'message': f'{model_name}模式已切换为: {new_mode}',
                    'new_mode': new_mode,
                    'model': model_name,
                    'error': f'自动重启失败: {str(e)}',
                    'note': '请手动重启交易系统'
            }), 200
        
        elif action == 'get_status':
            import subprocess
            try:
                result = subprocess.run(
                    ['screen', '-ls'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                is_running = screen_name in result.stdout
                
                current_mode = 'UNKNOWN'
                if os.path.exists(env_file):
                    with open(env_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                            current_mode = 'TEST'
                        elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                            current_mode = 'LIVE'
                
                return jsonify({
                    'running': is_running,
                    'mode': current_mode,
                    'model': model_name,
                    'screen_output': result.stdout
                }), 200
            except Exception as e:
                return jsonify({'error': f'检查状态失败: {str(e)}'}), 500

        else:
            return jsonify({'error': '未知操作'}), 400

    except Exception as e:
        logging.error(f"控制交易系统失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-dashboard')
def trading_dashboard():
    """AI交易系统完整监控页面"""
    log_visitor()
    return '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>追踪狗AI交易系统（内测展示版）</title><link rel="icon" type="image/png" href="https://bitechain.io/assets/images/logo/soltracker-logo.png"/><script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js">
let positionsData=[],tradesData=[],currentPositionPage=1,currentTradePage=1;function getPageSize(type){const isMobile=window.innerWidth<=768;if(type==='positions')return isMobile?3:5;return isMobile?5:10}
function renderPositions(positions){positionsData=positions||[];positionsData.sort((a,b)=>{const timeA=a.open_time||'';const timeB=b.open_time||'';return timeB.localeCompare(timeA)});const pageSize=getPageSize('positions');const totalPages=Math.ceil(positionsData.length/pageSize);currentPositionPage=Math.min(currentPositionPage,Math.max(1,totalPages));const start=(currentPositionPage-1)*pageSize;const end=start+pageSize;const pageData=positionsData.slice(start,end);const table=document.getElementById('positionsTable');if(!pageData.length){table.innerHTML='<div class="no-data">暂无持仓</div>';document.getElementById('positionsPagination').style.display='none';return}
const isMobile=window.innerWidth<=768;const showModel=currentModel==='combined';if(isMobile){let html='';pageData.forEach(p=>{const pnl=parseFloat(p.unrealized_pnl||0),c=pnl>=0?'#10b981':'#ef4444';let holdTime='',openTimeStr='';if(p.open_time){const openTime=new Date(p.open_time.replace(' ','T')+'+08:00');openTimeStr=openTime.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai'}).replace(/\//g,'-');const now=new Date();const diffMs=now-openTime;const diffHours=Math.floor(diffMs/3600000);const diffDays=Math.floor(diffHours/24);const remainHours=diffHours%24;if(diffDays>0){holdTime=`${diffDays}天${remainHours}h`}else if(diffHours>0){holdTime=`${diffHours}h`}else{holdTime='<1h'}}else{openTimeStr='--';holdTime='--'}const entryPrice=parseFloat(p.entry_price||0);const stopLoss=parseFloat(p.stop_loss||0);const takeProfit=parseFloat(p.take_profit||0);const riskReward=parseFloat(p.risk_reward||0);const leverage=parseFloat(p.leverage||1);const margin=parseFloat(p.margin||0);const expectedPnl=parseFloat(p.expected_pnl||0);const openReason=(p.open_reason||p.开仓理由||'无决策记录');const modelBadge=showModel&&p.model?`<span style="display:inline-block;padding:2px 6px;background:${p.model==='deepseek'?'#e0f2fe':'#fed7aa'};color:${p.model==='deepseek'?'#0369a1':'#c2410c'};border-radius:4px;font-size:9px;font-weight:600;margin-left:5px">${p.model==='deepseek'?'🤖DS':'🧠QW'}</span>`:'';const reasonData=encodeURIComponent(JSON.stringify({type:'position',symbol:p.symbol,side:p.side,openReason:openReason,openTime:openTimeStr,holdTime:holdTime,margin:margin.toFixed(2),leverage:leverage.toFixed(1),takeProfit:takeProfit.toFixed(2),stopLoss:stopLoss.toFixed(2)}));html+=`<div class="position-card" onclick="showReasonDialog('${reasonData}')" style="cursor:pointer"><div class="position-card-header"><span class="symbol">${p.symbol}</span><span class="side">${p.side}${modelBadge}</span></div><div class="position-card-row"><span class="label">开仓时间</span><span class="value">${openTimeStr}</span></div><div class="position-card-row"><span class="label">持仓时长</span><span class="value">${holdTime}</span></div><div class="position-card-row"><span class="label">开仓价</span><span class="value">$${entryPrice.toFixed(2)}</span></div><div class="position-card-row"><span class="label">数量</span><span class="value">${parseFloat(p.size).toFixed(4)}</span></div><div class="position-card-row"><span class="label">保证金</span><span class="value">${margin.toFixed(2)}U</span></div><div class="position-card-row"><span class="label">杠杆率</span><span class="value">${leverage.toFixed(1)}x</span></div><div class="position-card-row"><span class="label">预计止盈价</span><span class="value" style="color:#10b981">$${takeProfit.toFixed(2)}</span></div><div class="position-card-row"><span class="label">预计止损价</span><span class="value" style="color:#ef4444">$${stopLoss.toFixed(2)}</span></div><div class="position-card-row"><span class="label">预计盈亏比</span><span class="value">${riskReward?riskReward.toFixed(2):'--'}</span></div><div class="position-card-row"><span class="label">预期盈亏</span><span class="value" style="color:#10b981">${expectedPnl.toFixed(2)}U</span></div><div class="position-card-row"><span class="label">当前盈亏</span><span class="value" style="color:${c};font-weight:700;font-size:15px">${pnl>=0?'+':''}${pnl.toFixed(2)}U</span></div></div>`});table.innerHTML=html}else{let html=`<table style="font-size:12px"><thead><tr><th>币种</th><th>方向</th>${showModel?'<th>模型</th>':''}<th>开仓时间</th><th>持仓时长</th><th>开仓价</th><th>数量</th><th>保证金</th><th>杠杆率</th><th>预计止盈价</th><th>预计止损价</th><th>预计盈亏比</th><th>预期盈亏</th><th>当前盈亏</th></tr></thead><tbody>`;pageData.forEach(p=>{const pnl=parseFloat(p.unrealized_pnl||0),c=pnl>=0?'profit':'loss';let holdTime='',openTimeStr='';if(p.open_time){const openTime=new Date(p.open_time.replace(' ','T')+'+08:00');openTimeStr=openTime.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai'}).replace(/\//g,'-');const now=new Date();const diffMs=now-openTime;const diffHours=Math.floor(diffMs/3600000);const diffDays=Math.floor(diffHours/24);const remainHours=diffHours%24;if(diffDays>0){holdTime=`${diffDays}天${remainHours}h`}else if(diffHours>0){holdTime=`${diffHours}h`}else{holdTime='<1h'}}else{openTimeStr='--';holdTime='--'}const entryPrice=parseFloat(p.entry_price||0);const stopLoss=parseFloat(p.stop_loss||0);const takeProfit=parseFloat(p.take_profit||0);const riskReward=parseFloat(p.risk_reward||0);const leverage=parseFloat(p.leverage||1);const margin=parseFloat(p.margin||0);const expectedPnl=parseFloat(p.expected_pnl||0);const openReason=(p.open_reason||p.开仓理由||'无决策记录');const tooltip=`📝 开仓决策:\n${openReason}\n\n📊 详细信息:\n开仓时间: ${openTimeStr}\n持仓时长: ${holdTime}\n保证金: ${margin.toFixed(2)}U\n杠杆率: ${leverage.toFixed(1)}x\n止盈价: $${takeProfit.toFixed(2)}\n止损价: $${stopLoss.toFixed(2)}`;const modelCell=showModel&&p.model?`<td><span style="display:inline-block;padding:2px 6px;background:${p.model==='deepseek'?'#e0f2fe':'#fed7aa'};color:${p.model==='deepseek'?'#0369a1':'#c2410c'};border-radius:4px;font-size:10px;font-weight:600">${p.model==='deepseek'?'🤖DS':'🧠QW'}</span></td>`:'';html+=`<tr title="${tooltip}" style="cursor:pointer"><td><strong>${p.symbol}</strong></td><td>${p.side}</td>${modelCell}<td style="font-size:10px">${openTimeStr}</td><td style="font-size:10px">${holdTime}</td><td>$${entryPrice.toFixed(2)}</td><td>${parseFloat(p.size).toFixed(4)}</td><td>${margin.toFixed(2)}U</td><td>${leverage.toFixed(1)}x</td><td style="color:#10b981">$${takeProfit.toFixed(2)}</td><td style="color:#ef4444">$${stopLoss.toFixed(2)}</td><td>${riskReward?riskReward.toFixed(2):'--'}</td><td style="color:#10b981">${expectedPnl.toFixed(2)}U</td><td class="${c}">${pnl>=0?'+':''}${pnl.toFixed(2)}U</td></tr>`});html+='</tbody></table>';table.innerHTML=html}if(totalPages>1){document.getElementById('positionsPagination').style.display='block';document.getElementById('positionsPageInfo').textContent=`第 ${currentPositionPage}/${totalPages} 页 (共${positionsData.length}条)`;document.querySelector('#positionsPagination button:first-child').disabled=currentPositionPage===1;document.querySelector('#positionsPagination button:last-child').disabled=currentPositionPage===totalPages}else{document.getElementById('positionsPagination').style.display='none'}}
function renderTrades(trades){tradesData=trades||[];tradesData.sort((a,b)=>{const timeA=a['平仓时间']||'';const timeB=b['平仓时间']||'';return timeB.localeCompare(timeA)});const pageSize=getPageSize('trades');const totalPages=Math.ceil(tradesData.length/pageSize);currentTradePage=Math.min(currentTradePage,Math.max(1,totalPages));const start=(currentTradePage-1)*pageSize;const end=start+pageSize;const pageData=tradesData.slice(start,end);const table=document.getElementById('tradesTable');if(!pageData.length){table.innerHTML='<div class="no-data">暂无交易记录</div>';document.getElementById('tradesPagination').style.display='none';return}
const isMobile=window.innerWidth<=768;const showModel=currentModel==='combined';if(isMobile){let html='';pageData.forEach(t=>{const pnl=parseFloat(t['盈亏(U)']||0);const c=pnl>=0?'#10b981':'#ef4444';const posSize=parseFloat(t['仓位(U)']||0);const leverage=parseInt(t['杠杆率']||1);const notionalValue=posSize*leverage;let openTimeStr='',closeTimeStr='',holdTime='';if(t['开仓时间']){const dt=new Date(t['开仓时间'].replace(' ','T'));openTimeStr=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-');}if(t['平仓时间']){const dt=new Date(t['平仓时间'].replace(' ','T'));closeTimeStr=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-');if(t['开仓时间']){const open=new Date(t['开仓时间'].replace(' ','T'));const close=new Date(t['平仓时间'].replace(' ','T'));const diffMs=close-open;const diffHours=Math.floor(diffMs/3600000);const diffDays=Math.floor(diffHours/24);const remainHours=diffHours%24;if(diffDays>0){holdTime=`${diffDays}天${remainHours}h`}else if(diffHours>0){holdTime=`${diffHours}h`}else{const diffMins=Math.floor(diffMs/60000);holdTime=`${diffMins}min`}}}const openPrice=parseFloat(t['开仓价格']||0);const closePrice=parseFloat(t['平仓价格']||0);const openReason=t['开仓理由']||'';const closeReason=t['平仓理由']||'';const modelBadge=showModel&&t.model?`<span style="display:inline-block;padding:2px 6px;background:${t.model==='deepseek'?'#e0f2fe':'#fed7aa'};color:${t.model==='deepseek'?'#0369a1':'#c2410c'};border-radius:4px;font-size:9px;font-weight:600;margin-left:5px">${t.model==='deepseek'?'🤖DS':'🧠QW'}</span>`:'';const reasonData=encodeURIComponent(JSON.stringify({type:'trade',symbol:t['币种']||'',side:t['方向']||'',openReason:openReason,closeReason:closeReason,openTime:openTimeStr,closeTime:closeTimeStr,holdTime:holdTime,posSize:posSize.toFixed(2),leverage:leverage,notionalValue:notionalValue.toFixed(2)}));html+=`<div class="trade-card" onclick="showReasonDialog('${reasonData}')" style="cursor:pointer"><div class="trade-card-header"><span class="symbol">${t['币种']||'--'}</span><span class="side">${t['方向']||'--'}${modelBadge}</span></div><div class="trade-card-row"><span class="label">开仓时间</span><span class="value">${openTimeStr||'--'}</span></div><div class="trade-card-row"><span class="label">平仓时间</span><span class="value">${closeTimeStr||'--'}</span></div><div class="trade-card-row"><span class="label">持仓时长</span><span class="value">${holdTime||'--'}</span></div><div class="trade-card-row"><span class="label">保证金</span><span class="value">${posSize.toFixed(2)}U</span></div><div class="trade-card-row"><span class="label">杠杆率</span><span class="value">${leverage}x</span></div><div class="trade-card-row"><span class="label">持仓价值</span><span class="value">${notionalValue.toFixed(2)}U</span></div><div class="trade-card-row"><span class="label">开仓价</span><span class="value">$${openPrice.toFixed(2)}</span></div><div class="trade-card-row"><span class="label">平仓价</span><span class="value">${closePrice?'$'+closePrice.toFixed(2):'--'}</span></div><div class="trade-card-row"><span class="label">盈亏</span><span class="value" style="color:${c};font-weight:700;font-size:15px">${pnl?((pnl>=0?'+':'')+pnl.toFixed(2)+'U'):'--'}</span></div></div>`});table.innerHTML=html}else{let html=`<table style="font-size:11px"><thead><tr><th>币种</th><th>方向</th>${showModel?'<th>模型</th>':''}<th>开仓时间</th><th>平仓时间</th><th>持仓时长</th><th>保证金</th><th>杠杆率</th><th>持仓价值</th><th>开仓价</th><th>平仓价</th><th>盈亏</th></tr></thead><tbody>`;pageData.forEach(t=>{const pnl=parseFloat(t['盈亏(U)']||0);const c=pnl>=0?'profit':'loss';const posSize=parseFloat(t['仓位(U)']||0);const leverage=parseInt(t['杠杆率']||1);const notionalValue=posSize*leverage;let openTimeStr='',closeTimeStr='',holdTime='';if(t['开仓时间']){const dt=new Date(t['开仓时间'].replace(' ','T'));openTimeStr=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-');}if(t['平仓时间']){const dt=new Date(t['平仓时间'].replace(' ','T'));closeTimeStr=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-');if(t['开仓时间']){const open=new Date(t['开仓时间'].replace(' ','T'));const close=new Date(t['平仓时间'].replace(' ','T'));const diffMs=close-open;const diffHours=Math.floor(diffMs/3600000);const diffDays=Math.floor(diffHours/24);const remainHours=diffHours%24;if(diffDays>0){holdTime=`${diffDays}天${remainHours}h`}else if(diffHours>0){holdTime=`${diffHours}h`}else{const diffMins=Math.floor(diffMs/60000);holdTime=`${diffMins}min`}}}const openPrice=parseFloat(t['开仓价格']||0);const closePrice=parseFloat(t['平仓价格']||0);const openReason=t['开仓理由']||'';const closeReason=t['平仓理由']||'';const tooltip=`📝 开仓决策:\n${openReason}\n\n🔒 平仓决策:\n${closeReason||'无'}\n\n📊 详细信息:\n保证金: ${posSize.toFixed(2)}U\n杠杆率: ${leverage}x\n持仓价值: ${notionalValue.toFixed(2)}U\n持仓时长: ${holdTime||'--'}`;const modelCell=showModel&&t.model?`<td><span style="display:inline-block;padding:2px 6px;background:${t.model==='deepseek'?'#e0f2fe':'#fed7aa'};color:${t.model==='deepseek'?'#0369a1':'#c2410c'};border-radius:4px;font-size:10px;font-weight:600">${t.model==='deepseek'?'🤖DS':'🧠QW'}</span></td>`:'';html+=`<tr title="${tooltip}" style="cursor:pointer"><td><strong>${t['币种']||''}</strong></td><td>${t['方向']||''}</td>${modelCell}<td style="font-size:10px">${openTimeStr||'--'}</td><td style="font-size:10px">${closeTimeStr||'--'}</td><td style="font-size:10px">${holdTime||'--'}</td><td>${posSize.toFixed(2)}U</td><td>${leverage}x</td><td><strong>${notionalValue.toFixed(2)}U</strong></td><td>$${openPrice.toFixed(2)}</td><td>$${closePrice?closePrice.toFixed(2):'--'}</td><td class="${c}">${pnl?((pnl>=0?'+':'')+pnl.toFixed(2)+'U'):'--'}</td></tr>`});html+='</tbody></table>';table.innerHTML=html}if(totalPages>1){document.getElementById('tradesPagination').style.display='block';document.getElementById('tradesPageInfo').textContent=`第 ${currentTradePage}/${totalPages} 页 (共${tradesData.length}条)`;document.querySelector('#tradesPagination button:first-child').disabled=currentTradePage===1;document.querySelector('#tradesPagination button:last-child').disabled=currentTradePage===totalPages}else{document.getElementById('tradesPagination').style.display='none'}}
function changePositionPage(delta){const pageSize=getPageSize('positions');const totalPages=Math.ceil(positionsData.length/pageSize);const newPage=currentPositionPage+delta;if(newPage>=1&&newPage<=totalPages){currentPositionPage=newPage;renderPositions(positionsData)}}

const originalFetch=window.fetch;window.fetch=function(...args){return originalFetch.apply(this,args).then(response=>{const url=args[0];if(response.ok&&(url.includes('/trading-summary')||url.includes('/trading-combined'))){return response.clone().json().then(data=>{window.lastSummaryData=data;if(data.positions)setTimeout(()=>renderPositions(data.positions),50);if(data.recent_trades)setTimeout(()=>renderTrades(data.recent_trades),50);return response})}return response})}
function changeTradePage(delta){const pageSize=getPageSize('trades');const totalPages=Math.ceil(tradesData.length/pageSize);const newPage=currentTradePage+delta;if(newPage>=1&&newPage<=totalPages){currentTradePage=newPage;renderTrades(tradesData)}}
</script><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;background:#fef8ed;padding:20px}.think-content{padding:10px;font-size:11px;color:#555;white-space:pre-wrap;height:150px;overflow-y:auto;line-height:1.5;display:none;background:#fff;border-radius:4px}.think-content.show{display:block}@media(max-width:768px){body{padding:10px}}.container{max-width:1600px;margin:0 auto}.header{background:linear-gradient(135deg,#f0bc3b 0%,#e8a825 100%);color:#2d1b00;padding:25px 30px;border-radius:12px;margin-bottom:20px;box-shadow:0 4px 20px rgba(240,188,59,0.3);display:flex;align-items:center;gap:15px}.logo{width:50px;height:50px;border-radius:50%;background:white;padding:5px;box-shadow:0 2px 8px rgba(0,0,0,0.1)}.logo img{width:100%;height:100%;object-fit:contain}.header-content{flex:1}.header h1{margin-bottom:8px;font-size:26px;font-weight:700}.header-subtitle{font-size:12px;opacity:0.85}.header-actions{display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap}.header-right{display:flex;align-items:center;gap:10px;flex-direction:column}.visitor-count{display:inline-flex;align-items:center;gap:5px;padding:6px 12px;background:rgba(255,255,255,0.25);border:1px solid rgba(255,255,255,0.4);border-radius:6px;font-size:12px;font-weight:600;white-space:nowrap}.share-btn{display:inline-flex;align-items:center;gap:5px;padding:8px 16px;background:rgba(255,255,255,0.3);border:1px solid rgba(255,255,255,0.5);color:#2d1b00;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600;transition:all 0.3s;white-space:nowrap}.share-btn:hover{background:rgba(255,255,255,0.5);transform:translateY(-1px)}.performance-badge{display:inline-block;padding:8px 16px;background:rgba(255,255,255,0.3);border-radius:8px;margin-left:8px;font-size:13px;font-weight:700;border:2px solid rgba(255,255,255,0.5)}.performance-badge.positive{background:rgba(16,185,129,0.2);border-color:#10b981;color:#065f46}.performance-badge.negative{background:rgba(239,68,68,0.2);border-color:#ef4444;color:#991b1b}.performance-badge.neutral{background:rgba(59,130,246,0.2);border-color:#3b82f6;color:#1e3a8a}.experiment-info{background:rgba(255,255,255,0.2);padding:12px 20px;border-radius:8px;margin-top:12px;font-size:12px;display:flex;flex-wrap:wrap;gap:15px;border:1px solid rgba(255,255,255,0.3)}.experiment-info-item{display:flex;align-items:center;gap:5px}.experiment-info-item strong{font-weight:600}.control-btn{padding:8px 16px;background:rgba(255,255,255,0.3);border:1px solid rgba(255,255,255,0.5);color:#2d1b00;border-radius:6px;cursor:pointer;margin-left:10px;font-size:13px;font-weight:600;transition:all 0.3s}.control-btn:hover{background:rgba(255,255,255,0.5)}.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin-bottom:20px}.stat-box{background:linear-gradient(135deg,#f0bc3b 0%,#e8a825 100%);color:#2d1b00;padding:20px;border-radius:10px;box-shadow:0 2px 10px rgba(240,188,59,0.2)}.stat-label{font-size:13px;opacity:0.9;margin-bottom:8px}.stat-value{font-size:28px;font-weight:bold}.grid{display:grid;grid-template-columns:2fr 1fr;gap:20px}@media(max-width:1200px){.grid{grid-template-columns:1fr}}.card{background:white;border-radius:10px;padding:25px;box-shadow:0 2px 10px rgba(0,0,0,0.1);margin-bottom:20px;overflow:visible;position:relative}.card-title{font-size:18px;font-weight:600;margin-bottom:15px;color:#333}.chart-container{position:relative;height:300px;margin-top:20px;padding-top:20px;overflow:visible;z-index:10}.chart-controls{display:flex;gap:8px;margin-bottom:15px;flex-wrap:wrap;align-items:center}.time-range-btn{padding:6px 12px;border:1px solid #e2e8f0;background:white;border-radius:6px;cursor:pointer;font-size:12px;color:#64748b;transition:all 0.3s}.time-range-btn:hover{background:#f8fafc;border-color:#f0bc3b}.time-range-btn.active{background:#f0bc3b;color:#2d1b00;border-color:#f0bc3b;font-weight:600}.date-picker-group{display:flex;gap:6px;align-items:center}.date-picker-input{padding:6px 10px;border:1px solid #e2e8f0;border-radius:6px;font-size:12px;color:#64748b;cursor:pointer}table{width:100%;border-collapse:collapse}thead{background:#f8fafc}th,td{padding:12px;text-align:left;border-bottom:1px solid #e2e8f0;font-size:13px}th{font-weight:600;color:#475569}td{color:#334155}.profit{color:#10b981;font-weight:600}.loss{color:#ef4444;font-weight:600}.loading,.no-data{text-align:center;padding:30px;color:#999;font-size:14px}.mode-badge{display:inline-block;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;margin-left:10px}.mode-test{background:#fef3c7;color:#92400e}.mode-live{background:#fee2e2;color:#991b1b}.cooldown-badge{display:inline-block;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;margin-left:10px;animation:pulse 2s infinite}.cooldown-normal{background:#d1fae5;color:#065f46;border:2px solid #10b981}.cooldown-paused{background:#fee2e2;color:#991b1b;border:2px solid #ef4444}@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.7}}.cooldown-badge.cooldown-normal{animation:none}.chat-container{height:500px;display:flex;flex-direction:column}.chat-messages{flex:1;overflow-y:auto;padding:15px;background:#f8fafc;border-radius:8px;margin-bottom:15px}.message{margin-bottom:15px}.message-user{text-align:right}.message-ai-decision{background:#f0f9ff;padding:12px;border-left:3px solid #0ea5e9;border-radius:6px;margin-bottom:15px}
.message-ai-decision.deepseek{background:#f0f9ff;border-left:3px solid #0ea5e9}
.message-ai-decision.qwen{background:#fff7ed;border-left:3px solid #f97316}.message-ai-decision.executed{background:linear-gradient(135deg,#fff9e6 0%,#ffffff 100%);border-left:4px solid #f0bc3b;box-shadow:0 2px 8px rgba(240,188,59,0.15)}

.message-ai-decision.executed::before{content:'✓ 实际执行';display:inline-block;padding:4px 10px;background:#f0bc3b;color:#2d1b00;border-radius:4px;font-size:11px;font-weight:700;margin-bottom:8px}.decision-content{color:#1e293b;line-height:1.6;background:transparent !important}.decision-analysis{font-size:13px;margin-bottom:15px;padding-bottom:12px;border-bottom:1px solid #e2e8f0;background:transparent !important;line-height:1.8}.decision-risk{font-size:12px;color:#475569;background:transparent !important;padding-top:5px;line-height:1.8}.message-ai-decision .decision-content,.message-ai-decision .decision-analysis,.message-ai-decision .decision-risk{background:transparent !important}.think-box{background:transparent;border:none;border-radius:6px;margin-bottom:12px;overflow:visible}.think-toggle{display:flex;align-items:center;justify-content:space-between;padding:8px 10px;cursor:pointer;background:#f8fafc;border-bottom:1px solid #e2e8f0;user-select:none}.think-toggle:hover{background:#f0f9ff}
.think-title{font-size:12px;font-weight:600;color:#0ea5e9}.think-arrow{font-size:10px;color:#666;transition:transform 0.2s}.think-arrow.open{transform:rotate(180deg)}.think-content{padding:10px;font-size:11px;color:#555;white-space:pre-wrap;height:150px;overflow-y:auto;line-height:1.5;display:none;background:#fff;border-radius:4px}.think-content.show{display:block}.message-content{display:inline-block;max-width:80%;padding:10px 14px;border-radius:10px;word-wrap:break-word;font-size:14px;line-height:1.6}.message-user .message-content{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white}.message-ai .message-content{background:white;border:1px solid #e2e8f0;color:#333}.message-time{font-size:11px;color:#999;margin-top:5px}.chat-input-area{display:flex;gap:10px}.chat-input{flex:1;padding:10px 14px;border:2px solid #e2e8f0;border-radius:8px;font-size:14px}.chat-input:focus{outline:none;border-color:#f0bc3b}.chat-send-btn{padding:10px 20px;background:linear-gradient(135deg,#f0bc3b 0%,#e8a825 100%);color:#2d1b00;border:none;border-radius:8px;cursor:pointer;font-weight:600;transition:all 0.3s;box-shadow:0 2px 8px rgba(240,188,59,0.3)}.chat-send-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(240,188,59,0.4)}.chat-send-btn:disabled{opacity:0.6;cursor:not-allowed;transform:none}.quick-btn{padding:6px 10px;background:#fff3dc;border:1px solid #f0bc3b;border-radius:6px;font-size:12px;cursor:pointer;margin-right:8px;margin-bottom:8px;color:#2d1b00;transition:all 0.3s}.quick-btn:hover{background:#f0bc3b;color:white;transform:translateY(-1px)}.contact-author{display:inline-flex;align-items:center;gap:5px;padding:6px 12px;background:rgba(255,255,255,0.25);border:1px solid rgba(255,255,255,0.4);border-radius:6px;color:#2d1b00;text-decoration:none;font-size:12px;font-weight:600;transition:all 0.3s;margin-left:10px}.contact-author:hover{background:rgba(255,255,255,0.4);transform:translateY(-1px)}.footer{background:linear-gradient(135deg,#f0bc3b 0%,#e8a825 100%);color:#2d1b00;padding:25px 30px;border-radius:12px;margin-top:20px;text-align:center;box-shadow:0 4px 20px rgba(240,188,59,0.3)}.footer-title{font-size:16px;font-weight:700;margin-bottom:15px}.footer-links{display:flex;justify-content:center;gap:20px;flex-wrap:wrap}.footer-link{display:inline-flex;align-items:center;gap:8px;padding:12px 24px;background:rgba(255,255,255,0.3);border:2px solid rgba(255,255,255,0.5);border-radius:10px;color:#2d1b00;text-decoration:none;font-size:14px;font-weight:600;transition:all 0.3s;box-shadow:0 2px 8px rgba(0,0,0,0.1)}.footer-link:hover{background:rgba(255,255,255,0.5);transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,0.15)}.footer-note{margin-top:15px;font-size:11px;opacity:0.75}.position-card,.trade-card{background:#f8fafc;border-radius:8px;padding:12px;margin-bottom:10px;border-left:3px solid #f0bc3b}.position-card-header,.trade-card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #e2e8f0}.position-card-header .symbol,.trade-card-header .symbol{font-size:16px;font-weight:700;color:#1e293b}.position-card-header .side,.trade-card-header .side{font-size:13px;color:#64748b;font-weight:600}.position-card-row,.trade-card-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;font-size:13px}.position-card-row .label,.trade-card-row .label{color:#64748b;font-weight:500}.position-card-row .value,.trade-card-row .value{color:#1e293b;font-weight:600;text-align:right}@media(max-width:768px){body{padding:8px;overflow-x:hidden}.container{max-width:100%;width:100%;padding:0}.header{padding:12px;flex-direction:column;align-items:center;gap:8px;margin-bottom:12px}.logo{width:45px;height:45px}.header-content{width:100%;text-align:center}.header h1{font-size:15px;margin-bottom:6px;line-height:1.3}.header-subtitle{font-size:11px}.header-actions{display:flex;flex-direction:row;justify-content:center;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap}.performance-badge{font-size:12px;padding:6px 12px;margin:3px}.control-btn{padding:6px 12px;font-size:11px;margin-left:0}.mode-badge{margin-left:0;font-size:11px}.contact-author{margin-left:0}.position-card,.trade-card{display:block}.decision-analysis,.decision-risk{font-size:13px !important;line-height:1.7;margin-bottom:10px}#latestDecision{font-size:14px !important;line-height:1.7}#latestDecision p{margin-bottom:8px}#latestDecision strong{font-size:13px}#aiAnalysis{font-size:14px !important;line-height:1.7}#aiAnalysis p{margin-bottom:8px}.experiment-info{padding:8px 12px;gap:8px;font-size:10px}.experiment-info-item{font-size:10px}.stats-grid{grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:12px}.stat-box{padding:10px;border-radius:8px}.stat-label{font-size:10px}.stat-value{font-size:18px}.grid{grid-template-columns:1fr;gap:12px}.card{padding:12px;border-radius:8px;margin-bottom:12px;width:100%;box-sizing:border-box}.card-title{font-size:14px;margin-bottom:10px;font-weight:600}.chart-container{height:200px;width:100%;position:relative;overflow:visible;margin-top:15px;padding-top:15px;z-index:10}.chat-container{height:300px;width:100%}.message{margin-bottom:10px}.message-content{max-width:88%;font-size:12px;padding:8px;overflow-wrap:break-word;word-wrap:break-word;hyphens:auto;line-height:1.5}.message-ai-decision{padding:8px;overflow-wrap:break-word;word-wrap:break-word;font-size:11px}.message-ai-decision.executed::before{font-size:10px;padding:2px 6px;margin-bottom:6px}.decision-content{font-size:11px;overflow-wrap:break-word;word-wrap:break-word;background:transparent !important}.decision-analysis,.decision-risk{font-size:11px;line-height:1.6;overflow-wrap:break-word;word-wrap:break-word;white-space:normal;margin-bottom:8px;background:transparent !important}.think-box{margin-bottom:8px}.think-title{font-size:10px}.think-content{font-size:9px;padding:6px;height:120px;overflow-y:auto;overflow-wrap:break-word;word-wrap:break-word;white-space:pre-wrap;background:#fff;border-radius:4px}.chat-input-area{flex-direction:row;gap:6px;width:100%}.chat-input{font-size:13px;padding:8px;flex:1;min-width:0}.chat-send-btn{padding:8px 12px;font-size:12px;white-space:nowrap}.quick-btn{padding:4px 7px;font-size:10px;margin:0 3px 5px 0;display:inline-block}.loading,.no-data{font-size:12px;padding:15px}.contact-author{margin-left:0;margin-top:5px;font-size:10px;padding:4px 8px}.footer{padding:12px;margin-top:12px;border-radius:8px}.footer-title{font-size:13px;margin-bottom:10px}.footer-links{gap:8px;flex-direction:column}.footer-link{padding:8px 12px;font-size:11px;width:100%;box-sizing:border-box;justify-content:center}.footer-note{font-size:9px;margin-top:8px}#latestDecision{font-size:12px;line-height:1.6}#latestDecision p{margin-bottom:6px;overflow-wrap:break-word;word-wrap:break-word}#latestDecision strong{font-size:11px}#aiAnalysis{font-size:12px}#aiAnalysis p{overflow-wrap:break-word;word-wrap:break-word}}</style></head><body><div class="container"><div class="header"><div class="logo"><img src="https://bitechain.io/assets/images/logo/soltracker-logo.png" alt="追踪狗Logo"/></div><div class="header-content"><div style="display:flex;align-items:center;flex-wrap:wrap;gap:10px"><h1>🔍 追踪狗AI交易系统（内测展示版）</h1><span class="performance-badge" id="profitBadge">--</span><span class="performance-badge" id="annualBadge">--</span><span class="performance-badge neutral" id="drawdownBadge">--</span><span class="performance-badge neutral" id="sharpeBadge">--</span></div><div class="header-subtitle">更新时间: <span id="updateTime">--</span></div><div class="header-actions"><span class="mode-badge" id="modeBadge">--</span><span class="cooldown-badge" id="cooldownBadge" style="display:none">--</span><button class="control-btn" onclick="toggleMode()">切换模式</button><a href="https://x.com/bitechain" target="_blank" rel="noopener noreferrer" class="contact-author">📧 联系作者</a></div><div class="model-tabs" style="display:flex;gap:10px;margin-top:12px;justify-content:center;flex-wrap:wrap"><button class="tab-btn active" onclick="switchModel('combined')" id="tab-combined" style="padding:8px 16px;border:2px solid #f0bc3b;border-radius:8px;background:#f0bc3b;color:#2d1b00;font-weight:600;cursor:pointer;transition:all 0.3s">📊 综合</button><button class="tab-btn" onclick="switchModel('deepseek')" id="tab-deepseek" style="padding:8px 16px;border:2px solid #f0bc3b;border-radius:8px;background:transparent;color:#2d1b00;font-weight:600;cursor:pointer;transition:all 0.3s">🤖 DeepSeek</button><button class="tab-btn" onclick="switchModel('qwen')" id="tab-qwen" style="padding:8px 16px;border:2px solid #f0bc3b;border-radius:8px;background:transparent;color:#2d1b00;font-weight:600;cursor:pointer;transition:all 0.3s">🧠 通义千问</button></div><div class="experiment-info" id="experimentInfo"><div class="experiment-info-item">💰 <strong>初始资金:</strong> <span id="initCapital">--</span></div><div class="experiment-info-item">🪙 <strong>交易币种:</strong> <span id="tradingPairs">--</span></div><div class="experiment-info-item">📊 <strong>杠杆率:</strong> <span id="maxLeverage">--</span></div><div class="experiment-info-item">⚡ <strong>策略:</strong> <span id="strategy">--</span></div><div class="experiment-info-item">🎯 <strong>风控:</strong> <span id="riskControl">--</span></div></div></div><div class="header-right"><div class="visitor-count" id="visitorCount">👀 <span id="visitorNum">--</span> 人看过</div><button class="share-btn" onclick="shareToFriends()">📢 分享给好友，一起来围观</button></div></div><div class="stats-grid"><div class="stat-box"><div class="stat-label">总资产</div><div class="stat-value" id="totalAssets">--</div></div><div class="stat-box"><div class="stat-label">可用余额</div><div class="stat-value" id="balance">--</div></div><div class="stat-box"><div class="stat-label">保证金占用</div><div class="stat-value" id="positionValue">--</div></div><div class="stat-box"><div class="stat-label">未实现盈亏</div><div class="stat-value" id="unrealizedPnl">--</div></div><div class="stat-box"><div class="stat-label">账户总盈利</div><div class="stat-value" id="totalProfit">--</div></div></div><div class="grid"><div><div class="card"><div class="card-title">📈 盈亏曲线</div><div class="chart-controls"><button class="time-range-btn active" onclick="setTimeRange('all')">全部</button><button class="time-range-btn" onclick="setTimeRange('month')">当月</button><button class="time-range-btn" onclick="setTimeRange('week')">当周</button><button class="time-range-btn" onclick="setTimeRange('day')">当天</button><div class="date-picker-group"><input type="date" id="startDate" class="date-picker-input"/><span style="color:#64748b">至</span><input type="date" id="endDate" class="date-picker-input"/><button class="time-range-btn" onclick="setCustomRange()" style="padding:6px 10px">查询</button></div></div><div class="chart-container"><canvas id="pnlChart"></canvas></div></div><div class="card"><div class="card-title">💼 当前持仓</div><div id="positionsTable"><div class="loading">加载中...</div></div><div class="pagination" id="positionsPagination" style="display:none;margin-top:15px;text-align:center"><button onclick="changePositionPage(-1)" style="padding:6px 12px;margin:0 5px;border:1px solid #f0bc3b;background:white;color:#2d1b00;border-radius:4px;cursor:pointer">上一页</button><span id="positionsPageInfo" style="margin:0 10px;color:#64748b;font-size:13px">第 1 页</span><button onclick="changePositionPage(1)" style="padding:6px 12px;margin:0 5px;border:1px solid #f0bc3b;background:white;color:#2d1b00;border-radius:4px;cursor:pointer">下一页</button></div></div><div class="card"><div class="card-title">📝 最近交易</div><div id="tradesTable"><div class="loading">加载中...</div></div><div class="pagination" id="tradesPagination" style="display:none;margin-top:15px;text-align:center"><button onclick="changeTradePage(-1)" style="padding:6px 12px;margin:0 5px;border:1px solid #f0bc3b;background:white;color:#2d1b00;border-radius:4px;cursor:pointer">上一页</button><span id="tradesPageInfo" style="margin:0 10px;color:#64748b;font-size:13px">第 1 页</span><button onclick="changeTradePage(1)" style="padding:6px 12px;margin:0 5px;border:1px solid #f0bc3b;background:white;color:#2d1b00;border-radius:4px;cursor:pointer">下一页</button></div></div><div class="card"><div class="card-title">⚡ 最新决策</div><div id="latestDecision" style="line-height:1.6;color:#555;font-size:14px"><div class="loading">加载中...</div></div></div></div><div><div class="card"><div class="card-title">💬 AI决策记录 & 对话</div><div style="margin-bottom:10px"><button class="quick-btn" onclick="sendQuick('当前持仓分析')">持仓分析</button><button class="quick-btn" onclick="sendQuick('是否调仓？')">调仓建议</button><button class="quick-btn" onclick="sendQuick('风险评估')">风险评估</button></div><div class="chat-container"><div class="chat-messages" id="chatMessages"><div class="loading">加载AI决策...</div></div><div class="chat-input-area"><input type="text" class="chat-input" id="chatInput" placeholder="输入问题..." onkeypress="if(event.keyCode==13)sendMsg()"/><button class="chat-send-btn" id="sendBtn" onclick="sendMsg()">发送</button></div></div></div><div class="card"><div class="card-title">🤖 AI最新分析</div><div id="aiAnalysis" style="line-height:1.6;color:#555;font-size:14px"><div class="loading">加载中...</div></div></div></div></div><div class="footer"><div class="footer-title">🔥 相关产品推荐</div><div class="footer-links"><a href="https://bitechain.io/" target="_blank" rel="noopener noreferrer" class="footer-link">🐶 追踪狗聪明钱包<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg></a><a href="https://bitechain.xyz/" target="_blank" rel="noopener noreferrer" class="footer-link">🎯 追踪狗个人导航页<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg></a></div><div class="footer-note">Powered by 追踪狗团队 | 内测展示版本</div></div></div><script>let chart=null,lastDecisionCount=0,currentModel='combined',compareChart=null,deepseekChart=null,qwenChart=null,currentTimeRange='all',customStartDate='',customEndDate='';function setTimeRange(range){currentTimeRange=range;customStartDate='';customEndDate='';document.querySelectorAll('.time-range-btn').forEach(btn=>btn.classList.remove('active'));event.target.classList.add('active');refresh()}function setCustomRange(){const start=document.getElementById('startDate').value;const end=document.getElementById('endDate').value;if(!start||!end){alert('请选择开始和结束日期');return}if(start>end){alert('开始日期不能晚于结束日期');return}customStartDate=start;customEndDate=end;currentTimeRange='custom';document.querySelectorAll('.time-range-btn').forEach(btn=>btn.classList.remove('active'));refresh()}
function switchModel(model){currentModel=model;lastDecisionCount=0;document.querySelectorAll('.tab-btn').forEach(btn=>{btn.style.background='transparent'});document.getElementById(`tab-${model}`).style.background='#f0bc3b';const chatDiv=document.getElementById('chatMessages');chatDiv.innerHTML='<div class="loading">加载AI决策...</div>';const aiAnalysisDiv=document.getElementById('aiAnalysis');aiAnalysisDiv.innerHTML='<div class="loading">加载中...</div>';document.getElementById('latestDecision').innerHTML='<div class="loading">加载中...</div>';document.getElementById('tradesTable').innerHTML='<div class="loading">加载中...</div>';document.getElementById('positionsTable').innerHTML='<div class="loading">加载中...</div>';refresh()}async function load(){try{let params=new URLSearchParams({model:currentModel});if(currentTimeRange!=='all'){params.append('range',currentTimeRange)}if(customStartDate&&customEndDate){params.append('start_date',customStartDate);params.append('end_date',customEndDate)}const endpoint=currentModel==='combined'?`/trading-combined?${params}`:`/trading-summary?${params}`;const r=await fetch(endpoint);return await r.json()}catch(e){return null}}function calculateRemaining(pauseUntil){if(!pauseUntil)return'';try{const until=new Date(pauseUntil.replace(' ','T'));until.setHours(until.getHours()-8);const now=new Date();const diff=until-now;if(diff<=0)return'';const hours=Math.floor(diff/3600000);const minutes=Math.floor((diff%3600000)/60000);if(hours>24){return'(明日恢复)'}else if(hours>0){return'('+hours+'h'+minutes+'m)'}else{return'('+minutes+'m)'}}catch(e){console.error('计算剩余时间失败:',e);return''}}async function refresh(){const d=await load();if(!d)return;updateUI(d);updatePos(d);updateTrades(d)}let chatPassword=null;async function sendMsg(){const input=document.getElementById('chatInput'),msg=input.value.trim();if(!msg)return;if(!chatPassword){chatPassword=await verifyPassword();if(!chatPassword){addMsg('system','❌ 未输入密码或密码验证失败，消息未发送');return}}addMsg('user',msg);input.value='';const btn=document.getElementById('sendBtn');btn.disabled=true;btn.textContent='思考中...';try{const r=await fetch('/trading-chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg,password:chatPassword,model:currentModel})});const d=await r.json();if(d.success){addMsg('ai',d.reply)}else{if(d.error.includes('密码')){chatPassword=null;addMsg('system','❌ 密码验证失败，请重新输入')}else{addMsg('ai','❌ '+d.error)}}}catch(e){addMsg('ai','❌ 连接失败：'+e.message)}finally{btn.disabled=false;btn.textContent='发送'}}function sendQuick(q){document.getElementById('chatInput').value=q;sendMsg()}function addMsg(type,text){const div=document.getElementById('chatMessages');const m=document.createElement('div');m.className=`message message-${type}`;const now=new Date();const beijingTime=new Date(now.getTime()+8*60*60*1000);const t=beijingTime.toISOString().substr(11,5);m.innerHTML=`<div class="message-content">${text}</div><div class="message-time">${t}</div>`;div.appendChild(m);div.scrollTop=div.scrollHeight}async function toggleMode(){if(currentModel==='combined'){alert('请先选择具体的模型（DeepSeek或通义千问）再切换模式');return}const pwd=prompt('请输入控制密码:');if(!pwd)return;try{const r=await fetch('/trading-control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'toggle_mode',password:pwd,model:currentModel})});const d=await r.json();alert(d.message||d.error);refresh()}catch(e){alert('操作失败:'+e)}}document.addEventListener('DOMContentLoaded',()=>{refresh();setInterval(refresh,15000)})</script><script charset="UTF-8" id="LA_COLLECT" src="//sdk.51.la/js-sdk-pro.min.js"></script><script>LA.init({id:"3KofEcA7mg3VpMDc",ck:"3KofEcA7mg3VpMDc",autoTrack:true})
const _originalRefresh=typeof refresh!=='undefined'?refresh:null;if(_originalRefresh){window.refresh=function(){if(_originalRefresh)_originalRefresh();setTimeout(()=>{const summary=window.lastSummaryData;if(summary){if(summary.positions)renderPositions(summary.positions);if(summary.recent_trades)renderTrades(summary.recent_trades)}},100)}}
window.addEventListener('resize',()=>{if(positionsData.length)renderPositions(positionsData);if(tradesData.length)renderTrades(tradesData)});

function showReasonDialog(encodedData){const data=JSON.parse(decodeURIComponent(encodedData));const dialog=document.getElementById('reasonDialog');const title=document.getElementById('dialogTitle');const content=document.getElementById('dialogContent');if(data.type==='position'){title.textContent=`${data.symbol} ${data.side} - 持仓决策`;content.innerHTML=`<div style="background:#f0f9ff;padding:15px;border-radius:8px;margin-bottom:15px;border-left:3px solid #0ea5e9"><h4 style="margin:0 0 10px 0;color:#0369a1;font-size:16px">📝 开仓决策</h4><p style="margin:0;white-space:pre-wrap">${data.openReason}</p></div><div style="background:#f8fafc;padding:15px;border-radius:8px;border-left:3px solid #64748b"><h4 style="margin:0 0 10px 0;color:#475569;font-size:16px">📊 详细信息</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:14px"><div><span style="color:#64748b">开仓时间:</span><br/><strong>${data.openTime}</strong></div><div><span style="color:#64748b">持仓时长:</span><br/><strong>${data.holdTime}</strong></div><div><span style="color:#64748b">保证金:</span><br/><strong>${data.margin}U</strong></div><div><span style="color:#64748b">杠杆率:</span><br/><strong>${data.leverage}x</strong></div><div><span style="color:#64748b">止盈价:</span><br/><strong style="color:#10b981">$${data.takeProfit}</strong></div><div><span style="color:#64748b">止损价:</span><br/><strong style="color:#ef4444">$${data.stopLoss}</strong></div></div></div>`}else if(data.type==='trade'){title.textContent=`${data.symbol} ${data.side} - 交易决策`;content.innerHTML=`<div style="background:#f0f9ff;padding:15px;border-radius:8px;margin-bottom:15px;border-left:3px solid #0ea5e9"><h4 style="margin:0 0 10px 0;color:#0369a1;font-size:16px">📝 开仓决策</h4><p style="margin:0;white-space:pre-wrap">${data.openReason||'无'}</p></div><div style="background:#fff7ed;padding:15px;border-radius:8px;margin-bottom:15px;border-left:3px solid #f97316"><h4 style="margin:0 0 10px 0;color:#c2410c;font-size:16px">🔒 平仓决策</h4><p style="margin:0;white-space:pre-wrap">${data.closeReason||'无'}</p></div><div style="background:#f8fafc;padding:15px;border-radius:8px;border-left:3px solid #64748b"><h4 style="margin:0 0 10px 0;color:#475569;font-size:16px">📊 详细信息</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:14px"><div><span style="color:#64748b">开仓时间:</span><br/><strong>${data.openTime}</strong></div><div><span style="color:#64748b">平仓时间:</span><br/><strong>${data.closeTime}</strong></div><div><span style="color:#64748b">持仓时长:</span><br/><strong>${data.holdTime}</strong></div><div><span style="color:#64748b">保证金:</span><br/><strong>${data.posSize}U</strong></div><div><span style="color:#64748b">杠杆率:</span><br/><strong>${data.leverage}x</strong></div><div><span style="color:#64748b">持仓价值:</span><br/><strong>${data.notionalValue}U</strong></div></div></div>`}dialog.style.display='flex';document.body.style.overflow='hidden'}
function closeReasonDialog(event){if(!event||event.target.id==='reasonDialog'||event.target.tagName==='BUTTON'){document.getElementById('reasonDialog').style.display='none';document.body.style.overflow='auto'}}
</script><div id="reasonDialog" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10000;align-items:center;justify-content:center" onclick="closeReasonDialog(event)"><div style="background:white;border-radius:12px;max-width:90%;max-height:80vh;overflow-y:auto;padding:20px;box-shadow:0 4px 20px rgba(0,0,0,0.3);position:relative" onclick="event.stopPropagation()"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;border-bottom:2px solid #f0bc3b;padding-bottom:10px"><h3 id="dialogTitle" style="margin:0;color:#2d1b00;font-size:18px">决策详情</h3><button onclick="closeReasonDialog()" style="background:none;border:none;font-size:24px;cursor:pointer;color:#666;padding:0;width:30px;height:30px;display:flex;align-items:center;justify-content:center">×</button></div><div id="dialogContent" style="line-height:1.8;color:#333"></div></div></div></body></html>'''

if __name__ == '__main__':
    app.config['ENV'] = 'production'
    app.config['DEBUG'] = False
    app.run(host='0.0.0.0', port=5000)
