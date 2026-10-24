// Stories for <LineChart> — Figma: Line chart 201:1489, 🧩 Components. 1–2
// series × live, plus the derived no-data arm — including the 2-series × live
// combination the matrix tests exercise (UI_STATES §3b; arms mirror
// tests/components-3b.test.tsx).
import type { Meta, StoryObj } from "@storybook/react-vite";
import { LineChart } from "./LineChart";

const meta = {
  title: "Components/LineChart",
  component: LineChart,
} satisfies Meta<typeof LineChart>;

export default meta;
type Story = StoryObj<typeof meta>;

const ONE = [{ points: [1, 2, 1.5, 3] }] as const;
const TWO = [...ONE, { points: [3, 2, 2.5, 1] }] as const;

export const OneSeries: Story = { args: { series: ONE } };

export const TwoSeries: Story = { args: { series: TWO } };

// live = the last point pulses (an SSE-fed chart).
export const OneSeriesLive: Story = { args: { series: ONE, live: true } };

export const TwoSeriesLive: Story = { args: { series: TWO, live: true } };

// Empty series draws the grid and the label, never fake axes.
export const NoData: Story = { args: { series: [{ points: [] }] } };
