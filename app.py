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

def remove_readonly(func, path, excinfo):
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
    body { font-family: Arial; background:#1a0b2e; color:white; display:flex; justify-content:center; align-items:center; height:100vh; margin:0;}
    .card { background:#2e1a4f; padding:24px; max-width:720px; width:90%; border-radius:12px; box-shadow:0 0 20px rgba(0,0,0,0.5); text-align:center;}
    input { width:80%; padding:12px; margin-bottom:12px; border-radius:6px; border:none; }
    button { padding:12px 20px; border:none; border-radius:6px; background:#6a5acd; color:white; cursor:pointer; }
    button:disabled { background:#999; cursor:not-allowed; }
    #status { margin-top:12px; font-size:14px; }
  </style>
  <script>
    function analyzeRepo(form) {
        const btn = document.getElementById('analyzeBtn');
        btn.disabled = true;
        document.getElementById('status').innerText = 'Analyzing repository... Please wait.';
    }
  </script>
</head>
<body>
  <div class="card">
    <h2>RepoLens – GitHub Repository Analyzer</h2>
    <form method="post" action="/analyze" onsubmit="analyzeRepo(this);">
      <input name="repo_url" placeholder="https://github.com/user/repo" required />
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
    .card { background:#2e1a4f; padding:24px; max-width:900px; margin:auto; border-radius:12px; box-shadow:0 0 20px rgba(0,0,0,0.5); }
    ul { line-height:1.8; }
    a { color:#6a5acd; text-decoration:none; }
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
    <a href="/">Analyze another repo</a>
  </div>
</body>
</html>
"""


def parse_repo(url):
    parts = url.rstrip('/').split('/')
    return parts[-2], parts[-1]

def github_repo_info(owner, repo):
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}", timeout=10)
        return r.json() if r.ok else {}
    except:
        return {}

def github_commits(owner, repo):
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}/commits", timeout=10)
        return len(r.json()) if r.ok else 0
    except:
        return 0

def clone_repo(url):
    safe_delete(TEMP_DIR)
    try:
        Repo.clone_from(url, TEMP_DIR, depth=1)
        git_dir = os.path.join(TEMP_DIR, ".git")
        safe_delete(git_dir)
    except GitCommandError as e:
        print("[ERROR] Cloning failed:", e)

def analyze_files():
    files = []
    for root, _, f in os.walk(TEMP_DIR):
        for x in f:
            files.append(os.path.join(root, x))
    return files

def build_analysis(repo_url):
    owner, repo = parse_repo(repo_url)
    info = github_repo_info(owner, repo)
    commits = github_commits(owner, repo)

    clone_repo(repo_url)
    files = analyze_files()

    # Detect README
    readme_file = next((f for f in files if os.path.basename(f).lower().startswith("readme")), None)
    readme_content = False
    if readme_file:
        try:
            with open(readme_file, 'r', encoding='utf-8') as f:
                readme_content = len(f.read().strip()) > 10
        except:
            readme_content = False

    # Detect tests
    tests = any(
        "test" in os.path.basename(f).lower() or "tests" in f.lower().split(os.sep)
        for f in files
    )

    structure = "clean" if len(files) > 5 else "basic"

    return {
        "readme": readme_file is not None,
        "readme_content": readme_content,
        "tests": tests,
        "commits": commits,
        "structure": structure,
        "stars": info.get("stargazers_count", 0)
    }

def fallback_feedback(a):
    
    summary_parts = []
    summary_parts.append("Clean project structure" if a["structure"]=="clean" else "Basic project structure")
    summary_parts.append("with README" if a["readme"] else "missing README")
    summary_parts.append("includes tests" if a["tests"] else "no tests detected")
    summary = ", ".join(summary_parts) + "."

   
    roadmap = []
    if not a["readme"]:
        roadmap.append("Add a README with project overview and instructions")
    if not a["tests"]:
        roadmap.append("Add unit and integration tests")
    if a["commits"] < 10:
        roadmap.append("Commit more frequently with meaningful messages")
    if not roadmap:
        roadmap.append("Prepare project for open-source contribution")


    score = 50 + (10 if a["structure"]=="clean" else 0) + (10 if a["readme"] else 0) + (10 if a["tests"] else 0)
    score = min(score, 100)
    return summary, roadmap, score

def llm_feedback(a):
    if not HF_TOKEN:
        return fallback_feedback(a)
    try:
        prompt = f"""
You are an AI coding mentor.

Repository evaluation:
- Project structure: {a['structure']}
- README present: {a['readme']} (has content: {a['readme_content']})
- Tests present: {a['tests']}
- Commit count: {a['commits']}
- Stars: {a['stars']}

Task:
1. Provide one-line honest summary of the repository.
2. Assign a score between 0 and 100 based on code quality, documentation, tests, and activity.
3. Provide 5–7 actionable roadmap points tailored to this repo.
4. Each roadmap point should be concise and clear.

Format:
Summary: <one-line summary>
Score: <number out of 100>
Roadmap:
- point 1
- point 2
- point 3
- point 4
- point 5
- point 6
- point 7
"""
        headers = {"Authorization": f"Bearer {HF_TOKEN}"}
        r = requests.post(HF_API, headers=headers, json={"inputs": prompt}, timeout=60)

        if not r.ok:
            print("[HF ERROR]", r.status_code, r.text)
            return fallback_feedback(a)

        resp = r.json()
        text = ""
        if isinstance(resp, list):
            text = resp[0].get("generated_text", "")
        elif isinstance(resp, dict):
            text = resp.get("generated_text", "")
        if not text.strip():
            return fallback_feedback(a)

        lines = [l.strip('-• ') for l in text.split('\n') if l.strip()]

        # Parse summary
        summary_line = next((l.replace("Summary:", "").strip() for l in lines if "Summary:" in l), None)
        summary = summary_line if summary_line else None

        # Parse score
        score_line = next((l.replace("Score:", "").strip() for l in lines if "Score:" in l), None)
        try:
            score = int(score_line) if score_line else None
        except:
            score = None

        # Parse roadmap
        roadmap_start = False
        roadmap = []
        for l in lines:
            if "Roadmap" in l:
                roadmap_start = True
                continue
            if roadmap_start:
                if l.startswith("-") or l:
                    roadmap.append(l.strip('-• ').strip())
        if not summary or score is None or not roadmap:
            return fallback_feedback(a)

        return summary, roadmap[:7], score

    except Exception as e:
        print("[ERROR] LLM call failed:", e)
        return fallback_feedback(a)

# -------------------- ROUTES --------------------
@app.route('/')
def home():
    return render_template_string(INDEX_HTML)

@app.route('/analyze', methods=['POST'])
def analyze():
    url = request.form.get('repo_url')
    print(f"[INFO] Received repo URL: {url}")
    if not url:
        return "No URL received"

    try:
        analysis = build_analysis(url)
        summary, roadmap, score = llm_feedback(analysis)
    except Exception as e:
        print("[ERROR] Failed during analysis:", e)
        summary, roadmap, score = fallback_feedback(analysis)
    finally:
        safe_delete(TEMP_DIR)

    return render_template_string(
        RESULT_HTML,
        score=score,
        summary=summary,
        roadmap=roadmap
    )


if __name__ == '__main__':
    print("Starting RepoLens on port 8000...")
    app.run(debug=True, port=8000)
