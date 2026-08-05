import nextConfig from "eslint-config-next";

// eslint-config-next 16 ships native flat config exports, so no FlatCompat
// bridging is needed here, and FlatCompat actually breaks on this version
// (a circular reference inside eslint-plugin-react's flat preset crashes
// its legacy schema validator).
const eslintConfig = [...nextConfig];

export default eslintConfig;
