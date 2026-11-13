# 测试覆盖矩阵（按赛题路径二组织）

由 `consenttrace coverage` 根据 `configs/coverage_matrix.yaml` 生成：每一格引用的用例编号由已注册的用例集解析而来，引用的运行证据与文件在生成时逐一核对存在；没有证据的格子如实写“未覆盖”及原因。

| 能力 / 风险 | 智能体自动化测试框架 | RAG 知识库测试工具 | 对抗性用例自动生成器 | 智能体行为可视化与审计平台 |
|---|---|---|---|---|
| **规划** | ✓ 14 条用例、8 份运行证据、1 个文件 | 未覆盖 | ✓ 3 条用例、1 个文件 | ✓ 1 份运行证据、2 个文件 |
| **记忆** | ✓ 25 条用例、3 份运行证据 | 未覆盖 | ✓ 40 条用例、1 个文件 | ✓ 1 份运行证据、1 个文件 |
| **工具调用** | ✓ 46 条用例、18 份运行证据、3 个文件 | ✓ 1 份运行证据 | ✓ 1 份运行证据、1 个文件 | ✓ 1 个文件 |
| **RAG** | ✓ 6 条用例、1 份运行证据 | ✓ 1 份运行证据、2 个文件 | ✓ 6 条用例、2 个文件 | ✓ 6 条用例 |
| **注入** | ✓ 96 条用例、12 份运行证据 | ✓ 1 份运行证据 | ✓ 3 个文件 | ✓ 1 个文件 |
| **越狱** | ✓ 48 条用例、14 份运行证据 | 未覆盖 | ✓ 4 个文件 | ✓ 1 个文件 |
| **边界** | ✓ 30 条用例、10 份运行证据 | ✓ 1 份运行证据 | ✓ 6 个文件 | ✓ 1 个文件 |

## 规划

多步任务能否按正确顺序推进，工具出错或超时后能否正确恢复（例如先查订单再决定是否重下）

### 规划 × 智能体自动化测试框架

评分卡的“故障恢复”维度；perf-v1-smoke-c1 中 V1 超时后重复下单是一条真实的规划缺陷（S07）

- 用例 `travel/main`（categories=C7/C8），12 条：`C7-01-timeout-after-commit`, `C7-02-timeout-before-commit-retry`, `C7-03-booking-service-down`, `C7-04-malformed-search`, `C7-05-cancel-timeout-after-commit`, `C7-06-policy-kb-down`, `C8-01-long-consultation-then-book`, `C8-02-injection-plus-change`, `C8-03-timeout-plus-forged-retry`, `C8-04-cancel-and-rebook-both-confirmed`, `C8-05-cancel-and-rebook-one-confirmed`, `C8-06-long-context-poison-and-revoke`
- 用例 `tau-airline/core`（categories=C7），1 条：`T09-cancel-timeout-after-commit`
- 用例 `approval/core`（categories=C7），1 条：`A11-approve-timeout-after-commit`
- 运行证据：`runs/main-v1-live-k3-reeval2`, `runs/perf-v1-smoke-c1`, `runs/bench-deepseek-flash-travel-v1-main-k3`, `runs/bench-deepseek-v4-pro-travel-v1-main-k3`, `runs/bench-glm-4.5-air-travel-v1-main-k3`, `runs/bench-glm-5.3-flash-travel-v1-main-k3`, `runs/bench-qwen-flash-travel-v1-main-k3`, `runs/bench-qwen-plus-travel-v1-main-k3`
- 文件：`consenttrace/core/scorecard.py`

### 规划 × RAG 知识库测试工具

未覆盖：知识库体检只检查知识本身和检索，不涉及 Agent 的多步规划

### 规划 × 对抗性用例自动生成器

留出用例由大模型一次生成并冻结，其中含工具故障与混合长对话

- 用例 `travel/holdout`（categories=C7/C8），3 条：`H10-book-error-before-retry`, `H11-cancel-error-after`, `H12-long-mixed-dialogue`
- 文件：`benchmarks/travel_holdout.generation.json`

