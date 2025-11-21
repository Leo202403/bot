#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从币安统一账户(Portfolio Margin API)恢复数据
支持：
1. 获取账户余额和总资产
2. 获取当前持仓
3. 获取历史订单
4. 恢复到system_status.json和trades_history.csv

重要：DeepSeek和Qwen使用不同的币安账户
- deepseek: 使用 ds/.env 文件
- qwen: 使用 ds/.env.qwen 文件
"""

import os
import json
import csv
import ccxt
from pathlib import Path
from datetime import datetime
from typing import Any, Dict
from dotenv import load_dotenv

# 全局变量存储两个交易所实例
exchanges: Dict[str, Any] = {}


def init_exchange(model_name):
    """初始化指定模型的交易所实例"""
    # 确定环境变量文件
    if model_name == 'deepseek':
        env_file = Path(__file__).parent / ".env"
    elif model_name == 'qwen':
        env_file = Path(__file__).parent / ".env.qwen"
    else:
        print(f"❌ 未知的模型: {model_name}")
        return None
    
    if not env_file.exists():
        print(f"❌ 环境变量文件不存在: {env_file}")
        return None
    
    # 加载环境变量
    load_dotenv(env_file, override=True)
    
    # 获取API密钥
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    secret_key = os.getenv("BINANCE_SECRET_KEY", "").strip()
    use_portfolio = os.getenv("USE_PORTFOLIO_MARGIN", "true").lower() == "true"
    
    if not api_key or not secret_key:
        print(f"❌ {model_name}: 币安API密钥未配置")
        return None
    
    # 初始化交易所
    exchange = ccxt.binance({
        "apiKey": api_key,
        "secret": secret_key,
        "options": {
            "defaultType": "future",
            "portfolioMargin": use_portfolio,
            "recvWindow": 60000,
        },
        "timeout": 30000,
        "enableRateLimit": True,
    })
    
    print(f"✅ {model_name}: 已连接 (API Key: {api_key[:10]}...)")
    
    return exchange


print("=" * 60)
print("📊 从币安统一账户恢复数据")
print("=" * 60)
print("⚠️  注意: DeepSeek和Qwen使用不同的币安账户")
print("")


def get_account_balance(exchange, model_name):
    """获取账户余额和总资产"""
    try:
        # 对于统一账户，使用fapiPrivateV2GetAccount或直接fetch_balance
        balance = exchange.fetch_balance()
        
        print(f"📌 {model_name} 账户余额信息:")
        print(f"  总权益: {balance.get('total', {}).get('USDT', 0):.2f} USDT")
        print(f"  可用余额: {balance.get('free', {}).get('USDT', 0):.2f} USDT")
        print(f"  冻结余额: {balance.get('used', {}).get('USDT', 0):.2f} USDT")
        
        # 获取详细信息
        if 'info' in balance:
            info = balance['info']
            
            # 统一账户的字段可能不同
            total_wallet_balance = 0
            total_unrealized_profit = 0
            
            # 尝试从不同字段获取
            if 'totalWalletBalance' in info:
                total_wallet_balance = float(info['totalWalletBalance'])
            if 'totalUnrealizedProfit' in info:
                total_unrealized_profit = float(info['totalUnrealizedProfit'])
            
            # 计算总资产
            if 'totalMarginBalance' in info:
                total_assets = float(info['totalMarginBalance'])
            elif 'totalWalletBalance' in info:
                total_assets = total_wallet_balance + total_unrealized_profit
            else:
                # 备用方案：使用USDT余额
                total_assets = balance.get('total', {}).get('USDT', 0)
            
            print("\n💰 总资产详情:")
            print(f"  钱包余额: {total_wallet_balance:.2f} USDT")
            print(f"  未实现盈亏: {total_unrealized_profit:+.2f} USDT")
            print(f"  总资产: {total_assets:.2f} USDT")
            
            return {
                'total_assets': total_assets,
                'wallet_balance': total_wallet_balance,
                'unrealized_profit': total_unrealized_profit,
                'available_balance': balance.get('free', {}).get('USDT', 0),
                'used_balance': balance.get('used', {}).get('USDT', 0),
            }
        
        return None
        
    except Exception as e:
        print(f"❌ 获取账户余额失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_open_positions(exchange, model_name):
    """获取当前持仓"""
    try:
        # 使用fetch_positions获取持仓
        positions = exchange.fetch_positions()
        
        # 过滤出有持仓的
        open_positions = [p for p in positions if float(p.get('contracts', 0)) > 0]
        
        print(f"\n📋 {model_name} 当前持仓: {len(open_positions)} 个")
        
        formatted_positions = []
        for pos in open_positions:
            symbol = pos.get('symbol', '')
            side = pos.get('side', '')  # long/short
            contracts = float(pos.get('contracts', 0))
            entry_price = float(pos.get('entryPrice', 0))
            mark_price = float(pos.get('markPrice', 0))
            unrealized_pnl = float(pos.get('unrealizedPnl', 0))
            leverage = float(pos.get('leverage', 1))
            notional = float(pos.get('notional', 0))
            
            # 转换为中文方向
            direction_cn = "多" if side == "long" else "空"
            
            print(f"\n  {symbol} {direction_cn}")
            print(f"    数量: {contracts}")
            print(f"    开仓价: ${entry_price:.2f}")
            print(f"    标记价: ${mark_price:.2f}")
            print(f"    未实现盈亏: {unrealized_pnl:+.2f} USDT")
            print(f"    杠杆: {leverage}x")
            print(f"    仓位价值: ${notional:.2f}")
            
            formatted_positions.append({
                '币种': symbol.replace('/USDT', '').replace(':USDT', ''),
                '方向': direction_cn,
                'side': side,
                '数量': contracts,
                '开仓价格': entry_price,
                '当前价格': mark_price,
                '杠杆': int(leverage),
                '杠杆率': int(leverage),
                '盈亏': unrealized_pnl,
                '仓位(U)': abs(notional),
                '开仓时间': '',  # API不返回，需要从订单历史获取
                '止损': '',
                '止盈': '',
                '盈亏比': '',
                '开仓理由': '从币安API恢复',
            })
        
        return formatted_positions
        
    except Exception as e:
        print(f"❌ 获取持仓失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def get_order_history(exchange, model_name, symbol=None, limit=500):
    """获取历史订单"""
    try:
        print(f"\n📜 {model_name} 获取订单历史...")
        
        # 支持的交易对
        symbols = [
            'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 
            'BNB/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'LTC/USDT:USDT'
        ]
        
        all_orders = []
        
        for sym in symbols:
            try:
                # 获取该交易对的订单
                orders = exchange.fetch_orders(sym, limit=limit)
                all_orders.extend(orders)
                print(f"  {sym}: {len(orders)} 笔订单")
            except Exception as e:
                print(f"  ⚠️  {sym}: 获取失败 - {e}")
                continue
        
        print(f"\n总计: {len(all_orders)} 笔订单")
        
        return all_orders
        
    except Exception as e:
        print(f"❌ 获取订单历史失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def restore_to_system_status(model_name, account_data, positions):
    """恢复到system_status.json"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    status_file = data_dir / "system_status.json"
    
    if not status_file.exists():
        print(f"⚠️  {model_name}: system_status.json 不存在，将创建新文件")
        status = {}
    else:
        with open(status_file, 'r', encoding='utf-8') as f:
            status = json.load(f)
    
    # 更新账户数据
    if account_data:
        status['总资产'] = account_data['total_assets']
        status['total_assets'] = account_data['total_assets']
        status['USDT余额'] = account_data['available_balance']
        status['usdt_balance'] = account_data['available_balance']
        status['未实现盈亏'] = account_data['unrealized_profit']
    
    # 更新持仓
    status['持仓详情'] = positions
    status['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 保存
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    
    print(f"✅ {model_name}: system_status.json 已更新")
    return True


def restore_to_trades_history(model_name, orders, positions):
    """恢复到trades_history.csv（仅添加当前持仓的开仓记录）"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    trades_file = data_dir / "trades_history.csv"
    
    # CSV字段（根据实际文件）
    fieldnames = [
        '开仓时间', '平仓时间', '币种', '方向', '数量', '开仓价格', '平仓价格',
        '仓位(U)', '杠杆率', '止损', '止盈', '盈亏比', '盈亏(U)', 
        '开仓理由', '平仓理由', '信号分数', '共振指标数'
    ]
    
    # 读取现有订单
    existing_trades = []
    if trades_file.exists():
        with open(trades_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            existing_trades = list(reader)
            # 获取实际的字段名
            if reader.fieldnames:
                fieldnames = list(reader.fieldnames)
    
    # 查找未平仓订单（考虑分批止盈，使用开仓价格作为唯一标识）
    open_trade_keys = set()
    for trade in existing_trades:
        if not trade.get('平仓时间', '').strip():
            # 未平仓记录：使用币种_方向_开仓时间_开仓价格作为唯一键
            key = f"{trade.get('币种', '')}_{trade.get('方向', '')}_{trade.get('开仓时间', '')}_{trade.get('开仓价格', '')}"
            open_trade_keys.add(key)
    
    # 需要添加的持仓
    trades_to_add = []
    for pos in positions:
        # 生成唯一键（与上面的逻辑一致）
        # 注意：从API获取的持仓没有开仓时间，所以需要用开仓价格判断
        key = f"{pos.get('币种', '')}_{pos.get('方向', '')}_{pos.get('开仓时间', '')}_{pos.get('开仓价格', '')}"
        
        # 如果开仓时间为空，则只用币种和方向匹配（向后兼容）
        if not pos.get('开仓时间', ''):
            simple_key = f"{pos.get('币种', '')}_{pos.get('方向', '')}"
            # 检查是否已存在该币种方向的未平仓记录
            already_exists = any(simple_key in k for k in open_trade_keys)
            if already_exists:
                continue
        elif key in open_trade_keys:
            # 精确匹配，跳过
            continue
        
        # 如果到这里，说明没有匹配的记录，需要添加
        if True:
            # 尝试从订单历史中获取开仓时间
            open_time = ''
            for order in orders:
                order_symbol = order.get('symbol', '').replace('/USDT:USDT', '').replace('/USDT', '')
                order_side_long = order.get('side', '') == 'buy'
                pos_side_long = pos.get('side', '') == 'long'
                
                if (order_symbol == pos.get('币种', '') and 
                    order_side_long == pos_side_long and
                    order.get('status') == 'closed'):
                    open_time = datetime.fromtimestamp(order['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    break
            
            if not open_time:
                open_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            trade_record = {}
            for field in fieldnames:
                field_clean = field.strip()
                
                if field_clean == '开仓时间':
                    trade_record[field] = open_time
                elif field_clean == '平仓时间':
                    trade_record[field] = ''
                elif field_clean == '币种':
                    trade_record[field] = pos.get('币种', '')
                elif field_clean == '方向':
                    trade_record[field] = pos.get('方向', '')
                elif field_clean == '数量':
                    trade_record[field] = pos.get('数量', 0)
                elif field_clean == '开仓价格':
                    trade_record[field] = pos.get('开仓价格', 0)
                elif field_clean == '平仓价格':
                    trade_record[field] = ''
                elif field_clean == '仓位(U)':
                    trade_record[field] = pos.get('仓位(U)', 0)
                elif field_clean == '杠杆率':
                    trade_record[field] = pos.get('杠杆率', 1)
                elif field_clean == '止损':
                    trade_record[field] = pos.get('止损', '')
                elif field_clean == '止盈':
                    trade_record[field] = pos.get('止盈', '')
                elif field_clean == '盈亏比':
                    trade_record[field] = pos.get('盈亏比', '')
                elif field_clean == '盈亏(U)':
                    trade_record[field] = ''
                elif field_clean == '开仓理由':
                    trade_record[field] = pos.get('开仓理由', '')
                elif field_clean == '平仓理由':
                    trade_record[field] = ''
                elif field_clean == '信号分数':
                    trade_record[field] = ''
                elif field_clean == '共振指标数':
                    trade_record[field] = ''
                else:
                    trade_record[field] = ''
            
            trades_to_add.append(trade_record)
            print(f"  + 添加: {pos.get('币种')} {pos.get('方向')}")
    
    if trades_to_add:
        # 追加到CSV
        with open(trades_file, 'a', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not existing_trades:  # 文件为空，写表头
                writer.writeheader()
            writer.writerows(trades_to_add)
        
        print(f"✅ {model_name}: 已添加 {len(trades_to_add)} 条持仓记录到 trades_history.csv")
    else:
        print(f"✓ {model_name}: 所有持仓记录已存在")
    
    return True


def main():
    """主函数"""
    # 1. 选择要恢复的模型
    print("请选择要恢复的账户:")
    print("  1) DeepSeek账户 (使用 ds/.env)")
    print("  2) Qwen账户 (使用 ds/.env.qwen)")
    print("  3) 两个账户都恢复")
    print("  4) 仅查看数据，不恢复")
    print("")
    
    choice = input("请选择 [1-4]: ").strip()
    
    models = []
    if choice == '1':
        models = ['deepseek']
    elif choice == '2':
        models = ['qwen']
    elif choice == '3':
        models = ['deepseek', 'qwen']
    elif choice == '4':
        view_only = True
        models = ['deepseek', 'qwen']
    else:
        print("❌ 无效选项")
        return
    
    view_only = (choice == '4')
    
    # 2. 为每个模型获取数据
    model_data = {}
    
    for model in models:
        print("\n" + "=" * 60)
        print(f"📊 处理 {model.upper()} 账户")
        print("=" * 60)
        
        # 初始化交易所
        exchange = init_exchange(model)
        if not exchange:
            print(f"⚠️  跳过 {model}")
            continue
        
        # 获取账户数据
        print(f"\n【步骤1】获取 {model} 账户余额")
        account_data = get_account_balance(exchange, model)
        
        if not account_data:
            print(f"❌ 无法获取 {model} 账户数据")
            continue
        
        # 获取持仓
        print(f"\n【步骤2】获取 {model} 当前持仓")
        positions = get_open_positions(exchange, model)
        
        # 获取订单历史
        print(f"\n【步骤3】获取 {model} 订单历史")
        orders = get_order_history(exchange, model, limit=500)
        
        # 保存数据
        model_data[model] = {
            'account_data': account_data,
            'positions': positions,
            'orders': orders
        }
        
        # 显示总结
        print(f"\n{'=' * 60}")
        print(f"📊 {model.upper()} 数据汇总")
        print(f"{'=' * 60}")
        print(f"总资产: {account_data['total_assets']:.2f} USDT")
        print(f"可用余额: {account_data['available_balance']:.2f} USDT")
        print(f"未实现盈亏: {account_data['unrealized_profit']:+.2f} USDT")
        print(f"当前持仓: {len(positions)} 个")
        print(f"历史订单: {len(orders)} 笔")
    
    # 如果只是查看，到此结束
    if view_only:
        print("\n✅ 数据查看完成")
        return
    
    # 3. 确认恢复
    print("\n" + "=" * 60)
    print("⚠️  确认恢复")
    print("=" * 60)
    
    for model in model_data.keys():
        data = model_data[model]
        print(f"\n{model.upper()}:")
        print(f"  将恢复总资产: {data['account_data']['total_assets']:.2f} USDT")
        print(f"  将恢复持仓: {len(data['positions'])} 个")
    
    print("")
    confirm = input("确认执行恢复? (y/n): ").strip().lower()
    
    if confirm != 'y':
        print("❌ 已取消")
        return
    
    # 4. 执行恢复
    print("\n" + "=" * 60)
    print("🔧 开始恢复数据")
    print("=" * 60)
    
    for model, data in model_data.items():
        print(f"\n【{model.upper()}】")
        
        # 备份
        data_dir = Path(__file__).parent / "trading_data" / model
        backup_dir = Path(__file__).parent / "data_backup" / f"before_binance_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        for file in ['system_status.json', 'trades_history.csv']:
            src = data_dir / file
            if src.exists():
                import shutil
                shutil.copy2(src, backup_dir / f"{model}_{file}")
        
        print(f"  ✓ 已备份到: {backup_dir}")
        
        # 恢复system_status.json
        restore_to_system_status(model, data['account_data'], data['positions'])
        
        # 恢复trades_history.csv（只添加缺失的持仓记录）
        restore_to_trades_history(model, data['orders'], data['positions'])
    
    print("\n" + "=" * 60)
    print("✅ 数据恢复完成！")
    print("=" * 60)
    print("\n💡 下一步:")
    print("   1. 重启后端服务")
    print("   2. 刷新前端页面")
    print("   3. 验证数据是否正确")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ 用户中断")
    except Exception as e:
        print(f"\n\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()

