// A small Python highlighter for the read-only code view. Good enough for the
// part programs Jig writes; the editable Code tab will use a full editor.

export type TokenKind = "kw" | "str" | "num" | "com" | "fn" | "cls" | "param" | "text";
export interface Token {
  kind: TokenKind;
  text: string;
}

const KEYWORDS = new Set(
  "and as assert break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield".split(" "),
);

const PATTERN =
  /(#.*$)|("""|''')|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(\b\d+(?:\.\d*)?(?:[eE][-+]?\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|.)/g;

/** Tokenize source into lines of tokens, carrying triple-quoted strings across lines. */
export function highlightPython(source: string): Token[][] {
  const lines = source.split("\n");
  const out: Token[][] = [];
  let openQuote: string | null = null;
  let previousWord = "";
  for (const line of lines) {
    const tokens: Token[] = [];
    let rest = line;
    if (openQuote) {
      const end = rest.indexOf(openQuote);
      if (end < 0) {
        out.push([{ kind: "str", text: rest }]);
        continue;
      }
      tokens.push({ kind: "str", text: rest.slice(0, end + 3) });
      rest = rest.slice(end + 3);
      openQuote = null;
    }
    PATTERN.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = PATTERN.exec(rest))) {
      const [text, comment, triple, string, number, word] = match;
      if (comment) tokens.push({ kind: "com", text });
      else if (triple) {
        const end = rest.indexOf(triple, PATTERN.lastIndex);
        if (end < 0) {
          tokens.push({ kind: "str", text: rest.slice(match.index) });
          openQuote = triple;
          break;
        }
        tokens.push({ kind: "str", text: rest.slice(match.index, end + 3) });
        PATTERN.lastIndex = end + 3;
      } else if (string) tokens.push({ kind: "str", text });
      else if (number) tokens.push({ kind: "num", text });
      else if (word) {
        let kind: TokenKind = "text";
        if (KEYWORDS.has(word)) kind = "kw";
        else if (previousWord === "def") kind = "fn";
        else if (/^[A-Z][A-Z0-9_]+$/.test(word)) kind = "param";
        else if (/^[A-Z]/.test(word)) kind = "cls";
        tokens.push({ kind, text });
        previousWord = word;
        continue;
      } else tokens.push({ kind: "text", text });
      if (text.trim()) previousWord = "";
    }
    out.push(tokens);
  }
  return out;
}
