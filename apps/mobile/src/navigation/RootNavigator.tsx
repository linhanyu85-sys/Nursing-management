import React, { useEffect, useState } from "react";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { View } from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";

import { useAppStore } from "../store/appStore";
import { colors, radius, shadows } from "../theme";
import { BrandSplashScreen } from "../screens/BrandSplashScreen";
import { CollaborationScreen } from "../screens/CollaborationScreen";
import { DocumentScreen } from "../screens/DocumentScreen";
import { HandoverScreen } from "../screens/HandoverScreen";
import { HomeScreen } from "../screens/HomeScreen";
import { LoginScreen } from "../screens/LoginScreen";
import { OrderCenterScreen } from "../screens/OrderCenterScreen";
import { PatientDetailScreen } from "../screens/PatientDetailScreen";
import { ProfileScreen } from "../screens/ProfileScreen";
import { RecommendationScreen } from "../screens/RecommendationScreen";
import { RegisterScreen } from "../screens/RegisterScreen";
import { WardOverviewScreen } from "../screens/WardOverviewScreen";

export type RootStackParamList = {
  Login: undefined;
  Register: undefined;
  MainTabs: undefined;
  PatientDetail: { patientId: string };
};

export type MainTabParamList = {
  Home: undefined;
  Ward: undefined;
  Orders: undefined;
  Handover: undefined;
  Recommendation: undefined;
  Document: undefined;
  Collaboration: undefined;
  Profile: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<MainTabParamList>();

const tabMeta: Record<keyof MainTabParamList, { label: string; icon: keyof typeof MaterialCommunityIcons.glyphMap }> = {
  Home: { label: "首页", icon: "home-outline" },
  Ward: { label: "病区", icon: "hospital-building" },
  Orders: { label: "医嘱", icon: "clipboard-pulse-outline" },
  Handover: { label: "交班", icon: "swap-horizontal-bold" },
  Recommendation: { label: "推荐", icon: "brain" },
  Document: { label: "文书", icon: "file-document-edit-outline" },
  Collaboration: { label: "协作", icon: "handshake-outline" },
  Profile: { label: "我的", icon: "account-circle-outline" },
};

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => {
        const meta = tabMeta[route.name as keyof MainTabParamList];
        return {
          headerShown: false,
          tabBarActiveTintColor: colors.primary,
          tabBarInactiveTintColor: colors.subText,
          tabBarLabelStyle: { fontSize: 12, fontWeight: "700", marginBottom: 4 },
          tabBarStyle: {
            position: "absolute",
            left: 12,
            right: 12,
            bottom: 12,
            borderTopWidth: 0,
            borderRadius: radius.lg,
            height: 74,
            paddingTop: 6,
            backgroundColor: "#ffffffef",
            ...shadows.tabBar,
          },
          tabBarLabel: meta.label,
          tabBarIcon: ({ focused, color }) => (
            <View
              style={{
                width: 32,
                height: 32,
                borderRadius: 16,
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: focused ? "#eaf1ff" : "transparent",
              }}
            >
              <MaterialCommunityIcons name={meta.icon} size={20} color={color} />
            </View>
          ),
        };
      }}
    >
      <Tab.Screen name="Home" component={HomeScreen} />
      <Tab.Screen name="Ward" component={WardOverviewScreen} />
      <Tab.Screen name="Orders" component={OrderCenterScreen} />
      <Tab.Screen name="Handover" component={HandoverScreen} />
      <Tab.Screen name="Recommendation" component={RecommendationScreen} />
      <Tab.Screen name="Document" component={DocumentScreen} />
      <Tab.Screen name="Collaboration" component={CollaborationScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
  );
}

export function RootNavigator() {
  const token = useAppStore((state) => state.token);
  const [showSplash, setShowSplash] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => setShowSplash(false), 1400);
    return () => clearTimeout(timer);
  }, []);

  if (showSplash) {
    return <BrandSplashScreen />;
  }

  if (!token) {
    return (
      <Stack.Navigator screenOptions={{ contentStyle: { backgroundColor: colors.bg } }}>
        <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
        <Stack.Screen name="Register" component={RegisterScreen} options={{ headerShown: false }} />
      </Stack.Navigator>
    );
  }

  return (
    <Stack.Navigator screenOptions={{ contentStyle: { backgroundColor: colors.bg } }}>
      <Stack.Screen name="MainTabs" component={MainTabs} options={{ headerShown: false }} />
      <Stack.Screen
        name="PatientDetail"
        component={PatientDetailScreen}
        options={{
          title: "患者详情",
          headerShadowVisible: false,
          headerStyle: { backgroundColor: colors.bgSoft },
        }}
      />
    </Stack.Navigator>
  );
}
