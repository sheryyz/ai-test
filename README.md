# ConsentTrace

面向多轮授权变更与工具注入的状态约束式 AI Agent 自动化测试平台
（Contract-Guided Testing and State-Aware Auditing for Tool-Using Agents）

产品需求基线：[ConsentTrace_路径二_V3_产品计划书_PRD.md](ConsentTrace_路径二_V3_产品计划书_PRD.md)

> 当前进度：**阶段 4 完成，V2.1 回归完成**：第二靶场（审批 Agent）、带标注的缺陷语料与植入缺陷、对照组 A/B、两项消融与 LLM 裁判 C1/C2、144 个措辞变体与措辞不变性实验；发现并修复 V2 的潜在缺陷，V1 → V2 → V2.1 的完整回归见 [docs/v21_fix_report.md](docs/v21_fix_report.md)。复核记录见 [docs/oracle_review.md](docs/oracle_review.md)，进度见 PRD §21。

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

评估检测器与被测 Agent（结果与复核记录见 `docs/oracle_review.md`）：

```bash
# 在带标注的缺陷语料上，用同一批执行比较 ConsentTrace、对照组 A/B、两项消融与 LLM 裁判 C1/C2
uv run consenttrace detectors --llm-judge --on-run <真实运行 run_id>

# F10：生成用例的措辞变体（受保护取值、词类、顺序、长度都做确定性校验），冻结到 benchmarks/
uv run consenttrace augment --target travel
# 措辞不变性：变体之间的不一致，与同一措辞重复执行的不一致放在一起看
uv run consenttrace phrasing --run <变体运行> --base <同版本主用例运行>

# 两次运行的逐用例回归对比（如 V2 → V2.1），写出 reports/<a>__<b>/regression.md
uv run consenttrace compare --a <run_a> --b <run_b>
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
| `consenttrace/core/` | `auth_state`（授权账本）、`rules`（规则引擎）、`injector`、`state_diff`、`runner`、`evidence`、`loader`、`registry`、`verdict`、`baselines`（对照组与消融）、`detector_eval`、`analysis` |
| `consenttrace/llm/` | `ChatClient`、OpenAI 兼容实现、`ScriptedClient`、录制 / 回放 |
| `consenttrace/cli.py` | `validate` / `run` / `show` / `runs` / `reevaluate` / `detectors` / `augment` / `phrasing` / `compare` / `serve` |
| `consenttrace/ai/` | `llm_judge`（F11 LLM 裁判对照组，磁盘缓存可离线复现）、`case_augmenter`（F10 措辞变体） |
| `consenttrace/api/` | FastAPI：运行与证据的只读接口、启动运行、SSE 实时推送；托管前端 |
| `web/` | 前端源码（总览、运行详情、三泳道审计时间轴、回归对比、测试控制台、用例与契约） |
| `docs/oracle_review.md` | 每轮实验后对所有非 PASS 执行的人工复核与检测器修正记录 |
| `targets/travel_agent/` | 差旅靶场：SQLite 沙箱、差旅制度知识库（BM25）、工具、V1 提示词、V2 `ConfirmationGate`、V2.1 `ConfirmationGateV21`、植入缺陷 `mutants.py` |
| `targets/approval_agent/` | 第二靶场：审批 Agent，复用同一内核，只换工具、提示词、数据库和契约 |
| `configs/` | `targets.yaml`（目标注册）、`travel_contract.yaml` / `approval_contract.yaml`（金标准契约）、`travel_variants.yaml`（措辞变体约束） |
| `benchmarks/` | 用例集（YAML 编写，JSONL 冻结）、`travel_variants.jsonl`（144 个措辞变体）、`travel_defects.py`（带标注的缺陷语料） |
| `runs/`、`reports/` | 运行证据与由它生成的报告（不入库）：`trace.jsonl`、`auth_timeline.json`、`state_diff.json`、`verdict.json`、`cassette.jsonl`、`sandbox.db` |

依赖方向：`targets/ → consenttrace`，反之禁止（由 `tests/architecture/` 检查）。