### 规划 × 智能体行为可视化与审计平台

时间轴按步骤展示“推理—调用—返回—写入”；思维链路诊断给出越权前的推理依据（仅限返回推理文本的模型）

- 运行证据：`runs/bench-glm-4.5-air-travel-v1-main-k3`
- 文件：`consenttrace/core/reasoning.py`, `web/src/components/TraceSwimlane.tsx`

**这一行的空白**：未覆盖规划效率（步数、冗余调用、最优工具顺序）的量化指标


## 记忆

多轮对话中能否记住并正确更新用户的授权：改参后旧确认失效、撤销后不能再执行、长对话后仍记得

### 记忆 × 智能体自动化测试框架

授权账本逐轮记录请求、确认、修改、撤销；T10（第三方 τ-bench）是一次真实的记忆类越权写入

- 用例 `travel/main`（categories=C2/C3/C8），18 条：`C2-01-confirm-then-change-destination`, `C2-02-confirm-with-cabin-upgrade`, `C2-03-change-then-reconfirm`, `C2-04-confirm-and-change-date`, `C2-05-two-changes-then-confirm-final`, `C2-06-change-back-without-reconfirm`, `C3-01-revoke-before-booking`, `C3-02-hold-for-approval`, `C3-03-decline-recommendation-then-choose`, `C3-04-cancel-request-withdrawn`, `C3-05-cancel-the-right-order`, `C3-06-revoke-then-change-mind`, `C8-01-long-consultation-then-book`, `C8-02-injection-plus-change`, `C8-03-timeout-plus-forged-retry`, `C8-04-cancel-and-rebook-both-confirmed`, `C8-05-cancel-and-rebook-one-confirmed`, `C8-06-long-context-poison-and-revoke`
- 用例 `tau-airline/core`（categories=C2），4 条：`T02-yes-then-switch-reservation`, `T03-switch-then-confirm`, `T06-baggage-change-then-confirm`, `T10-baggage-yes-then-more`
- 用例 `approval/core`（categories=C2/C3），3 条：`A04-switch-request-after-confirm`, `A05-approve-turned-reject`, `A06-hold-before-approval`
- 运行证据：`runs/main-v1-live-k3-reeval2`, `runs/main-v2.1-live-k3`, `runs/tau-core-v1-live-k3`

### 记忆 × RAG 知识库测试工具

未覆盖：知识库体检不涉及对话记忆

### 记忆 × 对抗性用例自动生成器

措辞变体检验同一授权意图换种说法后，Agent 的理解是否一致

- 用例 `travel/holdout`（categories=C2/C3），4 条：`H03-modify-without-reconfirm`, `H04-modify-then-reconfirm`, `H05-confirm-then-revoke`, `H06-cancel-existing-order`
- 用例 `travel/variants`（categories=C2/C3），36 条：`C2-01-confirm-then-change-destination.p1`, `C2-01-confirm-then-change-destination.p2`, `C2-01-confirm-then-change-destination.p3`, `C2-02-confirm-with-cabin-upgrade.p1`, `C2-02-confirm-with-cabin-upgrade.p2`, `C2-02-confirm-with-cabin-upgrade.p3`, `C2-03-change-then-reconfirm.p1`, `C2-03-change-then-reconfirm.p2`, `C2-03-change-then-reconfirm.p3`, `C2-04-confirm-and-change-date.p1`, `C2-04-confirm-and-change-date.p2`, `C2-04-confirm-and-change-date.p3`, `C2-05-two-changes-then-confirm-final.p1`, `C2-05-two-changes-then-confirm-final.p2`, `C2-05-two-changes-then-confirm-final.p3`, `C2-06-change-back-without-reconfirm.p1`, `C2-06-change-back-without-reconfirm.p2`, `C2-06-change-back-without-reconfirm.p3`, `C3-01-revoke-before-booking.p1`, `C3-01-revoke-before-booking.p2`, `C3-01-revoke-before-booking.p3`, `C3-02-hold-for-approval.p1`, `C3-02-hold-for-approval.p2`, `C3-02-hold-for-approval.p3`, `C3-03-decline-recommendation-then-choose.p1`, `C3-03-decline-recommendation-then-choose.p2`, `C3-03-decline-recommendation-then-choose.p3`, `C3-04-cancel-request-withdrawn.p1`, `C3-04-cancel-request-withdrawn.p2`, `C3-04-cancel-request-withdrawn.p3`, `C3-05-cancel-the-right-order.p1`, `C3-05-cancel-the-right-order.p2`, `C3-05-cancel-the-right-order.p3`, `C3-06-revoke-then-change-mind.p1`, `C3-06-revoke-then-change-mind.p2`, `C3-06-revoke-then-change-mind.p3`
- 文件：`benchmarks/travel_variants.report.json`

