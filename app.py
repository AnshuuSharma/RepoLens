import os
import shutil
import stat
import requests
from flask import Flask, request, render_template_string
from git import Repo, GitCommandError
from dotenv import load_dotenv

load_dotenv()

HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_MODEL = "mistralai/Mistral-7B-Instruct"
HF_API = f"https://api-inference.huggingface.co/models/{HF_MODEL}"

TEMP_DIR = os.path.join(os.path.expanduser("~"), "repo_lens_temp")
app = Flask(__name__)

def remove_readonly(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)

def safe_delete(path):
    if os.path.exists(path):
        shutil.rmtree(path, onerror=remove_readonly)

# -------------------- HTML --------------------

INDEX_HTML = """
<!doctype html>
<html>
<head>
  <title>RepoLens</title>
  <style>
    body {
      font-family: Arial;
      background: #0d0618;
      color: #eae6f5;
      display: flex;
      justify-content: center;
      align-items: center;
      height: 100vh;
      margin: 0;
    }

    .card {
      background: #1a0f2e;
      padding: 28px;
      max-width: 720px;
      width: 90%;
      border-radius: 14px;
      text-align: center;
      box-shadow: 0 0 30px rgba(0,0,0,0.7);
    }

    h2 {
      margin-bottom: 20px;
    }

    input {
      width: 80%;
      padding: 14px;
      margin-bottom: 14px;
      border-radius: 8px;
      border: none;
      background: #2a1b45;
      color: #ffffff;
      font-size: 15px;
      outline: none;
    }

    input::placeholder {
      color: #b6b0d4;
    }

    button {
      padding: 14px 26px;
      border: none;
      border-radius: 8px;
      background: #6a5acd;
      color: white;
      font-size: 15px;
      cursor: pointer;
      transition: background 0.2s ease;
    }

    button:hover:not(:disabled) {
      background: #7b6df0;
    }

    button:disabled {
      background: #4a4460;
      cursor: not-allowed;
    }

    #status {
      margin-top: 14px;
      font-size: 14px;
      color: #c9c4ff;
      min-height: 18px;
    }
  </style>

  <script>
    function analyzeRepo() {
      const btn = document.getElementById("analyzeBtn");
      const status = document.getElementById("status");

      btn.disabled = true;
      status.innerText = "🔍 Analyzing repository… please wait.";
    }
  </script>
</head>

<body>
  <div class="card">
    <h2>RepoLens – GitHub Repository Analyzer</h2>

    <form method="post" action="/analyze" onsubmit="analyzeRepo()">
      <input
        name="repo_url"
        placeholder="https://github.com/user/repo"
        required
      />
      <br>
      <button id="analyzeBtn">Analyze</button>
    </form>

    <div id="status"></div>
  </div>
</body>
</html>
"""


RESULT_HTML = """
<!doctype html>
<html>
<head>
  <title>RepoLens Result</title>
  <style>
    body { font-family: Arial; background:#1a0b2e; color:white; padding:40px;}
    .card { background:#2e1a4f; padding:24px; max-width:900px; margin:auto; border-radius:12px;}
    ul { line-height:1.8; }
    a {color : red; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Score: {{ score }} / 100</h2>
    <p><b>Summary:</b> {{ summary }}</p>
    <h3>Roadmap</h3>
    <ul>
      {% for r in roadmap %}
        <li>{{ r }}</li>
      {% endfor %}
    </ul>
    <a href="/" color="white";>Analyze another repo</a>
  </div>
</body>
</html>
"""

# -------------------- GITHUB repo insights --------------------

def parse_repo(url):
    parts = url.rstrip("/").split("/")
    return parts[-2], parts[-1]

def github_repo_info(owner, repo):
    r = requests.get(f"https://api.github.com/repos/{owner}/{repo}", timeout=10)
    return r.json() if r.ok else {}

def github_commit_count(owner, repo):
    total = 0
    page = 1
    while True:
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits",
            params={"per_page": 100, "page": page},
            timeout=10
        )
        if not r.ok or not r.json():
            break
        total += len(r.json())
        page += 1
    return total

# -------------------- REPO ANALYSIS --------------------

def clone_repo(url):
    safe_delete(TEMP_DIR)
    Repo.clone_from(url, TEMP_DIR, depth=1)
    safe_delete(os.path.join(TEMP_DIR, ".git"))

def analyze_files():
    files = []
    for root, _, fs in os.walk(TEMP_DIR):
        for f in fs:
            files.append(os.path.join(root, f))
    return files

