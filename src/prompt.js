// Prompt functions for promptfoo. Each returns a chat messages array.
//
// Every question type shares one code path so nothing about the prompt hints at the
// question type beyond the presence of choices: open and false-premise questions
// are presented identically.
//
//   bare      the question alone
//   tools     for providers with MCP tools: adds a hint to check facts with the tools
//   ethskills the ethskills index (https://ethskills.com/SKILL.md) inlined as system text

const FREE_TEXT_SYSTEM =
  "You are answering questions about Ethereum. Think the question through, then give a clear, direct answer.";

const MC_SYSTEM =
  "You are answering a multiple choice question about Ethereum. Reply in exactly the format the question asks for.";

const MC_TOOLS_HINT =
  "Call the available tools first to check the facts, then give your final reply in that format.";

const TOOLS_HINT =
  "You have tools available. Use them to look up anything you are not certain of before answering.";

const ETHSKILLS_URL = "https://ethskills.com/SKILL.md";
const MAX_DOCUMENT_CHARS = 100_000;

const LETTERS = "ABCDEFGH";

function isTrue(value) {
  return value === true || String(value).toLowerCase() === "true";
}

// The multiple choice templates are those of Inspect AI's multiple_choice solver, so
// results stay comparable with the Inspect version of this benchmark.
function multipleChoicePrompt(vars) {
  const choices = vars.choices.map((choice, i) => `${LETTERS[i]}) ${choice}`).join("\n");
  const letters = LETTERS.slice(0, vars.choices.length).split("").join(",");
  const multiple = isTrue(vars.multiple_correct);
  const cot = isTrue(vars.cot);

  const question = multiple
    ? "Answer the following multiple choice question where multiple answers may be correct."
    : "Answer the following multiple choice question.";
  const format = multiple
    ? `'ANSWER: $LETTERS' (without quotes) where LETTERS is one or more of ${letters}.`
    : `'ANSWER: $LETTER' (without quotes) where LETTER is one of ${letters}.`;
  const instruction = cot
    ? `The last line of your response should be of the following format: ${format} Think step by step before answering.`
    : `The entire content of your response should be of the following format: ${format}`;

  return `${question} ${instruction}\n\n${vars.question}\n\n${choices}`;
}

function messages(vars, { mcSystem, freeTextSystem }) {
  if (vars.type === "multiple_choice") {
    const result = [];
    if (mcSystem) result.push({ role: "system", content: mcSystem });
    result.push({ role: "user", content: multipleChoicePrompt(vars) });
    return result;
  }
  return [
    { role: "system", content: freeTextSystem },
    { role: "user", content: vars.question },
  ];
}

function bare({ vars }) {
  return messages(vars, { mcSystem: null, freeTextSystem: FREE_TEXT_SYSTEM });
}

function tools({ vars }) {
  return messages(vars, {
    mcSystem: `${MC_SYSTEM} ${MC_TOOLS_HINT}\n\n${TOOLS_HINT}`,
    freeTextSystem: `${FREE_TEXT_SYSTEM}\n\n${TOOLS_HINT}`,
  });
}

let ethskillsDocument;

async function fetchDocument(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`could not fetch ${url}: HTTP ${response.status}`);
  }
  let text = await response.text();
  if (text.length > MAX_DOCUMENT_CHARS) {
    text = `${text.slice(0, MAX_DOCUMENT_CHARS)}\n\n[truncated at ${MAX_DOCUMENT_CHARS} characters]`;
  }
  return text;
}

async function ethskills({ vars }) {
  // Fetched once per process; promptfoo calls the prompt function once per test.
  ethskillsDocument ??= fetchDocument(ETHSKILLS_URL);
  const skill = `# Skill: ethskills\nSource: ${ETHSKILLS_URL}\n\n${await ethskillsDocument}`;
  return messages(vars, {
    mcSystem: `${MC_SYSTEM}\n\n${skill}`,
    freeTextSystem: `${FREE_TEXT_SYSTEM}\n\n${skill}`,
  });
}

module.exports = { bare, tools, ethskills, multipleChoicePrompt, FREE_TEXT_SYSTEM, MC_SYSTEM };
