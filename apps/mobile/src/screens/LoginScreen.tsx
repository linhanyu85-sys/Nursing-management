import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
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
import { useAppStore } from "../store/appStore";
import { colors, radius } from "../theme";
import { clearRememberedLogin, loadRememberedLogin, saveRememberedLogin } from "../utils/rememberLogin";

type Props = NativeStackScreenProps<RootStackParamList, "Login">;

export function LoginScreen({ navigation }: Props) {
  const setAuth = useAppStore((state) => state.setAuth);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [rememberPassword, setRememberPassword] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const hydrateRemembered = async () => {
      const remembered = await loadRememberedLogin();
      if (!remembered.remember) {
        return;
      }
      setUsername(remembered.username);
      setPassword(remembered.password);
      setRememberPassword(true);
    };
    hydrateRemembered();
  }, []);

  const onLogin = async () => {
    if (!username || !password) {
      setError("请输入账号和密码");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const data = await api.login(username.trim(), password);
      const session = await api.bootstrapSession(data.user);
      if (rememberPassword) {
        await saveRememberedLogin(username, password);
      } else {
        await clearRememberedLogin();
      }
      setAuth(data.access_token, session.user, session.departmentId);
    } catch (err) {
      setError(getApiErrorMessage(err, "登录失败，请稍后重试。"));
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
            <Text style={styles.heroTitle}>欢迎登录</Text>
            <Text style={styles.heroSubTitle}>AI护理精细化系统</Text>
          </View>

          <View style={styles.card}>
            <Text style={styles.formTitle}>账号登录</Text>

            <View style={styles.field}>
              <Text style={styles.label}>账号</Text>
              <TextInput
                style={styles.input}
                placeholder="请输入账号"
                placeholderTextColor={colors.subText}
                value={username}
                onChangeText={setUsername}
                autoCapitalize="none"
                autoCorrect={false}
              />
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

            <Pressable style={styles.rememberRow} onPress={() => setRememberPassword((prev) => !prev)}>
              <View style={[styles.checkbox, rememberPassword && styles.checkboxActive]}>
                {rememberPassword ? <Text style={styles.checkboxTick}>✓</Text> : null}
              </View>
              <Text style={styles.rememberText}>记住密码</Text>
            </Pressable>

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <Pressable style={styles.button} onPress={onLogin} disabled={loading}>
              {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonText}>登录</Text>}
            </Pressable>

            <Pressable onPress={() => navigation.navigate("Register")} style={styles.linkBtn}>
              <Text style={styles.linkText}>没有账号？去注册</Text>
            </Pressable>

            <Text style={styles.hint}>测试账号：nurse01 / 123456</Text>
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
  formTitle: {
    color: "#0f172a",
    fontSize: 24,
    lineHeight: 30,
    fontWeight: "700",
    marginBottom: 2,
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
  rememberRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: 2,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: "#94a3b8",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ffffff",
  },
  checkboxActive: {
    borderColor: colors.primary,
    backgroundColor: "#eaf1ff",
  },
  checkboxTick: {
    color: colors.primary,
    fontWeight: "800",
    fontSize: 14,
    lineHeight: 16,
  },
  rememberText: {
    color: "#334155",
    fontSize: 15,
    lineHeight: 20,
    fontWeight: "600",
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
    fontSize: 20,
    lineHeight: 26,
    fontWeight: "700",
  },
  error: {
    color: colors.danger,
    fontSize: 15,
    lineHeight: 21,
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
  hint: {
    marginTop: 2,
    textAlign: "center",
    color: "#64748b",
    fontSize: 13,
    lineHeight: 18,
  },
});
