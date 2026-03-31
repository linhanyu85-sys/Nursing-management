import React, { useEffect, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";

import { api } from "../api/endpoints";
import { PatientCaseSelector } from "../components/PatientCaseSelector";
import { VoiceTextInput } from "../components/VoiceTextInput";
import { ActionButton, AnimatedBlock, ScreenShell, StatusPill, SurfaceCard } from "../components/ui";
import type { MainTabParamList } from "../navigation/RootNavigator";
import { useAppStore } from "../store/appStore";
import { colors, radius, spacing, typography } from "../theme";
import { formatAiText } from "../utils/text";
import { speakSummaryText } from "../utils/ttsPlayer";
import type { ConversationHistoryItem } from "../types";

type Props = BottomTabScreenProps<MainTabParamList, "Home">;

export function HomeScreen({ navigation }: Props) {
  const user = useAppStore((state) => state.user);
  const departmentId = useAppStore((state) => state.selectedDepartmentId);
  const selectedPatient = useAppStore((state) => state.selectedPatient);
  const setSelectedPatient = useAppStore((state) => state.setSelectedPatient);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<string>("");
  const [ttsLoading, setTtsLoading] = useState(false);
  const [ttsHint, setTtsHint] = useState("");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [history, setHistory] = useState<ConversationHistoryItem[]>([]);

  const patientId = selectedPatient?.id;

  const loadHistory = async () => {
    if (!patientId) {
      setHistory([]);
      return;
    }
    setHistoryLoading(true);
    try {
      const items = await api.getAllHistory(patientId, 30);
      setHistory(items);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, [patientId]);

  useEffect(() => {
    setQuery("");
    setResult("");
    setTtsHint("");
  }, [patientId]);

  const runVoiceWorkflow = async () => {
    if (!patientId) {
      Alert.alert("请先选择病例", "先在病例列表中点击患者，再发起AI问询。");
      return;
    }
    const prompt = query.trim() || "12床现在最需要注意什么？";
    try {
      const data = await api.runVoiceWorkflow(prompt, patientId);
      setResult(formatAiText(data.summary || "已生成摘要"));
      await loadHistory();
    } catch {
      Alert.alert("工作流调用失败", "请确认网关和编排服务正在运行");
    }
  };

  const runTts = async () => {
    const text = result.trim();
    if (!text || ttsLoading) {
      return;
    }
    setTtsLoading(true);
    setTtsHint("正在准备语音播报...");
    try {
      const played = await speakSummaryText(text);
      setTtsHint(played.detail);
    } catch {
      setTtsHint("语音播报失败，请检查 TTS 服务或手机音量。");
      Alert.alert("语音播报失败", "请检查 TTS 服务或手机音量。");
    } finally {
      setTtsLoading(false);
    }
  };

  const cards = [
    { title: "病区总览", icon: "🏥", onPress: () => navigation.navigate("Ward") },
    { title: "医嘱执行", icon: "💊", onPress: () => navigation.navigate("Orders") },
    { title: "每日交班", icon: "🔄", onPress: () => navigation.navigate("Handover") },
    { title: "智能推荐", icon: "🧠", onPress: () => navigation.navigate("Recommendation") },
    { title: "文书中心", icon: "📝", onPress: () => navigation.navigate("Document") },
  ];

  return (
    <ScreenShell
      title={`你好，${user?.full_name || "护士"}`}
      subtitle="AI护理精细化工作台 · 语音、推荐、文书、协作一体化"
      rightNode={<StatusPill text="在线值班" tone="success" />}
    >
      <AnimatedBlock delay={50}>
        <SurfaceCard>
          <Text style={styles.sectionTitle}>快捷入口</Text>
          <View style={styles.grid}>
            {cards.map((item) => (
              <Pressable key={item.title} style={styles.quickCard} onPress={item.onPress}>
                <View style={styles.quickIcon}>
                  <Text style={styles.quickIconText}>{item.icon}</Text>
                </View>
                <Text style={styles.quickTitle}>{item.title}</Text>
              </Pressable>
            ))}
          </View>
        </SurfaceCard>
      </AnimatedBlock>

      <AnimatedBlock delay={120}>
        <PatientCaseSelector
          departmentId={departmentId}
          selectedPatient={selectedPatient}
          onSelectPatient={setSelectedPatient}
        />
      </AnimatedBlock>

      {!selectedPatient ? (
        <AnimatedBlock delay={160}>
          <SurfaceCard>
            <Text style={styles.historyMeta}>请先在上方病例列表中点选患者，再进入该病例的 AI Agent 分析。</Text>
          </SurfaceCard>
        </AnimatedBlock>
      ) : (
        <>
          <AnimatedBlock delay={160}>
            <SurfaceCard>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>语音 + 打字输入</Text>
                <StatusPill text="双模输入" />
              </View>
              <Text style={styles.historyMeta}>当前病例：{selectedPatient.full_name}（{selectedPatient.id}）</Text>
              <VoiceTextInput
                value={query}
                onChangeText={setQuery}
                onSubmit={runVoiceWorkflow}
                placeholder="请输入"
              />
            </SurfaceCard>
          </AnimatedBlock>

          {result ? (
            <AnimatedBlock delay={200}>
              <SurfaceCard style={styles.resultCard}>
                <Text style={styles.resultLabel}>当前摘要</Text>
                <Text style={styles.resultText}>{result}</Text>
                <ActionButton
                  label={ttsLoading ? "播报中..." : "语音播报当前摘要"}
                  onPress={runTts}
                  variant="secondary"
                  disabled={ttsLoading}
                />
                {ttsHint ? <Text style={styles.ttsHint}>{ttsHint}</Text> : null}
              </SurfaceCard>
            </AnimatedBlock>
          ) : null}

          <AnimatedBlock delay={240}>
            <SurfaceCard>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>对话历史记录</Text>
                <ActionButton label="刷新历史" onPress={loadHistory} variant="secondary" />
              </View>
              {historyLoading ? <Text style={styles.historyMeta}>正在刷新历史...</Text> : null}
              {!historyLoading && history.length === 0 ? <Text style={styles.historyMeta}>暂无历史记录</Text> : null}
              {history.map((item) => (
                <Pressable
                  key={`${item.source}-${item.id}`}
                  style={styles.historyItem}
                  onPress={() => {
                    if (item.user_input) {
                      setQuery(item.user_input);
                    }
                    if (item.summary) {
                      setResult(formatAiText(item.summary));
                    }
                  }}
                >
                  <Text style={styles.historyMeta}>
                    {item.workflow_type} · {new Date(item.created_at).toLocaleString()}
                  </Text>
                  <Text style={styles.historyQuestion}>问：{formatAiText(item.user_input || "（无输入）")}</Text>
                  <Text style={styles.historySummary}>答：{formatAiText(item.summary)}</Text>
                  <Text style={styles.historyPick}>点击调取这条历史</Text>
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
    ...typography.section,
    color: colors.text,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  quickCard: {
    width: "48%",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: "#f8fbff",
    paddingVertical: 14,
    paddingHorizontal: 12,
    gap: 10,
  },
  quickIcon: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#e9f1ff",
  },
  quickIconText: {
    fontSize: 16,
  },
  quickTitle: {
    color: colors.text,
    fontSize: 15.5,
    fontWeight: "700",
  },
  resultCard: { gap: spacing.md },
  resultLabel: {
    color: colors.subText,
    fontSize: 12.5,
    fontWeight: "700",
  },
  resultText: {
    color: colors.text,
    ...typography.body,
  },
  ttsHint: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  historyItem: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.xs,
  },
  historyMeta: {
    color: colors.subText,
    fontSize: 12,
  },
  historyQuestion: {
    color: colors.primary,
    fontWeight: "700",
    lineHeight: 20,
  },
  historySummary: {
    color: colors.text,
    lineHeight: 20,
  },
  historyPick: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: "700",
  },
});
