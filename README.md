# RepoLens

RepoLens is a web app that analyzes GitHub repositories and provides:
- A summary of the project
- A score based on code quality, documentation, tests, and activity
- A roadmap of actionable improvements

## Technologies Used
- Python
- Flask
- GitPython
- Requests
- HuggingFace LLM (optional, for advanced feedback)
- HTML/CSS (for UI)
- dotenv (for storing API tokens)

## How It Works
1. User enters a GitHub repository URL.
2. RepoLens clones the repository locally.
3. It analyzes the project structure, README, tests, commit history, and stars.
4. Generates a score, summary, and roadmap using either an LLM or fallback logic.
5. Displays results in a web interface.

## How to Run Locally
1. Clone the repository:
   ```bash
   git clone <your-github-repo-url>
   cd RepoLens