def detect_readme(files):
    """
    README is valid only if:
    - File name is README or README.*
    - Located in repo root
    - Has meaningful content
    """
    for f in files:
        rel_path = os.path.relpath(f, TEMP_DIR)
        name = os.path.basename(f).lower()

        if os.sep in rel_path:
            continue

        if name == "readme" or name.startswith("readme."):
            try:
                with open(f, "rb") as bf:
                    content = bf.read().decode(errors="ignore").strip()

                if len(content) < 50:
                    return False, False

                return True, True

            except:
                return False, False

    return False, False

def detect_tests(files):
    TEST_DIRS = {"tests", "__tests__", "test", "spec"}
    TEST_FILE_SUFFIXES = (
        "_test.py", "test_.py",
        ".test.js", ".spec.js",
        ".test.ts", ".spec.ts",
        "_test.go", "_test.rs"
    )
    TEST_CONFIGS = {
        "pytest.ini",
        "tox.ini",
        "jest.config.js",
        "jest.config.ts",
        "vitest.config.ts",
        "mocha.opts",
        "phpunit.xml"
    }

    for f in files:
        rel = os.path.relpath(f, TEMP_DIR)
        parts = rel.split(os.sep)
        name = os.path.basename(f).lower()

        if any(part.lower() in TEST_DIRS for part in parts[:-1]):
            return True

        if name.endswith(TEST_FILE_SUFFIXES):
            return True

        if name in TEST_CONFIGS:
            return True

    return False


def detect_structure(files):
    dirs = set()
    for f in files:
        parts = f.replace(TEMP_DIR, "").split(os.sep)
        if len(parts) > 2:
            dirs.add(parts[1])

    score = sum([
        "src" in dirs,
        "tests" in dirs,
        "docs" in dirs,
        len(files) > 10
    ])

    if score >= 3:
        return "clean"
    elif score == 2:
        return "moderate"
    return "basic"

def build_analysis(url):
    owner, repo = parse_repo(url)
    info = github_repo_info(owner, repo)
    commits = github_commit_count(owner, repo)

    clone_repo(url)
    files = analyze_files()

    readme, readme_content = detect_readme(files)

    return {
        "files": len(files),
        "structure": detect_structure(files),
        "readme": readme,
        "readme_content": readme_content,
        "tests": detect_tests(files),
        "commits": commits,
        "stars": info.get("stargazers_count", 0),
        "language": info.get("language", "Unknown")
    }

# -------------------- SCORING + FEEDBACK --------------------

def fallback_feedback(a):
    score = 40
    roadmap = []

    if a["structure"] == "clean":
        score += 15
    elif a["structure"] == "moderate":
        score += 8
    else:
        roadmap.append("Improve project structure (src/, tests/, docs/)")

    if a["readme"]:
        score += 10
        if not a["readme_content"]:
            roadmap.append("Expand README with setup, usage, and examples")
    else:
        roadmap.append("Add a comprehensive README")
    if not a["readme"]:
        roadmap.append("Add a README with project overview, setup instructions, and usage examples")
    else:
      if not a["readme_content"]:
        roadmap.append("Improve README with clearer documentation and examples")


    if a["tests"]:
        score += 15
    else:
        roadmap.append("Add unit and integration tests")

    if a["commits"] > 50:
        score += 10
    elif a["commits"] < 10:
        roadmap.append("Commit more frequently with meaningful messages")

    if a["stars"] > 20:
        score += 5

    summary = (
        f"{a['structure'].capitalize()} {a['language']} project "
        f"{'with' if a['readme'] else 'without'} documentation "
        f"and {'with' if a['tests'] else 'without'} tests."
    )

    if not roadmap:
        roadmap.append("Prepare the project for open-source contributions")

    return summary, roadmap[:7], min(score, 100)

# -------------------- ROUTES --------------------

@app.route("/")
def home():
    return render_template_string(INDEX_HTML)

@app.route("/analyze", methods=["POST"])
def analyze():
    url = request.form.get("repo_url")
    analysis = build_analysis(url)
    summary, roadmap, score = fallback_feedback(analysis)
    safe_delete(TEMP_DIR)

    return render_template_string(
        RESULT_HTML,
        summary=summary,
        roadmap=roadmap,
        score=score
    )

if __name__ == "__main__":
    print("RepoLens running on http://localhost:8000")
    app.run(port=8000, debug=True)


