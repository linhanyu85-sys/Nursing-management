import React, { useEffect, useState } from "react";
import { Alert, StyleSheet, Text } from "react-native";

import { api } from "../api/endpoints";
import { PatientCaseSelector } from "../components/PatientCaseSelector";
import { ActionButton, AnimatedBlock, ProgressTimeline, ScreenShell, StatusPill, SurfaceCard } from "../components/ui";
import { useAppStore } from "../store/appStore";
import { colors } from "../theme";
import { formatAiText } from "../utils/text";
import type { GenerateProgressStep, HandoverResult } from "../types";

const BASE_PROGRESS: GenerateProgressStep[] = [
  { key: "context", label: "读取患者上下文", done: false, active: true },
  { key: "change", label: "比较本班与上班变化", done: false, active: false },
  { key: "summary", label: "生成交班摘要与优先级", done: false, active: false },
  { key: "archive", label: "写入可追溯历史", done: false, active: false },
];

export function HandoverScreen() {
  const departmentId = useAppStore((state) => state.selectedDepartmentId);
  const selectedPatient = useAppStore((state) => state.selectedPatient);
  const setSelectedPatient = useAppStore((state) => state.setSelectedPatient);
  const [result, setResult] = useState<HandoverResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<GenerateProgressStep[]>([]);

  useEffect(() => {
    setResult(null);
    setError("");
    setProgress([]);
  }, [selectedPatient?.id]);

  const onGenerate = async () => {
    if (!selectedPatient?.id) {
      Alert.alert("请先选择病例", "请先在病例列表中点击患者，再生成该病例交班摘要。");
      return;
    }

    setError("");
    setLoading(true);
    setProgress(BASE_PROGRESS.map((item, idx) => ({ ...item, done: false, active: idx === 0 })));

    let stepIndex = 0;
    const timer = setInterval(() => {
      stepIndex += 1;
      setProgress((prev) =>
        prev.map((item, idx) => ({
          ...item,
          done: idx < stepIndex,
          active: idx === stepIndex,
        }))
      );
    }, 500);

    try {
      const data = await api.generateHandover(selectedPatient.id);
      setResult({
        ...data,
        summary: formatAiText(data.summary),
        next_shift_priorities: (data.next_shift_priorities || []).map((item) => formatAiText(item)),
      });
      setProgress((prev) => prev.map((item) => ({ ...item, done: true, active: false })));
    } catch {
      setError("交班生成失败，请检查后端服务状态。");
    } finally {
      clearInterval(timer);
      setLoading(false);
    }
  };

  return (
    <ScreenShell
      title="每日交班"
      subtitle={selectedPatient ? `当前病例：${selectedPatient.full_name}（${selectedPatient.id}）` : "请先选择病例"}
      rightNode={<StatusPill text={loading ? "生成中" : "待生成"} tone={loading ? "warning" : "info"} />}
    >
      <AnimatedBlock delay={40}>
        <PatientCaseSelector
          departmentId={departmentId}
          selectedPatient={selectedPatient}
          onSelectPatient={setSelectedPatient}
        />
      </AnimatedBlock>

      {!selectedPatient ? (
        <AnimatedBlock delay={90}>
          <SurfaceCard>
            <Text style={styles.content}>请先在病例列表中选择患者，再生成该病例交班摘要。</Text>
          </SurfaceCard>
        </AnimatedBlock>
      ) : (
        <>
          <AnimatedBlock delay={90}>
            <SurfaceCard>
              <ActionButton label="生成当前病例交班摘要" onPress={onGenerate} />
            </SurfaceCard>
          </AnimatedBlock>

          {progress.length > 0 ? (
            <AnimatedBlock delay={120}>
              <ProgressTimeline title="交班生成进度" steps={progress} />
            </AnimatedBlock>
          ) : null}

          {error ? (
            <AnimatedBlock delay={130}>
              <SurfaceCard>
                <Text style={styles.error}>{error}</Text>
              </SurfaceCard>
            </AnimatedBlock>
          ) : null}

          {result ? (
            <AnimatedBlock delay={170}>
              <SurfaceCard>
                <Text style={styles.label}>交班摘要</Text>
                <Text style={styles.content}>{formatAiText(result.summary)}</Text>
                <Text style={styles.label}>下班次优先事项</Text>
                {result.next_shift_priorities.map((item) => (
                  <Text key={item} style={styles.content}>
                    • {formatAiText(item)}
                  </Text>
                ))}
              </SurfaceCard>
            </AnimatedBlock>
          ) : null}
        </>
      )}
    </ScreenShell>
  );
}

const styles = StyleSheet.create({
  error: { color: colors.danger },
  label: { color: colors.primary, fontWeight: "700" },
  content: { color: colors.text, lineHeight: 20 },
});
