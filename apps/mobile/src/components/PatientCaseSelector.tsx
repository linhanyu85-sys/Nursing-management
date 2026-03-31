import React, { useEffect, useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { api, getApiErrorMessage } from "../api/endpoints";
import { ActionButton, StatusPill, SurfaceCard } from "./ui";
import { colors } from "../theme";
import type { BedOverview, Patient } from "../types";

type Props = {
  departmentId: string;
  selectedPatient: Patient | null;
  onSelectPatient: (patient: Patient) => void;
  onCasesUpdated?: (cases: BedOverview[]) => void;
  embedded?: boolean;
};

export function PatientCaseSelector({
  departmentId,
  selectedPatient,
  onSelectPatient,
  onCasesUpdated,
  embedded = false,
}: Props) {
  const [beds, setBeds] = useState<BedOverview[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [selectingPatientId, setSelectingPatientId] = useState<string>("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [expandedPatientIds, setExpandedPatientIds] = useState<string[]>([]);

  const cases = useMemo(() => beds.filter((item) => item.current_patient_id), [beds]);
  const filteredCases = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase();
    if (!keyword) {
      return cases;
    }
    return cases.filter((item) => {
      const haystack = [
        item.bed_no,
        item.patient_name || "",
        item.current_patient_id || "",
        ...(Array.isArray(item.risk_tags) ? item.risk_tags : []),
        ...(Array.isArray(item.pending_tasks) ? item.pending_tasks : []),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [cases, searchKeyword]);

  const loadCases = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await api.getWardBeds(departmentId);
      const list = Array.isArray(data) ? data : [];
      setBeds(list);
      onCasesUpdated?.(list);
    } catch {
      setBeds([]);
      setLoadError("病例加载失败，请检查网络或网关服务。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCases();
  }, [departmentId]);

  useEffect(() => {
    if (!selectedPatient?.id) {
      return;
    }
    setExpandedPatientIds((prev) => (prev.includes(selectedPatient.id) ? prev : [...prev, selectedPatient.id]));
  }, [selectedPatient?.id]);

  const toggleExpand = (patientId: string) => {
    if (!patientId) {
      return;
    }
    setExpandedPatientIds((prev) =>
      prev.includes(patientId) ? prev.filter((item) => item !== patientId) : [...prev, patientId]
    );
  };

  const choosePatient = async (patientId: string) => {
    if (!patientId) {
      return;
    }
    setSelectingPatientId(patientId);
    try {
      setLoadError("");
      const patient = await api.getPatient(patientId);
      onSelectPatient(patient);
    } catch (error) {
      setLoadError(getApiErrorMessage(error, "病例详情加载失败，请检查后端连接。"));
    } finally {
      setSelectingPatientId("");
    }
  };

  const content = (
    <>
      <View style={styles.header}>
        <Text style={styles.title}>{embedded ? "选择病例" : "病例列表（先选病例，再进入 AI Agent）"}</Text>
        <ActionButton label={embedded ? "刷新" : "刷新病例"} onPress={loadCases} variant="secondary" />
      </View>

      {selectedPatient ? (
        <View style={styles.selectedWrap}>
          <StatusPill text="当前病例" tone="success" />
          <Text style={styles.selectedText}>
            {selectedPatient.full_name}（ID: {selectedPatient.id}）
          </Text>
        </View>
      ) : (
        <Text style={styles.emptyTip}>{embedded ? "先从下方选择一个病例。" : "尚未选择病例，请先点击下方患者卡片。"}</Text>
      )}

      <View style={styles.searchWrap}>
        <TextInput
          value={searchKeyword}
          onChangeText={setSearchKeyword}
          style={styles.searchInput}
          placeholder="搜索床号/姓名/风险/待办"
          placeholderTextColor={colors.subText}
        />
        <ActionButton
          label="清空"
          onPress={() => setSearchKeyword("")}
          variant="secondary"
          style={styles.clearBtn}
          disabled={!searchKeyword}
        />
      </View>
      <Text style={styles.meta}>
        全部病例 {cases.length} 例 · 匹配 {filteredCases.length} 例
      </Text>

      {loading ? <Text style={styles.meta}>正在加载病例...</Text> : null}
      {!loading && loadError ? <Text style={styles.error}>{loadError}</Text> : null}
      {!loading && cases.length === 0 ? <Text style={styles.meta}>当前病区暂无在床患者。</Text> : null}
      {!loading && cases.length > 0 && filteredCases.length === 0 ? (
        <Text style={styles.meta}>没有搜索到匹配病例，请换关键词再试。</Text>
      ) : null}

      {filteredCases.map((item) => {
        const patientId = item.current_patient_id || "";
        const active = selectedPatient?.id === patientId;
        const selecting = selectingPatientId === patientId;
        const expanded = expandedPatientIds.includes(patientId);
        const riskText = item.risk_tags.join(" / ") || "-";
        const taskText = item.pending_tasks.join(" / ") || "-";
        return (
          <Pressable
            key={item.id}
            onPress={() => choosePatient(patientId)}
            style={[styles.caseCard, active && styles.caseCardActive]}
          >
            <View style={styles.caseTop}>
              <Text style={styles.caseName}>
                {item.bed_no}床 · {item.patient_name || patientId}
              </Text>
              <View style={styles.caseActions}>
                {!embedded ? (
                  <Pressable onPress={() => toggleExpand(patientId)} hitSlop={8}>
                    <Text style={styles.caseToggle}>{expanded ? "收起" : "展开"}</Text>
                  </Pressable>
                ) : null}
                <Text style={styles.caseStatus}>{active ? "已选中" : selecting ? "切换中..." : embedded ? "选择" : "点击切换"}</Text>
              </View>
            </View>
            {embedded ? (
              <Text style={styles.caseMeta}>
                风险 {item.risk_tags.length} 项 · 待处理 {item.pending_tasks.length} 项
                {item.latest_document_sync ? ` · 文书 ${item.latest_document_sync}` : ""}
              </Text>
            ) : expanded ? (
              <>
                <Text style={styles.caseMeta}>风险：{riskText}</Text>
                <Text style={styles.caseMeta}>待处理：{taskText}</Text>
                {item.latest_document_sync ? <Text style={styles.caseMeta}>文书：{item.latest_document_sync}</Text> : null}
              </>
            ) : (
              <Text style={styles.caseMeta}>点击“展开”查看风险、待处理和文书同步信息</Text>
            )}
          </Pressable>
        );
      })}
    </>
  );

  if (embedded) {
    return <View style={styles.embeddedShell}>{content}</View>;
  }

  return (
    <SurfaceCard>
      {content}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  embeddedShell: {
    gap: 10,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  title: {
    color: colors.text,
    fontWeight: "700",
    fontSize: 15,
    flex: 1,
  },
  selectedWrap: {
    gap: 4,
  },
  searchWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  searchInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    backgroundColor: colors.card,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.text,
  },
  clearBtn: {
    minWidth: 72,
  },
  selectedText: {
    color: colors.primary,
    fontWeight: "700",
  },
  emptyTip: {
    color: colors.warning,
    fontWeight: "600",
  },
  meta: {
    color: colors.subText,
    fontSize: 12,
  },
  caseCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 10,
    gap: 4,
  },
  caseCardActive: {
    borderColor: colors.primary,
    backgroundColor: "#edf3ff",
  },
  caseTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  caseActions: {
    alignItems: "flex-end",
    gap: 4,
  },
  caseName: {
    color: colors.text,
    fontWeight: "700",
  },
  caseToggle: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: "700",
  },
  caseStatus: {
    color: colors.subText,
    fontSize: 12,
  },
  caseMeta: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  error: {
    color: colors.danger,
    fontWeight: "600",
    fontSize: 12.5,
  },
});
