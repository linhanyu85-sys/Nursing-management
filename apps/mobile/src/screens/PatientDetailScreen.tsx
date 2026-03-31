import React, { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, Text, View } from "react-native";
import { NativeStackScreenProps } from "@react-navigation/native-stack";

import { api, getApiErrorMessage } from "../api/endpoints";
import { subscribePatientContext } from "../api/realtime";
import { AnimatedBlock, ScreenShell, StatusPill, SurfaceCard } from "../components/ui";
import type { RootStackParamList } from "../navigation/RootNavigator";
import { colors } from "../theme";
import type { OrderListOut, Patient, PatientContext } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "PatientDetail">;

export function PatientDetailScreen({ route }: Props) {
  const { patientId } = route.params;
  const [patient, setPatient] = useState<Patient | null>(null);
  const [context, setContext] = useState<PatientContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [streamStatus, setStreamStatus] = useState("未连接");
  const [lastPushAt, setLastPushAt] = useState<string>("-");
  const [orderList, setOrderList] = useState<OrderListOut | null>(null);

  useEffect(() => {
    const run = async () => {
      setLoading(true);
      setError("");
      try {
        const [patientData, contextData, orderData] = await Promise.all([
          api.getPatient(patientId),
          api.getPatientContext(patientId),
          api.getPatientOrders(patientId).catch(() => null),
        ]);
        setPatient(patientData);
        setContext(contextData);
        setOrderList(orderData);
      } catch (loadError) {
        setPatient(null);
        setContext(null);
        setOrderList(null);
        setError(getApiErrorMessage(loadError, "患者详情加载失败，请检查后端连接。"));
      } finally {
        setLoading(false);
      }
    };
    run();
  }, [patientId]);

  useEffect(() => {
    const unsubscribe = subscribePatientContext(
      patientId,
      (payload) => {
        if (payload?.type === "patient_context_update" && payload?.data) {
          setContext(payload.data);
          setLastPushAt(new Date().toLocaleTimeString());
          setStreamStatus("已连接");
        } else if (payload?.type === "heartbeat") {
          setStreamStatus("心跳正常");
          setLastPushAt(new Date().toLocaleTimeString());
        }
      },
      () => setStreamStatus("连接异常")
    );
    return unsubscribe;
  }, [patientId]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <ScreenShell
      title={patient?.full_name || "患者详情"}
      subtitle={`${patient?.gender || "-"} · ${patient?.age || "-"}岁 · 血型 ${patient?.blood_type || "-"}`}
      rightNode={<StatusPill text={streamStatus} tone={streamStatus === "连接异常" ? "danger" : "info"} />}
    >
      {error ? (
        <AnimatedBlock delay={20}>
          <SurfaceCard>
            <Text style={styles.error}>{error}</Text>
          </SurfaceCard>
        </AnimatedBlock>
      ) : null}

      <AnimatedBlock delay={40}>
        <SurfaceCard>
          <Text style={styles.info}>病案号：{patient?.mrn}</Text>
          <Text style={styles.info}>过敏史：{patient?.allergy_info || "无"}</Text>
          <Text style={styles.info}>最近推送：{lastPushAt}</Text>
          {context?.latest_document_sync ? <Text style={styles.docSync}>{context.latest_document_sync}</Text> : null}
        </SurfaceCard>
      </AnimatedBlock>

      <AnimatedBlock delay={90}>
        <Section title="诊断">
          {(context?.diagnoses || []).map((item) => (
            <Text key={item} style={styles.item}>
              • {item}
            </Text>
          ))}
        </Section>
      </AnimatedBlock>

      <AnimatedBlock delay={130}>
        <Section title="风险标签">
          {(context?.risk_tags || []).map((item) => (
            <Text key={item} style={styles.item}>
              • {item}
            </Text>
          ))}
        </Section>
      </AnimatedBlock>

      <AnimatedBlock delay={170}>
        <Section title="待处理任务">
          {(context?.pending_tasks || []).map((item) => (
            <Text key={item} style={styles.item}>
              • {item}
            </Text>
          ))}
        </Section>
      </AnimatedBlock>

      <AnimatedBlock delay={210}>
        <Section title="最新观察值">
          {(context?.latest_observations || []).map((item, idx) => (
            <Text key={`${item.name}-${idx}`} style={styles.item}>
              • {item.name}：{item.value}
              {item.abnormal_flag ? ` (${item.abnormal_flag})` : ""}
            </Text>
          ))}
        </Section>
      </AnimatedBlock>

      {(context?.latest_document_status || context?.latest_document_excerpt) ? (
        <AnimatedBlock delay={250}>
          <Section title="文书同步状态">
            {context.latest_document_status ? <Text style={styles.item}>状态：{context.latest_document_status}</Text> : null}
            {context.latest_document_type ? <Text style={styles.item}>类型：{context.latest_document_type}</Text> : null}
            {context.latest_document_updated_at ? (
              <Text style={styles.item}>更新时间：{context.latest_document_updated_at}</Text>
            ) : null}
            {context.latest_document_excerpt ? <Text style={styles.item}>摘要：{context.latest_document_excerpt}</Text> : null}
          </Section>
        </AnimatedBlock>
      ) : null}

      {orderList ? (
        <AnimatedBlock delay={290}>
          <Section title="医嘱执行概览">
            <Text style={styles.item}>
              待执行：{orderList.stats.pending} · 30分钟到时：{orderList.stats.due_30m} · 超时：{orderList.stats.overdue}
            </Text>
            <Text style={styles.item}>高警示医嘱：{orderList.stats.high_alert}</Text>
            {(orderList.orders || []).slice(0, 3).map((order) => (
              <Text key={order.id} style={styles.item}>
                • {order.priority} {order.title}（{order.status}）
              </Text>
            ))}
          </Section>
        </AnimatedBlock>
      ) : null}
    </ScreenShell>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <SurfaceCard>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: colors.bg },
  sectionTitle: { color: colors.primary, fontWeight: "700" },
  info: { color: colors.subText, fontSize: 14 },
  item: { color: colors.text, lineHeight: 22 },
  docSync: { color: colors.primary, fontSize: 13, fontWeight: "600" },
  error: { color: colors.danger, lineHeight: 20, fontWeight: "600" },
});