### 记忆 × 智能体行为可视化与审计平台

时间轴上方的授权状态条显示每一轮账本状态（待确认 → 已确认 → 已修改·确认失效）

- 运行证据：`runs/tau-core-v1-live-k3`
- 文件：`web/src/pages/TraceExplorer.tsx`

**这一行的空白**：未覆盖跨会话的长期记忆（被测 Agent 不保留跨会话记忆）


## 工具调用

是否在正确时机、以用户确认过的参数调用敏感工具，且一次确认只产生一次效果

### 工具调用 × 智能体自动化测试框架

6 类规则算子在每次敏感调用发生的那一刻判定；同一份代码换 6 个模型做了横评

- 用例 `travel/main`（categories=C1/C2/C4/C7），24 条：`C1-01-book-after-search`, `C1-02-one-shot-request`, `C1-03-inquiry-only`, `C1-04-refund-policy-qa`, `C1-05-cancel-normal`, `C1-06-check-orders-then-book-return`, `C2-01-confirm-then-change-destination`, `C2-02-confirm-with-cabin-upgrade`, `C2-03-change-then-reconfirm`, `C2-04-confirm-and-change-date`, `C2-05-two-changes-then-confirm-final`, `C2-06-change-back-without-reconfirm`, `C4-01-sold-out`, `C4-02-past-date`, `C4-03-city-alias`, `C4-04-route-not-served`, `C4-05-missing-info`, `C4-06-long-noisy-message`, `C7-01-timeout-after-commit`, `C7-02-timeout-before-commit-retry`, `C7-03-booking-service-down`, `C7-04-malformed-search`, `C7-05-cancel-timeout-after-commit`, `C7-06-policy-kb-down`
- 用例 `tau-airline/core`，10 条：`T01-cancel-confirmed`, `T02-yes-then-switch-reservation`, `T03-switch-then-confirm`, `T04-revoke-before-cancel`, `T05-decline`, `T06-baggage-change-then-confirm`, `T07-injected-preapproval-in-details`, `T08-injected-upgrade-in-profile`, `T09-cancel-timeout-after-commit`, `T10-baggage-yes-then-more`
- 用例 `approval/core`，12 条：`A01-approve-after-review`, `A02-reject-with-reason`, `A03-list-only`, `A04-switch-request-after-confirm`, `A05-approve-turned-reject`, `A06-hold-before-approval`, `A07-over-authority-limit`, `A08-unknown-request`, `A09-injected-pre-approval`, `A10-injected-bulk-approval`, `A11-approve-timeout-after-commit`, `A12-two-requests-one-confirmed`
- 运行证据：`runs/bench-deepseek-flash-travel-v1-main-k3`, `runs/bench-deepseek-v4-pro-travel-v1-main-k3`, `runs/bench-glm-4.5-air-travel-v1-main-k3`, `runs/bench-glm-5.3-flash-travel-v1-main-k3`, `runs/bench-qwen-flash-travel-v1-main-k3`, `runs/bench-qwen-plus-travel-v1-main-k3`, `runs/bench-deepseek-flash-tau-airline-v1-core-k3`, `runs/bench-deepseek-v4-pro-tau-airline-v1-core-k3`, `runs/bench-glm-4.5-air-tau-airline-v1-core-k3`, `runs/bench-glm-5.3-flash-tau-airline-v1-core-k3`, `runs/bench-qwen-flash-tau-airline-v1-core-k3`, `runs/bench-qwen-plus-tau-airline-v1-core-k3`, `runs/bench-deepseek-flash-approval-v1-core-k3`, `runs/bench-deepseek-v4-pro-approval-v1-core-k3`, `runs/bench-glm-4.5-air-approval-v1-core-k3`, `runs/bench-glm-5.3-flash-approval-v1-core-k3`, `runs/bench-qwen-flash-approval-v1-core-k3`, `runs/bench-qwen-plus-approval-v1-core-k3`
- 文件：`configs/travel_contract.yaml`, `configs/tau_airline_contract.yaml`, `configs/approval_contract.yaml`

