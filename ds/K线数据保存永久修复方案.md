# K线数据保存永久修复方案

## 🎯 问题根源

**系统从未实现K线数据的单独保存逻辑！**

虽然 `get_ohlcv_data()` 函数获取了K线数据，但只用于：
1. ✅ 计算技术指标
2. ✅ 保存到市场快照（`market_snapshots/`）
3. ❌ **从未单独保存到 `kline_data/` 目录**

## 📋 修复方案

### 方案1：在 `get_ohlcv_data()` 中添加保存逻辑（推荐）

在 `deepseek_多币种智能版.py` 和 `qwen_多币种智能版.py` 的 `get_ohlcv_data()` 函数末尾添加：

```python
def get_ohlcv_data(symbol):
    """获取单个币种的K线数据和技术指标"""
    try:
        # ... 现有代码 ...
        
        # 【新增】保存K线数据用于前端显示
        save_kline_data_for_frontend(symbol, ohlcv_15m)
        
        return {
            # ... 现有返回值 ...
        }
    except Exception as e:
        # ... 现有异常处理 ...
```

### 方案2：创建独立的保存函数

在文件开头添加新函数：

```python
def save_kline_data_for_frontend(symbol: str, ohlcv_data: list):
    """
    保存K线数据用于前端图表显示
    
    Args:
        symbol: 交易对，如 "BTC/USDT:USDT"
        ohlcv_data: K线数据列表，格式：[[timestamp, open, high, low, close, volume], ...]
    """
    try:
        import json
        from pathlib import Path
        
        model_name = os.getenv("MODEL_NAME", "deepseek")
        kline_dir = Path("trading_data") / model_name / "kline_data"
        kline_dir.mkdir(parents=True, exist_ok=True)
        
        # 简化K线数据（只保留前端需要的字段）
        simplified_klines = []
        for kline in ohlcv_data:
            if len(kline) >= 6:
                simplified_klines.append({
                    'timestamp': int(kline[0]),  # 时间戳（毫秒）
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
        
        # 只保留最近1440条（24小时，15分钟K线）
        if len(simplified_klines) > 1440:
            simplified_klines = simplified_klines[-1440:]
        
        # 文件名：BTC_USDT_USDT_15m.json
        # 将 "BTC/USDT:USDT" 转换为 "BTC_USDT_USDT"
        file_name = symbol.replace("/", "_").replace(":", "_") + "_15m.json"
        file_path = kline_dir / file_name
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(simplified_klines, f, ensure_ascii=False)
        
        # 不打印日志，避免刷屏
        # print(f"✅ 已保存K线数据: {file_name} ({len(simplified_klines)}条)")
        
    except Exception as e:
        # 静默失败，不影响主流程
        pass
```

### 方案3：在 `save_market_snapshot_v7()` 中同时保存

在 `save_market_snapshot_v7()` 函数中添加K线数据保存逻辑：

```python
def save_market_snapshot_v7(market_data_list):
    """保存市场快照（每15分钟）供复盘分析"""
    try:
        # ... 现有代码 ...
        
        # 【新增】同时保存K线数据用于前端
        kline_dir = Path("trading_data") / model_name / "kline_data"
        kline_dir.mkdir(parents=True, exist_ok=True)
        
        for data in market_data_list:
            if data is None:
                continue
            
            symbol = data.get("symbol", "")
            kline_data = data.get("kline_data", [])
            
            if not kline_data:
                continue
            
            # 读取现有K线数据（如果有）
            file_name = symbol.replace("/", "_").replace(":", "_") + "_15m.json"
            file_path = kline_dir / file_name
            
            existing_klines = []
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        existing_klines = json.load(f)
                except:
                    existing_klines = []
            
            # 添加新K线数据
            for kline in kline_data:
                if len(kline) >= 6:
                    kline_dict = {
                        'timestamp': int(kline[0]),
                        'open': float(kline[1]),
                        'high': float(kline[2]),
                        'low': float(kline[3]),
                        'close': float(kline[4]),
                        'volume': float(kline[5])
                    }
                    
                    # 去重（基于时间戳）
                    if not any(k['timestamp'] == kline_dict['timestamp'] for k in existing_klines):
                        existing_klines.append(kline_dict)
            
            # 按时间戳排序
            existing_klines.sort(key=lambda x: x['timestamp'])
            
            # 只保留最近1440条（24小时）
            if len(existing_klines) > 1440:
                existing_klines = existing_klines[-1440:]
            
            # 保存
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(existing_klines, f, ensure_ascii=False)
        
        # ... 现有代码继续 ...
        
    except Exception as e:
        print(f"❌ 保存市场快照失败: {e}")
```

