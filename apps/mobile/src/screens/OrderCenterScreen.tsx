import React, { useEffect, useMemo, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { api, getApiErrorMessage } from "../api/endpoints";
import { PatientCaseSelector } from "../components/PatientCaseSelector";
import { ActionButton, AnimatedBlock, ScreenShell, StatusPill, SurfaceCard } from "../components/ui";
import { useAppStore } from "../store/appStore";
import { colors, radius } from "../theme";
import type { ClinicalOrder, OrderListOut } from "../types";

function dueText(order: ClinicalOrder): string {
  if (!order.due_at) {
    return "无到时限制";
  }
  const now = Date.now();
  const due = new Date(order.due_at).getTime();
  const diffMinutes = Math.round((due - now) / 60000);
  if (Number.isNaN(diffMinutes)) {
    return "时间格式异常";
  }
  if (diffMinutes < 0) {
    return `已超时 ${Math.abs(diffMinutes)} 分钟`;
  }
  if (diffMinutes === 0) {
    return "即将到时";
  }
  return `${diffMinutes} 分钟后到时`;
}

function statusTone(status: string): "info" | "success" | "warning" | "danger" {
  if (status === "executed") {
    return "success";
  }
  if (status === "exception" || status === "cancelled") {
    return "danger";
  }
  if (status === "checked") {
    return "info";
  }
  return "warning";
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: "待执行",
    checked: "已核对",
    executed: "已执行",
    exception: "异常上报",
    cancelled: "已取消",
  };
  return map[status] || status;
}

