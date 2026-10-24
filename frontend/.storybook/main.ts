// Storybook 10: the unified `storybook` package plus the react-vite framework
// (ADR-0043). Vite config is read from ../vite.config.ts by SB itself — the
// Tailwind v4 plugin and the /design fs.allow ride along and are deliberately
// not duplicated here.
import type { StorybookConfig } from "@storybook/react-vite";

const config: StorybookConfig = {
  framework: "@storybook/react-vite",
  stories: ["../src/**/*.stories.tsx"],
  addons: ["@chromatic-com/storybook"],
};

export default config;
