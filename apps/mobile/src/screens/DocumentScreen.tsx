import React, { useEffect, useState } from "react";
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system";

import { api } from "../api/endpoints";
import { PatientCaseSelector } from "../components/PatientCaseSelector";
import { VoiceTextInput } from "../components/VoiceTextInput";
import { ActionButton, AnimatedBlock, ProgressTimeline, ScreenShell, StatusPill, SurfaceCard } from "../components/ui";
import { useAppStore } from "../store/appStore";
import { colors, radius, spacing } from "../theme";
import type { DocumentDraft, DocumentTemplate, GenerateProgressStep } from "../types";

const DRAFT_PROGRESS_TEMPLATE: GenerateProgressStep[] = [
  { key: "context", label: "读取患者上下文", done: false, active: true },
  { key: "template", label: "载入模板并填充", done: false, active: false },
  { key: "adapt", label: "主AI格式自适应", done: false, active: false },
  { key: "save", label: "写入草稿和历史", done: false, active: false },
];

export function DocumentScreen() {
  const user = useAppStore((state) => state.user);
  const departmentId = useAppStore((state) => state.selectedDepartmentId);
  const selectedPatient = useAppStore((state) => state.selectedPatient);
  const setSelectedPatient = useAppStore((state) => state.setSelectedPatient);

  const [text, setText] = useState("");
  const [drafts, setDrafts] = useState<DocumentDraft[]>([]);
  const [history, setHistory] = useState<DocumentDraft[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [templates, setTemplates] = useState<DocumentTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [templateName, setTemplateName] = useState("护理记录模板");
  const [templateText, setTemplateText] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<GenerateProgressStep[]>([]);
  const [lastActionHint, setLastActionHint] = useState("");
  const [editingDraftId, setEditingDraftId] = useState("");
  const [templatePanelOpen, setTemplatePanelOpen] = useState(false);
  const [historyPanelOpen, setHistoryPanelOpen] = useState(false);

  const patientId = selectedPatient?.id;

  const loadDrafts = async () => {
    if (!patientId) {
      setDrafts([]);
      return;
    }
    const data = await api.listDrafts(patientId);
    setDrafts(data);
  };

  const loadTemplates = async () => {
    const data = await api.listDocumentTemplates();
    setTemplates(data);
    if (!selectedTemplateId && data.length > 0) {
      setSelectedTemplateId(data[0].id);
    }
  };

  const loadHistory = async () => {
    if (!patientId) {
      setHistory([]);
      return;
    }
    setHistoryLoading(true);
    try {
      const data = await api.listDocumentHistory(patientId, 80);
      setHistory(data);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    loadTemplates();
    loadDrafts();
    loadHistory();
  }, [patientId]);

  useEffect(() => {
    setText("");
    setError("");
    setProgress([]);
    setLastActionHint("");
    setEditingDraftId("");
  }, [patientId]);

  const importTemplateFromText = async () => {
    const content = templateText.trim();
    if (!content) {
      Alert.alert("请先输入模板内容");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const item = await api.importDocumentTemplate({
        name: templateName.trim() || "文本模板",
        templateText: content,
      });
      setSelectedTemplateId(item.id);
      setTemplateText("");
      await loadTemplates();
      Alert.alert("模板导入成功", `已导入：${item.name}`);
    } catch {
      setError("模板导入失败，请检查后端服务。");
    } finally {
      setLoading(false);
    }
  };

  const importTemplateFromFile = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: [
        "text/*",
        "application/json",
        "application/xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      ],
      copyToCacheDirectory: true,
      multiple: false,
    });
    if (result.canceled) {
      return;
    }

    const file = result.assets[0];
    setError("");
    setLoading(true);
    try {
      const base64 = await FileSystem.readAsStringAsync(file.uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      const item = await api.importDocumentTemplate({
        name: templateName.trim() || file.name || "文件模板",
        templateBase64: base64,
        fileName: file.name,
        mimeType: file.mimeType || undefined,
      });
      setSelectedTemplateId(item.id);
      await loadTemplates();
      Alert.alert("模板导入成功", `已导入：${item.name}`);
    } catch {
      setError("文件模板导入失败，请确认文件可读取。");
    } finally {
      setLoading(false);
    }
  };

  const createDraft = async () => {
    if (!patientId) {
      Alert.alert("请先选择病例");
      return;
    }
    setError("");
    setLoading(true);
    setProgress(DRAFT_PROGRESS_TEMPLATE.map((item, idx) => ({ ...item, done: false, active: idx === 0 })));

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
    }, 450);

    try {
      const selected = templates.find((item) => item.id === selectedTemplateId);
      const draft = await api.createDocumentDraft(patientId, text.trim(), {
        templateId: selected?.id || undefined,
        templateName: selected?.name || undefined,
      });
      setLastActionHint(`草稿已生成：${draft.id}`);
      setText("");
      setEditingDraftId("");
      await loadDrafts();
      await loadHistory();
      setProgress((prev) => prev.map((item) => ({ ...item, done: true, active: false })));
    } catch {
      setError("文书草稿生成失败。");
    } finally {
      clearInterval(timer);
      setLoading(false);
    }
  };

  const startEditDraft = (draft: DocumentDraft) => {
    setEditingDraftId(draft.id);
    setText(draft.draft_text);
    setLastActionHint(`正在编辑草稿：${draft.id}`);
  };

  const saveEditedDraft = async () => {
    if (!editingDraftId) {
      Alert.alert("请先在草稿列表点击“编辑”");
      return;
    }
    const content = text.trim();
    if (!content) {
      Alert.alert("请输入文书内容");
      return;
    }
    setLoading(true);
    try {
      const updated = await api.updateDraft(editingDraftId, content, user?.id);
      setLastActionHint(`草稿已保存：${updated.id}`);
      await loadDrafts();
      await loadHistory();
    } catch {
      Alert.alert("保存失败", "请检查 document-service 与网关连接。");
    } finally {
      setLoading(false);
    }
  };

  const cancelEditDraft = () => {
    setEditingDraftId("");
    setText("");
    setLastActionHint("已取消编辑");
  };

  const reviewDraft = async (draftId: string) => {
    if (!user) {
      return;
    }
    await api.reviewDraft(draftId, user.id);
    await loadDrafts();
    await loadHistory();
  };

  const submitDraft = async (draftId: string) => {
    if (!user) {
      return;
    }
    await api.submitDraft(draftId, user.id);
    await loadDrafts();
    await loadHistory();
  };

  const createOrderRequestFromDraft = async (draft: DocumentDraft) => {
    if (!patientId || !user?.id) {
      Alert.alert("请先登录并选择病例");
      return;
    }
    try {
      const order = await api.createOrderRequest({
        patientId,
        requestedBy: user.id,
        title: "请医生核对文书相关医嘱",
        details: `文书草稿(${draft.id})已更新，请核对执行要点：\n${draft.draft_text.slice(0, 200)}${
          draft.draft_text.length > 200 ? "..." : ""
        }`,
        priority: "P2",
      });
      Alert.alert("已创建医嘱请求", `请求单号：${order.order_no}`);
    } catch {
      Alert.alert("创建失败", "文书已生成，但医嘱请求创建失败，请稍后重试。");
    }
  };

  return (
    <ScreenShell
      title="文书中心"
      subtitle={selectedPatient ? `病例：${selectedPatient.full_name}（${selectedPatient.id}）` : "请先选择病例"}
      rightNode={<StatusPill text={loading ? "处理中" : editingDraftId ? "编辑中" : "可新建"} tone={loading ? "warning" : "success"} />}
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
            <Text style={styles.tip}>请先在病例列表中选择患者，再进入文书生成与编辑。</Text>
          </SurfaceCard>
        </AnimatedBlock>
      ) : (
        <>
          <AnimatedBlock delay={80}>
            <View style={styles.editorHeader}>
              <Text style={styles.sectionTitle}>文书编辑区</Text>
              <StatusPill text={editingDraftId ? "当前编辑草稿" : "新建模式"} tone={editingDraftId ? "warning" : "info"} />
            </View>
            <VoiceTextInput
              value={text}
              onChangeText={setText}
              onSubmit={editingDraftId ? saveEditedDraft : createDraft}
              placeholder="请输入护理记录内容（支持语音 + 打字）"
            />
            <View style={styles.row}>
              {editingDraftId ? (
                <>
                  <ActionButton label="保存当前草稿" onPress={saveEditedDraft} style={styles.flexBtn} />
                  <ActionButton label="取消编辑" onPress={cancelEditDraft} variant="secondary" style={styles.flexBtn} />
                </>
              ) : (
                <ActionButton label="新建文书草稿" onPress={createDraft} style={styles.fullBtn} />
              )}
            </View>
            {lastActionHint ? <Text style={styles.pathText}>{lastActionHint}</Text> : null}
          </AnimatedBlock>

          {progress.length > 0 ? (
            <AnimatedBlock delay={100}>
              <ProgressTimeline title="文书生成进度" steps={progress} />
            </AnimatedBlock>
          ) : null}

          <AnimatedBlock delay={120}>
            <SurfaceCard>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionTitle}>模板管理</Text>
                <ActionButton
                  label={templatePanelOpen ? "收起" : "展开"}
                  onPress={() => setTemplatePanelOpen((prev) => !prev)}
                  variant="secondary"
                />
              </View>
              {templatePanelOpen ? (
                <>
                  <TextInput
                    style={styles.input}
                    value={templateName}
                    onChangeText={setTemplateName}
                    placeholder="模板名称"
                    placeholderTextColor={colors.subText}
                  />
                  <TextInput
                    style={[styles.input, styles.templateInput]}
                    value={templateText}
                    onChangeText={setTemplateText}
                    multiline
                    placeholder="支持占位符：{{patient_id}} {{bed_no}} {{diagnoses}} {{risk_tags}} {{pending_tasks}} {{spoken_text}}"
                    placeholderTextColor={colors.subText}
                  />
                  <View style={styles.row}>
                    <ActionButton label="文本导入模板" onPress={importTemplateFromText} variant="secondary" style={styles.flexBtn} />
                    <ActionButton label="文件导入模板" onPress={importTemplateFromFile} variant="secondary" style={styles.flexBtn} />
                  </View>
                  <ActionButton label="刷新模板列表" onPress={loadTemplates} variant="secondary" />
                  <View style={styles.templateList}>
                    {templates.map((item) => {
                      const active = item.id === selectedTemplateId;
                      return (
                        <Pressable
                          key={item.id}
                          style={[styles.templateTag, active && styles.templateTagActive]}
                          onPress={() => setSelectedTemplateId(item.id)}
                        >
                          <Text style={[styles.templateTagText, active && styles.templateTagTextActive]}>{item.name}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                </>
              ) : (
                <Text style={styles.tip}>模板面板已收起，点击“展开”管理模板。</Text>
              )}
            </SurfaceCard>
          </AnimatedBlock>

          {error ? (
            <AnimatedBlock delay={130}>
              <SurfaceCard>
                <Text style={styles.error}>{error}</Text>
              </SurfaceCard>
            </AnimatedBlock>
          ) : null}

          <AnimatedBlock delay={150}>
            <SurfaceCard>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionTitle}>草稿列表</Text>
                <ActionButton label="刷新草稿" onPress={loadDrafts} variant="secondary" />
              </View>
              {drafts.length === 0 ? <Text style={styles.tip}>暂无草稿</Text> : null}
              {drafts.map((draft) => (
                <View key={draft.id} style={styles.draftCard}>
                  <Text style={styles.meta}>
                    {draft.document_type} · {draft.status} · {new Date(draft.updated_at).toLocaleString()}
                  </Text>
                  <Text style={styles.meta}>模板：{String((draft.structured_fields?.template_name as string) || "未指定")}</Text>
                  <Text style={styles.content} numberOfLines={5}>{draft.draft_text}</Text>
                  <View style={styles.row}>
                    <ActionButton label="编辑" onPress={() => startEditDraft(draft)} variant="secondary" style={styles.flexBtn} />
                    <ActionButton label="审核" onPress={() => reviewDraft(draft.id)} variant="secondary" style={styles.flexBtn} />
                    <ActionButton label="提交" onPress={() => submitDraft(draft.id)} style={styles.flexBtn} />
                  </View>
                  <ActionButton label="生成医生核对医嘱请求" onPress={() => createOrderRequestFromDraft(draft)} variant="secondary" />
                </View>
              ))}
            </SurfaceCard>
          </AnimatedBlock>

          <AnimatedBlock delay={190}>
            <SurfaceCard>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionTitle}>文书历史（可调取）</Text>
                <ActionButton
                  label={historyPanelOpen ? "收起" : "展开"}
                  onPress={() => setHistoryPanelOpen((prev) => !prev)}
                  variant="secondary"
                />
              </View>
              {historyPanelOpen ? (
                <>
                  <ActionButton label="刷新历史" onPress={loadHistory} variant="secondary" />
                  {historyLoading ? <Text style={styles.tip}>正在刷新历史...</Text> : null}
                  {!historyLoading && history.length === 0 ? <Text style={styles.tip}>暂无历史记录</Text> : null}
                  {history.map((item) => (
                    <Pressable
                      key={`his-${item.id}`}
                      style={styles.historyCard}
                      onPress={() => {
                        setEditingDraftId(item.id);
                        setText(item.draft_text);
                        setLastActionHint(`已调取历史草稿：${item.id}`);
                      }}
                    >
                      <Text style={styles.meta}>
                        {item.document_type} · {item.status} · {new Date(item.updated_at).toLocaleString()}
                      </Text>
                      <Text style={styles.historyText} numberOfLines={4}>{item.draft_text}</Text>
                      <Text style={styles.pickHint}>点击调取到编辑区</Text>
                    </Pressable>
                  ))}
                </>
              ) : (
                <Text style={styles.tip}>历史面板已收起，点击“展开”查看。</Text>
              )}
            </SurfaceCard>
          </AnimatedBlock>
        </>
      )}
    </ScreenShell>
  );
}