export function OrderCenterScreen() {
  const user = useAppStore((state) => state.user);
  const departmentId = useAppStore((state) => state.selectedDepartmentId);
  const selectedPatient = useAppStore((state) => state.selectedPatient);
  const setSelectedPatient = useAppStore((state) => state.setSelectedPatient);
  const patientId = selectedPatient?.id;

  const [orderList, setOrderList] = useState<OrderListOut | null>(null);
  const [history, setHistory] = useState<ClinicalOrder[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [requestTitle, setRequestTitle] = useState("请求医生核对医嘱优先级");
  const [requestDetail, setRequestDetail] = useState("请根据当前生命体征与尿量变化，协助复核医嘱执行顺序。\n重点：先处理P1，再处理P2。\n触发条件：若收缩压<90或尿量持续下降，请升级处理。");

  const stats = useMemo(
    () =>
      orderList?.stats || {
        pending: 0,
        due_30m: 0,
        overdue: 0,
        high_alert: 0,
      },
    [orderList]
  );

  const loadOrders = async () => {
    if (!patientId) {
      setOrderList(null);
      setHistory([]);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [listData, historyData] = await Promise.all([
        api.getPatientOrders(patientId),
        api.getPatientOrderHistory(patientId, 100),
      ]);
      setOrderList(listData);
      setHistory(historyData);
    } catch (err) {
      setError(getApiErrorMessage(err, "医嘱加载失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadOrders();
  }, [patientId]);

  const ensureUser = () => {
    if (!user?.id) {
      Alert.alert("请先登录", "登录后才能进行医嘱核对与执行留痕。");
      return false;
    }
    return true;
  };

  const doDoubleCheck = async (order: ClinicalOrder) => {
    if (!ensureUser()) {
      return;
    }
    try {
      await api.doubleCheckOrder(order.id, user!.id, "移动端双人核对");
      await loadOrders();
      Alert.alert("核对完成", `已完成：${order.title}`);
    } catch (err) {
      Alert.alert("核对失败", getApiErrorMessage(err));
    }
  };

  const doExecute = async (order: ClinicalOrder) => {
    if (!ensureUser()) {
      return;
    }
    Alert.alert("确认执行医嘱", `确认已执行：${order.title}？`, [
      { text: "取消", style: "cancel" },
      {
        text: "确认执行",
        onPress: async () => {
          try {
            await api.executeOrder(order.id, user!.id, "移动端执行留痕");
            await loadOrders();
            Alert.alert("执行成功", "已写入执行记录与历史。");
          } catch (err) {
            Alert.alert("执行失败", getApiErrorMessage(err));
          }
        },
      },
    ]);
  };

  const reportException = async (order: ClinicalOrder, reason: string) => {
    if (!ensureUser()) {
      return;
    }
    try {
      await api.reportOrderException(order.id, user!.id, reason);
      await loadOrders();
      Alert.alert("异常已上报", reason);
    } catch (err) {
      Alert.alert("上报失败", getApiErrorMessage(err));
    }
  };

  const openExceptionChoices = (order: ClinicalOrder) => {
    Alert.alert("异常上报", "请选择最接近的原因：", [
      { text: "患者拒绝", onPress: () => reportException(order, "患者拒绝执行") },
      { text: "静脉通路异常", onPress: () => reportException(order, "静脉通路异常，需重新建立") },
      { text: "药品/耗材暂缺", onPress: () => reportException(order, "药品或耗材暂缺") },
      { text: "取消", style: "cancel" },
    ]);
  };

  const createOrderRequest = async () => {
    if (!patientId) {
      Alert.alert("请先选择病例", "先选病例再发起医嘱请求。");
      return;
    }
    if (!ensureUser()) {
      return;
    }

    const title = requestTitle.trim();
    const details = requestDetail.trim();
    if (!title || !details) {
      Alert.alert("请完善请求内容", "标题和详情都不能为空。");
      return;
    }

    try {
      const order = await api.createOrderRequest({
        patientId,
        requestedBy: user!.id,
        title,
        details,
        priority: "P2",
      });
      await loadOrders();
      Alert.alert("已创建请求", `请求单号：${order.order_no}`);
    } catch (err) {
      Alert.alert("创建失败", getApiErrorMessage(err));
    }
  };

  return (
    <ScreenShell
      title="医嘱执行中心"
      subtitle={selectedPatient ? `当前病例：${selectedPatient.full_name}（${selectedPatient.id}）` : "请先选择病例"}
      rightNode={<StatusPill text={loading ? "同步中" : "实时闭环"} tone={loading ? "warning" : "success"} />}
    >
      <AnimatedBlock delay={40}>
        <PatientCaseSelector
          departmentId={departmentId}
          selectedPatient={selectedPatient}
          onSelectPatient={setSelectedPatient}
        />
      </AnimatedBlock>

      {!selectedPatient ? (
        <AnimatedBlock delay={80}>
          <SurfaceCard>
            <Text style={styles.tip}>先选病例，再进入该病例的医嘱核对、执行留痕和异常上报流程。</Text>
          </SurfaceCard>
        </AnimatedBlock>
      ) : (
        <>
          <AnimatedBlock delay={80}>
            <SurfaceCard>
              <Text style={styles.sectionTitle}>临床痛点聚焦</Text>
              <Text style={styles.tip}>1. 高频漏执行：到时提醒 + 超时高亮</Text>
              <Text style={styles.tip}>2. 高警示药风险：双人核对强提醒</Text>
              <Text style={styles.tip}>3. 追责困难：执行与异常全留痕可追溯</Text>
            </SurfaceCard>
          </AnimatedBlock>

          <AnimatedBlock delay={110}>
            <SurfaceCard>
              <Text style={styles.sectionTitle}>AI 生成医嘱请求（发送给医生核对）</Text>
              <TextInput
                style={styles.input}
                value={requestTitle}
                onChangeText={setRequestTitle}
                placeholder="请求标题"
                placeholderTextColor={colors.subText}
              />
              <TextInput
                style={[styles.input, styles.multiInput]}
                value={requestDetail}
                onChangeText={setRequestDetail}
                multiline
                placeholder="请求详情"
                placeholderTextColor={colors.subText}
              />
              <ActionButton label="生成并写入医嘱请求" onPress={createOrderRequest} />
            </SurfaceCard>
          </AnimatedBlock>

          <AnimatedBlock delay={120}>
            <SurfaceCard>
              <View style={styles.statsRow}>
                <View style={styles.statBlock}>
                  <Text style={styles.statLabel}>待执行</Text>
                  <Text style={styles.statValue}>{stats.pending}</Text>
                </View>
                <View style={styles.statBlock}>
                  <Text style={styles.statLabel}>30分钟到时</Text>
                  <Text style={[styles.statValue, { color: "#b45309" }]}>{stats.due_30m}</Text>
                </View>
                <View style={styles.statBlock}>
                  <Text style={styles.statLabel}>超时</Text>
                  <Text style={[styles.statValue, { color: colors.danger }]}>{stats.overdue}</Text>
                </View>
                <View style={styles.statBlock}>
                  <Text style={styles.statLabel}>高警示</Text>
                  <Text style={[styles.statValue, { color: "#7c3aed" }]}>{stats.high_alert}</Text>
                </View>
              </View>
            </SurfaceCard>
          </AnimatedBlock>

          {error ? (
            <AnimatedBlock delay={130}>
              <SurfaceCard>
                <Text style={styles.error}>{error}</Text>
              </SurfaceCard>
            </AnimatedBlock>
          ) : null}

          <AnimatedBlock delay={160}>
            <SurfaceCard>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionTitle}>当前医嘱</Text>
                <ActionButton label="刷新医嘱" onPress={loadOrders} variant="secondary" />
              </View>
              {(orderList?.orders || []).length === 0 ? <Text style={styles.tip}>当前无待处理医嘱。</Text> : null}
              {(orderList?.orders || []).map((order) => (
                <View key={order.id} style={styles.orderCard}>
                  <View style={styles.rowBetween}>
                    <Text style={styles.orderTitle}>
                      {order.priority} · {order.title}
                    </Text>
                    <StatusPill text={statusLabel(order.status)} tone={statusTone(order.status)} />
                  </View>

                  <Text style={styles.meta}>医嘱号：{order.order_no}</Text>
                  <Text style={styles.meta}>到时：{dueText(order)}</Text>
                  <Text style={styles.meta}>内容：{order.instruction}</Text>
                  {order.risk_hints.length > 0 ? (
                    <Text style={styles.meta}>风险提示：{order.risk_hints.join(" / ")}</Text>
                  ) : null}

                  <View style={styles.actionRow}>
                    {order.requires_double_check && !order.check_by && (order.status === "pending" || order.status === "checked") ? (
                      <ActionButton label="双人核对" onPress={() => doDoubleCheck(order)} variant="secondary" style={styles.flexBtn} />
                    ) : null}
                    {order.status === "pending" || order.status === "checked" ? (
                      <ActionButton label="执行并留痕" onPress={() => doExecute(order)} style={styles.flexBtn} />
                    ) : null}
                    <ActionButton label="异常上报" onPress={() => openExceptionChoices(order)} variant="danger" style={styles.flexBtn} />
                  </View>
                </View>
              ))}
            </SurfaceCard>
          </AnimatedBlock>

          <AnimatedBlock delay={200}>
            <SurfaceCard>
              <Text style={styles.sectionTitle}>医嘱历史记录（可追溯）</Text>
              {history.length === 0 ? <Text style={styles.tip}>暂无历史记录</Text> : null}
              {history.map((item) => (
                <Pressable key={`hist-${item.id}-${item.status}`} style={styles.historyCard}>
                  <Text style={styles.orderTitle}>
                    {item.priority} · {item.title}
                  </Text>
                  <Text style={styles.meta}>结果：{statusLabel(item.status)}</Text>
                  <Text style={styles.meta}>
                    执行人：{item.executed_by || item.check_by || "-"} · {new Date(item.executed_at || item.check_at || item.ordered_at || "").toLocaleString()}
                  </Text>
                  {item.execution_note ? <Text style={styles.meta}>备注：{item.execution_note}</Text> : null}
                  {item.exception_reason ? <Text style={styles.meta}>异常：{item.exception_reason}</Text> : null}
                </Pressable>
              ))}
            </SurfaceCard>
          </AnimatedBlock>
        </>
      )}
    </ScreenShell>
  );
}

const styles = StyleSheet.create({
  sectionTitle: {
    color: colors.text,
    fontWeight: "700",
    fontSize: 16,
  },
  tip: {
    color: colors.subText,
    lineHeight: 21,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    color: colors.text,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  multiInput: {
    minHeight: 92,
    textAlignVertical: "top",
  },
  statsRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 8,
  },
  statBlock: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: "#f9fbff",
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  statLabel: {
    color: colors.subText,
    fontSize: 12,
  },
  statValue: {
    marginTop: 4,
    color: colors.primary,
    fontWeight: "800",
    fontSize: 20,
  },
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  orderCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: 10,
    gap: 6,
  },
  orderTitle: {
    color: colors.text,
    fontWeight: "700",
    fontSize: 15,
  },
  meta: {
    color: colors.subText,
    lineHeight: 19,
    fontSize: 12.5,
  },
  actionRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 4,
  },
  flexBtn: {
    flex: 1,
    minWidth: 112,
  },
  historyCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: 10,
    gap: 4,
  },
  error: {
    color: colors.danger,
    fontWeight: "600",
  },
});
