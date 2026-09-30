// craco.config.js
const path = require("path");

module.exports = {
  eslint: {
    configure: {
      extends: ["plugin:react-hooks/recommended"],
      rules: {
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
      },
    },
  },
  webpack: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  // dev only: forward API calls to the local server (npm start in ../server)
  devServer: (devServerConfig) => ({
    ...devServerConfig,
    proxy: { "/api": "http://localhost:8001" },
  }),
};