const styles = StyleSheet.create({
  editorHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  sectionTitle: {
    color: colors.text,
    fontWeight: "700",
    fontSize: 15,
  },
  row: {
    flexDirection: "row",
    gap: 10,
    marginTop: spacing.xs,
  },
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  fullBtn: {
    flex: 1,
  },
  flexBtn: {
    flex: 1,
  },
  pathText: {
    color: colors.primary,
    fontSize: 12.5,
    lineHeight: 18,
    marginTop: 6,
    fontWeight: "600",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 8,
    color: colors.text,
    marginTop: 8,
  },
  templateInput: {
    minHeight: 120,
    textAlignVertical: "top",
  },
  templateList: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 8,
  },
  templateTag: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  templateTagActive: {
    borderColor: colors.primary,
    backgroundColor: "#e8f0ff",
  },
  templateTagText: {
    color: colors.subText,
    fontSize: 12,
  },
  templateTagTextActive: {
    color: colors.primary,
    fontWeight: "700",
  },
  draftCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 12,
    gap: 8,
  },
  historyCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 12,
    gap: 8,
    marginTop: 8,
  },
  tip: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
    marginTop: 8,
  },
  error: {
    color: colors.danger,
  },
  meta: {
    color: colors.subText,
    fontSize: 12,
  },
  content: {
    color: colors.text,
    lineHeight: 20,
  },
  historyText: {
    color: colors.text,
    lineHeight: 20,
  },
  pickHint: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: "700",
  },
});
