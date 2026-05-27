#!/usr/bin/env node
/**
 * resumint-cli — Node.js shim that bootstraps the Python venv (in ~/.resumint/venv) and launches generate.py.
 */

const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const PKG_DIR = path.resolve(__dirname, "..");
const SCRIPT = path.join(PKG_DIR, "src", "generate.py");
const REQUIREMENTS = path.join(PKG_DIR, "requirements.txt");

// User config directory: ~/.resumint
const USER_HOME = os.homedir();
const RESUMINT_DIR = path.join(USER_HOME, ".resumint");
const VENV_DIR = path.join(RESUMINT_DIR, "venv");
const PYTHON = path.join(VENV_DIR, "bin", "python3");

const args = process.argv.slice(2);
const isInit = args.includes("init") || args.includes("--init");

function ensureVenv() {
  if (!fs.existsSync(PYTHON)) {
    console.log("⚙  Setting up Python virtual environment in ~/.resumint/venv...");

    // Create ~/.resumint if it doesn't exist
    if (!fs.existsSync(RESUMINT_DIR)) {
      fs.mkdirSync(RESUMINT_DIR, { recursive: true });
    }

    // Find a suitable python3
    const python3 = (() => {
      for (const candidate of ["python3", "python"]) {
        try {
          const result = spawnSync(candidate, ["--version"], { encoding: "utf8" });
          if (result.status === 0) return candidate;
        } catch (_) {}
      }
      return null;
    })();

    if (!python3) {
      console.error("❌  Python 3 not found. Please install Python 3 (with venv module) and try again.");
      process.exit(1);
    }

    console.log("   Creating virtual environment...");
    const venvResult = spawnSync(python3, ["-m", "venv", VENV_DIR], { stdio: "inherit" });
    if (venvResult.status !== 0) {
      console.error("❌  Failed to create Python virtual environment.");
      process.exit(1);
    }

    console.log("   Installing dependencies...");
    const pip = path.join(VENV_DIR, "bin", "pip");
    const pipResult = spawnSync(pip, ["install", "-r", REQUIREMENTS], { stdio: "inherit" });
    if (pipResult.status !== 0) {
      console.error("❌  Failed to install Python dependencies.");
      process.exit(1);
    }

    console.log("✅  Environment ready.\n");
  }
}

// 1. Ensure venv exists
ensureVenv();

// 2. Check if initialized
const profilePath = path.join(RESUMINT_DIR, "profile.yaml");
if (!fs.existsSync(profilePath) && !isInit) {
  console.log("⚠️  resumint-cli is not initialized yet!");
  console.log("Please run the following command to set up your profile and configuration:");
  console.log("\n   resumint-cli init\n");
  process.exit(0);
}

// 3. Spawn generate.py
const runArgs = [SCRIPT, ...args];
const result = spawnSync(PYTHON, runArgs, {
  stdio: "inherit",
  cwd: PKG_DIR,
});

process.exit(result.status ?? 1);
