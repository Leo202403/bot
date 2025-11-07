# Qwen vs DeepSeek 配置差异记录

## 需要修改的配置项

### 1. API Client 初始化
**位置**: 文件顶部（约Line 538）

**deepseek**:
```python
deepseek_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)
```

**qwen**:
```python
qwen_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)
```

---

### 2. 模型名称
**所有调用位置**: 搜索`model=`

**deepseek**:
- `deepseek-chat`
- `deepseek-reasoner`

**qwen**:
- `qwen-plus`
- `qwen-max`

---

### 3. Client变量名
**所有调用位置**: 搜索`_client.chat.completions.create`

**deepseek**: `deepseek_client`
**qwen**: `qwen_client`

---

### 4. 配置文件路径
**位置**: 所有`trading_data/`路径

**deepseek**: `trading_data/deepseek/`
**qwen**: `trading_data/qwen/`

**具体文件**:
- `learning_config.json`
- `iterative_optimization_history.jsonl`
- `market_snapshots/`
- 日志文件等

---

### 5. 邮件标识
**位置**: 邮件subject和内容

**deepseek**: `[DeepSeek]` / `DeepSeek智能交易系统`
**qwen**: `[通义千问]` / `通义千问智能交易系统`

**关键字**: 搜索`subject.*=`和`此邮件由`

---

### 6. Bark推送标识
**位置**: Bark通知内容

**deepseek**: `[DeepSeek]` / `[深度求索]`
**qwen**: `[通义千问]` / `[Qwen]`

**关键字**: 搜索`send_bark_notification.*title`

---

### 7. Bark分组
**位置**: Bark推送配置

**deepseek**: `group=deepseek` 或 `group=ds`
**qwen**: `group=qwen` 或 `group=qw`

---

### 8. 日志文件名
**位置**: logging配置

**deepseek**: 无特殊要求（通用日志）
**qwen**: 无特殊要求（通用日志）

（注：日志通常在脚本外部控制，文件名由启动脚本指定）

---

### 9. 打印输出标识
**位置**: print语句中的模型名

**deepseek**: `DeepSeek`, `深度求索`
**qwen**: `Qwen`, `通义千问`

**关键字**: 搜索`print.*DeepSeek|print.*深度求索`

---

### 10. 函数/变量命名
**需要检查的名称**:
- 不应该有：`deepseek_xxx`变量名（除了client）
- 应该是通用名称，或使用`qwen_xxx`

---

## 修改步骤

1. 复制deepseek完整内容到qwen
2. 全局替换（按顺序）:
   - `deepseek_client` → `qwen_client`
   - `deepseek-chat` → `qwen-plus`
   - `deepseek-reasoner` → `qwen-max`
   - `trading_data/deepseek/` → `trading_data/qwen/`
   - `[DeepSeek]` → `[通义千问]`
   - `[深度求索]` → `[通义千问]`
   - `DeepSeek智能交易系统` → `通义千问智能交易系统`
3. 手动修改API初始化（base_url不同）
4. 验证Bark分组（如果有）

---

## 验证检查

完成后检查：
```bash
# 1. 不应该出现deepseek相关（除了注释）
grep -i "deepseek" qwen_多币种智能版.py | grep -v "^#" | grep -v "说明\|注释\|deepseek_client"

# 2. 应该出现qwen相关
grep "qwen_client\|qwen-plus\|qwen-max" qwen_多币种智能版.py | wc -l

# 3. 配置路径正确
grep "trading_data/qwen" qwen_多币种智能版.py | wc -l

# 4. 邮件标识正确
grep "通义千问" qwen_多币种智能版.py | wc -l
```

---

**创建日期**: 2025-11-07  
**用途**: 确保qwen和deepseek完全同步，只在配置上有差异  

