// One canvas for the coded library (ADR-0043): the app's single style entry,
// the Code Panel (Storysource was removed upstream in SB 9 — this is its
// successor), and the theme toolbar.
//
// Dark tokens are scoped `:root[data-theme="dark"]` (design/tokens), so the
// decorator sets the attribute on the story iframe's documentElement — a
// wrapper <div data-theme> would never match it. Chromatic captures the light
// default; the toolbar is for the human's eyes.
import type { Preview } from "@storybook/react-vite";
import "../src/styles/theme.css";

const preview: Preview = {
  globalTypes: {
    theme: {
      toolbar: { title: "Theme", items: ["light", "dark"], dynamicTitle: true },
    },
  },
  initialGlobals: { theme: "light" },
  decorators: [
    (Story, context) => {
      document.documentElement.setAttribute(
        "data-theme",
        context.globals.theme === "dark" ? "dark" : "light",
      );
      return <Story />;
    },
  ],
  parameters: { docs: { codePanel: true } },
};

export default preview;
