# Viva Preparation: Questions and Answers

**1. What is an AI Test Case Generator Agent?**
A program that reads a software requirement in plain English and, through several steps (understand, choose scenarios, generate, validate), produces structured test cases. It is "agentic" because it follows a multi-stage workflow and decides which scenario types are needed instead of answering in one shot.

**2. What problem does it solve?**
Writing test cases by hand is slow and testers often forget negative and boundary cases. The tool creates a first draft in seconds that the tester reviews, edits and exports.

**3. Why did you choose Streamlit?**
It lets me build a complete interactive dashboard (text area, tables, forms, download button) in pure Python without HTML/JavaScript. It was also a required technology.

**4. What is Ollama?**
A tool that downloads and runs open-source large language models on your own computer and serves them through a local API (`http://localhost:11434`).

**5. Why use a local LLM?**
Privacy (requirements never leave the machine), no API cost, works offline after download, and no API keys. Trade-off: slower and less accurate than large cloud models.

**6. What is LangChain?**
A Python framework for building LLM applications. I use `ChatOllama` from `langchain-ollama` to send system and user messages to the local model and get text back, and I organise the agent in stages around it.

**7. How does the agent understand requirements?**
Stage 1 sends the requirement to the model with a prompt asking only for analysis: feature name, summary, testing purpose, conditions, assumptions and whether the text is clear. Python also rejects empty or very short input before calling the model. If the model says it is unclear, the user gets a clarification question.

**8. How are positive, negative and edge cases generated?**
Stage 2 asks the model to choose scenarios and label each as Positive, Negative or Edge (valid flow; invalid or missing input; boundaries, long text, special characters). Stage 3 writes one test case per selected scenario. Python checks the labels, and warns if a type is missing.

**9. How is JSON validated?**
`extract_json` removes code fences and extra text and parses the JSON. `validate_response` then checks required fields, ID format `TC-001` and uniqueness, scenario type, priority (High/Medium/Low), non-empty steps and expected result, and that test data is an object. It removes duplicates and renumbers IDs. If anything fails, the agent retries once with the error message; if it fails again the user sees a clear error and nothing is saved.

**10. Why is SQLite used?**
It is built into Python, needs no server, stores everything in one file, and keeps data after restart. Two tables (requirements, test_cases) are linked by a foreign key, and a requirement with its test cases is saved in one transaction.

**11. How does CSV export work?**
Test cases are converted into a Pandas DataFrame (the same one shown on screen), then `df.to_csv()` creates the file, encoded as UTF-8 with BOM so Excel on Windows opens it correctly. Streamlit's download button serves the bytes. Cells starting with `=`, `+`, `-` or `@` are escaped to prevent spreadsheet formula injection.

**12. How are errors handled?**
Each case has its own exception and a friendly message: empty requirement (warning), unclear requirement (clarification + "generate anyway"), invalid model output (one retry, then error), Ollama not running (start instructions), model missing (`ollama pull` command), database errors (message; app keeps running). A final catch-all prevents raw tracebacks.

**13. What are the limitations?**
Output quality depends on the model size; slow on CPUs; it cannot know rules not in the requirement (it lists assumptions); single-user; English works best; test cases need human review.

**14. What future enhancements can be added?**
Import from Jira or documents, export to Excel/TestRail, generate automated test code (Selenium/Playwright), coverage reports, history search, prompt/model comparison, and multi-user accounts.

## Extra questions you may be asked

- **Why three LLM calls instead of one?** Separating understanding, scenario selection and generation gives better focus, lets me validate each step, and shows a visible agent workflow.
- **How do you avoid invented rules?** The prompt forbids it and asks for assumptions; the UI displays assumptions separately.
- **How do you avoid duplicates?** The prompt asks for non-duplicates and Python removes cases with the same type and normalised title.
- **Why `format="json"`?** It makes Ollama constrain the output to valid JSON, reducing parse failures; Python validation is still needed because valid JSON can have wrong content.
- **Where are the prompts?** `prompts.py`.
- **What did you test, and what did you not?** Logic is covered by 19 automated tests with a fake model; real-model and browser tests are done manually (see the testing report).
