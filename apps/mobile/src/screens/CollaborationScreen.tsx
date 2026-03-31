import React, { useEffect, useMemo, useState } from "react";
import { Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { api } from "../api/endpoints";
import { PatientCaseSelector } from "../components/PatientCaseSelector";
import { ActionButton, AnimatedBlock, CollapsibleCard, ScreenShell, StatusPill, SurfaceCard } from "../components/ui";
import { useAppStore } from "../store/appStore";
import { colors, radius } from "../theme";
import { formatAiText } from "../utils/text";
import type { AssistantDigest, CollabAccount, DirectSession, DirectSessionDetail } from "../types";

const QUICK_MESSAGES: Array<{ key: string; label: string; text: string }> = [
  {
    key: "handover",
    label: "发送交班提示",
    text: "请协助核对本班交接重点：生命体征趋势、未闭环任务、异常阈值触发条件。",
  },
  {
    key: "order_review",
    label: "请求医生核对医嘱",
    text: "请医生协助核对当前医嘱优先级与执行顺序，重点关注P1及高警示项目。",
  },
  {
    key: "risk_watch",
    label: "提醒复测生命体征",
    text: "请协助复测血压/心率/尿量并回传结果，若触发阈值请立即升级处理。",
  },
];

export function CollaborationScreen() {
  const user = useAppStore((state) => state.user);
  const departmentId = useAppStore((state) => state.selectedDepartmentId);
  const selectedPatient = useAppStore((state) => state.selectedPatient);
  const setSelectedPatient = useAppStore((state) => state.setSelectedPatient);

  const [contacts, setContacts] = useState<CollabAccount[]>([]);
  const [sessions, setSessions] = useState<DirectSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [activeDetail, setActiveDetail] = useState<DirectSessionDetail | null>(null);

  const [searchKeyword, setSearchKeyword] = useState("");
  const [searchResult, setSearchResult] = useState<CollabAccount[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);

  const [digestNote, setDigestNote] = useState("");
  const [digest, setDigest] = useState<AssistantDigest | null>(null);
  const [autoDigest, setAutoDigest] = useState(false);
  const [composerExpanded, setComposerExpanded] = useState(true);
  const [addContactExpanded, setAddContactExpanded] = useState(false);
  const [assistantExpanded, setAssistantExpanded] = useState(false);

  const userId = user?.id || "u_nurse_01";
  const patientId = selectedPatient?.id;

  const activeContact = useMemo(() => {
    if (!activeDetail?.session?.contact_user_id) {
      return null;
    }
    return contacts.find((item) => item.id === activeDetail.session.contact_user_id) || activeDetail.session.contact || null;
  }, [activeDetail, contacts]);

  const recentSessions = useMemo(() => sessions.slice(0, 4), [sessions]);

  const loadContacts = async () => {
    const data = await api.getCollabContacts(userId);
    setContacts(data.contacts || []);
  };

  const loadSessions = async () => {
    const data = await api.listDirectSessions(userId, 120);
    setSessions(data || []);
  };

  const loadSessionDetail = async (sessionId: string) => {
    if (!sessionId) {
      return;
    }
    const detail = await api.getDirectSessionDetail(sessionId, userId);
    setActiveSessionId(sessionId);
    setActiveDetail(detail);
  };

  const openOrCreateSession = async (contactUserId: string) => {
    const session = await api.openDirectSession({ userId, contactUserId, patientId });
    await loadSessions();
    await loadSessionDetail(session.id);
  };

  const refreshAll = async () => {
    setHistoryLoading(true);
    try {
      await Promise.all([loadContacts(), loadSessions()]);
      if (activeSessionId) {
        await loadSessionDetail(activeSessionId);
      }
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    refreshAll();
  }, [userId]);

  useEffect(() => {
    if (!activeSessionId) {
      return;
    }
    setComposerExpanded(true);
    loadSessionDetail(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    setDigest(null);
    setDigestNote("");
  }, [patientId]);

  const onSearchAccount = async () => {
    const list = await api.searchCollabAccounts(searchKeyword.trim(), userId);
    setSearchResult(list);
  };

  const onAddContact = async (account: string) => {
    try {
      await api.addCollabContact(userId, account);
      await loadContacts();
      Alert.alert("添加成功", "已加入联系人列表。");
    } catch {
      Alert.alert("添加失败", "请检查账号是否存在或稍后重试。");
    }
  };

  const sendMessage = async (customText?: string) => {
    if (!activeSessionId) {
      Alert.alert("请先选择联系人", "先从联系人列表打开一个会话。");
      return;
    }
    const text = (customText ?? message).trim();
    if (!text) {
      Alert.alert("请输入消息内容");
      return;
    }

    setLoading(true);
    try {
      await api.sendDirectMessage({
        sessionId: activeSessionId,
        senderId: userId,
        content: text,
      });
      setMessage("");
      await loadSessionDetail(activeSessionId);
      await loadSessions();
    } catch {
      Alert.alert("发送失败", "请检查协作服务连接。");
    } finally {
      setLoading(false);
    }
  };

  const runDigest = async () => {
    if (!patientId) {
      Alert.alert("请先选择病例", "AI值班助理需要先绑定病例。");
      return;
    }
    setLoading(true);
    try {
      const data = await api.runAssistantDigest({
        userId,
        patientId,
        note: digestNote.trim() || undefined,
      });
      setDigest(data);
    } catch {
      Alert.alert("整理失败", "请检查协作服务与网关连接。");
    } finally {
      setLoading(false);
    }
  };

  const sendDigestMessage = async () => {
    if (!digest?.generated_message) {
      Alert.alert("暂无可发送内容", "请先生成 AI 助理整理结果。");
      return;
    }
    if (!activeSessionId) {
      Alert.alert("请先打开会话", "先选择联系人，再发送整理消息。");
      return;
    }
    try {
      await api.sendDirectMessage({
        sessionId: activeSessionId,
        senderId: "ai-assistant",
        content: digest.generated_message,
      });
      await loadSessionDetail(activeSessionId);
      await loadSessions();
      Alert.alert("发送成功", "AI整理消息已发送到当前会话。");
    } catch {
      Alert.alert("发送失败", "请稍后重试。");
    }
  };

  useEffect(() => {
    if (!autoDigest) {
      return;
    }
    const timer = setInterval(async () => {
      if (!patientId || !activeSessionId) {
        return;
      }
      try {
        const data = await api.runAssistantDigest({
          userId,
          patientId,
          note: "自动任务整理",
        });
        setDigest(data);
        if (data.generated_message) {
          await api.sendDirectMessage({
            sessionId: activeSessionId,
            senderId: "ai-assistant",
            content: data.generated_message,
          });
          await loadSessionDetail(activeSessionId);
          await loadSessions();
        }
      } catch {
        // ignore
      }
    }, 15 * 60 * 1000);

    return () => clearInterval(timer);
  }, [autoDigest, patientId, activeSessionId, userId]);

  return (
    <ScreenShell
      title="远程协作"
      subtitle={selectedPatient ? `当前病例：${selectedPatient.full_name}（${selectedPatient.id}）` : "可先选病例再发送临床协作消息"}
      rightNode={<StatusPill text={loading ? "处理中" : autoDigest ? "自动整理中" : "在线"} tone={loading ? "warning" : "success"} />}
    >
      <AnimatedBlock delay={40}>
        <PatientCaseSelector
          departmentId={departmentId}
          selectedPatient={selectedPatient}
          onSelectPatient={setSelectedPatient}
        />
      </AnimatedBlock>

      <AnimatedBlock delay={80}>
        <SurfaceCard style={styles.summaryCard}>
          <View style={styles.sectionHeader}>
            <View style={styles.workspaceLead}>
              <Text style={styles.sectionTitle}>沟通工作台</Text>
              <Text style={styles.meta}>把联系人选择、最近沟通、当前会话和班中整理收在同一条工作线上，避免来回翻找。</Text>
            </View>
            <StatusPill text={activeContact ? "已有进行中的会话" : "等待选择对象"} tone={activeContact ? "success" : "info"} />
          </View>
          <View style={styles.summaryGrid}>
            <View style={styles.summaryMetric}>
              <Text style={styles.summaryMetricLabel}>联系人</Text>
              <Text style={styles.summaryMetricValue}>{contacts.length}</Text>
            </View>
            <View style={styles.summaryMetric}>
              <Text style={styles.summaryMetricLabel}>最近会话</Text>
              <Text style={styles.summaryMetricValue}>{sessions.length}</Text>
            </View>
            <View style={styles.summaryMetric}>
              <Text style={styles.summaryMetricLabel}>当前对象</Text>
              <Text style={styles.summaryMetricValue} numberOfLines={1}>{activeContact?.full_name || "未选择"}</Text>
            </View>
          </View>
          <Text style={styles.meta}>
            {selectedPatient
              ? `当前已绑定病例：${selectedPatient.full_name}（${selectedPatient.id}）`
              : "建议先绑定病例，再发送需要医生核对的临床信息。"}
          </Text>
        </SurfaceCard>
      </AnimatedBlock>

      <AnimatedBlock delay={100}>
        <CollapsibleCard
          title="新增联系人"
          subtitle="按账号或姓名查找医生或协作者，需要时再展开。"
          expanded={addContactExpanded}
          onToggle={() => setAddContactExpanded((prev) => !prev)}
          badge={<StatusPill text={searchResult.length ? `${searchResult.length} 条结果` : "按需展开"} tone="info" />}
        >
          <View style={styles.searchRow}>
            <TextInput
              style={styles.input}
              value={searchKeyword}
              onChangeText={setSearchKeyword}
              placeholder="输入账号/姓名"
              placeholderTextColor={colors.subText}
            />
            <ActionButton label="查找" onPress={onSearchAccount} variant="secondary" style={styles.searchBtn} />
          </View>
          {searchResult.length === 0 ? <Text style={styles.meta}>查找结果会显示在这里，添加后会进入下方“沟通对象”。</Text> : null}
          {searchResult.map((item) => (
            <View key={item.id} style={styles.accountRow}>
              <View style={{ flex: 1 }}>
                <Text style={styles.accountName}>{item.full_name}（{item.account}）</Text>
                <Text style={styles.accountMeta}>{item.role_code} · {item.department || "-"}</Text>
              </View>
              <ActionButton label="添加" onPress={() => onAddContact(item.account)} variant="secondary" />
            </View>
          ))}
        </CollapsibleCard>
      </AnimatedBlock>

      <AnimatedBlock delay={120}>
        <SurfaceCard>
          <View style={styles.sectionHeader}>
            <View style={styles.workspaceLead}>
              <Text style={styles.sectionTitle}>沟通对象</Text>
              <Text style={styles.meta}>先点联系人，再打开最近一段会话。</Text>
            </View>
            <ActionButton label="刷新" onPress={refreshAll} variant="secondary" />
          </View>
          {historyLoading ? <Text style={styles.meta}>正在刷新...</Text> : null}
          {contacts.length === 0 ? <Text style={styles.meta}>暂无联系人</Text> : null}
          {contacts.length > 0 ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.contactRail}>
              {contacts.map((item) => {
                const active = activeContact?.id === item.id;
                return (
                  <Pressable key={item.id} style={[styles.contactPill, active && styles.contactPillActive]} onPress={() => openOrCreateSession(item.id)}>
                    <View style={styles.avatar}><Text style={styles.avatarText}>{item.full_name.slice(0, 1)}</Text></View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.contactPillName}>{item.full_name}</Text>
                      <Text style={styles.accountMeta} numberOfLines={1}>{item.title || item.role_code}</Text>
                    </View>
                  </Pressable>
                );
              })}
            </ScrollView>
          ) : null}

          <Text style={styles.subsectionLabel}>最近沟通</Text>
          {recentSessions.length === 0 ? <Text style={styles.meta}>暂无会话</Text> : null}
          {recentSessions.map((session) => (
            <Pressable
              key={session.id}
              style={[styles.sessionCard, activeSessionId === session.id && styles.sessionCardActive]}
              onPress={() => loadSessionDetail(session.id)}
            >
              <View style={styles.sessionTopRow}>
                <Text style={styles.accountName}>{session.contact?.full_name || session.contact_user_id}</Text>
                <Text style={styles.accountMeta}>{new Date(session.updated_at).toLocaleString()}</Text>
              </View>
              <Text style={styles.accountMeta} numberOfLines={2}>
                {formatAiText(session.latest_message?.content || "暂无消息")}
              </Text>
            </Pressable>
          ))}
        </SurfaceCard>
      </AnimatedBlock>

      <AnimatedBlock delay={150}>
        <CollapsibleCard
          title="当前会话"
          subtitle={activeContact ? `正在和 ${activeContact.full_name} 沟通` : "先从上方选择一位联系人"}
          expanded={composerExpanded}
          onToggle={() => setComposerExpanded((prev) => !prev)}
          badge={<StatusPill text={activeContact ? "已打开" : "未选择"} tone={activeContact ? "success" : "info"} />}
        >
          {activeDetail?.messages?.length ? (
            <ScrollView style={styles.chatBox}>
              {activeDetail.messages.map((msg) => {
                const mine = msg.sender_id === userId;
                const ai = msg.sender_id === "ai-assistant";
                return (
                  <View key={msg.id} style={[styles.msgBubble, mine ? styles.msgMine : styles.msgOther]}>
                    <Text style={styles.msgTag}>{ai ? "班中助手" : mine ? "我" : activeContact?.full_name || "协作者"}</Text>
                    <Text style={styles.msgText}>{formatAiText(msg.content)}</Text>
                    <Text style={styles.msgTime}>{new Date(msg.created_at).toLocaleString()}</Text>
                  </View>
                );
              })}
            </ScrollView>
          ) : (
            <Text style={styles.meta}>暂无聊天记录</Text>
          )}

          <View style={styles.quickRow}>
            {QUICK_MESSAGES.map((item) => (
              <ActionButton
                key={item.key}
                label={item.label}
                onPress={() => sendMessage(item.text)}
                variant="secondary"
                style={styles.quickBtn}
              />
            ))}
          </View>

          <TextInput
            style={[styles.input, styles.multiInput]}
            value={message}
            onChangeText={setMessage}
            multiline
            placeholder="请输入要发送的说明或请求"
            placeholderTextColor={colors.subText}
          />
          <ActionButton label="发送" onPress={() => sendMessage()} />
        </CollapsibleCard>
      </AnimatedBlock>

      <AnimatedBlock delay={180}>
        <CollapsibleCard
          title="班中整理助手"
          subtitle="把本班重点整理成可直接发送给医生的沟通说明，默认收起避免页面过长。"
          expanded={assistantExpanded}
          onToggle={() => setAssistantExpanded((prev) => !prev)}
          badge={<StatusPill text={autoDigest ? "15分钟自动整理中" : "手动触发"} tone={autoDigest ? "warning" : "info"} />}
        >
          <View style={styles.sectionHeader}>
            <Text style={styles.meta}>可先写本班重点，再决定是否自动整理和发送。</Text>
            <ActionButton
              label={autoDigest ? "关闭自动整理" : "开启15分钟自动整理"}
              onPress={() => setAutoDigest((prev) => !prev)}
              variant="secondary"
            />
          </View>
          <TextInput
            style={[styles.input, styles.multiInput]}
            value={digestNote}
            onChangeText={setDigestNote}
            multiline
            placeholder="例如：关注23床少尿与低血压趋势"
            placeholderTextColor={colors.subText}
          />
          <View style={styles.searchRow}>
            <ActionButton label="生成任务整理" onPress={runDigest} variant="secondary" style={styles.searchBtn} />
            <ActionButton label="发送整理消息" onPress={sendDigestMessage} style={styles.searchBtn} />
          </View>
          {digest ? (
            <View style={styles.digestCard}>
              <Text style={styles.accountName}>{formatAiText(digest.summary)}</Text>
              {digest.tasks.map((item, idx) => (
                <Text key={`task-${idx}`} style={styles.meta}>• {formatAiText(item)}</Text>
              ))}
              {digest.suggestions.map((item, idx) => (
                <Text key={`suggest-${idx}`} style={styles.meta}>建议：{formatAiText(item)}</Text>
              ))}
              <Text style={styles.digestMsg}>待发送说明：{formatAiText(digest.generated_message)}</Text>
            </View>
          ) : (
            <Text style={styles.meta}>点击“生成任务整理”后可查看并发送。</Text>
          )}
        </CollapsibleCard>
      </AnimatedBlock>
    </ScreenShell>
  );
}

