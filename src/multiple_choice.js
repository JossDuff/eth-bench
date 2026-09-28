// promptfoo javascript assertion for multiple choice questions.
//
// The model was asked for an `ANSWER: X` line. The last such line is parsed and the
// set of letters it names must equal the answer key exactly (no partial credit for
// multiple-correct questions). The parsing rules are those of Inspect AI's
// multiple_choice solver, so results stay comparable with the Inspect version.

const LETTERS = "ABCDEFGH";

const STRICT = /^ANSWER\s*:\s*([A-Za-z\d ,]+)\s*(?:$|\n|\.)/gim;
const LOOSE = /ANSWER\s*:\s*([A-Za-z\d ,]+)(?:[^\w]|\n|$|\.)/gi;

function lastMatch(pattern, text) {
  const matches = [...text.matchAll(pattern)];
  return matches.length ? matches[matches.length - 1][1] : null;
}

/**
 * Parse the letters the model chose. Returns a sorted array, or null when no valid
 * answer line was found.
 */
function parseAnswer(output, validLetters, multiple) {
  const text = String(output ?? "");
  let raw = lastMatch(STRICT, text) ?? lastMatch(LOOSE, text);
  if (raw === null) return null;
  raw = raw.trim().replace(/\.$/, "").toUpperCase();

  if (!multiple) {
    const tokens = raw.split(",").map((t) => t.trim()).filter(Boolean);
    return tokens.length === 1 && validLetters.includes(tokens[0]) ? tokens : null;
  }

  const cleaned = raw.replace(/ AND /g, ",").replace(/ /g, "");
  const isValid = (letters) => letters.length > 0 && letters.every((l) => validLetters.includes(l));
  const byComma = cleaned.split(",").filter(Boolean);
  if (isValid(byComma)) return [...new Set(byComma)].sort();
  const byChar = cleaned.replace(/,/g, "").split("");
  if (isValid(byChar)) return [...new Set(byChar)].sort();
  return null;
}

function expectedLetters(vars) {
  return String(vars.answer)
    .split(",")
    .map((l) => l.trim().toUpperCase())
    .filter(Boolean)
    .sort();
}

function grade(output, context) {
  const vars = context.vars;
  const validLetters = LETTERS.slice(0, vars.choices.length).split("");
  const multiple = vars.multiple_correct === true || String(vars.multiple_correct) === "true";
  const expected = expectedLetters(vars);
  const chosen = parseAnswer(output, validLetters, multiple);

  if (chosen === null) {
    return { pass: false, score: 0, reason: `No ANSWER line found; expected ${expected.join(", ")}` };
  }
  const pass = chosen.length === expected.length && chosen.every((l, i) => l === expected[i]);
  return {
    pass,
    score: pass ? 1 : 0,
    reason: pass
      ? `Answered ${chosen.join(", ")}`
      : `Answered ${chosen.join(", ")}; expected ${expected.join(", ")}`,
  };
}

module.exports = grade;
module.exports.parseAnswer = parseAnswer;
