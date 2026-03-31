/* eslint-disable @typescript-eslint/no-var-requires */

// Install runtime polyfills before Expo.fx executes.
(function installRuntimePolyfills() {
  const g = globalThis;

  if (typeof g.setImmediate !== "function") {
    g.setImmediate = function setImmediatePolyfill(callback, ...args) {
      return setTimeout(() => callback(...args), 0);
    };
  }

  if (typeof g.clearImmediate !== "function") {
    g.clearImmediate = function clearImmediatePolyfill(handle) {
      clearTimeout(handle);
    };
  }

  if (typeof g.FormData === "undefined") {
    try {
      const rnFormData = require("react-native/Libraries/Network/FormData");
      g.FormData = rnFormData?.default || rnFormData;
    } catch (e) {
      // noop
    }
  }
})();

const registerRootComponent = require("expo/src/launch/registerRootComponent").default;
const App = require("./App").default;
registerRootComponent(App);
