// Empty rule set on purpose: prettier owns formatting, tsc --noEmit owns
// types, and there is no TS-capable eslint parser for typescript@7 — the
// Go port has no JS API, so typescript-eslint peers <6.1.0 only. Revisit
// when typescript-eslint (or core eslint) supports TS 7; until then eslint
// covers .js/.mjs and every src file is .ts.
export default [];
