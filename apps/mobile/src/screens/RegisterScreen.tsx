import React, { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { SafeAreaView } from "react-native-safe-area-context";

import { api, getApiErrorMessage } from "../api/endpoints";
import type { RootStackParamList } from "../navigation/RootNavigator";
import { colors, radius } from "../theme";

type Props = NativeStackScreenProps<RootStackParamList, "Register">;

const ROLE_OPTIONS: Array<{ code: string; label: string }> = [
  { code: "nurse", label: "护士" },
  { code: "attending_doctor", label: "医生" },
  { code: "admin", label: "管理员" },
];

export function RegisterScreen({ navigation }: Props) {
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [roleCode, setRoleCode] = useState("nurse");
  const [loading, setLoading] = useState(false);

  const onRegister = async () => {
    if (!username || !fullName || !password) {
      Alert.alert("请完整填写注册信息");
      return;
    }
    if (password !== confirmPassword) {
      Alert.alert("两次密码不一致");
      return;
    }

    setLoading(true);
    try {
      await api.register({
        username: username.trim(),
        password,
        full_name: fullName.trim(),
        role_code: roleCode,
      });
      Alert.alert("注册成功", "请返回登录页登录", [{ text: "确定", onPress: () => navigation.replace("Login") }]);
    } catch (error) {
      Alert.alert("注册失败", getApiErrorMessage(error, "注册失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right", "bottom"]}>
      <View style={styles.bgTopGlow} />
      <View style={styles.bgBottomGlow} />

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.flex}>
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
        >
          <View style={styles.hero}>
            <Text style={styles.heroTitle}>账号注册</Text>
            <Text style={styles.heroSubTitle}>创建医护账号后返回登录页面</Text>
          </View>

          <View style={styles.card}>
            <View style={styles.field}>
              <Text style={styles.label}>登录名</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入登录名"
                placeholderTextColor={colors.subText}
                value={username}
                onChangeText={setUsername}
                autoCapitalize="none"
                autoCorrect={false}
              />
            </View>

            <View style={styles.field}>
              <Text style={styles.label}>姓名</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入姓名"
                placeholderTextColor={colors.subText}
                value={fullName}
                onChangeText={setFullName}
              />
            </View>

            <View style={styles.field}>
              <Text style={styles.label}>角色</Text>
              <View style={styles.roleRow}>
                {ROLE_OPTIONS.map((item) => {
                  const active = item.code === roleCode;
                  return (
                    <Pressable
                      key={item.code}
                      style={[styles.roleTag, active && styles.roleTagActive]}
                      onPress={() => setRoleCode(item.code)}
                    >
                      <Text style={[styles.roleTagText, active && styles.roleTagTextActive]}>{item.label}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>

            <View style={styles.field}>
              <Text style={styles.label}>密码</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入密码"
                placeholderTextColor={colors.subText}
                secureTextEntry
                value={password}
                onChangeText={setPassword}
                autoCorrect={false}
              />
            </View>

            <View style={styles.field}>
              <Text style={styles.label}>确认密码</Text>
              <TextInput
                style={styles.input}
                placeholder="请再次输入密码"
                placeholderTextColor={colors.subText}
                secureTextEntry
                value={confirmPassword}
                onChangeText={setConfirmPassword}
                autoCorrect={false}
              />
            </View>

            <Pressable style={styles.button} onPress={onRegister} disabled={loading}>
              {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonText}>注册并返回登录</Text>}
            </Pressable>

            <Pressable onPress={() => navigation.replace("Login")} style={styles.linkBtn}>
              <Text style={styles.linkText}>已有账号？返回登录</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  flex: {
    flex: 1,
  },
  scrollContent: {
    minHeight: "100%",
    paddingHorizontal: 18,
    paddingTop: 14,
    paddingBottom: 24,
    gap: 14,
  },
  bgTopGlow: {
    position: "absolute",
    width: 220,
    height: 220,
    borderRadius: 110,
    backgroundColor: "rgba(47,109,242,0.14)",
    top: -40,
    right: -36,
  },
  bgBottomGlow: {
    position: "absolute",
    width: 260,
    height: 260,
    borderRadius: 130,
    backgroundColor: "rgba(25,168,140,0.12)",
    bottom: -100,
    left: -80,
  },
  hero: {
    backgroundColor: colors.primary,
    borderRadius: radius.lg,
    paddingVertical: 18,
    paddingHorizontal: 18,
    marginTop: 4,
  },
  heroTitle: {
    color: "#ffffff",
    fontSize: 34,
    lineHeight: 40,
    fontWeight: "700",
  },
  heroSubTitle: {
    color: "#e2ebff",
    fontSize: 16,
    lineHeight: 22,
    marginTop: 4,
    fontWeight: "500",
  },
  card: {
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: "#cbd5e1",
    backgroundColor: "#ffffff",
    padding: 16,
    gap: 10,
  },
  field: {
    gap: 6,
  },
  label: {
    color: "#0f172a",
    fontSize: 16,
    lineHeight: 22,
    fontWeight: "600",
  },
  input: {
    borderWidth: 1,
    borderColor: "#94a3b8",
    borderRadius: radius.md,
    backgroundColor: "#ffffff",
    paddingHorizontal: 12,
    paddingVertical: 12,
    color: "#0f172a",
    fontSize: 17,
    lineHeight: 24,
    minHeight: 52,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: radius.md,
    minHeight: 52,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 2,
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 19,
    lineHeight: 26,
    fontWeight: "700",
  },
  linkBtn: {
    alignItems: "center",
    paddingTop: 4,
  },
  linkText: {
    color: "#1d4ed8",
    fontSize: 16,
    lineHeight: 22,
    fontWeight: "600",
  },
  roleRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  roleTag: {
    borderWidth: 1,
    borderColor: "#94a3b8",
    borderRadius: 999,
    backgroundColor: "#ffffff",
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  roleTagActive: {
    borderColor: colors.primary,
    backgroundColor: "#eaf1ff",
  },
  roleTagText: {
    color: "#334155",
    fontSize: 14,
    fontWeight: "600",
  },
  roleTagTextActive: {
    color: colors.primary,
  },
});
