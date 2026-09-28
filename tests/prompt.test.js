const assert = require("node:assert/strict");
const { test } = require("node:test");

const { bare, tools, FREE_TEXT_SYSTEM, MC_SYSTEM } = require("../src/prompt.js");

// The prompt promises an `ANSWER: X` line and the question files grade it with a
// regex. A model that follows the prompt must pass.
const MC_REGEX = (answer) => new RegExp(`ANSWER:\\W*${answer}\\b(?!\\s*,\\s*[A-H]\\b)`);

test("a reply in the requested format passes the multiple choice regex", () => {
  assert.ok(MC_REGEX("C").test("ANSWER: C"));
  assert.ok(MC_REGEX("C").test("ANSWER: C."));
  assert.ok(MC_REGEX("C").test("Reasoning...\n\nANSWER: C"));
  assert.ok(!MC_REGEX("C").test("ANSWER: D"));
  assert.ok(!MC_REGEX("C").test("ANSWER: C, D"));
  assert.ok(!MC_REGEX("C").test("ANSWER: CD"));
});

const mc = { type: "multiple_choice", question: "Which fork shipped PUSH0?", choices: ["Berlin", "London", "Shanghai", "Cancun"], answer: "C" };
const open = { type: "open", question: "What does DELEGATECALL preserve?", answer: "msg.sender and storage" };

test("bare multiple choice uses the strict Inspect template and no system message", () => {
  const messages = bare({ vars: mc });
  assert.deepEqual(
    messages.map((m) => m.role),
    ["user"],
  );
  assert.equal(
    messages[0].content,
    "Answer the following multiple choice question. The entire content of your response should be of the following format: 'ANSWER: $LETTER' (without quotes) where LETTER is one of A,B,C,D.\n\n" +
      "Which fork shipped PUSH0?\n\n" +
      "A) Berlin\nB) London\nC) Shanghai\nD) Cancun",
  );
});

test("cot switches to the last-line template", () => {
  for (const cot of [true, "true"]) {
    const [message] = bare({ vars: { ...mc, cot } });
    assert.match(message.content, /^Answer the following multiple choice question\. The last line of your response should be of the following format: 'ANSWER: \$LETTER' \(without quotes\) where LETTER is one of A,B,C,D\. Think step by step before answering\.\n\n/);
  }
  const [strict] = bare({ vars: { ...mc, cot: "false" } });
  assert.match(strict.content, /The entire content of your response/);
});

test("multiple_correct asks for one or more letters", () => {
  const [message] = bare({ vars: { ...mc, multiple_correct: true, answer: "A, C" } });
  assert.match(message.content, /^Answer the following multiple choice question where multiple answers may be correct\. The entire content of your response should be of the following format: 'ANSWER: \$LETTERS' \(without quotes\) where LETTERS is one or more of A,B,C,D\.\n\n/);
});

test("letters follow the number of choices", () => {
  const [message] = bare({ vars: { ...mc, choices: ["a", "b"] } });
  assert.match(message.content, /LETTER is one of A,B\./);
  assert.match(message.content, /A\) a\nB\) b$/);
});

test("open and false-premise questions get the same system prompt and the bare question", () => {
  for (const type of ["open", "false_premise"]) {
    const messages = bare({ vars: { ...open, type } });
    assert.deepEqual(messages, [
      { role: "system", content: FREE_TEXT_SYSTEM },
      { role: "user", content: open.question },
    ]);
    assert.doesNotMatch(messages[1].content, /ANSWER:/);
  }
});

test("tools variant adds the tools hint", () => {
  const mcMessages = tools({ vars: mc });
  assert.equal(mcMessages[0].role, "system");
  assert.ok(mcMessages[0].content.startsWith(MC_SYSTEM));
  assert.match(mcMessages[0].content, /Call the available tools first/);
  assert.equal(mcMessages[1].content, bare({ vars: mc })[0].content);

  const openMessages = tools({ vars: open });
  assert.ok(openMessages[0].content.startsWith(FREE_TEXT_SYSTEM));
  assert.match(openMessages[0].content, /You have tools available/);
  assert.equal(openMessages[1].content, open.question);
});
