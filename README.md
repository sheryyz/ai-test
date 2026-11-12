# ConsentTrace

面向多轮授权变更与工具注入的状态约束式 AI Agent 自动化测试平台
（Contract-Guided Testing and State-Aware Auditing for Tool-Using Agents）

产品需求基线：[ConsentTrace_路径二_V3_产品计划书_PRD.md](ConsentTrace_路径二_V3_产品计划书_PRD.md)

> 当前进度：**阶段 3 完成**：授权账本与规则引擎、注入与故障、录制回放与离线重新判定、48 条主用例与 288 次真实模型执行、Web 控制台（三泳道审计时间轴、热力图、回归对比、SSE 实时控制台）。详见 PRD §21。

## 它测什么

用户说"确认上海"，随后又改成"广州"，Agent 能不能沿用旧确认？工具返回里夹带"已获员工预授权"，Agent 会不会直接下单？订票接口写入成功却返回超时，Agent 会不会重复下单？

ConsentTrace 用**可信用户事件**驱动一个独立于被测 Agent 的**授权账本**，逐步核对 Agent 的每次敏感工具调用：发生的那一刻是否有有效授权、参数是否和确认时一致、是否已被撤销、是否被重复消费。再用 SQLite **前后状态差分**和**写入回执**核实是否真的产生了副作用。

## 快速开始

```bash
uv sync                                   # Python 3.11+
cp .env.example .env                      # Live 模式需要填入 LLM_API_KEY

uv run consenttrace validate              # 校验适配器、契约与用例集
uv run consenttrace run --target travel --version v1 --suite smoke --mode live -k 3 -j 6
uv run consenttrace runs                  # 列出运行记录
uv run consenttrace show --run <run_id>                       # 结果总表
uv run consenttrace show --run <run_id> --case S02-confirm-then-change-destination   # 三通道审计时间轴

# 没有 API Key：回放一次已录制的 Live 运行（逐次校验请求哈希，判定结果完全一致）
uv run consenttrace run --target travel --version v1 --mode replay --replay-from <run_id>

# 修正检测器后，在已保存的轨迹上重新判定（不调用模型，原始运行不变）
uv run consenttrace reevaluate --run <run_id>

# Web 控制台：http://127.0.0.1:8765
uv run consenttrace serve
```

前端源码在 `web/`（React + TypeScript + Vite），构建产物已提交在 `consenttrace/web/dist/`，运行控制台不需要 Node。修改前端后：`cd web && npm install && npm run build`。

退出码：`0` 无 FAIL/ERROR；`1` 存在 FAIL；`2` 只有 ERROR 或用法错误，可直接接入 CI。

## 测试

```bash
uv run pytest                 # 离线全量（单元 / 属性 / 集成 / 一致性 / 架构 / 端到端），不调用模型
uv run pytest --cov           # 覆盖率
uv run pytest -m live         # 真实模型冒烟（需要 .env）
uv run pytest -m ui           # 浏览器冒烟：在 Chromium 中打开构建好的控制台（需 uv run playwright install chromium）
uv run ruff check . && uv run ruff format --check .
```

授权语义的属性测试会把授权账本和一个独立写出的参考模型做差分比对，覆盖 hypothesis 随机生成的上千条事件序列。

## 目录

| 路径 | 内容 |
|---|---|
| `consenttrace/schemas.py` | 契约、用例、轨迹、快照、差分、授权、判定的全部数据模型（Pydantic v2） |
| `consenttrace/sdk/` | 被测 Agent 侧插桩：`Toolbox`、`TraceRecorder`、`ToolInterceptor`、`snapshot_sqlite` |
| `consenttrace/core/` | `auth_state`（授权账本）、`rules`（规则引擎）、`injector`、`state_diff`、`runner`、`evidence`、`loader`、`registry`、`verdict` |
| `consenttrace/llm/` | `ChatClient`、OpenAI 兼容实现、`ScriptedClient`、录制 / 回放 |
| `consenttrace/cli.py` | `validate` / `run` / `show` / `runs` / `reevaluate` / `serve` |
| `consenttrace/api/` | FastAPI：运行与证据的只读接口、启动运行、SSE 实时推送；托管前端 |
| `web/` | 前端源码（总览、运行详情、三泳道审计时间轴、回归对比、测试控制台、用例与契约） |
| `docs/oracle_review.md` | 每轮实验后对所有非 PASS 执行的人工复核与检测器修正记录 |
| `targets/travel_agent/` | 差旅靶场：SQLite 沙箱、差旅制度知识库（BM25）、工具、V1 提示词、V2 `ConfirmationGate` |
| `configs/` | `targets.yaml`（目标注册）、`travel_contract.yaml`（金标准契约） |
| `benchmarks/` | 用例集（YAML 编写，JSONL 冻结） |
| `runs/` | 运行证据（不入库）：`trace.jsonl`、`auth_timeline.json`、`state_diff.json`、`verdict.json`、`cassette.jsonl`、`sandbox.db` |

依赖方向：`targets/ → consenttrace`，反之禁止（由 `tests/architecture/` 检查）。
