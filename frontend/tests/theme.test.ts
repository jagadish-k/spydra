import { describe, expect, test } from "vitest";
import {
  initialTheme,
  readStoredTheme,
  storeTheme,
  toggleTheme,
} from "../src/lib/theme";

const nothing: () => string | null = () => null;

describe("readStoredTheme", () => {
  test("returns a stored valid choice", () => {
    expect(readStoredTheme(() => "dark")).toBe("dark");
    expect(readStoredTheme(() => "light")).toBe("light");
  });

  test("rejects garbage as no choice", () => {
    expect(readStoredTheme(() => "blue")).toBeNull();
    expect(readStoredTheme(nothing)).toBeNull();
  });

  test("a throwing localStorage reads as no choice, not a crash", () => {
    const throws = (): string | null => {
      throw new Error("private window");
    };
    expect(readStoredTheme(throws)).toBeNull();
  });
});

describe("storeTheme", () => {
  test("stores the choice", () => {
    const pairs: Array<[string, string]> = [];
    storeTheme((k, v) => pairs.push([k, v]), "dark");
    expect(pairs).toEqual([["spydra-theme", "dark"]]);
  });

  test("a throwing localStorage does not crash the toggle", () => {
    expect(() =>
      storeTheme(() => {
        throw new Error("private window");
      }, "light"),
    ).not.toThrow();
  });
});

describe("initialTheme", () => {
  test("the stored choice wins over prefers-color-scheme", () => {
    expect(initialTheme(() => "light", true)).toBe("light");
    expect(initialTheme(() => "dark", false)).toBe("dark");
  });

  test("first visit follows prefers-color-scheme, light by default", () => {
    expect(initialTheme(nothing, true)).toBe("dark");
    expect(initialTheme(nothing, false)).toBe("light");
  });
});

test("toggleTheme inverts", () => {
  expect(toggleTheme("light")).toBe("dark");
  expect(toggleTheme("dark")).toBe("light");
});
