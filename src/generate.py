#!/usr/bin/env python3
"""
resumint-cli — Public AI-powered Tailored Resume and Cover Letter CLI/TUI.
Generates highly tailored resumes using Google Gemini API and Tectonic.
"""

import os
import sys
import re
import glob
import json
import datetime
import subprocess
import argparse
import shutil
import yaml
import jinja2
from dotenv import load_dotenv

# Resolve ~/.resumint pathing
RESUMINT_DIR = os.path.expanduser("~/.resumint")
os.makedirs(RESUMINT_DIR, exist_ok=True)
os.makedirs(os.path.join(RESUMINT_DIR, "templates"), exist_ok=True)
os.makedirs(os.path.join(RESUMINT_DIR, "prompts"), exist_ok=True)
os.makedirs(os.path.join(RESUMINT_DIR, "jds"), exist_ok=True)

# Load env from user directory
load_dotenv(os.path.join(RESUMINT_DIR, ".env"))

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ----------------------------------------------------------------------
# 1. Pydantic Schemas for Gemini Structured Outputs
# ----------------------------------------------------------------------
from pydantic import BaseModel, Field

class ProjectLink(BaseModel):
    label: str = Field(description="Label of the link, e.g. 'GitHub' or 'Live Demo'")
    url: str = Field(description="URL of the link")

class SelectedProject(BaseModel):
    title: str = Field(description="Title of the project, exactly as in the profile")
    date: str = Field(description="Date duration of the project, exactly as in the profile")
    tech_stack: list[str] = Field(description="Selected technologies used in this project")
    links: list[ProjectLink] = Field(description="List of links associated with the project")
    bullet_points: list[str] = Field(
        description="Select and order the best bullet points for this project. Keep formatting plain, use **bold** for key achievements."
    )

class SelectedAchievement(BaseModel):
    description: str = Field(description="Achievement description text. Include bolding/links in markdown format if relevant.")

class SelectedSkillCategory(BaseModel):
    category: str = Field(description="Category of the skills (e.g. Programming Languages)")
    items: list[str] = Field(description="List of selected skill names in this category")

class ResumeSelectionSchema(BaseModel):
    selected_projects: list[SelectedProject] = Field(description="List of selected projects, ordered by relevance")
    selected_achievements: list[SelectedAchievement] = Field(description="List of selected achievements, ordered by relevance")
    selected_skills: list[SelectedSkillCategory] = Field(description="List of selected skills per category")

class CoverLetterSchema(BaseModel):
    recipient_name: str = Field(description="Name/Title of the recipient, e.g. 'Hiring Manager' or 'SDE Recruitment Team'")
    subject: str = Field(description="Subject line, e.g., 'Application for Software Engineer - Google'")
    paragraphs: list[str] = Field(description="List of paragraphs for the body of the cover letter")

# ----------------------------------------------------------------------
# 2. Helper Utilities & LaTeX Escaping
# ----------------------------------------------------------------------
def escape_latex(text):
    if not isinstance(text, str):
        return text
    
    conv = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
        '\\': r'\textbackslash{}',
    }
    
    regex = re.compile('|'.join(re.escape(str(key)) for key in sorted(conv.keys(), key=lambda item: -len(item))))
    escaped = regex.sub(lambda match: conv[match.group()], text)
    
    escaped = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', escaped)
    escaped = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\\href{\2}{\1}', escaped)
    return escaped

