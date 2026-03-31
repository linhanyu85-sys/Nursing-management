import React from "react";
import { Alert, StyleSheet, Text } from "react-native";

import { apiBaseURL, isMockMode } from "../api/client";
import { ActionButton, AnimatedBlock, ScreenShell, SurfaceCard } from "../components/ui";
import { useAppStore } from "../store/appStore";
import { colors } from "../theme";

export function ProfileScreen() {
  const user = useAppStore((state) => state.user);
  const logout = useAppStore((state) => state.logout);

  const onLogout = () => {
    Alert.alert("确认退出", "退出后将返回登录/注册页面。", [
      { text: "取消", style: "cancel" },
      {
        text: "确认退出",
        style: "destructive",
        onPress: () => logout(),
      },
    ]);
  };

  return (
    <ScreenShell title="个人中心" subtitle="账号、环境与会话管理">
      <AnimatedBlock delay={40}>
        <SurfaceCard>
          <Text style={styles.item}>姓名：{user?.full_name || "-"}</Text>
          <Text style={styles.item}>账号：{user?.username || user?.account || "-"}</Text>
          <Text style={styles.item}>角色：{user?.role_code || "-"}</Text>
          <Text style={styles.item}>科室：{user?.department || "-"}</Text>
          <Text style={styles.item}>职务：{user?.title || "-"}</Text>
          <Text style={styles.item}>状态：{user?.status || "-"}</Text>
          <Text style={styles.item}>用户ID：{user?.id || "-"}</Text>
          <Text style={styles.item}>接口地址：{apiBaseURL}</Text>
          <Text style={styles.item}>模拟模式：{String(isMockMode)}</Text>
        </SurfaceCard>
      </AnimatedBlock>

      <AnimatedBlock delay={90}>
        <SurfaceCard>
          <ActionButton label="退出登录" onPress={onLogout} variant="danger" />
        </SurfaceCard>
      </AnimatedBlock>
    </ScreenShell>
  );
}

const styles = StyleSheet.create({
  item: { color: colors.text },
});
