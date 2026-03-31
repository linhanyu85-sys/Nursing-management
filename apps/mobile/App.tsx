import React from "react";
import { NavigationContainer } from "@react-navigation/native";
import { StatusBar } from "expo-status-bar";
import { Text, TextInput } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { RootNavigator } from "./src/navigation/RootNavigator";

(Text as unknown as { defaultProps?: Record<string, unknown> }).defaultProps = {
  ...((Text as unknown as { defaultProps?: Record<string, unknown> }).defaultProps || {}),
  allowFontScaling: false,
};

(TextInput as unknown as { defaultProps?: Record<string, unknown> }).defaultProps = {
  ...((TextInput as unknown as { defaultProps?: Record<string, unknown> }).defaultProps || {}),
  allowFontScaling: false,
};

export default function App() {
  return (
    <SafeAreaProvider>
      <NavigationContainer>
        <StatusBar style="dark" />
        <RootNavigator />
      </NavigationContainer>
    </SafeAreaProvider>
  );
}
