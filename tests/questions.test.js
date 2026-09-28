// Every question file must be a valid eth-bench test file. A failure names the file
// and the question.

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const yaml = require("js-yaml");

const ROOT = path.resolve(__dirname, "..");
const QUESTIONS = path.join(ROOT, "questions");

const TYPES = ["multiple_choice", "open", "false_premise"];
const DIFFICULTIES = ["recall", "understanding", "reasoning"];
const VAR_KEYS = ["type", "question", "choices", "answer", "multiple_correct"];
const METADATA_KEYS = ["section", "type", "difficulty", "source", "tags"];
const LETTERS = "ABCDEFGH";
const ID = /^[a-z0-9]+(-[a-z0-9]+)*$/;

function sections() {
  return fs
    .readdirSync(QUESTIONS, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

function questionFiles(section) {
  return fs
    .readdirSync(path.join(QUESTIONS, section))
    .filter((name) => name.endsWith(".yaml") || name.endsWith(".yml"))
    .sort()
    .map((name) => path.join(QUESTIONS, section, name));
}

function load(file) {
  const tests = yaml.load(fs.readFileSync(file, "utf8"));
  assert.ok(Array.isArray(tests), `${file}: expected a list of tests at the top level`);
  assert.ok(tests.length > 0, `${file}: file is empty`);
  return tests;
}

function checkKeys(actual, allowed, where) {
  const unknown = Object.keys(actual).filter((k) => !allowed.includes(k));
  assert.deepEqual(unknown, [], `${where}: unknown keys ${unknown.join(", ")}`);
}

function answerLetters(answer) {
  return String(answer)
    .split(",")
    .map((l) => l.trim())
    .filter(Boolean);
}

function checkQuestion(t, section, where) {
  assert.equal(typeof t.description, "string", `${where}: description must be a string`);
  const [dir, id, ...rest] = t.description.split("/");
  assert.equal(rest.length, 0, `${where}: description must be <section>/<id>`);
  assert.equal(dir, section, `${where}: description section does not match the directory`);
  assert.match(id ?? "", ID, `${where}: id must be lowercase letters, digits and hyphens`);

  const vars = t.vars ?? {};
  const metadata = t.metadata ?? {};
  checkKeys(vars, VAR_KEYS, `${where} vars`);
  checkKeys(metadata, METADATA_KEYS, `${where} metadata`);

  assert.ok(TYPES.includes(vars.type), `${where}: type must be one of ${TYPES.join(", ")}`);
  assert.equal(metadata.type, vars.type, `${where}: metadata.type must equal vars.type`);
  assert.equal(metadata.section, section, `${where}: metadata.section must be the directory`);
  assert.ok(typeof vars.question === "string" && vars.question.trim(), `${where}: question must be non-empty text`);
  assert.ok(typeof vars.answer === "string" && vars.answer.trim(), `${where}: answer must be non-empty text`);
  if (metadata.difficulty !== undefined) {
    assert.ok(DIFFICULTIES.includes(metadata.difficulty), `${where}: difficulty must be one of ${DIFFICULTIES.join(", ")}`);
  }
  if (metadata.source !== undefined) {
    assert.equal(typeof metadata.source, "string", `${where}: source must be a string`);
  }
  if (metadata.tags !== undefined) {
    assert.ok(Array.isArray(metadata.tags) && metadata.tags.every((x) => typeof x === "string"), `${where}: tags must be a list of strings`);
  }
  if (vars.type === "false_premise") {
    assert.equal(section, "hallucination", `${where}: false_premise questions belong in hallucination/`);
  }

  assert.ok(Array.isArray(t.assert) && t.assert.length === 1, `${where}: exactly one assertion expected`);
  const [a] = t.assert;
  assert.equal(a.metric, section, `${where}: assertion metric must be the section`);

  if (vars.type === "multiple_choice") {
    const choices = vars.choices;
    assert.ok(Array.isArray(choices), `${where}: multiple_choice needs a choices list`);
    assert.ok(choices.length >= 2 && choices.length <= 8, `${where}: need between 2 and 8 choices`);
    assert.ok(choices.every((c) => typeof c === "string"), `${where}: every choice must be a string (quote numbers)`);
    assert.equal(new Set(choices.map((c) => c.trim())).size, choices.length, `${where}: choices must be distinct`);
    const valid = LETTERS.slice(0, choices.length);
    const letters = answerLetters(vars.answer);
    for (const l of letters) {
      assert.ok(valid.includes(l), `${where}: answer letter ${l} is not one of ${valid}`);
    }
    assert.equal(new Set(letters).size, letters.length, `${where}: answer letters must be distinct`);
    if (vars.multiple_correct) {
      assert.ok(letters.length >= 2, `${where}: multiple_correct needs at least two answer letters`);
    } else {
      assert.equal(letters.length, 1, `${where}: answer must be a single letter unless multiple_correct is set`);
    }
    assert.deepEqual({ type: a.type, value: a.value }, { type: "javascript", value: "file://src/multiple_choice.js" }, `${where}: multiple_choice assertion`);
  } else {
    assert.equal(vars.choices, undefined, `${where}: ${vars.type} questions must not have choices`);
    assert.equal(vars.multiple_correct, undefined, `${where}: ${vars.type} questions cannot set multiple_correct`);
    assert.deepEqual({ type: a.type, value: a.value }, { type: "llm-rubric", value: "{{answer}}" }, `${where}: ${vars.type} assertion`);
  }
}

test("every section has question files", () => {
  const all = sections();
  assert.ok(all.length > 0);
  for (const section of all) {
    assert.ok(questionFiles(section).length > 0, `${section}/ has no question files`);
  }
});

test("every question is valid and ids are unique", () => {
  const seen = new Map();
  for (const section of sections()) {
    for (const file of questionFiles(section)) {
      const rel = path.relative(ROOT, file);
      load(file).forEach((t, i) => {
        const where = `${rel} (${t?.description ?? `item ${i}`})`;
        checkQuestion(t, section, where);
        assert.ok(!seen.has(t.description), `${where}: duplicate id, also in ${seen.get(t.description)}`);
        seen.set(t.description, rel);
      });
    }
  }
  assert.ok(seen.size > 0);
});

test("correct letters are spread across positions", () => {
  // Nothing shuffles choices at run time, so the files themselves must not favour a
  // position. A model that always picked the most common letter should gain little.
  const counts = {};
  let total = 0;
  for (const section of sections()) {
    for (const file of questionFiles(section)) {
      for (const t of load(file)) {
        if (t.vars.type !== "multiple_choice" || t.vars.multiple_correct) continue;
        const letter = answerLetters(t.vars.answer)[0];
        counts[letter] = (counts[letter] ?? 0) + 1;
        total += 1;
      }
    }
  }
  for (const [letter, n] of Object.entries(counts)) {
    assert.ok(n / total <= 0.4, `${letter} is the answer to ${n} of ${total} questions; move some correct choices elsewhere`);
  }
});
