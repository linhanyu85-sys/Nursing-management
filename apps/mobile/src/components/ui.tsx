import React, { useEffect, useMemo, useRef } from "react";
import {
  Animated,
  Platform,
  Pressable,
  ScrollView,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";

import { colors, radius, shadows, spacing, typography } from "../theme";

type ScreenShellProps = {
  title: string;
  subtitle?: string;
  rightNode?: React.ReactNode;
  children: React.ReactNode;
  scroll?: boolean;
};

export function ScreenShell({ title, subtitle, rightNode, children, scroll = true }: ScreenShellProps) {
  const insets = useSafeAreaInsets();
  const Body = scroll ? ScrollView : View;
  const bottomSpacing = Math.max(spacing.xl + 16, insets.bottom + 132);
  const bodyStyle = [
    styles.content,
    {
      paddingTop: Math.max(spacing.sm, insets.top > 0 ? spacing.xs : spacing.sm),
      paddingBottom: bottomSpacing,
    },
  ];
  const bodyProps = scroll ? { contentContainerStyle: bodyStyle } : { style: bodyStyle };

  return (
    <SafeAreaView style={styles.safe} edges={["top", "left", "right"]}>
      <View style={styles.bgTopGlow} />
      <View style={styles.bgBottomGlow} />

      <Body {...bodyProps}>
        <View style={styles.hero}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>{title}</Text>
            {subtitle ? <Text style={styles.subTitle}>{subtitle}</Text> : null}
          </View>
          {rightNode}
        </View>
        {children}
      </Body>
    </SafeAreaView>
  );
}

type CardProps = {
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  elevated?: boolean;
};

export function SurfaceCard({ children, style, elevated = true }: CardProps) {
  return <View style={[styles.card, elevated && styles.cardElevated, style]}>{children}</View>;
}

type CollapsibleCardProps = {
  title: string;
  subtitle?: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
  elevated?: boolean;
  expanded?: boolean;
  defaultExpanded?: boolean;
  onToggle?: () => void;
};

export function CollapsibleCard({
  title,
  subtitle,
  badge,
  children,
  style,
  elevated = true,
  expanded,
  defaultExpanded = false,
  onToggle,
}: CollapsibleCardProps) {
  const [internalExpanded, setInternalExpanded] = React.useState(defaultExpanded);
  const isControlled = typeof expanded === "boolean";
  const open = isControlled ? Boolean(expanded) : internalExpanded;

  const handleToggle = () => {
    if (!isControlled) {
      setInternalExpanded((prev) => !prev);
    }
    onToggle?.();
  };

  return (
    <SurfaceCard style={style} elevated={elevated}>
      <Pressable style={styles.collapseHead} onPress={handleToggle}>
        <View style={styles.collapseHeadText}>
          <Text style={styles.collapseTitle}>{title}</Text>
          {subtitle ? <Text style={styles.collapseSubtitle}>{subtitle}</Text> : null}
        </View>
        <View style={styles.collapseHeadAside}>
          {badge}
          <Text style={styles.collapseAction}>{open ? "收起" : "展开"}</Text>
        </View>
      </Pressable>
      {open ? <View style={styles.collapseBody}>{children}</View> : null}
    </SurfaceCard>
  );
}

type ActionButtonProps = {
  label: string;
  onPress: () => void;
  variant?: "primary" | "secondary" | "danger";
  style?: StyleProp<ViewStyle>;
  disabled?: boolean;
};

export function ActionButton({
  label,
  onPress,
  variant = "primary",
  style,
  disabled = false,
}: ActionButtonProps) {
  const buttonStyle = useMemo(() => {
    if (variant === "danger") {
      return [styles.btnBase, styles.btnDanger];
    }
    if (variant === "secondary") {
      return [styles.btnBase, styles.btnSecondary];
    }
    return [styles.btnBase, styles.btnPrimary];
  }, [variant]);

  const textStyle = useMemo(() => {
    if (variant === "primary" || variant === "danger") {
      return styles.btnTextPrimary;
    }
    return styles.btnTextSecondary;
  }, [variant]);

  return (
    <Pressable style={[buttonStyle, disabled && styles.btnDisabled, style]} onPress={onPress} disabled={disabled}>
      <Text style={textStyle}>{label}</Text>
    </Pressable>
  );
}

export function StatusPill({
  text,
  tone = "info",
}: {
  text: string;
  tone?: "info" | "success" | "warning" | "danger";
}) {
  const toneStyle =
    tone === "success"
      ? styles.pillSuccess
      : tone === "warning"
      ? styles.pillWarning
      : tone === "danger"
      ? styles.pillDanger
      : styles.pillInfo;

  const textStyle =
    tone === "success"
      ? styles.pillTextSuccess
      : tone === "warning"
      ? styles.pillTextWarning
      : tone === "danger"
      ? styles.pillTextDanger
      : styles.pillTextInfo;

  return (
    <View style={[styles.pill, toneStyle]}>
      <Text style={[styles.pillText, textStyle]}>{text}</Text>
    </View>
  );
}

export function AnimatedBlock({
  children,
  delay = 0,
  style,
}: {
  children: React.ReactNode;
  delay?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(12)).current;
  const useNativeDriver = Platform.OS !== "web";

  useEffect(() => {
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 1,
        duration: 420,
        delay,
        useNativeDriver,
      }),
      Animated.timing(translateY, {
        toValue: 0,
        duration: 420,
        delay,
        useNativeDriver,
      }),
    ]).start();
  }, [delay, opacity, translateY, useNativeDriver]);

  return <Animated.View style={[style, { opacity, transform: [{ translateY }] }]}>{children}</Animated.View>;
}