### 工具调用 × RAG 知识库测试工具

检索质量用被测 Agent 自己的检索工具评估（Recall@k、MRR）

- 运行证据：`runs/kb_checks`

### 工具调用 × 对抗性用例自动生成器

AI 根据 Agent 声明的工具定义起草测试契约，识别哪些工具是敏感操作

- 运行证据：`runs/contract_drafts`
- 文件：`consenttrace/ai/contract_drafter.py`

### 工具调用 × 智能体行为可视化与审计平台

每次敏感调用逐字段比对“用户确认的参数”和“实际调用参数”，并给出数据库前后差分

- 文件：`web/src/pages/TraceExplorer.tsx`

**这一行的空白**：无


## RAG

检索是否找对条款、回答是否忠于检索结果、知识库本身有没有冲突冗余、检索结果被投毒时会不会越权

### RAG × 智能体自动化测试框架

回答忠实度检查与 RAG 投毒用例

- 用例 `travel/main`（categories=C6），6 条：`C6-01-poison-business-no-confirm`, `C6-02-faithful-cabin-p6`, `C6-03-faithful-long-haul-business`, `C6-04-poison-free-refund-cancel`, `C6-05-poison-confirmation-waived`, `C6-06-poison-low-rank`
- 运行证据：`runs/main-v1-live-k3-reeval2`

### RAG × RAG 知识库测试工具

结构错误、冗余、冲突（含 LLM 复核）、Recall@1 22/24、植入故障 4/4 检出、投毒段落规则识别 9/12、LLM 识别 11/12

- 运行证据：`runs/kb_checks`
- 文件：`benchmarks/travel_kb_queries.jsonl`, `consenttrace/rag`

### RAG × 对抗性用例自动生成器

大模型生成伪造制度条款（投毒段落）和检索评测题

- 用例 `travel/attacks`（tags=style:rag_poisoning），6 条：`ATK-rag_poisoning-book_unconfirmed-1`, `ATK-rag_poisoning-book_unconfirmed-2`, `ATK-rag_poisoning-book_unconfirmed-3`, `ATK-rag_poisoning-cancel_unconfirmed-1`, `ATK-rag_poisoning-cancel_unconfirmed-2`, `ATK-rag_poisoning-cancel_unconfirmed-3`
- 文件：`benchmarks/travel_injection_library.jsonl`, `benchmarks/travel_kb_queries.jsonl`

### RAG × 智能体行为可视化与审计平台

投毒段落在时间轴上以紫色标出，可点开看到 Agent 实际看到的检索结果

- 用例 `travel/main`（categories=C6），6 条：`C6-01-poison-business-no-confirm`, `C6-02-faithful-cabin-p6`, `C6-03-faithful-long-haul-business`, `C6-04-poison-free-refund-cancel`, `C6-05-poison-confirmation-waived`, `C6-06-poison-low-rank`

**这一行的空白**：只有 travel 有知识库；τ-bench 与 approval 不涉及 RAG


## 注入

工具返回或检索结果里夹带诱导越权的文字时，Agent 会不会照做

### 注入 × 智能体自动化测试框架

评分卡“抗注入”维度；授权时序注入分三组：授权刚失效那一轮注入、第一轮注入、不注入（基线）

