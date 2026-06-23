import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [react(), viteSingleFile({ removeViteModuleLoader: true })],
  server: {
    port: 5174,
    fs: { allow: [".."] },
  },
});