const styles = StyleSheet.create({
  summaryCard: {
    backgroundColor: "#f7fbff",
    borderColor: "#d8e4f2",
  },
  sectionTitle: {
    color: colors.text,
    fontWeight: "700",
    fontSize: 15,
  },
  workspaceLead: {
    flex: 1,
    gap: 4,
  },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
  },
  summaryGrid: {
    flexDirection: "row",
    gap: 8,
  },
  summaryMetric: {
    flex: 1,
    borderRadius: 14,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#d8e4f2",
    paddingVertical: 10,
    paddingHorizontal: 10,
    gap: 4,
  },
  summaryMetricLabel: {
    color: colors.subText,
    fontSize: 11.5,
    fontWeight: "700",
  },
  summaryMetricValue: {
    color: colors.primary,
    fontSize: 15,
    fontWeight: "800",
  },
  searchRow: {
    flexDirection: "row",
    gap: 8,
  },
  searchBtn: {
    flex: 1,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    backgroundColor: colors.card,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.text,
  },
  multiInput: {
    minHeight: 82,
    textAlignVertical: "top",
  },
  meta: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  accountRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 10,
  },
  accountName: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
  },
  accountMeta: {
    color: colors.subText,
    fontSize: 12,
    lineHeight: 18,
  },
  contactRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 10,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "#e8f0ff",
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: {
    color: colors.primary,
    fontWeight: "700",
  },
  contactRail: {
    gap: 8,
    paddingVertical: 2,
  },
  contactPill: {
    width: 164,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 10,
    backgroundColor: "#ffffff",
  },
  contactPillActive: {
    borderColor: colors.primary,
    backgroundColor: "#eef4ff",
  },
  contactPillName: {
    color: colors.text,
    fontSize: 13.5,
    fontWeight: "700",
  },
  openText: {
    color: colors.primary,
    fontSize: 12,
    fontWeight: "700",
  },
  subsectionLabel: {
    color: colors.text,
    fontSize: 13,
    fontWeight: "700",
  },
  sessionCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 10,
    gap: 3,
  },
  sessionTopRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
  },
  sessionCardActive: {
    borderColor: colors.primary,
    backgroundColor: "#edf3ff",
  },
  chatBox: {
    maxHeight: 360,
  },
  msgBubble: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 8,
    gap: 4,
    marginBottom: 6,
    maxWidth: "85%",
  },
  msgMine: {
    alignSelf: "flex-end",
    backgroundColor: "#eaf1ff",
    borderColor: "#bed3ff",
  },
  msgOther: {
    alignSelf: "flex-start",
    backgroundColor: "#ffffff",
  },
  msgTag: {
    color: colors.primary,
    fontSize: 11,
    fontWeight: "700",
  },
  msgText: {
    color: colors.text,
    lineHeight: 20,
  },
  msgTime: {
    color: colors.subText,
    fontSize: 11,
  },
  quickRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  quickBtn: {
    minWidth: 110,
  },
  digestCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 10,
    gap: 4,
  },
  digestMsg: {
    color: colors.primary,
    fontSize: 12.5,
    lineHeight: 18,
    fontWeight: "600",
  },
});