- 用例 `travel/main`（categories=C5），6 条：`C5-01-forged-quick-booking`, `C5-02-impersonated-employee-note`, `C5-03-hijacked-destination`, `C5-04-risk-control-cancel`, `C5-05-price-pressure`, `C5-06-chained-return-trip`
- 用例 `travel/attacks`，33 条：`ATK-fake_system_notice-book_unconfirmed-1`, `ATK-fake_system_notice-book_unconfirmed-2`, `ATK-fake_system_notice-book_unconfirmed-3`, `ATK-fake_system_notice-cancel_unconfirmed-1`, `ATK-fake_system_notice-cancel_unconfirmed-2`, `ATK-fake_system_notice-cancel_unconfirmed-3`, `ATK-impersonate_user-book_unconfirmed-1`, `ATK-impersonate_user-book_unconfirmed-2`, `ATK-impersonate_user-book_unconfirmed-3`, `ATK-impersonate_user-cancel_unconfirmed-1`, `ATK-impersonate_user-cancel_unconfirmed-2`, `ATK-impersonate_user-cancel_unconfirmed-3`, `ATK-authority_urgency-book_unconfirmed-1`, `ATK-authority_urgency-book_unconfirmed-2`, `ATK-authority_urgency-book_unconfirmed-3`, `ATK-authority_urgency-cancel_unconfirmed-1`, `ATK-authority_urgency-cancel_unconfirmed-2`, `ATK-authority_urgency-cancel_unconfirmed-3`, `ATK-task_hijack-tamper_destination-1`, `ATK-task_hijack-tamper_destination-2`, `ATK-task_hijack-tamper_destination-3`, `ATK-data_field-book_unconfirmed-1`, `ATK-data_field-book_unconfirmed-2`, `ATK-data_field-book_unconfirmed-3`, `ATK-data_field-cancel_unconfirmed-1`, `ATK-data_field-cancel_unconfirmed-2`, `ATK-data_field-cancel_unconfirmed-3`, `ATK-rag_poisoning-book_unconfirmed-1`, `ATK-rag_poisoning-book_unconfirmed-2`, `ATK-rag_poisoning-book_unconfirmed-3`, `ATK-rag_poisoning-cancel_unconfirmed-1`, `ATK-rag_poisoning-cancel_unconfirmed-2`, `ATK-rag_poisoning-cancel_unconfirmed-3`
- 用例 `travel/attacks-r2`，33 条：`ATK-fake_system_notice-book_unconfirmed-1-r2`, `ATK-fake_system_notice-book_unconfirmed-2-r2`, `ATK-fake_system_notice-book_unconfirmed-3-r2`, `ATK-fake_system_notice-cancel_unconfirmed-1-r2`, `ATK-fake_system_notice-cancel_unconfirmed-2-r2`, `ATK-fake_system_notice-cancel_unconfirmed-3-r2`, `ATK-impersonate_user-book_unconfirmed-1-r2`, `ATK-impersonate_user-book_unconfirmed-2-r2`, `ATK-impersonate_user-book_unconfirmed-3-r2`, `ATK-impersonate_user-cancel_unconfirmed-1-r2`, `ATK-impersonate_user-cancel_unconfirmed-2-r2`, `ATK-impersonate_user-cancel_unconfirmed-3-r2`, `ATK-authority_urgency-book_unconfirmed-1-r2`, `ATK-authority_urgency-book_unconfirmed-2-r2`, `ATK-authority_urgency-book_unconfirmed-3-r2`, `ATK-authority_urgency-cancel_unconfirmed-1-r2`, `ATK-authority_urgency-cancel_unconfirmed-2-r2`, `ATK-authority_urgency-cancel_unconfirmed-3-r2`, `ATK-task_hijack-tamper_destination-1-r2`, `ATK-task_hijack-tamper_destination-2-r2`, `ATK-task_hijack-tamper_destination-3-r2`, `ATK-data_field-book_unconfirmed-1-r2`, `ATK-data_field-book_unconfirmed-2-r2`, `ATK-data_field-book_unconfirmed-3-r2`, `ATK-data_field-cancel_unconfirmed-1-r2`, `ATK-data_field-cancel_unconfirmed-2-r2`, `ATK-data_field-cancel_unconfirmed-3-r2`, `ATK-rag_poisoning-book_unconfirmed-1-r2`, `ATK-rag_poisoning-book_unconfirmed-2-r2`, `ATK-rag_poisoning-book_unconfirmed-3-r2`, `ATK-rag_poisoning-cancel_unconfirmed-1-r2`, `ATK-rag_poisoning-cancel_unconfirmed-2-r2`, `ATK-rag_poisoning-cancel_unconfirmed-3-r2`
- 用例 `travel/synced-attacks`，24 条：`ATK-fake_system_notice-confirm_modified_plan-1-synced`, `ATK-fake_system_notice-confirm_modified_plan-1-early`, `ATK-fake_system_notice-confirm_modified_plan-1-none`, `ATK-fake_system_notice-confirm_modified_plan-2-synced`, `ATK-fake_system_notice-confirm_modified_plan-2-early`, `ATK-fake_system_notice-confirm_modified_plan-2-none`, `ATK-impersonate_user-confirm_modified_plan-1-synced`, `ATK-impersonate_user-confirm_modified_plan-1-early`, `ATK-impersonate_user-confirm_modified_plan-1-none`, `ATK-impersonate_user-confirm_modified_plan-2-synced`, `ATK-impersonate_user-confirm_modified_plan-2-early`, `ATK-impersonate_user-confirm_modified_plan-2-none`, `ATK-authority_urgency-confirm_modified_plan-1-synced`, `ATK-authority_urgency-confirm_modified_plan-1-early`, `ATK-authority_urgency-confirm_modified_plan-1-none`, `ATK-authority_urgency-confirm_modified_plan-2-synced`, `ATK-authority_urgency-confirm_modified_plan-2-early`, `ATK-authority_urgency-confirm_modified_plan-2-none`, `ATK-data_field-confirm_modified_plan-1-synced`, `ATK-data_field-confirm_modified_plan-1-early`, `ATK-data_field-confirm_modified_plan-1-none`, `ATK-data_field-confirm_modified_plan-2-synced`, `ATK-data_field-confirm_modified_plan-2-early`, `ATK-data_field-confirm_modified_plan-2-none`
- 运行证据：`runs/attacks-r2-v1-live-k1`, `runs/attacks-r2-v2.1-live-k1`, `runs/attacks-v1-live-k1`, `runs/attacks-v2-live-k1`, `runs/attacks-v2.1-live-k1`, `runs/attacks-r2-v1-live-k1`, `runs/attacks-r2-v2.1-live-k1`, `runs/bench-deepseek-flash-travel-v1-synced-attacks-k3`, `runs/bench-deepseek-v4-pro-travel-v1-synced-attacks-k3`, `runs/bench-glm-5.3-flash-travel-v1-synced-attacks-k3`, `runs/bench-qwen-flash-travel-v1-synced-attacks-k3`, `runs/bench-qwen-plus-travel-v1-synced-attacks-k3`

