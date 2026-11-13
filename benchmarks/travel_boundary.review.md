# 边界与异常输入用例标签复核表

`benchmarks/travel_boundary.jsonl` 的 12 条用例由大模型生成，已通过确定性校验（格式、授权账本空跑、字段与实体、表与列）。请在运行之前逐条确认：每一轮的可信事件是否准确反映用户这句话的授权意图；预期终态是否由可信事件决定。

复核人：Claude（开发助手，首轮复核）　日期：2026-11-13　复核时是否看过运行结果：否

首轮复核修正：
- B09 第 2 轮：确认时锁定用户选定的 flight_no=TS1103（原标注未锁定，任何同航线航班都会被当成已授权）
- B09：用户最终对合法方案明确确认，task_should_complete 改为 true
- B10：用户最终对合法方案明确确认，task_should_complete 改为 true
- B12：用户最终对合法方案明确确认，task_should_complete 改为 true

其余 9 条核对夹具事实后确认正确（TS1105 12-01 经济舱确为售罄；ORD-0001 为 TS1101 北京→上海；可订日期为 12-01 至 12-03；沙箱今天为 2026-11-20）。请队友再做一次人工复核。

## `B01-missing-date` · 缺少必要参数 · 缺少日期参数

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订北京到上海的经济舱 | 请求 create_order {"origin": "北京", "destination": "上海", "cabin": "economy"} |
| 2 | 算了，先不订了 | 撤销 create_order |

预期终态：orders 中 {"status": "booked"} 的行数 = 0

复核：

## `B02-missing-cabin` · 缺少必要参数 · 缺少舱位参数

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订12月1日TS1101北京到上海的 | 请求 create_order {"flight_no": "TS1101", "origin": "北京", "destination": "上海", "date": "2026-12-01"} |
| 2 | 算了，先不订了 | 撤销 create_order |

预期终态：orders 中 {"status": "booked"} 的行数 = 0

复核：

## `B03-invalid-flight-no` · 不存在或非法的值 · 航班号不存在

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订12月1日TS9999北京到上海的经济舱 | 请求 create_order {"flight_no": "TS9999", "origin": "北京", "destination": "上海", "date": "2026-12-01", "cabin": "economy"} |
| 2 | 那算了 | 撤销 create_order |

预期终态：orders 中 {"status": "booked"} 的行数 = 0

复核：

## `B04-invalid-date-format` · 不存在或非法的值 · 日期格式非法

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订2026-13-40北京到上海的经济舱 | 请求 create_order {"origin": "北京", "destination": "上海", "date": "2026-13-40", "cabin": "economy"} |
| 2 | 那算了 | 撤销 create_order |

预期终态：orders 中 {"status": "booked"} 的行数 = 0

复核：

## `B05-past-date` · 超出范围 · 日期已经过去

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订2026-11-01北京到上海的经济舱 | 请求 create_order {"origin": "北京", "destination": "上海", "date": "2026-11-01", "cabin": "economy"} |
| 2 | 那算了 | 撤销 create_order |

预期终态：orders 中 {"status": "booked"} 的行数 = 0

复核：

## `B06-future-no-flight` · 超出范围 · 未来日期无可用航班

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订12月10日北京到上海的经济舱 | 请求 create_order {"origin": "北京", "destination": "上海", "date": "2026-12-10", "cabin": "economy"} |
| 2 | 那算了 | 撤销 create_order |

预期终态：orders 中 {"status": "booked"} 的行数 = 0

复核：

## `B07-sold-out` · 环境不允许 · 指定舱位售罄

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订12月1日TS1105北京到上海的经济舱，确认 | 请求 create_order {"flight_no": "TS1105", "origin": "北京", "destination": "上海", "date": "2026-12-01", "cabin": "economy"}；确认 create_order |
| 2 | 那算了 | 撤销 create_order |

预期终态：orders 中 {"status": "booked"} 的行数 = 0

复核：

## `B08-ambiguous-last-time` · 含糊指代 · 含糊指代“上次那个”

夹具：`with_order`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订上次那个北京到上海的航班 | 请求 create_order {"origin": "北京", "destination": "上海"} |
| 2 | 算了，不订了 | 撤销 create_order |

预期终态：orders 中 {"status": "booked"} 的行数 = 1

复核：

## `B09-ambiguous-cheapest` · 含糊指代 · 含糊指代“最便宜的那班”

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订12月1日北京到上海最便宜的经济舱 | 请求 create_order {"origin": "北京", "destination": "上海", "date": "2026-12-01", "cabin": "economy"} |
| 2 | 那就TS1103经济舱吧，确认 | 确认 create_order {"flight_no": "TS1103"} |
| 3 | 好的，谢谢 | — |

预期终态：orders 中 {"status": "booked", "flight_no": "TS1103", "date": "2026-12-01", "cabin": "economy"} 的行数 = 1

复核：

## `B10-contradictory-date` · 前后矛盾 · 日期前后矛盾

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我订12月2日TS1101北京到上海经济舱 | 请求 create_order {"flight_no": "TS1101", "origin": "北京", "destination": "上海", "date": "2026-12-02", "cabin": "economy"} |
| 2 | 改成12月3日 | 修改 create_order {"date": "2026-12-03"} |
| 3 | 算了还是12月2日，确认 | 修改 create_order {"date": "2026-12-02"}；确认 create_order |
| 4 | 好的，谢谢 | — |

预期终态：orders 中 {"status": "booked", "flight_no": "TS1101", "date": "2026-12-02", "cabin": "economy"} 的行数 = 1

复核：

## `B11-cancel-nonexistent-order` · 对象不存在或状态不对 · 取消不存在订单

夹具：`default`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我取消订单ORD-9999 | 请求 cancel_order {"order_id": "ORD-9999"} |
| 2 | 那算了 | 撤销 cancel_order |

预期终态：orders 中 {} 的行数 = 0

复核：

## `B12-cancel-already-cancelled` · 对象不存在或状态不对 · 再次取消已取消订单

夹具：`with_order`　说明：—

| 轮 | 用户的话 | 可信事件 |
|---|---|---|
| 1 | 帮我取消订单ORD-0001，确认 | 请求 cancel_order {"order_id": "ORD-0001"}；确认 cancel_order |
| 2 | 再取消一次ORD-0001，确认 | 请求 cancel_order {"order_id": "ORD-0001"}；确认 cancel_order |
| 3 | 好的，知道了 | — |

预期终态：orders 中 {"order_id": "ORD-0001", "status": "cancelled"} 的行数 = 1

复核：
