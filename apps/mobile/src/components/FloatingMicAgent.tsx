import React, { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from "react-native";
import { Audio } from "expo-av";
import * as FileSystem from "expo-file-system";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api } from "../api/endpoints";
import { useAppStore } from "../store/appStore";
import { colors, radius, shadows } from "../theme";
import { formatAiText } from "../utils/text";

function extractBedNo(input: string): string | undefined {
  const text = input || "";
  const direct = text.match(/(\d{1,3})\s*(床|号床|床位)/);
  if (direct?.[1]) {
    return direct[1];
  }
  const fallback = text.match(/^\s*(\d{1,3})(?=\D|$)/);
  return fallback?.[1];
}

function isInvalidTranscription(text: string, provider: string): boolean {
  if (!text) {
    return true;
  }
  const normalized = text.trim();
  const blockedPhrases = [
    "语音转写失败",
    "手动输入",
    "语音已接收",
    "请补充床号",
    "未识别到有效语音",
  ];
  if (provider === "fallback") {
    return true;
  }
  return blockedPhrases.some((item) => normalized.includes(item));
}

async function uriToBase64(uri: string): Promise<string> {
  try {
    return await FileSystem.readAsStringAsync(uri, { encoding: FileSystem.EncodingType.Base64 });
  } catch {
    const response = await fetch(uri);
    const blob = await response.blob();
    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = String(reader.result || "");
        const parts = result.split(",");
        resolve(parts.length > 1 ? parts[1] : "");
      };
      reader.onerror = () => reject(new Error("read_file_failed"));
      reader.readAsDataURL(blob);
    });
  }
}

export function FloatingMicAgent() {
  const user = useAppStore((state) => state.user);
  const selectedDepartmentId = useAppStore((state) => state.selectedDepartmentId);
  const selectedPatient = useAppStore((state) => state.selectedPatient);
  const insets = useSafeAreaInsets();

  const [recording, setRecording] = useState<Audio.Recording | null>(null);
  const [recordingOn, setRecordingOn] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [busy, setBusy] = useState(false);
  const [lastText, setLastText] = useState("");
  const [lastSummary, setLastSummary] = useState("");
  const [statusText, setStatusText] = useState("点击麦克风可直接语音提问");
  const [collapsed, setCollapsed] = useState(true);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
      if (recording) {
        recording.stopAndUnloadAsync().catch(() => null);
      }
    };
  }, [recording]);

  const startRecording = async () => {
    try {
      const permission = await Audio.requestPermissionsAsync();
      if (!permission.granted) {
        Alert.alert("麦克风权限被拒绝");
        return;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
        shouldDuckAndroid: true,
        playThroughEarpieceAndroid: false,
        staysActiveInBackground: false,
      });

      const { recording: nextRecording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );

      setRecording(nextRecording);
      setRecordingOn(true);
      setRecordSeconds(0);
      setLastText("");
      setStatusText("正在录音，请说话。再次点击可结束。");
      setCollapsed(false);

      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
      timerRef.current = setInterval(() => {
        setRecordSeconds((prev) => prev + 1);
      }, 1000);
    } catch {
      Alert.alert("录音启动失败");
    }
  };

  const runAgentByVoice = async (voiceText: string) => {
    const bedNo = extractBedNo(voiceText);
    let patientId = selectedPatient?.id;

    try {
      if (!patientId && bedNo) {
        const beds = await api.getWardBeds(selectedDepartmentId);
        const target = beds.find((item) => String(item.bed_no) === String(bedNo));
        patientId = target?.current_patient_id || patientId;
      }

      const response = await api.runAiChat({
        mode: "agent_cluster",
        clusterProfile: "nursing_default_cluster",
        userInput: voiceText,
        patientId,
        bedNo,
        departmentId: selectedDepartmentId,
        requestedBy: user?.id,
      });
      setLastSummary(formatAiText(response.summary));
      setStatusText("AI Agent 处理完成。");
    } catch {
      setLastSummary("");
      setStatusText("AI Agent 调用失败，请检查后端服务。");
      Alert.alert("AI Agent 调用失败", "请检查后端服务是否启动。");
    }
  };

  const stopRecordingAndRun = async () => {
    if (!recording) {
      return;
    }

    setBusy(true);
    try {
      await recording.stopAndUnloadAsync();
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: false,
        playsInSilentModeIOS: true,
      });

      const uri = recording.getURI();
      let audioBase64: string | undefined;
      if (uri) {
        audioBase64 = await uriToBase64(uri);
      }

      const transcribe = await api.transcribe({ audioBase64 });
      const provider = String(transcribe?.provider || "");
      const voiceText = String(transcribe?.text || "").trim();

      if (isInvalidTranscription(voiceText, provider)) {
        setLastText("");
        setLastSummary("");
        setStatusText("当前未拿到有效语音文本，请重试并靠近麦克风，或先手动输入。");
        return;
      }

      setLastText(voiceText);
      setStatusText(`语音已转文字（${provider || "asr"}），正在触发 AI Agent...`);
      await runAgentByVoice(voiceText);
    } catch {
      setLastText("");
      setLastSummary("");
      setStatusText("语音处理失败，请重试。");
      Alert.alert("语音处理失败", "请检查麦克风权限和 ASR 服务状态。");
    } finally {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
      setRecordSeconds(0);
      setRecording(null);
      setRecordingOn(false);
      setBusy(false);
    }
  };

  const onPressMain = async () => {
    if (busy) {
      return;
    }
    if (recordingOn) {
      await stopRecordingAndRun();
      return;
    }
    await startRecording();
  };

  return (
    <>
      {!collapsed ? (
        <View style={[styles.panel, { bottom: insets.bottom + 198 }]}>
          <View style={styles.panelHeader}>
            <Text style={styles.panelTitle}>悬浮语音助手</Text>
            <Pressable onPress={() => setCollapsed(true)}>
              <MaterialCommunityIcons name="close" size={18} color={colors.subText} />
            </Pressable>
          </View>
          <Text style={styles.panelText}>{statusText}</Text>
          {recordingOn ? <Text style={styles.panelMeta}>录音中 {recordSeconds}s</Text> : null}
          {lastText ? <Text style={styles.panelMeta}>识别：{lastText}</Text> : null}
          {lastSummary ? <Text style={styles.panelMeta}>结果：{lastSummary.slice(0, 70)}...</Text> : null}
        </View>
      ) : null}

      <Pressable
        style={[styles.fab, { bottom: insets.bottom + 128 }, recordingOn && styles.fabRecording]}
        onPress={onPressMain}
      >
        {busy ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <MaterialCommunityIcons
            name={recordingOn ? "microphone-off" : "microphone"}
            size={26}
            color="#ffffff"
          />
        )}
      </Pressable>
    </>
  );
}

const styles = StyleSheet.create({
  fab: {
    position: "absolute",
    right: 20,
    width: 58,
    height: 58,
    borderRadius: 29,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.primary,
    ...shadows.floatingFab,
    zIndex: 90,
  },
  fabRecording: {
    backgroundColor: colors.danger,
  },
  panel: {
    position: "absolute",
    right: 16,
    width: 260,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#ffffff",
    padding: 10,
    gap: 6,
    ...shadows.floatingPanel,
    zIndex: 89,
  },
  panelHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  panelTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
  },
  panelText: {
    color: colors.text,
    fontSize: 12.5,
    lineHeight: 18,
  },
  panelMeta: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 17,
  },
});