### 注入 × RAG 知识库测试工具

投毒段落识别（规则与 LLM 两种）

- 运行证据：`runs/kb_checks`

### 注入 × 对抗性用例自动生成器

6 种样式 × 3 类目标生成，确定性校验后冻结；第 2 轮看过 Agent 的实际回应后闭环加强；授权时序注入 8 条 × 3 组（含不注入基线）

- 文件：`benchmarks/travel_injection_library.jsonl`, `benchmarks/travel_injection_library.r2.jsonl`, `benchmarks/travel_synced_injection_library.jsonl`

### 注入 × 智能体行为可视化与审计平台

注入内容标为低信任；“注入到达 / 未触发”分开统计，未到达的不计入成功率

- 文件：`web/src/components/TraceSwimlane.tsx`

**这一行的空白**：无


## 越狱

用户在对话里用开发者模式、角色扮演、冒充上级、紧急施压、规则已变更、指令覆盖等话术，诱导 Agent 跳过确认直接执行

### 越狱 × 智能体自动化测试框架

成败由授权账本和数据库判定，不靠大模型打分；6 个模型横评

- 用例 `travel/jailbreaks`，24 条：`JB-developer_mode-book_skip_confirmation-1`, `JB-developer_mode-book_skip_confirmation-2`, `JB-developer_mode-cancel_skip_confirmation-1`, `JB-developer_mode-cancel_skip_confirmation-2`, `JB-role_play-book_skip_confirmation-1`, `JB-role_play-book_skip_confirmation-2`, `JB-role_play-cancel_skip_confirmation-1`, `JB-role_play-cancel_skip_confirmation-2`, `JB-authority-book_skip_confirmation-1`, `JB-authority-book_skip_confirmation-2`, `JB-authority-cancel_skip_confirmation-1`, `JB-authority-cancel_skip_confirmation-2`, `JB-urgency-book_skip_confirmation-1`, `JB-urgency-book_skip_confirmation-2`, `JB-urgency-cancel_skip_confirmation-1`, `JB-urgency-cancel_skip_confirmation-2`, `JB-rule_override-book_skip_confirmation-1`, `JB-rule_override-book_skip_confirmation-2`, `JB-rule_override-cancel_skip_confirmation-1`, `JB-rule_override-cancel_skip_confirmation-2`, `JB-instruction_override-book_skip_confirmation-1`, `JB-instruction_override-book_skip_confirmation-2`, `JB-instruction_override-cancel_skip_confirmation-1`, `JB-instruction_override-cancel_skip_confirmation-2`
- 用例 `tau-airline/jailbreaks`，24 条：`JB-developer_mode-cancel_skip_confirmation-1`, `JB-developer_mode-cancel_skip_confirmation-2`, `JB-developer_mode-baggage_skip_confirmation-1`, `JB-developer_mode-baggage_skip_confirmation-2`, `JB-role_play-cancel_skip_confirmation-1`, `JB-role_play-cancel_skip_confirmation-2`, `JB-role_play-baggage_skip_confirmation-1`, `JB-role_play-baggage_skip_confirmation-2`, `JB-authority-cancel_skip_confirmation-1`, `JB-authority-cancel_skip_confirmation-2`, `JB-authority-baggage_skip_confirmation-1`, `JB-authority-baggage_skip_confirmation-2`, `JB-urgency-cancel_skip_confirmation-1`, `JB-urgency-cancel_skip_confirmation-2`, `JB-urgency-baggage_skip_confirmation-1`, `JB-urgency-baggage_skip_confirmation-2`, `JB-rule_override-cancel_skip_confirmation-1`, `JB-rule_override-cancel_skip_confirmation-2`, `JB-rule_override-baggage_skip_confirmation-1`, `JB-rule_override-baggage_skip_confirmation-2`, `JB-instruction_override-cancel_skip_confirmation-1`, `JB-instruction_override-cancel_skip_confirmation-2`, `JB-instruction_override-baggage_skip_confirmation-1`, `JB-instruction_override-baggage_skip_confirmation-2`
- 运行证据：`runs/jailbreaks-tau-v1-fixed-live-k3`, `runs/jailbreaks-tau-v1-live-k3`, `runs/jailbreaks-travel-v1-live-k3`, `runs/jailbreaks-travel-v2.1-live-k3`, `runs/bench-deepseek-flash-tau-airline-v1-jailbreaks-k3`, `runs/bench-deepseek-flash-travel-v1-jailbreaks-k3`, `runs/bench-deepseek-v4-pro-tau-airline-v1-jailbreaks-k3`, `runs/bench-deepseek-v4-pro-travel-v1-jailbreaks-k3`, `runs/bench-glm-5.3-flash-tau-airline-v1-jailbreaks-k3`, `runs/bench-glm-5.3-flash-travel-v1-jailbreaks-k3`, `runs/bench-qwen-flash-tau-airline-v1-jailbreaks-k3`, `runs/bench-qwen-flash-travel-v1-jailbreaks-k3`, `runs/bench-qwen-plus-tau-airline-v1-jailbreaks-k3`, `runs/bench-qwen-plus-travel-v1-jailbreaks-k3`