export function ProgressTimeline({
  title = "AI 处理进度",
  steps,
}: {
  title?: string;
  steps: Array<{ key: string; label: string; done: boolean; active: boolean }>;
}) {
  if (!steps || steps.length === 0) {
    return null;
  }

  return (
    <SurfaceCard style={styles.progressCard}>
      <Text style={styles.progressTitle}>{title}</Text>
      {steps.map((step) => (
        <View key={step.key} style={styles.progressRow}>
          <View
            style={[
              styles.progressDot,
              step.done && styles.progressDotDone,
              step.active && styles.progressDotActive,
            ]}
          />
          <Text
            style={[
              styles.progressText,
              step.done && styles.progressTextDone,
              step.active && styles.progressTextActive,
            ]}
          >
            {step.label}
          </Text>
        </View>
      ))}
    </SurfaceCard>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: colors.bg,
  },
  content: {
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
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
    borderRadius: radius.xl,
    marginTop: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.lg,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.primary,
    ...shadows.hero,
  },
  title: {
    ...typography.title,
    color: "#f8fbff",
  },
  subTitle: {
    marginTop: 4,
    color: "rgba(240,247,255,0.92)",
    fontSize: 14,
    lineHeight: 20,
  },
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.sm,
  },
  cardElevated: {
    ...shadows.card,
  },
  collapseHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  collapseHeadText: {
    flex: 1,
    gap: 4,
  },
  collapseHeadAside: {
    alignItems: "flex-end",
    gap: 6,
  },
  collapseTitle: {
    color: colors.text,
    fontSize: 16,
    fontWeight: "700",
  },
  collapseSubtitle: {
    color: colors.subText,
    fontSize: 12.5,
    lineHeight: 18,
  },
  collapseAction: {
    color: colors.primary,
    fontSize: 12.5,
    fontWeight: "700",
  },
  collapseBody: {
    marginTop: spacing.sm,
    gap: spacing.sm,
  },
  btnBase: {
    minHeight: 46,
    paddingHorizontal: 16,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
  },
  btnPrimary: {
    borderColor: colors.primary,
    backgroundColor: colors.primary,
  },
  btnSecondary: {
    borderColor: colors.borderStrong,
    backgroundColor: "#f9fbff",
  },
  btnDanger: {
    borderColor: colors.danger,
    backgroundColor: colors.danger,
  },
  btnDisabled: {
    opacity: 0.5,
  },
  btnTextPrimary: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 15,
  },
  btnTextSecondary: {
    color: colors.text,
    fontWeight: "700",
    fontSize: 15,
  },
  pill: {
    borderRadius: 100,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignSelf: "flex-start",
  },
  pillText: {
    fontSize: 11.5,
    fontWeight: "700",
  },
  pillInfo: {
    backgroundColor: "#e7f0ff",
  },
  pillSuccess: {
    backgroundColor: "#def6f1",
  },
  pillWarning: {
    backgroundColor: "#fff2da",
  },
  pillDanger: {
    backgroundColor: "#ffe3e8",
  },
  pillTextInfo: {
    color: "#1f58c7",
  },
  pillTextSuccess: {
    color: "#0f8a70",
  },
  pillTextWarning: {
    color: "#b06a04",
  },
  pillTextDanger: {
    color: "#b62036",
  },
  progressCard: {
    gap: 6,
  },
  progressTitle: {
    color: colors.text,
    fontSize: 14,
    fontWeight: "700",
  },
  progressRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  progressDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    borderWidth: 1,
    borderColor: colors.borderStrong,
    backgroundColor: "#f2f5fb",
  },
  progressDotDone: {
    borderColor: "#2f6df2",
    backgroundColor: "#2f6df2",
  },
  progressDotActive: {
    borderColor: "#d97706",
    backgroundColor: "#fff2da",
  },
  progressText: {
    color: colors.subText,
    fontSize: 12.5,
  },
  progressTextDone: {
    color: colors.primary,
    fontWeight: "600",
  },
  progressTextActive: {
    color: "#b06a04",
    fontWeight: "700",
  },
});

