# mobile

护士用的移动端 App，React Native + Expo 开发。

## 当前功能

- 登录/注册（账号存本地 JSON，服务重启不会丢）
- 首页：患者选择、语音/文字输入、历史记录查看
- 病区总览：床位状态、患者列表
- 患者详情：基本信息、医嘱执行、历史对话
- 医嘱执行中心：待执行列表、双人核对、执行记录、异常上报
- 交班：生成交班草稿（需确认后提交）
- 推荐：语音/文字/附件输入，获取处置建议（带人工复核标记）
- 文书：选择模板生成草稿，支持审核和提交
- 协作：通知值班医生

## 技术

- React Native 0.72 + Expo
- React Navigation 6
- Zustand（状态管理）
- Axios（HTTP 请求）

## 运行

```powershell
cd apps\mobile
npm install
npm run start
```

按 `w` 打开 Web 预览，或用手机 Expo Go App 扫码。

## 配置

在 `apps/mobile/.env` 或系统环境变量：

```
EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
EXPO_PUBLIC_API_MOCK=true    # true=用 mock 数据，false=连真实后端
```

建议先开 mock 看界面，确认后端启动后再关 mock。

## 已知问题

- 中文路径可能导致 Metro bundler 报错，建议项目放在纯英文目录
- 真机调试需要手机和电脑在同一局域网
- 部分组件依赖 expo-vector-icons，如果图标不显示尝试 `npx expo install expo-vector-icons`