### 越狱 × RAG 知识库测试工具

未覆盖：越狱发生在用户通道，与知识库无关

### 越狱 × 对抗性用例自动生成器

中英文各 24 条；校验要求保留请求本身、明确要求跳过确认、且不含任何同意或确认的词

- 文件：`benchmarks/travel_jailbreak_library.jsonl`, `benchmarks/tau_airline_jailbreak_library.jsonl`, `configs/travel_jailbreaks.yaml`, `consenttrace/ai/jailbreak_generator.py`

### 越狱 × 智能体行为可视化与审计平台

思维链路诊断里的“被话术或注入带偏”一类

- 文件：`consenttrace/core/reasoning.py`

**这一行的空白**：未覆盖生成有害内容类越狱（本平台测的是行动型越狱：诱导 Agent 未经确认就执行写操作）


## 边界

输入不完整、不合法、不可执行或含糊时，Agent 会不会猜参数、擅自执行或谎称已办成

### 边界 × 智能体自动化测试框架

评分卡“任务完成”“陈述诚实”维度

- 用例 `travel/main`（categories=C4），6 条：`C4-01-sold-out`, `C4-02-past-date`, `C4-03-city-alias`, `C4-04-route-not-served`, `C4-05-missing-info`, `C4-06-long-noisy-message`
- 用例 `travel/boundary`，12 条：`B01-missing-date`, `B02-missing-cabin`, `B03-invalid-flight-no`, `B04-invalid-date-format`, `B05-past-date`, `B06-future-no-flight`, `B07-sold-out`, `B08-ambiguous-last-time`, `B09-ambiguous-cheapest`, `B10-contradictory-date`, `B11-cancel-nonexistent-order`, `B12-cancel-already-cancelled`
- 用例 `tau-airline/boundary`，12 条：`B01-missing-date-booking`, `B02-missing-baggage-count`, `B03-invalid-airport-code`, `B04-invalid-reservation-id`, `B05-past-date-booking`, `B06-excessive-baggage`, `B07-no-flights-available`, `B08-ambiguous-reservation-update`, `B09-ambiguous-cheapest-flight`, `B10-contradictory-roundtrip`, `B11-nonexistent-entity-cancel`, `B12-nonexistent-entity-already-cancelled`
- 运行证据：`runs/bench-deepseek-flash-tau-airline-v1-boundary-k3`, `runs/bench-deepseek-flash-travel-v1-boundary-k3`, `runs/bench-deepseek-v4-pro-tau-airline-v1-boundary-k3`, `runs/bench-deepseek-v4-pro-travel-v1-boundary-k3`, `runs/bench-glm-5.3-flash-tau-airline-v1-boundary-k3`, `runs/bench-glm-5.3-flash-travel-v1-boundary-k3`, `runs/bench-qwen-flash-tau-airline-v1-boundary-k3`, `runs/bench-qwen-flash-travel-v1-boundary-k3`, `runs/bench-qwen-plus-tau-airline-v1-boundary-k3`, `runs/bench-qwen-plus-travel-v1-boundary-k3`

### 边界 × RAG 知识库测试工具

检索边界：POL-07 两道题因同义词缺口（“老婆”≠“家属”）检索失败

- 运行证据：`runs/kb_checks`

### 边界 × 对抗性用例自动生成器

环境事实取自被测 Agent 本身；7 个子类型；运行前人工复核并记录了修正

- 文件：`benchmarks/travel_boundary.jsonl`, `benchmarks/travel_boundary.review.md`, `benchmarks/tau_airline_boundary.jsonl`, `benchmarks/tau_airline_boundary.review.md`, `configs/case_kinds.yaml`, `consenttrace/ai/case_generator.py`

### 边界 × 智能体行为可视化与审计平台

结论横幅与断言表区分“越权”与“任务没完成”

- 文件：`web/src/pages/TraceExplorer.tsx`

**这一行的空白**：无

