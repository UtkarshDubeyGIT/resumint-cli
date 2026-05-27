<img width="1983" height="793" alt="ChatGPT Image May 27, 2026 at 09_18_53 PM" src="https://github.com/user-attachments/assets/ac528efe-a25f-41ba-9ac4-a3f83530df31" />

# resumint-cli 🙌

**resumint-cli** is an AI-powered resume and cover letter generator designed to tailor your master profile to specific job descriptions in seconds. Powered by the **Google Gemini API** and compiled locally using **Tectonic (LaTeX)**, it ensures your resume remains ATS-friendly, professional, and directly targeted to the role.

```
  ___  ___ ___ _   _ __  __ ___ _  _ _____ 
 | _ \/ __| __| | | |  \/  |_ _| \| |_   _|
 |   /\__ \ _| |_| | |\/| || || .` | | |  
 |_|_\|___/___|\___/|_|  |_|___|_|\_| |_|  
```

---

## Key Features

- 🎯 **AI-Powered Re-ranking & Tweaking:** Automatically selects the best projects, achievements, and skills based on the Job Description (JD). Re-ranks bullet points to place the most relevant impact metrics first.
- 💻 **Interactive TUI & Profile Editor:** Edit your contact information and preview your master profile yaml directly within a premium dark terminal interface.
- 📝 **Cover Letter Generator:** Automatically drafts a professional cover letter matching your customized resume, adopting your personal tone.
- 🛠 **Local LaTeX Compilation:** Generates clean, type-perfect PDFs on your machine using `tectonic`.
- ⚙️ **Self-Healing Virtual Environment:** Global npm wrapper automatically sets up and maintains its own Python virtual environment.

---

## Installation & Setup

### 1. Prerequisites

Make sure you have **Node.js (>=16)**, **Python (>=3.10)**, and the **Tectonic** LaTeX compiler installed on your system.

If you have [Homebrew](https://brew.sh/) installed, you can install Tectonic using:
```bash
brew install tectonic
```
*(If Tectonic is missing, resumint-cli will offer to auto-install it via Homebrew on first run).*

### 2. Global Installation

Install the package globally via npm:
```bash
npm install -g resumint-cli
```

### 3. Initialize Workspace

Run the initialization command to scaffold your configuration directory in `~/.resumint`:
```bash
resumint-cli init
```

This scaffolds the following directory structure:
```
~/.resumint/
├── profile.yaml          # Your master profile database (projects, skills, etc.)
├── .env                  # Contains your GEMINI_API_KEY
├── templates/            # Put custom LaTeX .tex files here to override package defaults
└── jds/                  # Directory to save job descriptions
```

---

## 🔑 Gemini API Key Configuration

To use the AI tailoring features, you need a Google Gemini API key:

1. Head over to [Google AI Studio](https://aistudio.google.com/) and create a free API key.
2. Open `~/.resumint/.env` in your editor and add your key:
   ```env
   GEMINI_API_KEY=your_actual_api_key_here
   GEMINI_MODEL=gemini-2.5-flash
   ```
   *(Alternatively, you can export `GEMINI_API_KEY` in your shell profile).*

---

## 🚀 How to Use

### A. The Interactive TUI (Recommended)
Simply type:
```bash
resumint-cli
```
This launches a beautiful, tabbed terminal dashboard:
1. **Tailor Resume Tab:** Enter target company name, select resume type, paste the JD & any custom instruction prompts, and click **Generate Resume**.
2. **Edit Profile Tab:** Edit your personal contact details, save directly, or press **Open in External Editor** to open your entire `profile.yaml` file in your favorite terminal editor (e.g. Nano/Vim).

### B. The CLI Headless Mode (Automation/Scripts)
Generate tailored resumes directly from a file:
```bash
resumint-cli --type sde --company Google --jd ~/.resumint/jds/sde_google.txt --cover
```
**Available flags:**
- `--type`: `sde`, `ai`, or `research`
- `--company`: Name of target company
- `--jd`: Path to text file containing job description/context
- `--cover`: (Optional) Generate matching cover letter
- `--max-projects`: (Optional) Limit selected projects (Default: 3)
- `--max-achievements`: (Optional) Limit selected achievements (Default: 5)
- `--output-dir`: (Optional) Custom path for output PDFs (Default: `~/resumint-output`)

---

## 💡 Maximum Efficacy Guide

To get the absolute best results out of `resumint-cli`, follow these core tips:

### 1. Build a Comprehensive `profile.yaml`
Do not limit your `profile.yaml` to a single page. It is your master database! 
- Add **5 to 8 projects** and **10+ achievements**.
- Write multiple bullet points per project (e.g. 4-6 lines) spanning different angles (e.g., frontend, performance, scaling, DB optimization).
- Gemini will select the best 3 projects and the best 3-4 bullet points per project that directly fit the target job.

### 2. Leverage Profile Tagging
Use tags in your `profile.yaml` (e.g. `tags: [sde, ai, research]`) to tell the generator which context projects belong to.
- For example, if you apply for an ML engineer role using `--type ai`, the engine prioritizes projects and achievements tagged with `ai` or `ml`, falling back to general SDE items only if needed.

### 3. Customize Your Personal Voice
The `personal_voice` block at the bottom of `profile.yaml` controls how the LLM drafts your cover letter and tweaks your bullet points:
```yaml
personal_voice:
  tone: "Professional, confident, and metrics-oriented."
  style_guidelines: "Direct and technical. Emphasize scale, latency numbers, and design decisions."
```
Make this reflect your style!

### 4. Provide Custom Prompt Instructions
Don't just paste the Job Description. Include custom instructions in the TUI context text area or JD file:
```markdown
[JOB DESCRIPTION]
... paste JD here ...

[CUSTOM INSTRUCTION]
Focus heavily on my distributed database and backend systems experience.
Make sure to emphasize Go and Kubernetes.
```

---

## 🎨 Customizing Templates

`resumint-cli` comes with professional, ATS-optimized off-campus LaTeX templates. If you want to customize the look or add university-specific formats:

1. Copy the default templates from the package directory or create your own `.tex` files.
2. Put them in `~/.resumint/templates/` with the names:
   - `sde_offcampus.tex`
   - `ai_offcampus.tex`
   - `research_offcampus.tex`
   - `cover_letter.tex`
3. Files placed in your home folder `~/.resumint/templates/` automatically take priority.
4. Use standard **Jinja2** styling to output profile values:
   - `((( personal_info.name )))` for variables.
   - `((% for project in projects %))` / `((% endfor %))` for control blocks.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/UtkarshDubeyGIT/resumint-cli/issues).

---

## License

MIT © Utkarsh Dubey
