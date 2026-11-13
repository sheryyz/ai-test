# ConsentTrace Agent 接入协议（v1）

ConsentTrace 不 import、也不修改被测 Agent。被测 Agent 作为**独立进程**运行，ConsentTrace 只知道它的 URL，所有判定依据都通过本协议取得：对话输出、工具轨迹、业务状态快照，以及模型调用录制（用于离线回放）。

本仓库的三个被测 Agent 都通过本协议接入，`uv run consenttrace serve` 会把它们作为子进程启动：
- 第三方的 τ-bench 航空客服 Agent（:9103，代码未修改，见 [targets/tau_airline/adapter.py](../targets/tau_airline/adapter.py)）。
- 两个自建靶场：差旅（:9101）和审批（:9102）。

任何语言写的 Agent，只要实现下面的接口就能被同一个测试内核测试。

如果是别人写好、不便改动的 Agent，比如 τ-bench，可以在它已有的接缝上接入，不需要改它的代码：
- 用户输入接口：用可信用户事件替代它原来的用户模拟器。
- 工具表：对工具做插桩，写入回执由每次调用改动的数据行推出。
- 模型调用入口：接到 ConsentTrace 的录制 / 回放客户端。

## 1. 接入方式

**Python Agent**：用 SDK 插桩工具，再用一行代码把 Agent 暴露为服务：

```python
from consenttrace.sdk.agent_server import serve_agent

serve_agent(
    name="my-agent",
    versions=["v1"],
    factory=lambda clients, version: MyAdapter(clients, version=version),  # 实现 AgentAdapter 协议
    default_port=9200,
)
```

`MyAdapter` 的写法见 [targets/approval_agent/adapter.py](../targets/approval_agent/adapter.py)，大约 100 行：
- 工具通过 `Toolbox` 注册，SDK 会按真实发生顺序记录 `tool_call_attempt → write_receipt → injection → tool_result`。
- `snapshot()` 可以直接复用 `snapshot_sqlite()`。

**其他语言**：实现第 2 节的接口即可，事件与快照的 JSON 结构见 [consenttrace/schemas.py](../consenttrace/schemas.py)（`TraceEvent`、`StateSnapshot`、`TurnResult`、`AdapterCapabilities`）。

**注册**：在 `configs/targets.yaml` 中登记 URL、测试契约和用例集：

```yaml
targets:
  my-agent:
    service: {url: http://127.0.0.1:9200}
    contract: configs/my_contract.yaml
    versions: [v1]
    suites: {core: benchmarks/my_core.yaml}
```

**接入检查**：`uv run consenttrace probe --url http://127.0.0.1:9200`，Web 端在「被测 Agent」页。接入检查不调用模型，逐项核对 Agent 声明的能力是否真的提供。

## 2. 接口

所有路径都带前缀 `/ct/v1`，请求和响应都是 JSON。

| 方法与路径 | 作用 | 返回 |
|---|---|---|
| `GET /info` | 身份与能力声明 | `{protocol: "1", name, description, versions[], capabilities, llm: {live_available, model, replay}}` |
| `GET /describe?version=` | 工具定义、系统提示词、状态表结构（可选，供 AI 起草契约） | `AgentDescription`；不支持时返回 404 |
| `POST /sessions` | 为一次用例执行开启**隔离**会话 | `{session_id}` |
| `POST /sessions/{id}/messages` | 发送一轮可信用户消息 `{text}` | `TurnResult` |
| `GET /sessions/{id}/events?since=N` | 取 `step_id > N` 的轨迹事件，不会清除已取的事件 | `TraceEvent[]` |
| `GET /sessions/{id}/snapshot` | 当前业务状态；没有状态访问能力时返回 `null` | `StateSnapshot \| null` |
| `GET /sessions/{id}/cassette` | 本会话中 Live 模型调用的录制 | 录制条目数组 |
| `GET /sessions/{id}/artifacts[/name]` | Agent 为本会话保留的文件，例如 SQLite 库 | 文件名列表或文件内容 |
| `DELETE /sessions/{id}` | 结束会话，释放沙箱 | `{closed}` |

`POST /sessions` 的请求体：

```json
{
  "version": "v1",
  "run_id": "...", "case_id": "...", "fixture": "default", "seed": 0,
  "injections": [{"injection_id": "INJ-1", "tool": "search_flights", "occurrence": 1, "mode": "append_text", "payload": "..."}],
  "llm": {"mode": "live | replay | scripted", "cassette": [...], "script": [...], "timeout": 90}
}
```

- **injections**：注入点由测试平台下发，由 Agent 一侧的工具层在第 n 次合法调用时执行。注入只改变模型看到的工具返回，不改变真实执行。每次注入都必须留下 `injection` 事件。
- **llm.mode**：
  - `live`：Agent 使用**自己的**模型 Key，平台看不到 Key。
  - `replay`：按平台发来的录制逐次回放，每次请求都会校验请求哈希，内容不一致就报错。
  - `scripted`：使用固定回复，专供接入检查使用，不调用模型。

## 3. 能力声明必须如实

`capabilities` 中有五项：`output`、`trace`、`state`、`inject_tool_response`、`visible_reasoning`。平台据此决定开启哪些断言：

| Agent 提供的能力 | 平台能判定的内容 |
|---|---|
| 只有 output（纯黑盒） | 回复内容检查。授权类和状态类断言显示 **UNSUPPORTED**，不会给出 PASS |
| + trace | 每次敏感工具调用发生时是否有有效授权（越权尝试） |
| + state | 越权是否真的写入了业务数据（状态差分与写入回执交叉核验）、任务终态 |
| + inject_tool_response | 工具返回注入、RAG 检索段投毒、故障注入类用例 |

声明了能力却交不出相应证据，接入检查会判为 FAIL，例如声明了 `state` 但快照为空。

## 4. 隔离与并发

- 每个会话要有独立的沙箱，新会话的初始状态必须一致；接入检查会比较两次新会话的状态摘要。
- 参考实现会把每个会话固定在它自己的线程上执行，因为 sqlite3 连接这类资源只能在创建它的线程里使用。
- 同一会话内的轮次严格串行；轮次进行中再发消息会返回 409。
- 不同会话可以并行，平台默认并发度为 4。
