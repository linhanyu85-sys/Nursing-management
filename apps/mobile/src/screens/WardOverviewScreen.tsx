import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { useFocusEffect, useNavigation } from "@react-navigation/native";
import type { NativeStackNavigationProp } from "@react-navigation/native-stack";

import { api, getApiErrorMessage } from "../api/endpoints";
import { subscribeWardBeds } from "../api/realtime";
import { ActionButton, AnimatedBlock, ScreenShell, StatusPill, SurfaceCard } from "../components/ui";
import type { RootStackParamList } from "../navigation/RootNavigator";
import { useAppStore } from "../store/appStore";
import { colors, spacing } from "../theme";
import type { BedOverview } from "../types";

export function WardOverviewScreen() {
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const departmentId = useAppStore((state) => state.selectedDepartmentId);
  const setSelectedPatient = useAppStore((state) => state.setSelectedPatient);
  const [loading, setLoading] = useState(true);
  const [beds, setBeds] = useState<BedOverview[]>([]);
  const [searchKeyword, setSearchKeyword] = useState("");
  const [loadError, setLoadError] = useState("");
  const [streamStatus, setStreamStatus] = useState("未连接");
  const [lastPushAt, setLastPushAt] = useState("-");

  const filteredBeds = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase();
    if (!keyword) {
      return beds;
    }
    return beds.filter((bed) => {
      const haystack = [
        bed.bed_no,
        bed.patient_name || "",
        bed.current_patient_id || "",
        ...(Array.isArray(bed.risk_tags) ? bed.risk_tags : []),
        ...(Array.isArray(bed.pending_tasks) ? bed.pending_tasks : []),
        bed.latest_document_sync || "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [beds, searchKeyword]);

  const loadBeds = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await api.getWardBeds(departmentId);
      setBeds(data);
    } catch (error) {
      setBeds([]);
      setStreamStatus("连接异常");
      setLoadError(getApiErrorMessage(error, "病区数据加载失败，请检查后台网关。"));
    } finally {
      setLoading(false);
    }
  };

  useFocusEffect(
    useCallback(() => {
      loadBeds();
    }, [departmentId])
  );

  useEffect(() => {
    const unsubscribe = subscribeWardBeds(
      departmentId,
      (payload) => {
        if (payload?.type === "ward_beds_update" && Array.isArray(payload?.data)) {
          setBeds(payload.data);
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
  }, [departmentId]);

  return (
    <ScreenShell
      title="病区床位总览"
      subtitle={`实时状态：${streamStatus} · 最近推送 ${lastPushAt}`}
      rightNode={<StatusPill text={streamStatus} tone={streamStatus === "连接异常" ? "danger" : "success"} />}
    >
      <AnimatedBlock delay={30}>
        <SurfaceCard>
          <View style={styles.searchRow}>
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
          <Text style={styles.searchMeta}>
            全部床位 {beds.length} 张 · 匹配 {filteredBeds.length} 张
          </Text>
        </SurfaceCard>
      </AnimatedBlock>

      {loading ? (
        <View style={styles.loadingWrap}>
          <ActivityIndicator color={colors.primary} />
          <Text style={styles.loadingText}>正在加载病区数据...</Text>
        </View>
      ) : filteredBeds.length === 0 ? (
        <SurfaceCard>
          <Text style={styles.loadingText}>没有搜索到匹配床位，请换关键词再试。</Text>
        </SurfaceCard>
      ) : (
        filteredBeds.map((bed, idx) => (
          <AnimatedBlock key={bed.id} delay={60 + idx * 40}>
            <Pressable
              style={styles.pressableReset}
              onPress={async () => {
                if (!bed.current_patient_id) {
                  return;
                }
                try {
                  const patient = await api.getPatient(bed.current_patient_id);
                  setSelectedPatient(patient);
                  navigation.navigate("PatientDetail", { patientId: bed.current_patient_id });
                } catch (error) {
                  Alert.alert("病例加载失败", getApiErrorMessage(error, "患者详情暂时不可用，请稍后再试。"));
                }
              }}
            >
              <SurfaceCard>
                <View style={styles.cardTop}>
                  <Text style={styles.bedNo}>{bed.bed_no}床</Text>
                  <Text style={styles.status}>{bed.status}</Text>
                </View>
                <Text style={styles.patient}>{bed.patient_name || "空床"}</Text>
                <Text style={styles.meta}>风险：{bed.risk_tags.join(" / ") || "-"}</Text>
                <Text style={styles.meta}>待处理：{bed.pending_tasks.join(" / ") || "-"}</Text>
                {bed.latest_document_sync ? <Text style={styles.docSync}>{bed.latest_document_sync}</Text> : null}
              </SurfaceCard>
            </Pressable>
          </AnimatedBlock>
        ))
      )}

      {!loading && loadError ? (
        <AnimatedBlock delay={110}>
          <SurfaceCard>
            <Text style={styles.errorText}>{loadError}</Text>
          </SurfaceCard>
        </AnimatedBlock>
      ) : null}
    </ScreenShell>
  );
}

const styles = StyleSheet.create({
  searchRow: {
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
  searchMeta: {
    color: colors.subText,
    fontSize: 12,
  },
  loadingWrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
  },
  loadingText: {
    color: colors.subText,
  },
  errorText: {
    color: colors.danger,
    lineHeight: 20,
    fontWeight: "600",
  },
  pressableReset: {
    borderRadius: 16,
  },
  cardTop: { flexDirection: "row", justifyContent: "space-between" },
  bedNo: { color: colors.primary, fontWeight: "700", fontSize: 18 },
  status: { color: colors.subText },
  patient: { color: colors.text, fontSize: 16, fontWeight: "600" },
  meta: { color: colors.subText, fontSize: 13 },
  docSync: { color: colors.primary, fontSize: 12.5, fontWeight: "600" },
});
