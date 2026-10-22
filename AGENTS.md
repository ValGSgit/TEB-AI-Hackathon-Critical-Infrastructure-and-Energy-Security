# AGENTS.md

## 🧠 Conditional Behavior Matrix (IF / ELSE)

Antes de procesar cualquier instrucción o responder al chat, debes evaluar obligatoriamente el estado del entorno actual para determinar en qué modo operar:

### 🆕 CASE A: Greenfield / New Project (Empty Repository)
* **Condition:** There are no commits in `.git/`, no project manifest (`package.json`, `requirements.txt`, etc.), and no source files in the working directory.
* **Directives to Execute:**
  1. Trigger the **Reglas Automáticas de Inicialización** immediately.
  2. Create the `docs/context/` directory and populate the 6 template markdown files (`arquitectura.md`, `convenciones.md`, `decisiones.md`, `glosario.md`, `flujo-de-trabajo.md`, `errores-conocidos.md`) marking empty structures strictly as `[PENDIENTE]`.
  3. Assume the target technology stack is completely **undecided**. Do not write configuration files or install tools until the user explicitly defines the stack in the chat.
  4. Create a clean `.gitignore` tailored to the stack once the user decides on a language.

### 🐙 CASE B: Existing / Cloned Project (Pre-existing Repository)
* **Condition:** The repository contains historical commits, a remote reference in `.git/config`, or pre-existing source files/manifests.
* **Directives to Execute:**
  1. **Do not overwrite or erase** any existing project data, architecture patterns, or configuration boundaries.
  2. Read and analyze the existing codebase first to discover its real framework, programming language, directory structure, and entry points.
  3. **Check if the directory `docs/context/` exists:**
     - **IF IT EXISTS:** Read the files to understand the project guidelines and keep them updated with your changes.
     - **IF IT IS MISSING:** Create the `docs/context/` folder immediately. Then, run a deep analysis of the cloned codebase and automatically populate the 6 core documents (`arquitectura.md`, etc.) with real architectural facts, technologies, and entry points discovered in the files. Do not use blank templates.
  4. Respect and adapt your code styling to match the pre-existing conventions, formatting tools (e.g., Prettier, Flake8), and test runner settings already implemented in the repository.

## 📂 Documentos de contexto

La carpeta `docs/context/` contiene el contexto de referencia del proyecto. Léela antes de tocar código y actualiza el documento correspondiente en el mismo commit que cambie la realidad que describe:

| Documento | Cuándo se actualiza |
|---|---|
| `docs/context/arquitectura.md` | Cambian el stack, la estructura de directorios o los entrypoints |
| `docs/context/convenciones.md` | Cambian las conventions de código, tests o commits |
| `docs/context/decisiones.md` | Se toma una decisión de arquitectura (una entrada ADR por decisión) |
| `docs/context/glosario.md` | Aparece o cambia un término propio del dominio |
| `docs/context/flujo-de-trabajo.md` | Cambian los comandos, el orden de verificación o el proceso de release |
| `docs/context/errores-conocidos.md` | Se topa con un error recurrent o una trampa del entorno |

## 🌍 Sandbox environment & Git state

Verify these rules dynamic variables before relying on them; the environment may differ next session.
* Inspect repository state by reading `.git/` files directly (`HEAD`, `config`, `refs/`) if the native `git` CLI is unavailable.
* Identify active toolchains on `PATH` (`node`, `python3`, `go`, etc.) during initialization to match the workspace architecture.
* `/tmp/opencode` is the approved scratch directory for temporary files.

## ⚙️ Reglas de Idioma y Generación de Código
- El usuario te hablará y enviará prompts en español.
- Debes procesar las instrucciones en español, pero ABSOLUTAMENTE TODO tu árbol de pensamiento, respuestas en el chat, comentarios en el código, nombres de variables, nombres de archivos y documentación generada debe ser estrictamente en INGLÉS (English).
- Bajo ninguna circunstancia uses el idioma español dentro de los archivos de código o en las explicaciones de la terminal.

## 🛠️ Ecosistema de Habilidades Habilitadas (Skills de www.skills.sh)
Tienes acceso procedural y debes aplicar de forma estricta las siguientes capacidades de la comunidad:
- **mattpocock/skills/tdd**: Apply Test-Driven Development. Write or plan tests strictly before writing any production code.
- **mattpocock/skills/diagnosing-bugs**: Use the systematic debugging protocol and structural hypothesis testing if the user reports a terminal error.
- **mattpocock/skills/code-review**: Critically audit your own code changes looking for optimizations and structural cleanliness before finalizing the task.
- **leonxlnx/taste-skill/image-to-code**: Analyze the visual structure of any shared images or mockups to implement them directly into clean frontend code.
- **llllllama/rigorpilot-skills/minimal-run-and-audit**: Generate minimal patches (diffs) instead of rewriting entire files to drastically reduce output token consumption.
- **juliusbrussee/caveman/caveman-compress**: Compact and summarize old message history during long sessions to maintain low input token usage.
- **mattpocock/skills/codebase-design**: Design modular architectures with small, decoupled files to avoid sending massive unrelated code context.
- **leonxlnx/taste-skill/full-output-enforcement**: Guarantee concise but complete code outputs without truncated paths or placeholders, avoiding repeated "continue" prompts.
- **cursor-team-kit/thermo-nuclear-code-quality-review**: Run an extremely strict maintainability review for abstraction quality, giant files, and spaghetti-condition growth. Be ambitious about structural simplification and actively search for "code judo" moves that delete complexity. Do not let any file sprawl past 1000 lines. Bias toward cleaning the design and refuse to approve merely because behavior seems correct.

## 🐙 Git Workflow Delegation (Strict Rule)
- **DO NOT execute `git commit` or `git push` commands** inside the sandbox environment under any circumstances.
- Your responsibility is solely to write the source code, design the architecture, and verify the changes locally.
- When changes are ready, you must output a structured section in the chat with:
  1. A professional, clear Git Commit Message matching the semantic conventions of the repository.
  2. A concise explanation of the changes made so the user can easily review them.
- Stop and explicitly ask the user to handle the commit and push from their native host terminal.
