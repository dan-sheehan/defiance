"use strict";

const form = document.querySelector("#ask-form");
const questionInput = document.querySelector("#question");
const submitButton = document.querySelector("#submit-question");
const loading = document.querySelector("#loading");
const result = document.querySelector("#result");
const resultHeading = document.querySelector("#result-heading");
const answerText = document.querySelector("#answer-text");
const sourceList = document.querySelector("#source-list");
const suggestionList = document.querySelector("#suggestion-list");
const askAnother = document.querySelector("#ask-another");
const exampleButtons = Array.from(document.querySelectorAll("[data-question]"));
let pending = false;

function questionButtons() {
  return [...exampleButtons, ...suggestionList.querySelectorAll("button")];
}

function setPending(value) {
  pending = value;
  form.setAttribute("aria-busy", String(value));
  questionInput.disabled = value;
  submitButton.disabled = value;
  askAnother.disabled = value;
  for (const button of questionButtons()) {
    button.disabled = value;
  }
  loading.hidden = !value;
}

function makeQuestionButton(question) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = question;
  button.addEventListener("click", () => submitQuestion(question));
  return button;
}

function renderSources(evidence) {
  sourceList.replaceChildren();
  if (!Array.isArray(evidence) || evidence.length === 0) {
    return;
  }
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = `Sources (${evidence.length})`;
  const list = document.createElement("ul");
  list.className = "sources";
  for (const source of evidence) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.textContent = source.label;
    link.href = source.original_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    item.append(link);
    list.append(item);
  }
  details.append(summary, list);
  sourceList.append(details);
}

function renderSuggestions(suggestions) {
  suggestionList.replaceChildren();
  if (!Array.isArray(suggestions) || suggestions.length === 0) {
    return;
  }
  const block = document.createElement("div");
  block.className = "suggestion-block";
  const heading = document.createElement("h3");
  heading.textContent = "Try asking";
  const buttons = document.createElement("div");
  buttons.className = "suggestions";
  for (const suggestion of suggestions) {
    buttons.append(makeQuestionButton(suggestion));
  }
  block.append(heading, buttons);
  suggestionList.append(block);
}

function showResult(status, text, evidence = [], suggestions = []) {
  result.dataset.status = status;
  answerText.textContent = text;
  renderSources(evidence);
  renderSuggestions(suggestions);
  result.hidden = false;
  resultHeading.focus({ preventScroll: true });
  result.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function submitQuestion(question) {
  if (pending) {
    return;
  }
  if (typeof question !== "string" || question.trim() === "") {
    showResult("invalid_request", "Enter one complete question about the 2017 season.");
    questionInput.focus();
    return;
  }

  result.hidden = true;
  setPending(true);
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const message = payload?.error?.message ?? "Defiance couldn't answer that right now. Try again.";
      showResult("request_error", message);
      return;
    }
    showResult(payload.status, payload.text, payload.evidence, payload.suggestions);
    form.reset();
  } catch {
    showResult("network_error", "Defiance couldn't answer that right now. Try again.");
  } finally {
    setPending(false);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitQuestion(questionInput.value);
});

for (const button of exampleButtons) {
  button.addEventListener("click", () => submitQuestion(button.dataset.question));
}

askAnother.addEventListener("click", () => {
  questionInput.focus();
  questionInput.scrollIntoView({ behavior: "smooth", block: "center" });
});
