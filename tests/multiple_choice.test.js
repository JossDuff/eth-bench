const assert = require("node:assert/strict");
const { test } = require("node:test");

const grade = require("../src/multiple_choice.js");
const { parseAnswer } = grade;

const FOUR = ["A", "B", "C", "D"];

test("parseAnswer, single answer", () => {
  const cases = [
    ["ANSWER: B", ["B"]],
    ["answer: b", ["B"]],
    ["ANSWER: B.", ["B"]],
    ["ANSWER:C", ["C"]],
    ["Some reasoning first.\n\nANSWER: D", ["D"]],
    ["ANSWER: A\nANSWER: C", ["C"]],
    // A line-start match beats a later inline mention, as in Inspect.
    ["ANSWER: A\nOn reflection, ANSWER: C", ["A"]],
    ["The answer: B", ["B"]],
    ["ANSWER: A, B", null],
    ["ANSWER: E", null],
    ["I think it is B", null],
    ["", null],
  ];
  for (const [output, expected] of cases) {
    assert.deepEqual(parseAnswer(output, FOUR, false), expected, JSON.stringify(output));
  }
});

test("parseAnswer, multiple answers", () => {
  const cases = [
    ["ANSWER: A, C", ["A", "C"]],
    ["ANSWER: C,A", ["A", "C"]],
    ["ANSWER: A and C", ["A", "C"]],
    ["ANSWER: AC", ["A", "C"]],
    ["ANSWER: B", ["B"]],
    ["ANSWER: A, E", null],
  ];
  for (const [output, expected] of cases) {
    assert.deepEqual(parseAnswer(output, FOUR, true), expected, JSON.stringify(output));
  }
});

test("grade compares the letter set with the answer key", () => {
  const context = (answer, extra = {}) => ({ vars: { choices: ["w", "x", "y", "z"], answer, ...extra } });

  assert.equal(grade("ANSWER: B", context("B")).pass, true);
  assert.equal(grade("ANSWER: C", context("B")).pass, false);
  assert.equal(grade("no idea", context("B")).pass, false);
  assert.match(grade("no idea", context("B")).reason, /No ANSWER line/);

  const multi = { multiple_correct: true };
  assert.equal(grade("ANSWER: A, C", context("A, C", multi)).pass, true);
  assert.equal(grade("ANSWER: C, A", context("A, C", multi)).pass, true);
  assert.equal(grade("ANSWER: A", context("A, C", multi)).pass, false, "no partial credit");
  assert.equal(grade("ANSWER: A, B, C", context("A, C", multi)).pass, false);
});