## 🎯 推荐方案

**推荐使用方案2（独立函数）+ 在 `get_ohlcv_data()` 中调用**

优点：
1. ✅ 代码清晰，职责分离
2. ✅ 不影响现有逻辑
3. ✅ 静默失败，不影响主流程
4. ✅ 易于维护和测试

## 📝 实施步骤

### 步骤1：临时修复（立即执行）

在服务器上运行：
```bash
cd /root/10-23-bot/ds
python3 fix_kline_data_save.py
```

这会从现有的 `market_snapshots` 中提取K线数据，立即解决前端显示问题。

### 步骤2：永久修复（代码修改）

1. 在 `deepseek_多币种智能版.py` 和 `qwen_多币种智能版.py` 中添加 `save_kline_data_for_frontend()` 函数

2. 在 `get_ohlcv_data()` 函数的返回语句之前调用：
   ```python
   # 【新增】保存K线数据用于前端显示
   save_kline_data_for_frontend(symbol, ohlcv_15m)
   ```

3. 重启服务：
   ```bash
   bash ~/快速重启_修复版.sh
   ```

### 步骤3：验证

1. 检查 `kline_data` 目录是否有文件：
   ```bash
   ls -lh /root/10-23-bot/ds/trading_data/qwen/kline_data/
   ls -lh /root/10-23-bot/ds/trading_data/deepseek/kline_data/
   ```

2. 检查前端是否能正常显示K线图

3. 运行诊断工具确认：
   ```bash
   cd /root/10-23-bot/ds
   python3 check_kline_data.py
   ```

## ⚠️ 注意事项

### 1. 数据量控制

- 只保留最近1440条（24小时，15分钟K线）
- 避免文件过大影响前端加载速度

### 2. 文件命名

- 格式：`{COIN}_USDT_USDT_15m.json`
- 示例：`BTC_USDT_USDT_15m.json`
- 确保与前端API的文件名格式一致

### 3. 更新频率

- 每次 `get_ohlcv_data()` 被调用时更新
- 通常是每15分钟一次

### 4. 错误处理

- 使用 `try-except` 包裹保存逻辑
- 静默失败，不影响主流程
- 不打印日志，避免刷屏

## 🔧 代码位置

### 需要修改的文件

1. `ds/deepseek_多币种智能版.py`
   - 添加 `save_kline_data_for_frontend()` 函数（在文件开头，约第100行）
   - 在 `get_ohlcv_data()` 函数中调用（约第12920行）

2. `ds/qwen_多币种智能版.py`
   - 同上

### 插入位置

在 `get_ohlcv_data()` 函数的返回语句之前：

```python
def get_ohlcv_data(symbol):
    """获取单个币种的K线数据和技术指标"""
    try:
        # ... 所有现有代码 ...
        
        # 【V8.5.2新增】保存K线数据用于前端显示
        save_kline_data_for_frontend(symbol, ohlcv_15m)
        
        return {
            "symbol": symbol,
            "price": current_price,
            # ... 其他返回值 ...
            "kline_data": ohlcv_15m,  # 原始K线数据
        }
    except Exception as e:
        # ... 异常处理 ...
```

## 📊 预期效果

修复后：
- ✅ 前端能正常显示K线图
- ✅ 每个币种都有独立的K线数据文件
- ✅ 数据实时更新（每15分钟）
- ✅ 不影响现有的回测和优化功能