def escape_json_data(data):
    if isinstance(data, dict):
        return {k: escape_json_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [escape_json_data(item) for item in data]
    elif isinstance(data, str):
        return escape_latex(data)
    else:
        return data

def clean_and_parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```[a-zA-Z]*\n', '', text)
        text = re.sub(r'\n```$', '', text)
    return json.loads(text.strip())

def check_tectonic():
    try:
        subprocess.run(["tectonic", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def setup_tectonic(log_callback=None):
    def log(msg, level="INFO"):
        if log_callback:
            log_callback(msg, level)
        else:
            print(f"[{level}] {msg}")

    if check_tectonic():
        return True, "Tectonic is already installed."
    
    try:
        subprocess.run(["brew", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        brew_available = True
    except FileNotFoundError:
        brew_available = False
        
    if brew_available:
        log("Tectonic compiler not found. Automatically installing via Homebrew...", "WARNING")
        result = subprocess.run(["brew", "install", "tectonic"], capture_output=True, text=True)
        if result.returncode == 0:
            return True, "Successfully installed Tectonic."
        else:
            return False, f"Failed to install Tectonic: {result.stderr}"
    else:
        return False, "Tectonic compiler missing. Please install it manually: https://tectonic-typesetting.github.io/"

def get_next_serial(company, date_str, output_dir):
    pattern = os.path.join(output_dir, f"{company}_{date_str}_*")
    existing_files = glob.glob(pattern)
    
    max_serial = 0
    for filepath in existing_files:
        filename = os.path.basename(filepath)
        parts = filename.split('_')
        if len(parts) >= 3:
            try:
                serial = int(parts[2])
                if serial > max_serial:
                    max_serial = serial
            except ValueError:
                pass
    return max_serial + 1

# Helper to find template (local user config first, then package default)
def find_asset(asset_subpath, filename):
    user_path = os.path.join(RESUMINT_DIR, asset_subpath, filename)
    if os.path.exists(user_path):
        return user_path
    
    pkg_path = os.path.join(SCRIPT_DIR, asset_subpath, filename)
    if os.path.exists(pkg_path):
        return pkg_path
    
    return None

# ----------------------------------------------------------------------
# 3. Core Generation Logic
# ----------------------------------------------------------------------
def run_generator(company, resume_type, campus_mode, context_input, generate_cover=False, 
                  max_projects=3, max_achievements=5, api_key=None, output_dir=None, log_callback=None):
    def log(msg, level="INFO"):
        if log_callback:
            log_callback(msg, level)
        else:
            print(f"[{level}] {msg}")

    if not output_dir:
        output_dir = os.path.expanduser("~/resumint-output")
    os.makedirs(output_dir, exist_ok=True)

    if not check_tectonic():
        log("Tectonic LaTeX compiler is missing. Attempting auto-install...", "WARNING")
        success, install_msg = setup_tectonic(log_callback)
        if not success:
            log(install_msg, "ERROR")
            raise RuntimeError(install_msg)
        log(install_msg, "INFO")
        
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log("GEMINI_API_KEY is not set. Please set it in ~/.resumint/.env or supply it.", "ERROR")
        raise ValueError("Missing Gemini API Key.")

    log("Loading master profile database...", "INFO")
    profile_path = os.path.join(RESUMINT_DIR, "profile.yaml")
    if not os.path.exists(profile_path):
        raise FileNotFoundError(f"profile.yaml not found at {profile_path}. Run 'resumint-cli init' to scaffold it.")
        
    with open(profile_path, "r") as f:
        profile_data = yaml.safe_load(f)

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log("google-genai SDK not found. Please verify dependencies in requirements.txt", "ERROR")
        raise
        
    client = genai.Client(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    log("Calling Google Gemini API to analyze JD and select matching profile details...", "INFO")
    selector_prompt_path = find_asset("prompts", "selector.txt")
    if not selector_prompt_path:
        raise FileNotFoundError("Selector prompt file selector.txt not found in package.")
        
    with open(selector_prompt_path, "r") as f:
        selector_system_prompt = f.read()

    selection_prompt_body = f"""
Target Resume Type: {resume_type.upper()}
Campus Placement Mode: {campus_mode.upper()}
Max Projects to Select: {max_projects}
Max Achievements to Select: {max_achievements}

Job Description & Context (JD, Policies, Instructions):
--------------------------------------------------
{context_input}
--------------------------------------------------

Master Profile Database:
--------------------------------------------------
{yaml.dump(profile_data, default_flow_style=False)}
--------------------------------------------------
"""

    response = client.models.generate_content(
        model=model_name,
        contents=selection_prompt_body,
        config=types.GenerateContentConfig(
            system_instruction=selector_system_prompt,
            response_mime_type="application/json",
            response_schema=ResumeSelectionSchema,
            temperature=0.1,
        )
    )

    log("Gemini structured output received successfully.", "INFO")
    resume_selection = clean_and_parse_json(response.text)

    for p in resume_selection.get("selected_projects", []):
        flat_links = {}
        for link in p.get("links", []):
            if isinstance(link, dict) and "label" in link and "url" in link:
                flat_links[link["label"]] = link["url"]
        p["links"] = flat_links

    log("Escaping data and translating formatting for LaTeX compatibility...", "INFO")
    escaped_selection = escape_json_data(resume_selection)
    
    escaped_personal_info = escape_json_data(profile_data.get("personal_info", {}))
    escaped_education = escape_json_data(profile_data.get("education", []))

    date_str = datetime.date.today().strftime("%Y-%m-%d")
    clean_company = re.sub(r'[^a-zA-Z0-9]', '', company).capitalize()
    serial_no = get_next_serial(clean_company, date_str, output_dir)
    serial_str = f"{serial_no:02d}"

    campus_suffix = "oncampus" if campus_mode.lower() in ["on", "oncampus"] else "offcampus"
    template_name = f"{resume_type.lower()}_{campus_suffix}.tex"
    
    user_template_dir = os.path.join(RESUMINT_DIR, "templates")
    pkg_template_dir = os.path.join(SCRIPT_DIR, "templates")
    
    jinja_env = jinja2.Environment(
        block_start_string='((%',
        block_end_string='%))',
        variable_start_string='(((',
        variable_end_string=')))',
        comment_start_string='((#',
        comment_end_string='#))',
        loader=jinja2.ChoiceLoader([
            jinja2.FileSystemLoader(user_template_dir),
            jinja2.FileSystemLoader(pkg_template_dir)
        ])
    )
    
    try:
        template = jinja_env.get_template(template_name)
    except jinja2.TemplateNotFound:
        log(f"Template {template_name} not found! Defaulting to sde_offcampus.tex", "WARNING")
        template = jinja_env.get_template("sde_offcampus.tex")

    render_context = {
        "personal_info": escaped_personal_info,
        "education": escaped_education,
        "projects": escaped_selection.get("selected_projects", []),
        "achievements": escaped_selection.get("selected_achievements", []),
        "skills": escaped_selection.get("selected_skills", [])
    }
    
    rendered_tex = template.render(render_context)

    resume_file_basename = f"{clean_company}_{date_str}_{serial_str}_{resume_type.lower()}_resume"
    log(f"Compiling resume to PDF: {output_dir}/{resume_file_basename}.pdf", "INFO")
    
    tex_path = os.path.join(output_dir, f"{resume_file_basename}.tex")
    with open(tex_path, "w") as f:
        f.write(rendered_tex)

    cmd = ["tectonic", "-o", output_dir, tex_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log("Tectonic compilation failed!", "ERROR")
        raise RuntimeError(f"LaTeX compile error:\n{result.stderr}")
    
    resume_pdf_path = os.path.join(output_dir, f"{resume_file_basename}.pdf")
    log("Resume compiled successfully!", "INFO")
    subprocess.run(["open", resume_pdf_path])

    if generate_cover:
        log("Generating cover letter...", "INFO")
        cover_prompt_path = find_asset("prompts", "cover_letter_selector.txt")
        if not cover_prompt_path:
            raise FileNotFoundError("Cover letter prompt cover_letter_selector.txt not found in package.")
            
        with open(cover_prompt_path, "r") as f:
            cover_system_prompt = f.read()

        cover_prompt_body = f"""
Applicant Name: {profile_data['personal_info']['name']}
Company Target: {company}
Resume Type: {resume_type.upper()}
Campus Placement Mode: {campus_mode.upper()}

Job Description & Context:
--------------------------------------------------
{context_input}
--------------------------------------------------

Personal Voice Guidelines & Profile Details:
--------------------------------------------------
{yaml.dump(profile_data.get('personal_voice', {}), default_flow_style=False)}
Selected Skills: {json.dumps(resume_selection.get('selected_skills'))}
Selected Projects: {json.dumps(resume_selection.get('selected_projects'))}
--------------------------------------------------
"""

        response_cover = client.models.generate_content(
            model=model_name,
            contents=cover_prompt_body,
            config=types.GenerateContentConfig(
                system_instruction=cover_system_prompt,
                response_mime_type="application/json",
                response_schema=CoverLetterSchema,
                temperature=0.2,
            )
        )

        log("Cover letter content received from Gemini.", "INFO")
        cover_data = clean_and_parse_json(response_cover.text)
        escaped_cover = escape_json_data(cover_data)

        cover_template = jinja_env.get_template("cover_letter.tex")
        cover_render_context = {
            "personal_info": escaped_personal_info,
            "date": date_str,
            "recipient_name": escaped_cover.get("recipient_name", "Hiring Team"),
            "subject": escaped_cover.get("subject", f"Application for Software Engineer - {company}"),
            "paragraphs": escaped_cover.get("paragraphs", [])
        }
        rendered_cover_tex = cover_template.render(cover_render_context)

        cover_file_basename = f"{clean_company}_{date_str}_{serial_str}_{resume_type.lower()}_cover"
        log(f"Compiling cover letter to PDF: {output_dir}/{cover_file_basename}.pdf", "INFO")

        cover_tex_path = os.path.join(output_dir, f"{cover_file_basename}.tex")
        with open(cover_tex_path, "w") as f:
            f.write(rendered_cover_tex)

        cmd_cover = ["tectonic", "-o", output_dir, cover_tex_path]
        result_cover = subprocess.run(cmd_cover, capture_output=True, text=True)
        if result_cover.returncode != 0:
            log("Cover letter Tectonic compilation failed!", "ERROR")
            raise RuntimeError(f"LaTeX compile error (Cover Letter):\n{result_cover.stderr}")

        cover_pdf_path = os.path.join(output_dir, f"{cover_file_basename}.pdf")
        log("Cover letter compiled successfully!", "INFO")
        subprocess.run(["open", cover_pdf_path])

    log("Generation process completed successfully!", "INFO")

# ----------------------------------------------------------------------
# 4. Textual TUI Application
# ----------------------------------------------------------------------
try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical
    from textual.widgets import Header, Footer, Input, TextArea, Checkbox, Button, Label, Select, TabbedContent, TabPane
    from textual.screen import Screen
    from textual.worker import get_current_worker

    class LogTextArea(TextArea):
        BINDINGS = [
            ("ctrl+c", "copy_selection", "Copy Selection"),
            ("c", "copy_selection", "Copy Selection"),
        ]

        def action_copy_selection(self) -> None:
            if self.selected_text:
                self.app.copy_to_clipboard(self.selected_text)
                self.app.notify("Selection copied to clipboard!", severity="info", timeout=2)
            else:
                if self.text.strip():
                    self.app.copy_to_clipboard(self.text)
                    self.app.notify("All logs copied to clipboard!", severity="info", timeout=2)

    # SplashScreen removed (now embedded directly in main screen layout)

    class ExitScreen(Screen):
        def compose(self) -> ComposeResult:
            yield Vertical(
                Label("Good luck with your applications! 🙌", id="exit-message"),
                id="exit-container"
            )

        def on_mount(self) -> None:
            self.set_timer(0.8, lambda: self.app.exit())

except ImportError:
    App = object
    class LogTextArea(object): pass
    class SplashScreen(object): pass
    class ExitScreen(object): pass

class ResumeGenTUI(App):
    ASCII_ART = r"""
  ___  ___ ___ _   _ __  __ ___ _  _ _____ 
 | _ \/ __| __| | | |  \/  |_ _| \| |_   _|
 |   /\__ \ _| |_| | |\/| || || .` | | |  
 |_|_\|___/___|\___/|_|  |_|___|_|\_| |_|  
"""

    CSS = """
    .hidden {
        display: none !important;
    }
    Screen {
        background: #121212;
    }
    #splash-container, #exit-container {
        align: center middle;
        background: #121212;
        height: 100%;
        width: 100%;
    }
    #splash-logo {
        color: #00E676;
        text-style: bold;
        margin-bottom: 1;
        content-align: center middle;
    }
    #splash-subtitle {
        color: #888888;
        margin-bottom: 2;
        content-align: center middle;
    }
    #splash-status {
        color: #00E676;
        content-align: center middle;
    }
    #exit-message {
        color: #00E676;
        text-style: bold;
        content-align: center middle;
    }
    TabbedContent {
        height: 100%;
        width: 100%;
    }
    #tab-generate, #tab-profile {
        padding: 1 2;
    }
    #generate-container, #profile-container {
        width: 100%;
        height: 100%;
    }
    #sidebar, #profile-form {
        width: 35%;
        height: 100%;
        border-right: solid #333333;
        padding-right: 2;
    }
    #content-area, #profile-preview-area {
        width: 65%;
        height: 100%;
        padding-left: 2;
    }
    .field-label {
        text-style: bold;
        color: #00E676;
        margin-top: 1;
        margin-bottom: 0;
    }
    .section-label {
        text-style: bold;
        color: #00E676;
        margin-bottom: 1;
    }
    #context-box {
        height: 55%;
        border: solid #333333;
    }
    #log-box {
        height: 30%;
        border: solid #333333;
        background: #0d0d0d;
    }
    #btn-generate {
        background: #00E676;
        color: black;
        width: 100%;
        margin-top: 1;
        text-style: bold;
    }
    #btn-generate:hover {
        background: #00C853;
    }
    .logs-header-row {
        height: 3;
        align: left middle;
        margin-top: 1;
    }
    .logs-header-spacer {
        width: 1fr;
    }
    #btn-copy-logs {
        height: 1;
        min-width: 15;
        border: none;
        background: #333333;
        color: #00E676;
        text-style: bold;
    }
    #btn-copy-logs:hover {
        background: #444444;
        color: #00FF87;
    }
    #profile-yaml-preview {
        height: 75%;
        border: solid #333333;
        background: #0d0d0d;
        margin-bottom: 1;
    }
    .profile-actions-row {
        height: 3;
        align: left middle;
    }
    #btn-profile-save {
        width: 100%;
        margin-top: 2;
    }
    #btn-profile-edit {
        background: #333333;
        color: white;
        margin-right: 2;
    }
    #btn-profile-reload {
        background: #333333;
        color: white;
    }
    """

    BINDINGS = [
        ("q", "custom_quit", "Quit"),
        ("ctrl+q", "custom_quit", "Quit"),
    ]

    def copy_to_clipboard(self, text: str) -> None:
        try:
            import platform
            if platform.system() == "Darwin":
                process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE, text=True)
                process.communicate(input=text)
                return
        except Exception:
            pass
        super().copy_to_clipboard(text)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        with Vertical(id="splash-container"):
            yield Label(self.ASCII_ART, id="splash-logo")
            yield Label("AI-Powered Resume Tailoring & Generation Tool", id="splash-subtitle")
            yield Label("Initializing...", id="splash-status")
            
        with TabbedContent(initial="tab-generate", id="main-tabs", classes="hidden"):
            with TabPane("Tailor Resume", id="tab-generate"):
                with Horizontal(id="generate-container"):
                    with Vertical(id="sidebar"):
                        if not os.getenv("GEMINI_API_KEY"):
                            yield Label("GEMINI API KEY", classes="field-label")
                            yield Input(
                                placeholder="Enter Gemini API Key...",
                                value="",
                                password=True,
                                id="api-key-input"
                            )
                        
                        yield Label("COMPANY TARGET NAME", classes="field-label")
                        yield Input(placeholder="e.g. Google, Microsoft...", id="company-input")
                        
                        yield Label("RESUME TYPE", classes="field-label")
                        yield Select(
                            options=[("Full Stack SDE", "sde"), ("AI Engineer", "ai"), ("ML / Research", "research")],
                            value="sde",
                            id="type-select"
                        )
                        
                        yield Label("CAMPUS PLACEMENT MODE", classes="field-label")
                        yield Select(
                            options=[("On-Campus (Bundled/Local)", "on"), ("Off-Campus (ATS Clean)", "off")],
                            value="off",
                            id="campus-select"
                        )
                        
                        yield Label("OPTIONS", classes="field-label")
                        yield Checkbox("Generate Cover Letter", value=False, id="cover-checkbox")
                        
                        yield Button("Generate Resume", id="btn-generate")

                    with Vertical(id="content-area"):
                        yield Label("PASTE JD, COMPANY POLICIES, & CUSTOM INSTRUCTIONS HERE", classes="field-label")
                        yield TextArea(
                            placeholder="Paste everything here...\n\n- Job Description\n- Company culture or cover letter guidelines\n- Any custom guidelines (e.g. 'Highlight AWS & Next.js projects')",
                            id="context-box"
                        )
                        
                        with Horizontal(classes="logs-header-row"):
                            yield Label("PROCESS LOGS", classes="field-label")
                            yield Label("", classes="logs-header-spacer")
                            yield Button("Copy Logs", id="btn-copy-logs")
                        yield LogTextArea(read_only=True, id="log-box")

            with TabPane("Edit Profile", id="tab-profile"):
                with Horizontal(id="profile-container"):
                    with Vertical(id="profile-form"):
                        yield Label("PERSONAL INFO", classes="field-label")
                        
                        yield Label("Full Name", classes="field-label")
                        yield Input(id="profile-name", placeholder="Your Name")
                        
                        yield Label("Email", classes="field-label")
                        yield Input(id="profile-email", placeholder="Email")
                        
                        yield Label("Phone", classes="field-label")
                        yield Input(id="profile-phone", placeholder="Phone number")
                        
                        yield Label("Institution", classes="field-label")
                        yield Input(id="profile-institution", placeholder="University / College")
                        
                        yield Label("Website", classes="field-label")
                        yield Input(id="profile-website", placeholder="Portfolio website url")
                        
                        yield Label("LinkedIn URL", classes="field-label")
                        yield Input(id="profile-linkedin", placeholder="LinkedIn url")
                        
                        yield Label("GitHub URL", classes="field-label")
                        yield Input(id="profile-github", placeholder="GitHub url")
                        
                        yield Label("LeetCode URL", classes="field-label")
                        yield Input(id="profile-leetcode", placeholder="LeetCode url")
                        
                        yield Button("Save Personal Info", id="btn-profile-save", variant="success")

                    with Vertical(id="profile-preview-area"):
                        yield Label("PREVIEW DATABASE (~/.resumint/profile.yaml)", classes="field-label")
                        yield TextArea(id="profile-yaml-preview", read_only=True)
                        with Horizontal(classes="profile-actions-row"):
                            yield Button("Open in External Editor", id="btn-profile-edit")
                            yield Button("Reload Profile", id="btn-profile-reload")
        yield Footer()

    def on_mount(self) -> None:
        self.reload_profile_data()
        self.set_timer(1.2, self.hide_splash)

    def hide_splash(self) -> None:
        self.query_one("#splash-container").add_class("hidden")
        self.query_one("#main-tabs").remove_class("hidden")

    def action_custom_quit(self) -> None:
        self.push_screen(ExitScreen())

    def reload_profile_data(self) -> None:
        profile_path = os.path.join(RESUMINT_DIR, "profile.yaml")
        if not os.path.exists(profile_path):
            return

        try:
            with open(profile_path, "r") as f:
                content = f.read()
                data = yaml.safe_load(content)
        except Exception as e:
            self.notify(f"Failed to load profile.yaml: {e}", severity="error")
            return

        # Update preview box
        preview_box = self.query_one("#profile-yaml-preview", TextArea)
        preview_box.text = content

        # Update inputs
        info = data.get("personal_info", {})
        self.query_one("#profile-name", Input).value = str(info.get("name", ""))
        self.query_one("#profile-email", Input).value = str(info.get("email", ""))
        self.query_one("#profile-phone", Input).value = str(info.get("phone", ""))
        self.query_one("#profile-institution", Input).value = str(info.get("institution", ""))
        self.query_one("#profile-website", Input).value = str(info.get("website", ""))
        self.query_one("#profile-linkedin", Input).value = str(info.get("linkedin", ""))
        self.query_one("#profile-github", Input).value = str(info.get("github", ""))
        self.query_one("#profile-leetcode", Input).value = str(info.get("leetcode", ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-copy-logs":
            log_widget = self.query_one("#log-box", LogTextArea)
            if log_widget.text.strip():
                self.copy_to_clipboard(log_widget.text)
                self.notify("All logs copied to clipboard!", severity="info", timeout=2)
            else:
                self.notify("No logs to copy!", severity="warning", timeout=2)
            return

        if event.button.id == "btn-profile-reload":
            self.reload_profile_data()
            self.notify("Reloaded profile from disk!", severity="info")
            return

        if event.button.id == "btn-profile-edit":
            profile_path = os.path.join(RESUMINT_DIR, "profile.yaml")
            editor = os.getenv("EDITOR", "nano")
            self.suspend(subprocess.run, [editor, profile_path])
            self.reload_profile_data()
            self.notify("Returned from editor & reloaded profile!", severity="info")
            return

        if event.button.id == "btn-profile-save":
            profile_path = os.path.join(RESUMINT_DIR, "profile.yaml")
            if not os.path.exists(profile_path):
                self.notify("profile.yaml not found!", severity="error")
                return

            try:
                with open(profile_path, "r") as f:
                    data = yaml.safe_load(f)
            except Exception as e:
                self.notify(f"Error reading YAML: {e}", severity="error")
                return

            if "personal_info" not in data:
                data["personal_info"] = {}

            data["personal_info"]["name"] = self.query_one("#profile-name", Input).value
            data["personal_info"]["email"] = self.query_one("#profile-email", Input).value
            data["personal_info"]["phone"] = self.query_one("#profile-phone", Input).value
            data["personal_info"]["institution"] = self.query_one("#profile-institution", Input).value
            data["personal_info"]["website"] = self.query_one("#profile-website", Input).value
            data["personal_info"]["linkedin"] = self.query_one("#profile-linkedin", Input).value
            data["personal_info"]["github"] = self.query_one("#profile-github", Input).value
            data["personal_info"]["leetcode"] = self.query_one("#profile-leetcode", Input).value

            try:
                with open(profile_path, "w") as f:
                    yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
                self.reload_profile_data()
                self.notify("Profile saved successfully!", severity="info")
            except Exception as e:
                self.notify(f"Error saving profile: {e}", severity="error")
            return

        if event.button.id == "btn-generate":
            try:
                api_key = self.query_one("#api-key-input", Input).value
            except Exception:
                api_key = os.getenv("GEMINI_API_KEY", "")
            
            company = self.query_one("#company-input", Input).value
            resume_type = self.query_one("#type-select", Select).value
            campus_mode = self.query_one("#campus-select", Select).value
            generate_cover = self.query_one("#cover-checkbox", Checkbox).value
            context_text = self.query_one("#context-box", TextArea).text

            log_widget = self.query_one("#log-box", LogTextArea)
            log_widget.text = ""

            if not company:
                log_widget.text += "ERROR: Please enter a Company Name.\n"
                return
            if not context_text.strip():
                log_widget.text += "ERROR: Please paste the Job Description / Context.\n"
                return
            if not api_key:
                log_widget.text += "ERROR: Gemini API Key is missing.\n"
                return

            event.button.disabled = True
            log_widget.text += "Starting generation worker...\n"
            
            def run():
                try:
                    run_generator(
                        company=company,
                        resume_type=resume_type,
                        campus_mode=campus_mode,
                        context_input=context_text,
                        generate_cover=generate_cover,
                        api_key=api_key,
                        log_callback=lambda msg, level: self.call_from_thread(self.log_level_write, msg, level)
                    )
                except Exception as e:
                    self.call_from_thread(self.log_level_write, f"Generation failed: {str(e)}", "ERROR")
                finally:
                    self.call_from_thread(self.enable_button)

            self.run_worker(run, thread=True)

    def log_level_write(self, msg: str, level: str):
        log_widget = self.query_one("#log-box", LogTextArea)
        clean_msg = f"[{level}] {msg}\n"
        log_widget.text += clean_msg
        
        lines = len(log_widget.text.splitlines())
        if lines > 0:
            log_widget.cursor_location = (lines - 1, 0)

    def enable_button(self):
        btn = self.query_one("#btn-generate", Button)
        btn.disabled = False

# ----------------------------------------------------------------------
# 5. CLI Scaffold Init Command
# ----------------------------------------------------------------------
def init_workspace():
    print("⚙  Scaffolding resumint-cli workspace in ~/.resumint...")
    
    # Create template directories
    os.makedirs(RESUMINT_DIR, exist_ok=True)
    os.makedirs(os.path.join(RESUMINT_DIR, "templates"), exist_ok=True)
    os.makedirs(os.path.join(RESUMINT_DIR, "prompts"), exist_ok=True)
    os.makedirs(os.path.join(RESUMINT_DIR, "jds"), exist_ok=True)
    
    # 1. Copy profile.yaml.example
    profile_src = os.path.join(SCRIPT_DIR, "scaffold", "profile.yaml.example")
    profile_dest = os.path.join(RESUMINT_DIR, "profile.yaml")
    if not os.path.exists(profile_dest):
        if os.path.exists(profile_src):
            shutil.copy(profile_src, profile_dest)
            print("   Scaffolded profile.yaml.")
        else:
            print("⚠️  Warning: profile.yaml.example not found in package directory.")
    else:
        print("   ~/.resumint/profile.yaml already exists. Skipping.")

    # 2. Setup ~/.resumint/.env
    env_dest = os.path.join(RESUMINT_DIR, ".env")
    if not os.path.exists(env_dest):
        with open(env_dest, "w") as f:
            f.write("# Enter your Google Gemini API key below:\nGEMINI_API_KEY=\nGEMINI_MODEL=gemini-2.5-flash\n")
        print("   Scaffolded .env config file.")
    else:
        print("   ~/.resumint/.env already exists. Skipping.")

    print("\n✅  Setup completed successfully!")
    print("\nNext Steps:")
    print(f"1. Open '{profile_dest}' and update it with your own details.")
    print(f"2. Add your Google Gemini API key to '{env_dest}'.")
    print("3. Launch the interactive TUI from anywhere by running: resumint-cli\n")

# ----------------------------------------------------------------------
# 6. Main CLI Router
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="resumint-cli — AI-powered tailored resume and cover letter CLI/TUI.")
    parser.add_argument("command", nargs="?", choices=["init"], help="Optional command: 'init' to scaffold workspace")
    parser.add_argument("--type", choices=["sde", "ai", "research"], help="Resume type: sde, ai, research")
    parser.add_argument("--campus", choices=["on", "off"], default="off", help="Campus placement mode: on, off")
    parser.add_argument("--company", help="Target company name")
    parser.add_argument("--jd", help="Path to text file containing job description/context")
    parser.add_argument("--cover", action="store_true", help="Generate Cover Letter")
    parser.add_argument("--max-projects", type=int, default=3, help="Max projects to select")
    parser.add_argument("--max-achievements", type=int, default=5, help="Max achievements to select")
    parser.add_argument("--output-dir", help="Output directory for generated PDFs")
    
    args = parser.parse_args()

    # Route 'init' command
    if args.command == "init":
        init_workspace()
        sys.exit(0)

    # Route CLI headless mode
    if args.type and args.company and args.jd:
        if not os.path.exists(args.jd):
            print(f"Error: JD file not found at {args.jd}")
            sys.exit(1)
            
        with open(args.jd, "r") as f:
            context_input = f.read()

        try:
            run_generator(
                company=args.company,
                resume_type=args.type,
                campus_mode=args.campus,
                context_input=context_input,
                generate_cover=args.cover,
                max_projects=args.max_projects,
                max_achievements=args.max_achievements,
                output_dir=args.output_dir
            )
        except Exception as e:
            print(f"Generation failed: {e}")
            sys.exit(1)
    else:
        # Route TUI mode
        try:
            import textual
        except ImportError:
            print("Error: Textual framework not installed in virtual environment.")
            sys.exit(1)
            
        app = ResumeGenTUI()
        app.run()

if __name__ == "__main__":
    main()
