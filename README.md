# ConsentTrace

面向多轮授权变更与工具注入的状态约束式 AI Agent 自动化测试平台
（Contract-Guided Testing and State-Aware Auditing for Tool-Using Agents）

产品需求基线：[ConsentTrace_路径二_V3_产品计划书_PRD.md](ConsentTrace_路径二_V3_产品计划书_PRD.md)

> 当前进度：**阶段 1**：Schema、SDK 插桩、Adapter 协议、差旅 SQLite 靶场（含差旅制度知识库检索）、V1 Agent、脚本化模型。规则引擎、Runner、前端等按 PRD §14 依次交付。

## 快速开始

```bash
uv sync                      # Python 3.11+；创建 .venv 并安装依赖
cp .env.example .env         # 可选：填入 LLM_API_KEY 以运行 Live 测试
uv run pytest                # 离线测试（不调用模型 API）
uv run pytest --cov          # 带覆盖率
uv run pytest -m live        # 真实模型冒烟测试（需要 .env 中的 LLM_API_KEY）
```

## 目录

| 路径 | 内容 |
|---|---|
| `consenttrace/schemas.py` | 契约、用例、轨迹、快照、判定结果等全部数据模型（Pydantic v2） |
| `consenttrace/sdk/` | 被测 Agent 侧插桩：`Toolbox`（工具注册与证据记录）、`TraceRecorder`、`ToolInterceptor`（注入钩子）、`snapshot_sqlite` |
| `consenttrace/llm/` | `ChatClient` 接口、OpenAI 兼容实现、`ScriptedClient`（确定性测试与回放的基础） |
| `consenttrace/adapters/` | `AgentAdapter` 协议与 `CaseContext` |
| `targets/common/agent_loop.py` | 通用工具调用循环（两个靶场共用） |
| `targets/travel_agent/` | 差旅靶场：SQLite 沙箱、虚构数据、差旅制度知识库与 BM25 检索、工具、V1 提示词、适配器 |
| `configs/travel_contract.yaml` | 差旅业务的金标准测试契约 |
| `tests/` | 单元、集成、架构约束、Live 冒烟测试 |

依赖方向：`targets/ → consenttrace`，反之禁止（由 `tests/architecture/` 检查）。
