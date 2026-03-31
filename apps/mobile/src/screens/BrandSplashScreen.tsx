import React from "react";
import { Image, StyleSheet, Text, View } from "react-native";

import { colors, shadows } from "../theme";

const logo = require("../../assets/login_logo_ai_nurse.png");

export function BrandSplashScreen() {
  return (
    <View style={styles.container}>
      <View style={styles.glowA} />
      <View style={styles.glowB} />
      <View style={styles.card}>
        <Image source={logo} style={styles.logo} resizeMode="contain" />
        <Text style={styles.title}>AI护理精细化系统</Text>
        <Text style={styles.subTitle}>医护智能语音 · 多 Agent 协同</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#f2f6fb",
    alignItems: "center",
    justifyContent: "center",
  },
  glowA: {
    position: "absolute",
    top: -80,
    right: -80,
    width: 220,
    height: 220,
    borderRadius: 110,
    backgroundColor: "rgba(44,99,228,0.2)",
  },
  glowB: {
    position: "absolute",
    bottom: -120,
    left: -120,
    width: 260,
    height: 260,
    borderRadius: 130,
    backgroundColor: "rgba(25,168,140,0.16)",
  },
  card: {
    width: "84%",
    borderRadius: 24,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: "#d9e4f2",
    alignItems: "center",
    paddingVertical: 30,
    ...shadows.hero,
  },
  logo: {
    width: 148,
    height: 148,
    marginBottom: 10,
  },
  title: {
    color: colors.text,
    fontSize: 26,
    fontWeight: "800",
  },
  subTitle: {
    marginTop: 6,
    color: colors.subText,
    fontSize: 14,
  },
});
