# Agent Workflows

## 统一输出结构
```json
{
  "summary": "",
  "findings": [],
  "recommendations": [],
  "confidence": 0.0,
  "review_required": true,
  "agent_goal": "",
  "plan": [],
  "memory": {},
  "artifacts": [],
  "next_actions": []
}
```

## 参与 Agent
- Planner Agent：任务拆解、工具选择、执行顺序规划
- Memory Agent：回看会话历史、患者事实、未闭环任务
- Intent Router Agent：识别工作流类型
- Patient Context Agent：拉取患者/病区上下文
- Recommendation Agent：生成结构化建议
- Handover Agent：生成交班草稿
- Document Agent：生成护理文书草稿
- Collaboration Agent：生成并发送协作消息
- Critic Agent：反思是否遗漏协作、留痕或升级动作
- Audit Agent：写入审计链路

## 1. 语音问询工作流
输入：
- `user_input`
- `patient_id` 或 `bed_no`

执行链：
1. Intent Router Agent 识别为 `voice_inquiry`
2. Memory Agent 回看最近上下文
3. Patient Context Agent 命中患者或病区
4. Recommendation Agent 生成摘要/重点/建议
5. Critic Agent 做安全校验

输出：
- 当前重点摘要
- 风险发现
- 待处理建议

## 2. 交班工作流
输入：
- `patient_id` 或 `department_id`
- `shift_date`
- `shift_type`

执行链：
1. 命中患者或病区上下文
2. Handover Agent 生成单人或批量交班
3. Audit Agent 留痕

输出：
- `new_changes`
- `worsening_points`
- `pending_closures`
- `next_shift_priorities`

## 3. 推荐工作流
输入：
- `patient_id`
- `question`
- `attachments[]`

执行链：
1. 命中患者上下文
2. 可选多模态附件分析
3. Recommendation Agent 输出优先级与升级条件
4. Critic Agent 检查是否需要补协作/补留痕

输出：
- 风险判断摘要
- 关键发现
- 分级建议
- 升级条件

## 4. 文书工作流
输入：
- `patient_id`
- `spoken_text`
- `document_type`

执行链：
1. Patient Context Agent 获取患者上下文
2. Document Agent 生成文书草稿
3. Audit Agent 写入留痕

输出：
- 文书草稿
- 结构化字段
- 提交前人工复核提示

## 5. 自动闭环工作流
工作流名：
- `autonomous_care`

典型输入：
- “自动跟进12床，高风险就通知医生并生成交班和护理记录”
- “盯住 8 床，如果超时医嘱还没处理就发协作消息并留痕”

执行链：
1. Planner Agent 拆解目标
2. Memory Agent 读取历史记忆
3. Patient Context Agent 建立患者状态
4. Recommendation Agent 生成临床建议
5. 根据计划自动触发：
   - Collaboration Agent
   - Handover Agent
   - Document Agent
   - 医嘱请求创建
6. Critic Agent 反思是否遗漏关键动作
7. 必要时自动补跑一轮

安全边界：
- 允许自动生成协作消息、交班草稿、文书草稿、医嘱请求
- 不允许自动执行医嘱
- 所有结果默认 `review_required=true`

输出新增字段：
- `agent_goal`
- `plan`
- `memory`
- `artifacts`
- `next_actions`
