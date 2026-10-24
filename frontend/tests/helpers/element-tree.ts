import { isValidElement, type ReactElement, type ReactNode } from "react";

// Wiring assertions for a string-render harness. renderToStaticMarkup drops
// event handlers, but a function component invoked with its props returns a
// plain element tree whose onClick props are still intact — so the matrix's
// behavioural contract (Tag onRemove, Modal confirm/cancel, Pagination
// bounds…) is tested by finding the element and invoking its handler, with
// no DOM and no new devDependencies (task file, "Decided").

export function prop(element: ReactElement, name: string): unknown {
  return (element.props as Record<string, unknown>)[name];
}

/** Every element in the tree (depth-first) matching `predicate`. */
export function findAll(
  root: ReactNode,
  predicate: (element: ReactElement) => boolean,
): ReactElement[] {
  const found: ReactElement[] = [];
  const visit = (node: ReactNode): void => {
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (!isValidElement(node)) return;
    if (predicate(node)) found.push(node);
    const children = (node.props as { children?: ReactNode }).children;
    visit(children);
  };
  visit(root);
  return found;
}

export function findOne(
  root: ReactNode,
  predicate: (element: ReactElement) => boolean,
): ReactElement {
  const found = findAll(root, predicate);
  if (found.length !== 1) {
    throw new Error(
      `expected exactly one matching element, got ${found.length}`,
    );
  }
  return found[0]!;
}

/** Invoke the element's onClick — the harness-side "click". */
export function click(element: ReactElement): void {
  const handler = prop(element, "onClick");
  if (typeof handler !== "function") {
    throw new Error("element carries no onClick to invoke");
  }
  (handler as () => void)();
}
